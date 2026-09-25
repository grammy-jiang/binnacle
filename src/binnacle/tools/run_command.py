"""run_command — run a shell command, wait-not-kill (yields a job_id).

Spec: docs/tools/run_command.md. Shared job machinery: jobs.py.
"""

import logging
import time
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from binnacle import job_output, job_owner, jobs
from binnacle.callctx import current_argument_names, current_call, current_client
from binnacle.config import get_settings
from binnacle.errors import CodedToolError
from binnacle.paths import resolve_path
from binnacle.run_command_evidence import record_auto_match
from binnacle.run_command_prediction import ShadowPredictionEngine
from binnacle.run_command_telemetry import DispatchPlan, build_command_features

RUN_SETTINGS = get_settings().run_command
RUN_WAIT_DEFAULT = RUN_SETTINGS.wait_default_s
RUN_WAIT_MAX = RUN_SETTINGS.wait_max_s
SHADOW_PREDICTOR = ShadowPredictionEngine(RUN_SETTINGS.shadow_prediction)
log = logging.getLogger("binnacle.run_command")

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "job_id": {"type": "string"},
        "state": {"type": "string", "enum": ["exited", "running"]},
        "exit_code": {"type": ["integer", "null"]},
        "signal": {"type": ["integer", "null"]},
        "output": {"type": "string"},
        "truncated": {"type": "boolean"},
        "output_bytes": {"type": "integer"},
        "duration_s": {"type": "number"},
        "runtime_s": {"type": "number"},
        "log_path": {"type": "string"},
        "workdir": {"type": "string"},
        "background_job": {"type": "boolean"},
    },
    "required": ["job_id", "state"],
}


def _shaped_output(
    job_id: str, tail_lines: int | None
) -> job_output.RunCommandOutputShape:
    log_text = jobs.read_log(job_id).decode("utf-8", errors="replace")
    return job_output.shape_run_command_output(
        log_text, jobs.RUN_MAX_OUTPUT_CHARS, tail_lines
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


def run_command_impl(
    command: str,
    workdir: str,
    wait_seconds: int,
    background: bool,
    stdin: str | None,
    tail_lines: int | None = None,
) -> ToolResult:
    resolved = resolve_path(workdir)
    if not resolved.is_dir():
        raise CodedToolError(
            "workdir_not_directory",
            f"workdir is not a directory: {resolved}. "
            f"Use a directory inside ~/Projects or /tmp.",
        )
    argument_names = current_argument_names.get()
    plan = DispatchPlan.build(
        command=command,
        wait_seconds=wait_seconds,
        background=background,
        argument_names=argument_names,
        client=current_client.get(),
        settings=RUN_SETTINGS,
        warmup_s=jobs.WARMUP_S,
        wait_max_s=RUN_WAIT_MAX,
        owner=jobs.OWNER_MODE,
    )
    call_id = current_call.get()
    declared_background = (
        str(background).lower() if "background" in argument_names else "none"
    )
    features = build_command_features(
        command,
        wait_seconds=wait_seconds,
        declared_background=declared_background,
        tail_lines=tail_lines,
    )
    try:
        SHADOW_PREDICTOR.submit(
            call_id=call_id,
            command=command,
            features=features,
            auto_rule_hash=plan.auto_rule_hash,
        )
    except Exception as exc:
        log.warning(
            "event=run_command_prediction_error schema=1 call=%s error=%s",
            call_id,
            type(exc).__name__,
        )
    plan.log_auto_background(call_id)
    if plan.auto_background and plan.auto_rule_hash is not None:
        record_auto_match(
            retention_days=RUN_SETTINGS.auto_background_evidence_retention_days,
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
            root=RUN_SETTINGS.auto_background_evidence_dir,
        )
    owner_started = time.perf_counter()
    try:
        job_id = job_owner.start_and_wait(
            command, resolved, stdin, plan.effective_wait_s
        )
    except (OSError, RuntimeError) as exc:
        plan.log_error(call_id, (time.perf_counter() - owner_started) * 1000, exc)
        raise ToolError(
            f"Could not start the job: {exc}. Run `binnacle doctor`."
        ) from exc

    owner_roundtrip_ms = (time.perf_counter() - owner_started) * 1000
    state = jobs.job_state(job_id)
    returned_state = state["state"] if state else "unknown"
    owner_instance = str((state or {}).get("owner_instance_id") or "-")[:12]
    plan.log_success(
        call_id, job_id, returned_state, owner_roundtrip_ms, owner_instance
    )
    shape = _shaped_output(job_id, tail_lines)
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
        try:
            SHADOW_PREDICTOR.record_runtime(features, float(state["runtime_s"]))
        except Exception as exc:
            log.warning(
                "event=run_command_prediction_memory_error schema=1 call=%s error=%s",
                call_id,
                type(exc).__name__,
            )
        payload = {
            "job_id": job_id,
            "state": "exited",
            "exit_code": state["exit_code"],
            "output": output,
            "truncated": truncated,
            "output_bytes": state["log_bytes"],
            "duration_s": state["runtime_s"],
            "log_path": state["log_path"],
            "workdir": str(resolved),
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
        return ToolResult(content=summary, structured_content=payload)

    # still running → hand back the job_id
    payload = {
        "job_id": job_id,
        "state": "running",
        "output": output,
        "truncated": truncated,
        "output_bytes": state["log_bytes"] if state else 0,
        "runtime_s": state["runtime_s"] if state else 0,
        "log_path": state["log_path"] if state else "",
        "workdir": str(resolved),
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
        "Use job_status when the result is needed, or stop_job to cancel."
    )
    return ToolResult(content=summary, structured_content=payload)


def register(mcp: FastMCP) -> None:
    SHADOW_PREDICTOR.log_config()

    @mcp.tool(
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        },
        output_schema=OUTPUT_SCHEMA,
    )
    def run_command(
        command: Annotated[str, Field(description="Shell command, run as bash -c.")],
        workdir: Annotated[
            str,
            Field(
                description="Working directory; absolute (~ ok) or relative to ~/Projects. Must be inside ~/Projects or /tmp."
            ),
        ] = "~/Projects",
        wait_seconds: Annotated[
            int,
            Field(
                ge=1,
                le=RUN_WAIT_MAX,
                description="Seconds to wait before yielding a job_id (max 50).",
            ),
        ] = RUN_WAIT_DEFAULT,
        background: Annotated[
            bool,
            Field(
                description="Return at once with a job_id after a 1 s warm-up. Local policy may also auto-background matching commands."
            ),
        ] = False,
        stdin: Annotated[
            str | None, Field(description="Text piped to the command's stdin.")
        ] = None,
        tail_lines: Annotated[
            int | None,
            Field(
                ge=1,
                description="Return only the last N lines of output (no need to pipe through tail).",
            ),
        ] = None,
    ) -> ToolResult:
        """Run a shell command with bash -c; several commands can go in one
        call (set -e; a && b). Waits up to wait_seconds; a command still
        running then is not killed: you get a job_id for job_status and
        stop_job. A command that finished created no job. Output merges
        stdout and stderr.
        """
        return run_command_impl(
            command, workdir, wait_seconds, background, stdin, tail_lines
        )
