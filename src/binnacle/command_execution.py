"""Run and stop orchestration over an explicit durable backend."""

import logging
import time
from pathlib import Path

from binnacle import job_output
from binnacle.callctx import current_argument_names, current_call, current_client
from binnacle.command_contracts import CommandBackend, CommandFailure, CommandReply
from binnacle.config import RunCommandSettings
from binnacle.run_command_evidence import record_auto_match
from binnacle.run_command_telemetry import DispatchPlan

log = logging.getLogger("binnacle.run_command")


def _shaped_output(
    backend: CommandBackend, job_id: str, tail_lines: int | None
) -> job_output.RunCommandOutputShape:
    log_text = backend.read_log(job_id).decode("utf-8", errors="replace")
    return job_output.shape_run_command_output(
        log_text, backend.max_output_chars, tail_lines
    )


def _log_output_shaping(
    call_id: str,
    job_id: str,
    state: str,
    shape: job_output.RunCommandOutputShape,
    tail_lines: int | None,
    log_bytes: int,
) -> None:
    if not shape.truncated:
        return
    log.info(
        "event=run_command_output_shaping call=%s job_id=%s state=%s reason=%s "
        "tail_lines=%s dropped_lines=%d char_clipped=%s selected_chars=%d "
        "returned_chars=%d omitted_chars=%d log_bytes=%d",
        call_id,
        job_id,
        state,
        shape.reason,
        tail_lines if tail_lines is not None else "-",
        shape.dropped_lines,
        str(shape.char_clipped).lower(),
        shape.selected_chars,
        shape.returned_chars,
        shape.omitted_chars,
        log_bytes,
    )


def run_command(
    command: str,
    workdir: Path,
    wait_seconds: int,
    background: bool,
    stdin: str | None,
    tail_lines: int | None = None,
    *,
    backend: CommandBackend,
    settings: RunCommandSettings,
) -> CommandReply:
    argument_names = current_argument_names.get()
    plan = DispatchPlan.build(
        command=command,
        wait_seconds=wait_seconds,
        background=background,
        argument_names=argument_names,
        client=current_client.get(),
        settings=settings,
        warmup_s=backend.warmup_s,
        wait_max_s=settings.wait_max_s,
        owner=backend.owner_mode,
    )
    call_id = current_call.get()
    plan.log_auto_background(call_id)
    if plan.auto_background and plan.auto_rule_hash is not None:
        record_auto_match(
            retention_days=settings.auto_background_evidence_retention_days,
            call_id=call_id,
            client=plan.client,
            command=command,
            command_hash=plan.command_hash,
            policy_hash=plan.auto_policy_hash,
            behavior_hash=plan.auto_behavior_hash,
            semantics_version=plan.auto_semantics_version,
            auto_warmup_s=plan.auto_warmup_s,
            rule_hash=plan.auto_rule_hash,
            match_start=plan.auto_match_start,
            match_end=plan.auto_match_end,
            root=settings.auto_background_evidence_dir,
        )
    owner_started = time.perf_counter()
    try:
        job_id = backend.start_and_wait(command, workdir, stdin, plan.effective_wait_s)
    except (OSError, RuntimeError) as exc:
        plan.log_error(call_id, (time.perf_counter() - owner_started) * 1000, exc)
        raise CommandFailure(
            f"Could not start the job: {exc}. Run `binnacle doctor`."
        ) from exc

    owner_roundtrip_ms = (time.perf_counter() - owner_started) * 1000
    state = backend.job_state(job_id)
    returned_state = state["state"] if state else "unknown"
    owner_instance = str((state or {}).get("owner_instance_id") or "-")[:12]
    plan.log_success(
        call_id, job_id, returned_state, owner_roundtrip_ms, owner_instance
    )
    shape = _shaped_output(backend, job_id, tail_lines)
    output, truncated = shape.output, shape.truncated
    _log_output_shaping(
        call_id,
        job_id,
        returned_state,
        shape,
        tail_lines,
        int((state or {}).get("log_bytes") or 0),
    )

    if state and state["state"] == "exited":
        payload = {
            "job_id": job_id,
            "state": "exited",
            "exit_code": state["exit_code"],
            "output": output,
            "truncated": truncated,
            "output_bytes": state["log_bytes"],
            "duration_s": state["runtime_s"],
            "log_path": state["log_path"],
            "workdir": str(workdir),
            "background_job": False,
        }
        if state["signal"] is not None:
            payload["signal"] = state["signal"]
        rc = state["exit_code"]
        if state["signal"] is not None:
            summary = f"Command killed by signal {state['signal']} after {state['runtime_s']} s."
        elif rc == 0:
            summary = f"Command exited 0 in {state['runtime_s']} s."
        else:
            summary = f"Command exited {rc} in {state['runtime_s']} s."
        # The command finished inline; there is no lingering job. Say so, because
        # models otherwise poll job_status to check (measured: 50 such no-arg
        # calls in a week, docs/usage-analysis-2026-09-06.md).
        summary += " It finished synchronously; no background job was created, so no job_status or stop_job is needed."
        return CommandReply(summary=summary, payload=payload)

    # still running → hand back the job_id
    payload = {
        "job_id": job_id,
        "state": "running",
        "output": output,
        "truncated": truncated,
        "output_bytes": state["log_bytes"] if state else 0,
        "runtime_s": state["runtime_s"] if state else 0,
        "log_path": state["log_path"] if state else "",
        "workdir": str(workdir),
        "background_job": True,
    }
    reason = (
        "started in background by local policy"
        if plan.auto_background
        else "started in background"
        if plan.background_requested
        else f"still running after {plan.bounded_wait_s} s"
    )
    summary = (
        f"Command {reason}; job_id={job_id}. "
        "This durable job keeps running without this ChatGPT turn. Unless the "
        "user explicitly asked you to wait for completion, report the job_id "
        "and current progress and return control instead of polling repeatedly; "
        "the user can ask for status later. Suggest a check-back interval only "
        "when grounded in the task or observed progress. Use job_status for a "
        "later update, or stop_job to cancel."
    )
    return CommandReply(summary=summary, payload=payload)


def stop_job(job_id: str, *, backend: CommandBackend) -> CommandReply:
    try:
        result = backend.stop_job(job_id)
    except RuntimeError as exc:
        raise CommandFailure(
            f"Could not stop the job: {exc}. Run `binnacle doctor`."
        ) from exc
    if result is None:
        raise CommandFailure(
            f"No job with id {job_id!r}. Call job_status without a job_id to list recent jobs."
        )
    payload = {
        "job_id": job_id,
        "state": result["state"],
        "exit_code": result["exit_code"],
        "signal": result["signal"],
    }
    if result["state"] == "exited":
        if result["signal"] is not None:
            summary = f"Job {job_id} stopped (signal {result['signal']})."
        elif result["exit_code"] is not None:
            summary = f"Job {job_id} already exited {result['exit_code']}."
        elif result.get("termination_reason"):
            summary = f"Job {job_id} was interrupted ({result['termination_reason']})."
        else:
            summary = f"Job {job_id} ended without a recorded exit status."
    else:
        summary = f"Job {job_id} is in state {result['state']}."
    return CommandReply(summary=summary, payload=payload)
