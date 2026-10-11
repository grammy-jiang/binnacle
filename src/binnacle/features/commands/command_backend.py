"""Stateless bridge to the existing process-owned durable job engine."""

import platform
import time
from importlib import import_module
from pathlib import Path

from binnacle.features.commands.command_contracts import (
    CommandBackend,
    CommandFailure,
    RestrictedCommandBackend,
)


class DurableCommandBackend:
    """Delegate without owning configuration, processes, caches, or resources."""

    __slots__ = ()

    def start_and_wait(
        self, command: str, workdir: Path, stdin: str | None, wait_seconds: float
    ) -> str:
        from binnacle.features.commands import job_owner

        return job_owner.start_and_wait(command, workdir, stdin, wait_seconds)

    def stop_job(self, job_id: str) -> dict | None:
        from binnacle.features.commands import job_owner

        return job_owner.stop_job(job_id)

    def job_state(self, job_id: str) -> dict | None:
        from binnacle.features.commands import jobs

        return jobs.job_state(job_id)

    def list_jobs(self) -> list[dict]:
        from binnacle.features.commands import jobs

        return jobs.list_jobs()

    def await_exit(self, job_id: str, timeout: float) -> dict | None:
        from binnacle.features.commands import jobs

        return jobs.await_exit(job_id, timeout)

    def read_log(self, job_id: str) -> bytes:
        from binnacle.features.commands import jobs

        return jobs.read_log(job_id)

    def read_log_range(
        self, job_id: str, start: int, max_bytes: int
    ) -> tuple[bytes, int]:
        from binnacle.features.commands import jobs

        return jobs.read_log_range(job_id, start, max_bytes)

    def job_processes(self, job_id: str, max_cmd_chars: int = 200) -> list[dict]:
        from binnacle.features.commands import jobs

        return jobs.processes_for_job(job_id, max_cmd_chars)

    @property
    def owner_mode(self) -> str:
        from binnacle.features.commands import jobs

        return jobs.OWNER_MODE

    @property
    def warmup_s(self) -> float:
        from binnacle.features.commands import jobs

        return jobs.WARMUP_S

    @property
    def max_output_chars(self) -> int:
        from binnacle.features.commands import jobs

        return jobs.RUN_MAX_OUTPUT_CHARS


# JCR-4: the manager-owned Darwin command descriptions are the Linux text plus
# exactly these disclosed differences.
DARWIN_COMMAND_DISCLOSURE = (
    "macOS differences: "
    "D-1: jobs of a lost manager are UNKNOWN; never adopted, never exited; "
    "D-2: CPU/RSS accounting is sampled; membership_closed=false; "
    "descendants_unverified=true: new sessions/process groups are not tracked."
)
DARWIN_OWNER_LOST_NOTE = "owner lost; process not tracked"
DARWIN_MANAGER_REVIEW_PENDING = (
    "native_capability_unavailable: Darwin manager-owned commands await their "
    "release review; there is no embedded fallback."
)
_COMMAND_TOOLS = ("run_command", "job_status", "stop_job")


def darwin_manager_description(docstring: str | None) -> str:
    """The Linux tool docstring, unchanged, followed by the disclosure text."""
    from inspect import cleandoc

    return cleandoc(docstring or "") + "\n\n" + DARWIN_COMMAND_DISCLOSURE


class _UncomposedJobClient:
    """Fail closed: never execute locally when no manager client is composed."""

    def _refuse(self, *args, **kwargs):
        from binnacle.platform.contracts.process_contracts import (
            JOB_MANAGER_UNAVAILABLE,
        )

        raise CommandFailure(f"{JOB_MANAGER_UNAVAILABLE}: client not composed")

    start = stop = ping = _refuse


