"""Stateless bridge to the existing process-owned durable job engine."""

import platform
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from binnacle.features.commands.command_contracts import (
    CommandBackend,
    CommandFailure,
    CommandReply,
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


# JCR-4 as amended (STEER-04): descriptions equal Linux byte for byte; the
# disclosed differences appear in the result text where they occur. The
# release table keeps the machine-readable disclosures.
DESCENDANTS_UNVERIFIED = "descendants_unverified=true."
RESOURCES_SAMPLED = "sampled"
DARWIN_OWNER_LOST_NOTE = "owner lost; process not tracked"
# SD-41: without PID adoption only the manager can verify a non-terminal record.
DARWIN_MANAGER_UNAVAILABLE_NOTE = "job manager unavailable; state unverified"
DARWIN_MANAGER_REVIEW_PENDING = (
    "native_capability_unavailable: Darwin manager-owned commands await their "
    "release review; there is no embedded fallback."
)
_COMMAND_TOOLS = ("run_command", "job_status", "stop_job")
# R-J2-F4: a reaped leader can precede its persisted record; bridge that window.
EXIT_RECORD_GRACE_S = 2.0


@dataclass(frozen=True)
class ManagerBindings:
    """Spool, call-context and refusal seams injected by the composition root.

    The frozen Commands boundary keeps this module's imports narrow, so the
    manager backend receives them instead of importing them (STEER-05).
    """

    store: Any  # job_store-shaped: read_meta, read_log, read_log_range, list_job_ids
    call_id: Callable[[], str]
    check_partial: Callable[[dict], None]
    owner_lost_refusal: str
    unavailable: str


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
        socket_path: Path | Callable[[], Path],
        release_states: dict[str, str],
        warmup_s: float,
        max_output_chars: int,
        client,
        bindings: ManagerBindings,
    ) -> None:
        self.jobs_dir = Path(jobs_dir)
        # A resolver runs per call, so startup never depends on the runtime dir.
        self._socket_path = socket_path
        self.release_states = dict(release_states)
        self.warmup_s = warmup_s
        self.max_output_chars = max_output_chars
        # composition.create_job_client(): features never import platform.darwin.
        self.client = client
        self.bindings = bindings

    @property
    def socket_path(self) -> Path:
        if not callable(self._socket_path):
            return Path(self._socket_path)
        try:
            return self._socket_path()
        except (OSError, RuntimeError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            raise CommandFailure(f"{self.bindings.unavailable}: {code}") from exc

    def require_available(self) -> None:
        # Committed rows, never reachability, decide availability (JCR-2).
        if any(self.release_states.get(t) != "AVAILABLE" for t in _COMMAND_TOOLS):
            raise CommandFailure(DARWIN_MANAGER_REVIEW_PENDING)

    def start_and_wait(
        self, command: str, workdir: Path, stdin: str | None, wait_seconds: float
    ) -> str:
        response = self.client.start(
            self.socket_path,
            command=command,
            workdir=workdir,
            stdin=stdin,
            wait_seconds=wait_seconds,
            call_id=self.bindings.call_id(),
        )
        job_id = str(response["job_id"])
        if response.get("state") != "running":
            # The reply state is never final (R-J2-F4): the spool record is.
            # Wait briefly for the manager to persist the exit, like Linux.
            self.await_exit(job_id, EXIT_RECORD_GRACE_S)
        return job_id

    def _meta(self, job_id: str) -> dict | None:
        return self.bindings.store.read_meta(self.jobs_dir, job_id)

    def stop_job(self, job_id: str) -> dict | None:
        meta = self._meta(job_id)
        if meta is None:
            return None
        if meta.get("authority") == "UNKNOWN":
            raise CommandFailure(self.bindings.owner_lost_refusal)
        self.bindings.check_partial(meta)
        state = self._state(job_id, None)  # an unreachable manager fails the stop
        if state is None or state["state"] != "running":
            return state
        self.client.stop(self.socket_path, job_id, call_id=self.bindings.call_id())
        return self.job_state(job_id)

    def _reachable(self) -> bool:
        try:
            self.client.ping(self.socket_path)
        except (CommandFailure, RuntimeError, OSError):
            return False
        return True

    def job_state(self, job_id: str) -> dict | None:
        return self._state(job_id, self._reachable)

    def _state(self, job_id: str, reachable: Callable[[], bool] | None) -> dict | None:
        """Spool state; ``reachable`` verifies a non-terminal record (SD-41)."""
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
        elif reachable is not None and not reachable():
            state, note = "unknown", DARWIN_MANAGER_UNAVAILABLE_NOTE  # SD-41
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
        ids = self.bindings.store.list_job_ids(self.jobs_dir)
        verdict: list[bool] = []

        def reachable() -> bool:  # SD-41: at most one ping per listing
            if not verdict:
                verdict.append(self._reachable())
            return verdict[0]

        states = [s for jid in ids if (s := self._state(jid, reachable)) is not None]
        states.sort(key=lambda s: s["started_at"], reverse=True)
        return states

    def await_exit(self, job_id: str, timeout: float) -> dict | None:
        deadline = time.monotonic() + timeout
        state = self.job_state(job_id)  # SD-41: verified before and after the wait
        while state is not None and state["state"] == "running":
            if time.monotonic() >= deadline:
                return self.job_state(job_id)
            time.sleep(0.05)
            state = self._state(job_id, None)
        return state

    def read_log(self, job_id: str) -> bytes:
        return self.bindings.store.read_log(self.jobs_dir, job_id)

    def read_log_range(
        self, job_id: str, start: int, max_bytes: int
    ) -> tuple[bytes, int]:
        store = self.bindings.store
        return store.read_log_range(self.jobs_dir, job_id, start, max_bytes)

    def job_processes(self, job_id: str, max_cmd_chars: int = 200) -> list[dict]:
        # JCRP-F6: the manager lists its own verified, running group read-only;
        # the MCP server never inspects a pid from disk. Unavailable -> [].
        processes = getattr(self.client, "processes", None)
        if processes is None:
            return []
        try:
            reply = processes(self.socket_path, job_id, max_cmd_chars=max_cmd_chars)
        except (CommandFailure, RuntimeError, OSError):
            return []
        listing = reply.get("processes")
        if not isinstance(listing, list):
            return []
        # The A3 reply is sort_keys JSON: rebuild each item in the Linux
        # job_processes key order (STEER-03); other keys follow, never dropped.
        order = ("pid", "state", "etime_s", "cpu_s", "cmd")
        return [
            {**{key: item[key] for key in order if key in item}, **item}
            if isinstance(item, dict)
            else item
            for item in listing
        ]

    def disclose_status(self, job_id: str, reply: CommandReply) -> CommandReply:
        """Add D-1 (owner lost), SD-41 (unverified) and D-2 (sampled) text."""
        state = self.job_state(job_id)
        if state is None:
            return reply
        summary, payload = reply.summary, dict(reply.payload)
        note = state.get("note")
        if note is None and payload.get("state") == "unknown":
            note = DARWIN_MANAGER_UNAVAILABLE_NOTE  # rendered unverified, never "gone"
        if note:
            # D-1 replaces the Linux "process is gone" text: never gone or exited.
            summary = f"Job {job_id} state unknown: {note}."
            payload["state"], payload["note"] = "unknown", note
        if isinstance(resources := state.get("resource_usage"), dict):
            payload["resource_usage"] = {**resources, "accounting": RESOURCES_SAMPLED}
            summary = f"{summary} Resource usage is {RESOURCES_SAMPLED}."
        return CommandReply(summary, payload)


_native_release_states: dict[str, str] | None = None
_native_backend_factory: Callable[[], CommandBackend] | None = None


def configure_native_release_states(states: dict[str, str] | None) -> None:
    """Receive committed per-tool release states from the composition root."""
    global _native_release_states
    _native_release_states = None if states is None else dict(states)


def configure_native_command_backend(
    factory: Callable[[], CommandBackend] | None,
) -> None:
    """Receive the composed-owner backend factory from the composition root."""
    global _native_backend_factory
    _native_backend_factory = factory


def create_command_backend() -> CommandBackend:
    """Capture engine settings at default selection, before accepting requests."""
    # Uncomposed callers on other hosts get an inert backend, never Linux jobs.
    # Native executors are injected by the application composition root.
    if platform.system() != "Linux":
        # The composition root hands in the composed owner's backend (or its
        # release states), so the focused Commands child serves the same
        # metadata as the root; no embedded execution here.
        if _native_backend_factory is not None:
            return _native_backend_factory()
        return RestrictedCommandBackend(release_states=_native_release_states)
    import_module("binnacle.features.commands.jobs")
    import_module("binnacle.features.commands.job_owner")
    return DurableCommandBackend()
