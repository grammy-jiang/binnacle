"""Status/list/wait/output orchestration over an explicit command backend."""

import logging
from time import perf_counter

from binnacle.callctx import (
    current_call,
    current_call_started,
    current_client,
    current_turn,
)
from binnacle.features.commands import job_output
from binnacle.features.commands.command_contracts import (
    CommandBackend,
    CommandFailure,
    CommandReply,
)
from binnacle.features.commands.job_store import JobGone

log = logging.getLogger("binnacle.job_status")


def _tail(text: str, n: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _command_preview(command: str, keep_chars: int) -> str:
    """Compact one-line head+tail identity for a recent-jobs listing."""
    display = command.replace("\n", "\\n")
    if len(display) <= keep_chars:
        return display
    head = keep_chars // 2
    tail = keep_chars - head
    omitted = len(display) - keep_chars
    return f"{display[:head]}…[{omitted} chars omitted]…{display[-tail:]}"


def _listing_rows(
    states: list[dict], history_limit: int, preview_chars: int
) -> tuple[list[dict], int]:
    """All running jobs plus bounded recent non-running history, newest first."""
    rows: list[dict] = []
    history = 0
    running = 0
    for state in states:
        is_running = state["state"] == "running"
        if is_running:
            running += 1
        elif history < history_limit:
            history += 1
        else:
            continue
        rows.append(
            {
                "job_id": state["job_id"],
                "state": state["state"],
                "exit_code": state["exit_code"],
                "runtime_s": state["runtime_s"],
                "started_at": state["started_at"],
                "workdir": state["workdir"],
                "command": _command_preview(state["command"], preview_chars),
            }
        )
    return rows, running


def _wait_for_exit(
    backend: CommandBackend, job_id: str, wait_seconds: int
) -> tuple[dict | None, float]:
    """Wait for recorded exit, up to the timeout, using backend.await_exit.

    Read disk across reloads and bridge the post-death reaper window, so a
    finishing job never produces a false "unknown".
    """
    t0 = perf_counter()
    state = backend.await_exit(job_id, wait_seconds)
    return state, round(perf_counter() - t0, 3)


def _elapsed_ms(start: float) -> float:
    return (perf_counter() - start) * 1_000


def _no_job_error(job_id: str) -> CommandFailure:
    return CommandFailure(
        f"No job with id {job_id!r}. Call job_status without a job_id to list recent jobs."
    )


def _cursor_offset(cursor: str, job_id: str) -> int | None:
    """Parse one v1 cursor; None means the explicit current-end seed."""
    if cursor == "start":
        return 0
    if cursor == "end":
        return None
    parts = cursor.split(":")
    if len(parts) != 3 or parts[0] != "v1" or not parts[1] or not parts[2].isdecimal():
        raise CommandFailure(
            "Invalid cursor: expected 'start', 'end', or v1:<job_id>:<offset>."
        )
    cursor_job = parts[1]
    if cursor_job != job_id:
        raise CommandFailure(f"cursor belongs to job {cursor_job}, not {job_id}")
    return int(parts[2])


def _cursor_delta(
    backend: CommandBackend, job_id: str, cursor: str, state: dict
) -> tuple[dict, int]:
    """Read and decode one bounded cursor chunk plus its open-file size."""
    requested_start = _cursor_offset(cursor, job_id)
    chunk_size = max(4, backend.max_output_chars)
    read_start = 0 if requested_start is None else requested_start
    read_limit = 0 if requested_start is None else chunk_size
    try:
        data, size_at_open = backend.read_log_range(job_id, read_start, read_limit)
    except JobGone:
        raise _no_job_error(job_id) from None

    delta_start = size_at_open if requested_start is None else requested_start
    if delta_start > size_at_open:
        raise CommandFailure("cursor beyond end of output")

    at_eof = delta_start + len(data) >= size_at_open
    final = state["state"] != "running"
    log_delta, consumed = job_output.consume_utf8(data, at_eof=at_eof, final=final)
    delta_end = delta_start + consumed
    pending_suffix = at_eof and not final and consumed < len(data)
    has_more = delta_end < size_at_open and not pending_suffix
    return (
        {
            "log_delta": log_delta,
            "delta_start": delta_start,
            "delta_end": delta_end,
            "next_cursor": f"v1:{job_id}:{delta_end}",
            "has_more": has_more,
        },
        size_at_open,
    )


def _log_wait_exception_timing(
    *,
    job_id: str,
    requested_wait_s: int,
    bounded_wait_s: int,
    waited_s: float,
    state_start: float,
    impl_start: float,
    dispatch_ms: float | None,
    turn: str | None,
    client: str | None,
    log_bytes: int,
) -> None:
    """Keep the timing record when a positive wait raises."""
    dispatch_field = f"{dispatch_ms:.2f}" if dispatch_ms is not None else "na"
    log.info(
        "event=job_status_timing call=%s job_id=%s wait_requested_s=%s "
        "wait_bounded_s=%s wait_effective_s=%s waited_s=%s turn=%s client=%s "
        "dispatch_ms=%s state_ms=%.2f read_log_ms=na process_scan_ms=na "
        "impl_ms=%.2f state=error processes=na log_bytes=%s",
        current_call.get(),
        job_id,
        requested_wait_s,
        bounded_wait_s,
        bounded_wait_s,
        waited_s,
        turn if turn is not None else "-",
        client if client is not None else "-",
        dispatch_field,
        _elapsed_ms(state_start),
        _elapsed_ms(impl_start),
        log_bytes,
    )


def _listing_result(
    backend: CommandBackend, history_limit: int, preview_chars: int
) -> CommandReply:
    states = backend.list_jobs()
    rows, running = _listing_rows(states, history_limit, preview_chars)
    if not states:
        summary = "No jobs recorded."
    elif len(rows) == len(states):
        summary = f"{len(rows)} job(s), newest first."
    else:
        summary = (
            f"{len(rows)} of {len(states)} job(s) shown, newest first: "
            f"all {running} running plus up to {history_limit} recent "
            "non-running jobs."
        )
    log.info(
        "event=job_listing call=%s recorded_jobs=%s returned_jobs=%s "
        "running_jobs=%s history_limit=%s command_preview_chars=%s",
        current_call.get(),
        len(states),
        len(rows),
        running,
        history_limit,
        preview_chars,
    )
    return CommandReply(summary=summary, payload={"jobs": rows})


def job_status(
    job_id: str | None,
    tail_lines: int,
    wait_seconds: int = 0,
    *,
    cursor: str | None = None,
    backend: CommandBackend,
    quiet_after_s: int,
    history_limit: int,
    preview_chars: int,
    wait_max: int,
    impl_start: float | None = None,
) -> CommandReply:
    # Include adapter default conversion in the historical timing scope.
    impl_start = perf_counter() if impl_start is None else impl_start
    call_start = current_call_started.get()
    dispatch_ms = (impl_start - call_start) * 1_000 if call_start is not None else None
    if cursor is not None and job_id is None:
        raise CommandFailure("cursor requires job_id")
    if job_id is None:
        return _listing_result(backend, history_limit, preview_chars)

    requested_wait_s = wait_seconds
    bounded_wait_s = max(0, min(requested_wait_s, wait_max))
    state_start = perf_counter()
    state = backend.job_state(job_id)
    if state is None:
        raise _no_job_error(job_id)

    client = current_client.get()
    turn = current_turn.get()
    if requested_wait_s > 0:
        wait_started = perf_counter()
        state_before_wait = state
        try:
            state, waited = _wait_for_exit(backend, job_id, bounded_wait_s)
        except BaseException:
            _log_wait_exception_timing(
                job_id=job_id,
                requested_wait_s=requested_wait_s,
                bounded_wait_s=bounded_wait_s,
                waited_s=round(perf_counter() - wait_started, 3),
                state_start=state_start,
                impl_start=impl_start,
                dispatch_ms=dispatch_ms,
                turn=turn,
                client=client,
                log_bytes=state_before_wait["log_bytes"],
            )
            raise
    else:
        waited = 0.0

    state_ms = _elapsed_ms(state_start)
    if state is None:
        raise _no_job_error(job_id)

    read_start = perf_counter()
    cursor_fields: dict | None = None
    cursor_log_bytes: int | None = None
    if cursor is None:
        log_text = backend.read_log(job_id).decode("utf-8", errors="replace")
        selected_tail = _tail(log_text, max(1, tail_lines))
        log_tail, log_tail_clipped, omitted_chars = job_output.clip_head_tail_hard(
            selected_tail, backend.max_output_chars
        )
        if log_tail_clipped:
            log.info(
                "event=job_status_output_shaping call=%s job_id=%s reason=char_limit "
                "tail_lines=%s limit_chars=%d selected_chars=%d returned_chars=%d "
                "omitted_chars=%d log_bytes=%d",
                current_call.get(),
                job_id,
                tail_lines,
                backend.max_output_chars,
                len(selected_tail),
                len(log_tail),
                omitted_chars,
                state["log_bytes"],
            )
    else:
        cursor_fields, cursor_log_bytes = _cursor_delta(backend, job_id, cursor, state)
    read_log_ms = _elapsed_ms(read_start)
    quiet = (
        state["state"] == "running"
        and state["last_output_age_s"] is not None
        and state["last_output_age_s"] >= quiet_after_s
    )

    process_start = perf_counter()
    processes = (
        backend.job_processes(state["pgid"]) if state["state"] == "running" else []
    )
    process_scan_ms = _elapsed_ms(process_start)
    payload = {
        "job_id": job_id,
        "state": state["state"],
        "exit_code": state["exit_code"],
        "signal": state["signal"],
        "runtime_s": state["runtime_s"],
        "last_output_age_s": state["last_output_age_s"],
        "quiet": quiet,
    }
    if cursor_fields is None:
        payload["log_tail"] = log_tail
    else:
        payload.update(cursor_fields)
    payload.update(
        {
            "log_bytes": state["log_bytes"],
            "log_path": state["log_path"],
            "command": _command_preview(state["command"], preview_chars),
            "workdir": state["workdir"],
            "processes": processes,
        }
    )
    if cursor_fields is not None:
        log.info(
            "event=job_status_cursor call=%s job_id=%s delta_start=%s delta_end=%s "
            "returned_chars=%s has_more=%s log_bytes=%s",
            current_call.get(),
            job_id,
            cursor_fields["delta_start"],
            cursor_fields["delta_end"],
            len(cursor_fields["log_delta"]),
            str(cursor_fields["has_more"]).lower(),
            cursor_log_bytes,
        )
    if requested_wait_s > 0:
        payload.update(
            {
                "waited_s": waited,
                "wait_requested_s": requested_wait_s,
                "wait_effective_s": bounded_wait_s,
            }
        )
    if state["state"] == "exited":
        rc = state["exit_code"]
        if state["signal"] is not None:
            detail = f"killed by signal {state['signal']}"
        elif rc is not None:
            detail = f"exited {rc}"
        elif state.get("termination_reason"):
            detail = f"interrupted ({state['termination_reason']})"
        else:
            detail = "ended without a recorded exit status"
        summary = f"Job {job_id} {detail} after {state['runtime_s']} s."
    elif state["state"] == "unknown":
        # A legacy orphan or a reused pid: the job's own process is gone.
        summary = (
            f"Job {job_id} state unknown: its process is gone and no exit "
            "status was recorded."
        )
    elif quiet:
        summary = (
            f"Job {job_id} running but quiet for {state['last_output_age_s']} s "
            f"({state['runtime_s']} s total)."
        )
    else:
        summary = f"Job {job_id} running ({state['runtime_s']} s)."
    if requested_wait_s > 0 and state["state"] == "running":
        summary += f" Still running after waiting {waited} s."
    if state["state"] == "running":
        summary += (
            " This durable job keeps running without this ChatGPT turn. If "
            "cursor mode has_more=true, drain the immediately available output "
            "first. Once caught up, unless the user explicitly asked you to "
            "wait for completion, report the job_id and current status and "
            "return control instead of starting another positive wait; the "
            "user can ask for status later."
        )
    impl_ms = _elapsed_ms(impl_start)
    dispatch_field = f"{dispatch_ms:.2f}" if dispatch_ms is not None else "na"
    log.info(
        "event=job_status_timing call=%s job_id=%s wait_requested_s=%s "
        "wait_bounded_s=%s wait_effective_s=%s waited_s=%s turn=%s client=%s "
        "dispatch_ms=%s state_ms=%.2f read_log_ms=%.2f process_scan_ms=%.2f "
        "impl_ms=%.2f state=%s processes=%s log_bytes=%s",
        current_call.get(),
        job_id,
        requested_wait_s,
        bounded_wait_s,
        bounded_wait_s,
        waited,
        turn if turn is not None else "-",
        client if client is not None else "-",
        dispatch_field,
        state_ms,
        read_log_ms,
        process_scan_ms,
        impl_ms,
        state["state"],
        len(processes),
        state["log_bytes"],
    )
    return CommandReply(summary=summary, payload=payload)
