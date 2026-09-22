"""Disk-backed job store shared by run_command / job_status / stop_job.

Design: docs/tools/run_command.md §6. Every command runs detached in its
own process group with output spooled to disk, so a job survives
`uvicorn --reload` and every state read comes from the filesystem, never
from process memory (ChatGPT re-initializes per call — no session state).
"""

import hashlib
import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from binnacle import job_store
from binnacle.callctx import current_call
from binnacle.config import get_settings
from binnacle.job_output import clip_head_tail as job_output_clip_head_tail
from binnacle.job_process import (
    _descendants,
    _pid_alive,
    _proc_starttime,
    job_processes,
    signal_group,
)

logger = logging.getLogger("binnacle.jobs")

JOBS_DIR = get_settings().jobs.dir
KEEP_NEWEST = get_settings().jobs.keep_newest
RUN_MAX_OUTPUT_CHARS = get_settings().jobs.max_output_chars
WARMUP_S = get_settings().jobs.warmup_s
_OWNER_SETTING = get_settings().jobs.owner
MANAGER_SOCKET = get_settings().jobs.socket_path


def _resolve_owner_mode() -> str:
    if _OWNER_SETTING != "auto":
        return _OWNER_SETTING
    return (
        "manager"
        if os.environ.get("BINNACLE_MANAGED_DEPLOYMENT") == "1"
        else "embedded"
    )


OWNER_MODE = _resolve_owner_mode()

# stop_job timings; module-level so tests can shrink the escalation wait.
STOP_SIGTERM_GRACE_S = 5.0  # wait for a clean SIGTERM exit before SIGKILL
STOP_SIGKILL_GRACE_S = 2.0  # wait for the forced exit to be recorded

# Serialize the prune + launch + durable-meta sequence. Multiple MCP calls can
# enter start_job concurrently through FastMCP's worker pool; without one store
# lock they can prune the same slot and both create a new directory. RLock lets
# start_job call _prune(), whose direct/test callers are protected too.
_STORE_LOCK = threading.RLock()

# stdout+stderr merge, interactivity neutered (Gemini's env hygiene set).
_ENV_OVERRIDES = {
    "PAGER": "cat",
    "GIT_PAGER": "cat",
    "GIT_TERMINAL_PROMPT": "0",
    "PYTHONUNBUFFERED": "1",
    "CI": "1",
    "BINNACLE": "1",
    "DEBIAN_FRONTEND": "noninteractive",
}


def _job_dir(job_id: str) -> Path:
    """Compatibility facade for the current job-store tests/callers."""
    return job_store.job_dir(JOBS_DIR, job_id)


def _read_meta(job_id: str) -> dict | None:
    """Compatibility facade over the storage-only module."""
    return job_store.read_meta(JOBS_DIR, job_id)


def _write_meta(job_id: str, meta: dict) -> None:
    """Compatibility facade preserving the existing atomic-write contract."""
    job_store.write_meta(JOBS_DIR, job_id, meta)


def _remove_job_dir(stale: Path) -> bool:
    """Compatibility facade for best-effort durable-store cleanup."""
    return job_store.remove_job_dir(stale)