class DarwinManagerCommandBackend:
    """Darwin com.binnacle.jobs owner: RPC for start/stop, spool reads for state.

    The MCP process holds no job state and no process authority (JCR-2): it
    never spawns, signals or adopts a pid. An unreachable manager is the Linux
    per-call "job manager unavailable" error; there is no embedded fallback.
    Records the manager marked authority UNKNOWN (D-1) render as ``unknown``,
    never as ``exited``.
    """

    owner_mode = "manager"

    def __init__(
        self,
        *,
        jobs_dir: Path,
        socket_path: Path,
        release_states: dict[str, str],
        warmup_s: float,
        max_output_chars: int,
        client=None,
    ) -> None:
        self.jobs_dir = Path(jobs_dir)
        self.socket_path = Path(socket_path)
        self.release_states = dict(release_states)
        self.warmup_s = warmup_s
        self.max_output_chars = max_output_chars
        # The A3 DarwinJobClient is injected by platform composition; until that
        # factory exists the uncomposed client fails closed per call.
        self.client = _UncomposedJobClient() if client is None else client

    def require_available(self) -> None:
        # Committed rows, never reachability, decide availability (JCR-2).
        if any(self.release_states.get(t) != "AVAILABLE" for t in _COMMAND_TOOLS):
            raise CommandFailure(DARWIN_MANAGER_REVIEW_PENDING)

    def start_and_wait(
        self, command: str, workdir: Path, stdin: str | None, wait_seconds: float
    ) -> str:
        from binnacle.mcp.callctx import current_call

        response = self.client.start(
            self.socket_path,
            command=command,
            workdir=workdir,
            stdin=stdin,
            wait_seconds=wait_seconds,
            call_id=current_call.get(),
        )
        return str(response["job_id"])

    def _meta(self, job_id: str) -> dict | None:
        from binnacle.features.commands import job_store

        return job_store.read_meta(self.jobs_dir, job_id)

    def stop_job(self, job_id: str) -> dict | None:
        from binnacle.features.commands.job_stop import raise_if_partial_signal
        from binnacle.mcp.callctx import current_call
        from binnacle.platform.contracts.process_contracts import (
            OWNER_LOST_STOP_REFUSED,
        )

        meta = self._meta(job_id)
        if meta is None:
            return None
        if meta.get("authority") == "UNKNOWN":
            raise CommandFailure(OWNER_LOST_STOP_REFUSED)
        raise_if_partial_signal(meta)
        state = self.job_state(job_id)
        if state is None or state["state"] != "running":
            return state
        self.client.stop(self.socket_path, job_id, call_id=current_call.get())
        return self.job_state(job_id)

    def job_state(self, job_id: str) -> dict | None:
        meta = self._meta(job_id)
        if meta is None or meta.get("pid") is None:
            return None  # absent, or reserved by the manager before spawn
        now = time.time()
        log_path = self.jobs_dir / job_id / "out.log"
        try:
            stat = log_path.stat()
            log_bytes, last_output_age = stat.st_size, now - stat.st_mtime
        except OSError:
            log_bytes, last_output_age = 0, None
        note = None
        if meta.get("authority") == "UNKNOWN":
            state, note = "unknown", DARWIN_OWNER_LOST_NOTE  # D-1: never exited
        elif "exit_code" in meta or "signal" in meta:
            state = "exited"
        else:
            state = "running"  # only the manager may decide otherwise
        result = {
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
            "cgroup": None,
            "resource_usage": meta.get("resource_usage"),
            "runtime_s": round((meta.get("ended_at") or now) - meta["started_at"], 3),
            "last_output_age_s": (
                round(last_output_age, 1) if last_output_age is not None else None
            ),
            "log_bytes": log_bytes,
            "log_path": str(log_path),
        }
        if note is not None:
            result["note"] = note
        return result

    def list_jobs(self) -> list[dict]:
        from binnacle.features.commands import job_store

        ids = job_store.list_job_ids(self.jobs_dir)
        states = [s for jid in ids if (s := self.job_state(jid)) is not None]
        states.sort(key=lambda s: s["started_at"], reverse=True)
        return states

    def await_exit(self, job_id: str, timeout: float) -> dict | None:
        deadline = time.monotonic() + timeout
        while True:
            state = self.job_state(job_id)
            if state is None or state["state"] != "running":
                return state
            if time.monotonic() >= deadline:
                return state
            time.sleep(0.05)

    def read_log(self, job_id: str) -> bytes:
        from binnacle.features.commands import job_store

        return job_store.read_log(self.jobs_dir, job_id)

    def read_log_range(
        self, job_id: str, start: int, max_bytes: int
    ) -> tuple[bytes, int]:
        from binnacle.features.commands import job_store

        return job_store.read_log_range(self.jobs_dir, job_id, start, max_bytes)

    def job_processes(self, job_id: str, max_cmd_chars: int = 200) -> list[dict]:
        # No process authority in the MCP server; never inspect a pid from disk.
        return []


_native_release_states: dict[str, str] | None = None


def configure_native_release_states(states: dict[str, str] | None) -> None:
    """Receive committed per-tool release states from the composition root."""
    global _native_release_states
    _native_release_states = None if states is None else dict(states)


def create_command_backend() -> CommandBackend:
    """Capture engine settings at default selection, before accepting requests."""
    # Uncomposed callers on other hosts get an inert backend, never Linux jobs.
    # Native executors are injected by the application composition root.
    if platform.system() != "Linux":
        # Release states are handed in by the application composition root, so
        # the focused Commands child serves the same metadata; no execution here.
        return RestrictedCommandBackend(release_states=_native_release_states)
    import_module("binnacle.features.commands.jobs")
    import_module("binnacle.features.commands.job_owner")
    return DurableCommandBackend()