def _prune(reserve: int = 0) -> None:
    """Prune the base retention window, sparing stale jobs still running.

    ``reserve`` removes slots from the *existing* window before a caller adds
    new jobs. ``start_job`` uses one reserved slot, so KEEP_NEWEST=50 means the
    new directory becomes the 50th base entry rather than a permanent 51st.
    Older live jobs outside that base window remain protected exceptions.
    """
    reserve = max(0, reserve)
    effective_keep = max(0, KEEP_NEWEST - reserve)
    with _STORE_LOCK:
        try:
            dirs = sorted(
                (d for d in JOBS_DIR.iterdir() if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        removed = 0
        skipped_running = 0
        for stale in dirs[effective_keep:]:
            # Never delete a live job: its process would keep running while
            # job_status loses it and the reaper crashes on exit. Unreadable or
            # malformed meta, exited, and unknown (process gone, exit never
            # recorded) all stay deletable so garbage cannot become immortal.
            try:
                state = job_state(stale.name)
            except KeyError:
                state = None  # meta parsed but incomplete (e.g. killed mid-write)
            if state is not None and state["state"] == "running":
                skipped_running += 1
                continue
            if _remove_job_dir(stale):
                removed += 1
        if removed or skipped_running:
            logger.info(
                "event=jobs_pruned removed=%d skipped_running=%d keep_newest=%d "
                "reserve=%d effective_keep=%d",
                removed,
                skipped_running,
                KEEP_NEWEST,
                reserve,
                effective_keep,
            )


def _termination_reason(meta: dict, rc: int | None) -> str:
    if meta.get("stop_requested"):
        return "stop_requested"
    if rc is not None and rc < 0:
        return "signal"
    return "normal_exit"


def record_exit(job_id: str, proc: subprocess.Popen) -> None:
    """Write an already-exited process's status to meta.json.

    The exit is read from the in-memory Popen object (``proc.returncode``),
    which is the authoritative record while the server lives; meta.json is
    the durable copy for later, stateless job_status/stop_job calls (which
    may run after a ``uvicorn --reload``). Whoever observed the exit calls
    this: the run_command request thread for a command that finished within
    its wait window, or the background reaper for one that outlived it.
    Call only after the process has exited (``proc.returncode`` is set).
    """
    rc = proc.returncode
    with _STORE_LOCK:
        meta = _read_meta(job_id) or {}
        if rc is not None and rc < 0:
            meta["signal"] = -rc
            meta["exit_code"] = None
        else:
            meta["exit_code"] = rc
        meta["ended_at"] = time.time()
        meta["termination_reason"] = _termination_reason(meta, rc)
        try:
            _write_meta(job_id, meta)
        except OSError:
            # The job dir vanished (pruned or removed externally); there is
            # nowhere to record the exit, and crashing helps nobody.
            logger.warning(
                "event=job_exit_unrecorded job_id=%s exit_code=%s signal=%s "
                "call=%s owner=%s owner_instance=%s command_hash=%s",
                job_id,
                meta.get("exit_code"),
                meta.get("signal"),
                meta.get("call_id", "-"),
                meta.get("owner", "embedded"),
                str(meta.get("owner_instance_id") or "-")[:12],
                meta.get("command_hash", "-"),
            )
            return
    try:
        log_bytes = (_job_dir(job_id) / "out.log").stat().st_size
    except OSError:
        log_bytes = 0
    started = meta.get("started_at")
    logger.info(
        "event=job_exit job_id=%s exit_code=%s signal=%s reason=%s runtime_s=%s "
        "log_bytes=%d call=%s owner=%s owner_instance=%s command_hash=%s",
        job_id,
        meta.get("exit_code"),
        meta.get("signal"),
        meta.get("termination_reason"),
        round(meta["ended_at"] - started, 3)
        if isinstance(started, (int, float))
        else "-",
        log_bytes,
        meta.get("call_id", "-"),
        meta.get("owner", "embedded"),
        str(meta.get("owner_instance_id") or "-")[:12],
        meta.get("command_hash", "-"),
    )


def reap_in_background(job_id: str, proc: subprocess.Popen) -> None:
    """Watch a still-running job from a daemon thread and record its exit.

    Used only when a command outlives its wait window and becomes a real
    background job — the one case that needs a dedicated waiter. A
    synchronous command is recorded inline by the request thread instead,
    so the common path spawns no thread.
    """

    def _watch() -> None:
        proc.wait()
        record_exit(job_id, proc)

    threading.Thread(target=_watch, daemon=True).start()


def start_job(
    command: str,
    workdir: Path,
    stdin: str | None,
    *,
    owner_instance_id: str | None = None,
    boot_id: str | None = None,
) -> tuple[str, subprocess.Popen]:
    # The whole reservation -> process launch -> complete meta sequence is one
    # store transaction. A second concurrent start must see the first new job
    # before deciding which old slot to prune.
    with _STORE_LOCK:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        _prune(reserve=1)
        job_id = job_store.new_job_id()
        d = _job_dir(job_id)
        d.mkdir(parents=True)
        log = d / "out.log"
        env = os.environ.copy()
        env.update(_ENV_OVERRIDES)
        # stdin goes through a spool file, not a pipe: a pipe write blocks once
        # the 64 KiB buffer fills if the command never reads it, which would hold
        # start_job (and run_command) until the command ends, defeating
        # wait_seconds. A file has no such coupling and survives reloads too.
        stdin_path = d / "stdin"
        if stdin is not None:
            stdin_path.write_bytes(stdin.encode("utf-8"))
        # Popen dups the fds, so the parent's copies can close right away and the
        # detached child keeps its own.
        with (
            open(log, "wb") as logf,
            open(stdin_path, "rb")
            if stdin is not None
            else open(os.devnull, "rb") as inf,
        ):
            proc = subprocess.Popen(
                ["bash", "-c", command],
                cwd=str(workdir),
                env=env,
                stdin=inf,
                stdout=logf,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # own process group; survives across turns
            )
        call_id = current_call.get()
        command_hash = hashlib.sha256(command.encode()).hexdigest()[:12]
        owner = "manager" if owner_instance_id is not None else "embedded"
        meta = {
            "command": command,
            "workdir": str(workdir),
            "pid": proc.pid,
            "pgid": proc.pid,  # start_new_session ⇒ pgid == pid
            "starttime": _proc_starttime(proc.pid),  # pid identity, see _pid_alive
            "started_at": time.time(),
            "call_id": call_id,
            "command_hash": command_hash,
            "owner": owner,
        }
        if owner_instance_id is not None:
            meta.update(
                schema_version=2,
                owner_instance_id=owner_instance_id,
                boot_id=boot_id,
            )
        _write_meta(job_id, meta)
        # Keep command/workdir/call in their historical order for old journal
        # consumers; append structured telemetry afterwards.
        logger.info(
            "event=job_start job_id=%s pid=%d command=%.60r workdir=%s call=%s "
            "owner=%s owner_instance=%s command_hash=%s command_chars=%d",
            job_id,
            proc.pid,
            command,
            workdir,
            call_id,
            owner,
            owner_instance_id[:12] if owner_instance_id else "-",
            command_hash,
            len(command),
        )
    # No watcher is spawned here: the caller waits on the process for its
    # wait window and records the exit itself (record_exit), and only calls
    # reap_in_background if the command outlives that window.
    return job_id, proc


def read_log(job_id: str) -> bytes:
    return job_store.read_log(JOBS_DIR, job_id)


def clip_head_tail(text: str, limit: int = RUN_MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    return job_output_clip_head_tail(text, limit)


def job_state(job_id: str) -> dict | None:
    """Full status derived from disk only. None if the job is unknown."""
    meta = _read_meta(job_id)
    if meta is None:
        return None
    now = time.time()
    log_path = _job_dir(job_id) / "out.log"
    try:
        stat = log_path.stat()
        log_bytes = stat.st_size
        last_output_age = now - stat.st_mtime
    except OSError:
        log_bytes = 0
        last_output_age = None
    if "exit_code" in meta or "signal" in meta:
        state = "exited"
    elif _pid_alive(meta["pid"], meta.get("starttime")):
        state = "running"
    else:
        state = "unknown"  # process gone but exit never recorded (server killed)
    return {
        "job_id": job_id,
        "state": state,
        "exit_code": meta.get("exit_code"),
        "signal": meta.get("signal"),
        "command": meta["command"],
        "workdir": meta["workdir"],
        "pid": meta["pid"],
        "pgid": meta.get("pgid", meta["pid"]),
        "started_at": meta["started_at"],
        "ended_at": meta.get("ended_at"),
        "termination_reason": meta.get("termination_reason"),
        "owner_instance_id": meta.get("owner_instance_id"),
        "boot_id": meta.get("boot_id"),
        "call_id": meta.get("call_id"),
        "command_hash": meta.get("command_hash"),
        "owner": meta.get("owner"),
        "runtime_s": round((meta.get("ended_at") or now) - meta["started_at"], 3),
        "last_output_age_s": (
            round(last_output_age, 1) if last_output_age is not None else None
        ),
        "log_bytes": log_bytes,
        "log_path": str(log_path),
    }


def list_jobs() -> list[dict]:
    ids = job_store.list_job_ids(JOBS_DIR)
    states = [s for jid in ids if (s := job_state(jid)) is not None]
    states.sort(key=lambda s: s["started_at"], reverse=True)
    return states


def _signal_job(pgid: int, strays: set[int], sig: int) -> None:
    """Signal the job's process group, then any descendant outside it."""
    signal_group(pgid, sig)
    for pid in strays:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def await_exit(job_id: str, timeout: float) -> dict | None:
    """Return the job's state, waiting up to ``timeout`` for it to be recorded.

    Consumers (stop_job, job_status) hold no process handle, so they cannot
    capture an exit themselves; only the waiter (the run_command thread or a
    background reaper) records it. Between a background process dying and its
    reaper writing meta.json there is a brief window where disk shows neither
    "running" (pid gone) nor "exited" (not yet written), i.e. a false
    "unknown". This bridges that window: it returns as soon as the state is
    "exited", and otherwise returns the latest state at the timeout — so a
    still-running job returns "running", and a truly orphaned one (its server
    died, nobody left to record it) returns "unknown" after the wait.
    """
    deadline = time.monotonic() + timeout
    interval = 0.02
    while True:
        st = job_state(job_id)
        if st is None or st["state"] == "exited" or time.monotonic() >= deadline:
            return st
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
        interval = min(interval * 1.5, 0.5)


def stop_job_embedded(job_id: str) -> dict | None:
    """Original signal/process-tree stop path, used by the stable owner process."""
    state = job_state(job_id)
    if state is None:
        return None
    if state["state"] != "running":
        if state["state"] == "unknown":
            meta = _read_meta(job_id)
            if meta is not None and meta.get("stop_requested"):
                return await_exit(job_id, STOP_SIGKILL_GRACE_S)
        return state
    pgid = state["pgid"]
    # Collect descendants BEFORE signaling: a setsid()'d child is outside the
    # group and only findable through its parent's ppid link while the
    # parent lives. Group members are covered by killpg already.
    group = {p["pid"] for p in job_processes(pgid)}
    strays = _descendants(state["pid"]) - group
    try:
        _signal_job(pgid, strays, signal.SIGTERM)
    except ProcessLookupError:
        return await_exit(job_id, STOP_SIGKILL_GRACE_S)
    # Wait for the recorded exit, not just for the pid to disappear: the
    # reaper writes the exit (signal 15) a moment after the process dies, and
    # returning before that would report a false "unknown".
    st = await_exit(job_id, STOP_SIGTERM_GRACE_S)
    if st is None or st["state"] == "exited":
        return st
    logger.warning(
        "event=job_stop_escalate job_id=%s call=%s signal=SIGKILL grace_s=%s",
        job_id,
        current_call.get(),
        STOP_SIGTERM_GRACE_S,
    )
    try:
        _signal_job(pgid, strays, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return await_exit(job_id, STOP_SIGKILL_GRACE_S)
