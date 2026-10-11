"""Darwin stable Job Manager: unchanged RPC v1 objects over A3 authenticated IPC.

Sole writer for jobs its ``DarwinJobOwner`` spawned; nothing from disk, a peer or
ps is adopted. D-1: other incarnations' unfinished records become UNKNOWN.
Layering forbids Commands imports: ``job_store``/``job_stop`` values are restated
and pinned to the Linux source by tests. A3's cooperative-UID boundary applies.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import math
import os
import re
import shutil
import signal
import threading
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.contracts.process_contracts import OwnedJobExit
from binnacle.provenance import runtime_provenance

log = logging.getLogger("binnacle.job_manager")
Partial, Unowned = pc.JobSignalDeliveryError, pc.UnverifiedJobProcess

PROTOCOL_VERSION = 1  # job_client.PROTOCOL_VERSION; the RPC objects are unchanged
MANAGER_LABEL = "com.binnacle.jobs"
AUTHORITY_FIELD, AUTHORITY_UNKNOWN = "authority", "UNKNOWN"
STOP_SIGTERM_GRACE_S, STOP_SIGKILL_GRACE_S = 5.0, 2.0  # Linux jobs values
_ENV = "PAGER=cat GIT_PAGER=cat GIT_TERMINAL_PROMPT=0 PYTHONUNBUFFERED=1 CI=1"
_ENV += " BINNACLE=1 DEBIAN_FRONTEND=noninteractive"
ENV_OVERRIDES: Mapping[str, str] = dict(i.split("=", 1) for i in _ENV.split())
META_REQUIRED = ("command", "workdir", "pid", "started_at")
PARTIAL_SIGNAL_FIELD = "stop_signal_partial"
PARTIAL_SIGNAL_MESSAGE = "previous verified process signal delivery was incomplete"
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_STOP_PHASES: tuple[Literal["terminate", "kill"], ...] = ("terminate", "kill")


@contextmanager
def _flock(path: Path, operation: int, busy: str = "") -> Iterator[None]:
    """CLOEXEC so spawned jobs never inherit (and pin) a manager lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags, 0o600)
    try:
        try:
            fcntl.flock(fd, operation)
        except BlockingIOError as exc:
            raise RuntimeError(busy) from exc
        yield
    finally:
        os.close(fd)


def jobs_dir_writer(jobs_dir: Path) -> Any:
    """Lifetime singleton: one manager writer per jobs dir, any runtime root."""
    busy = f"job manager already owns {jobs_dir}"
    return _flock(jobs_dir / ".manager.lock", fcntl.LOCK_EX | fcntl.LOCK_NB, busy)


def _terminal(meta: Mapping[str, object]) -> bool:
    return "exit_code" in meta or "signal" in meta


def read_meta(root: Path, job_id: str) -> dict[str, Any] | None:
    """``job_store.read_meta``: a complete record, or None when unusable."""
    try:
        meta = json.loads((root / job_id / "meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict) or any(k not in meta for k in META_REQUIRED):
        return None
    return meta


def list_job_ids(root: Path) -> list[str]:
    try:
        return [path.name for path in root.iterdir() if path.is_dir()]
    except OSError:
        return []


class DarwinJobManager:
    """RPC v1 dispatcher and durable-record writer for one owner incarnation."""

    def __init__(
        self,
        *,
        owner: pc.DarwinJobOwner,
        jobs_dir: Path,
        boot_id: str,
        wait_max_s: float,
        keep_newest: int,
        grace: tuple[float, float] = (STOP_SIGTERM_GRACE_S, STOP_SIGKILL_GRACE_S),
    ) -> None:
        self.owner, self.owner_instance_id = owner, owner.owner_instance_id
        self.jobs_dir, self.boot_id = jobs_dir, boot_id
        self.wait_max_s, self.keep_newest = float(wait_max_s), int(keep_newest)
        self.grace, self.provenance = grace, runtime_provenance()
        self._lock = threading.RLock()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """A process-local lock alone is insufficient; add the jobs-dir flock."""
        with self._lock, _flock(self.jobs_dir / ".lock", fcntl.LOCK_EX):
            yield

    def _write_meta(self, job_id: str, meta: Mapping[str, object]) -> None:
        """Atomic replace with file and directory fsync (durable before signal)."""
        directory = self.jobs_dir / job_id
        temp = directory / f".meta.{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            with os.fdopen(os.open(temp, flags, 0o600), "wb") as stream:
                stream.write(json.dumps(dict(meta)).encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, directory / "meta.json")
        finally:
            temp.unlink(missing_ok=True)
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _meta(self, job_id: str) -> dict[str, Any] | None:
        return read_meta(self.jobs_dir, job_id)

    def handle(self, payload: Mapping[str, object]) -> dict[str, Any]:
        """A3 handler with the Linux ``_Handler`` per-request error isolation."""
        request = dict(payload)
        try:
            return self.dispatch(request)
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("event=job_manager_request_invalid op=%s", request.get("op"))
            return {"ok": False, "error": f"invalid job-manager request: {exc}"}
        except Exception:
            log.exception("event=job_manager_request_error op=%s", request.get("op"))
            return {"ok": False, "error": "internal job-manager error"}

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("version") != PROTOCOL_VERSION:
            return {"ok": False, "error": "unsupported job-manager protocol version"}
        op = request.get("op")
        if op == "ping":
            reply: dict[str, Any] = {"ok": True, "version": PROTOCOL_VERSION}
            reply.update(owner_instance_id=self.owner_instance_id, boot_id=self.boot_id)
            reply["pid"] = os.getpid()
            reply["package_version"] = self.provenance.package_version
            return {**reply, "revision": self.provenance.revision}
        if op == "start":
            return self._start(request)
        if op == "stop":
            return self._stop(request)
        return {"ok": False, "error": f"unknown job-manager operation {op!r}"}

    def _start(self, request: dict[str, Any]) -> dict[str, Any]:
        command = request["command"]
        workdir = Path(request["workdir"])
        stdin = request.get("stdin")
        wait_seconds = float(request.get("wait_seconds", 0.0))
        call_id = str(request.get("call_id") or "-")
        if not isinstance(command, str) or not isinstance(stdin, (str, type(None))):
            raise TypeError("command/stdin have invalid types")
        if not workdir.is_dir():
            raise ValueError(f"workdir is not a directory: {workdir}")
        if not (math.isfinite(wait_seconds) and 0 <= wait_seconds <= self.wait_max_s):
            raise ValueError("wait_seconds outside manager bounds")
        try:
            job_id = self._launch(command, workdir, stdin, call_id)
        except (OSError, NativeCapabilityError) as exc:
            return {"ok": False, "error": f"could not start job: {exc}"}
        exited = self.owner.wait(job_id, wait_seconds)
        if exited is not None:
            self.record_exit(exited)
        return {"ok": True, "job_id": job_id, "state": self.state(job_id)}

    def _launch(
        self, command: str, workdir: Path, stdin: str | None, call_id: str
    ) -> str:
        """Reserve meta, spawn, complete meta: one interprocess transaction."""
        with self._transaction():
            self._prune(reserve=1)
            job_id = uuid.uuid4().hex[:12]  # job_store.new_job_id
            directory = self.jobs_dir / job_id
            directory.mkdir(parents=True)
            stdin_path = directory / "stdin"
            if stdin is not None:
                stdin_path.write_bytes(stdin.encode("utf-8"))
            meta: dict[str, Any] = dict.fromkeys(("pid", "pgid", "starttime"))
            meta.update(command=command, workdir=str(workdir), started_at=time.time())
            meta.update(call_id=call_id, owner="manager", schema_version=2)
            meta.update(owner_instance_id=self.owner_instance_id, boot_id=self.boot_id)
            meta["command_hash"] = hashlib.sha256(command.encode()).hexdigest()[:12]
            self._write_meta(job_id, meta)  # reserved before any spawn
            env = {**os.environ, **ENV_OVERRIDES, "BINNACLE_JOB_ID": job_id}
            source = stdin_path if stdin is not None else Path(os.devnull)
            try:
                with (
                    open(directory / "out.log", "wb") as out,
                    open(source, "rb") as inf,
                ):
                    argv = ["bash", "-c", command]
                    process = self.owner.spawn(
                        job_id, argv, workdir=workdir, env=env, stdin=inf, output=out
                    )
            except BaseException:
                if self.owner.authority(job_id).authority == "OWNED":
                    self._kill_quietly(job_id)  # never leave it running unobserved
                else:
                    shutil.rmtree(directory, ignore_errors=True)
                raise
            meta.update(pid=process.pid, pgid=process.pgid, starttime=process.birth)
            try:
                self._write_meta(job_id, meta)
            except OSError:
                self._kill_quietly(job_id)
                raise
            log.info("event=job_start job_id=%s call=%s owner=manager", job_id, call_id)
            return job_id

    def _kill_quietly(self, job_id: str) -> None:
        try:
            self.owner.signal_owned_group(job_id, "kill")
        except (Unowned, Partial, OSError):
            log.warning("event=job_start_cleanup_unverified job_id=%s", job_id)

    def _stop(self, request: dict[str, Any]) -> dict[str, Any]:
        job_id = request["job_id"]
        call_id = str(request.get("call_id") or "-")
        if not isinstance(job_id, str):
            raise TypeError("job_id must be a string")
        meta = self._meta(job_id) if _JOB_ID.fullmatch(job_id) else None
        try:
            if meta is not None and meta.get(PARTIAL_SIGNAL_FIELD) is True:
                raise Partial(PARTIAL_SIGNAL_MESSAGE)
            if meta is None:
                return {"ok": False, "error": f"no job with id {job_id!r}"}
            foreign = meta.get("owner_instance_id") != self.owner_instance_id
            lost = meta.get(AUTHORITY_FIELD) == AUTHORITY_UNKNOWN
            if lost or (foreign and not _terminal(meta)):
                log.warning("event=job_stop_owner_lost job_id=%s", job_id)
                return {"ok": False, "error": pc.OWNER_LOST_STOP_REFUSED}
            state = "exited" if _terminal(meta) else self._stop_owned(job_id, call_id)
        except Partial as exc:
            log.warning("event=job_manager_stop_partial job_id=%s", job_id)
            return {"ok": False, "error": f"job stop partially failed: {exc}"}
        log.info("event=job_stop job_id=%s call=%s state=%s", job_id, call_id, state)
        return {"ok": True, "job_id": job_id, "state": state}

    def _stop_owned(self, job_id: str, call_id: str) -> str:
        """A1 order: durable prepare -> TERM -> grace -> KILL -> reaper evidence."""
        with self._transaction():
            meta = self._meta(job_id)
            if meta is not None and not _terminal(meta):
                meta.update(stop_requested=True, stop_call_id=call_id)
                self._write_meta(job_id, meta)
        partial: list[Exception] = []
        for intent, grace in zip(_STOP_PHASES, self.grace, strict=True):
            try:
                self.owner.signal_owned_group(job_id, intent)
            except Unowned:
                break  # leader reaped (pgid may recycle) or not ours: no signal
            except Partial as exc:
                partial.append(exc)
                self._persist_partial(job_id)
            exited = self.owner.wait(job_id, grace)
            if exited is not None:
                self.record_exit(exited)
                break
        deadline = time.monotonic() + self.grace[1]
        while (state := self.state(job_id)) != "exited" and time.monotonic() < deadline:
            time.sleep(0.02)
        if partial:
            raise Partial("; ".join(str(item) for item in partial))
        return state

    def _persist_partial(self, job_id: str) -> None:
        """Never acknowledge a partial stop unless its durable marker was written."""
        with self._transaction():  # an OSError surfaces as a failed request
            meta = self._meta(job_id)
            if meta is None:
                raise Partial("partial stop not persisted")
            self._write_meta(job_id, {**meta, PARTIAL_SIGNAL_FIELD: True})

    def state(self, job_id: str) -> str:
        """Linux vocabulary; uncertainty is ``unknown``, never ``exited``."""
        meta = self._meta(job_id)
        if meta is None or meta.get(AUTHORITY_FIELD) == AUTHORITY_UNKNOWN:
            return "unknown"
        if _terminal(meta):
            return "exited"
        if meta.get("owner_instance_id") != self.owner_instance_id:
            return "unknown"
        seen = self.owner.authority(job_id)
        return "running" if seen.authority == "OWNED" and seen.alive else "unknown"

    def record_exit(self, exited: OwnedJobExit) -> bool:
        """Idempotent terminal write for this incarnation's own records only."""
        with self._transaction():
            meta = self._meta(exited.job_id)
            if meta is None or meta.get("owner_instance_id") != self.owner_instance_id:
                log.warning("event=job_exit_unrecorded job_id=%s", exited.job_id)
                return False
            if _terminal(meta):
                return True
            if exited.signal is not None:
                meta.update(signal=exited.signal, exit_code=None)
            else:
                meta["exit_code"] = exited.exit_code
            meta["ended_at"] = time.time()
            reason = "signal" if exited.signal is not None else "normal_exit"
            if exited.termination_reason == "owner_restart":
                reason = "owner_restart"
            stopped = meta.get("stop_requested")
            meta["termination_reason"] = "stop_requested" if stopped else reason
            try:
                self._write_meta(exited.job_id, meta)
            except OSError:
                log.warning("event=job_exit_unrecorded job_id=%s", exited.job_id)
                return False
        log.info("event=job_exit job_id=%s", exited.job_id)
        return True

    def _mark_unknown(self, job_id: str, meta: dict[str, Any], reason: str) -> None:
        meta.update(exit_code=None, signal=None, ended_at=time.time())
        meta.update(termination_reason=reason, **{AUTHORITY_FIELD: AUTHORITY_UNKNOWN})
        self._write_meta(job_id, meta)
        log.warning("event=job_interrupted job_id=%s reason=%s", job_id, reason)

    def recover(self) -> int:
        """Unfinished v2 records of other incarnations -> ``authority=UNKNOWN``."""
        recovered = 0
        with self._transaction():
            for job_id in list_job_ids(self.jobs_dir):
                meta = self._meta(job_id)
                if meta is None or meta.get("schema_version") != 2 or _terminal(meta):
                    continue
                if meta.get("owner_instance_id") == self.owner_instance_id:
                    continue
                rebooted = meta.get("boot_id") != self.boot_id
                reason = "host_reboot" if rebooted else "owner_restart"
                if meta.get("stop_requested"):
                    reason = "stop_requested"
                self._mark_unknown(job_id, meta, reason)
                recovered += 1
        return recovered

    def _prune(self, reserve: int = 0) -> None:
        """Retention spares running, reserved and UNKNOWN records."""
        keep = max(0, self.keep_newest - max(0, reserve))
        try:
            dirs = [d for d in self.jobs_dir.iterdir() if d.is_dir()]
            dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        except OSError:
            return
        for stale in dirs[keep:]:
            meta = self._meta(stale.name) or {"exit_code": 0}  # unusable: deletable
            if _terminal(meta) and meta.get(AUTHORITY_FIELD) != AUTHORITY_UNKNOWN:
                shutil.rmtree(stale, ignore_errors=True)

    def reap_forever(self, stop: threading.Event) -> None:
        """Drive the owner's sole reaper and persist every exit it reports."""
        while not stop.is_set():
            try:
                exits = self.owner.reap_exits(0.1)
            except Exception:
                log.exception("event=job_manager_reap_error")
                stop.wait(0.1)
                continue
            for exited in exits:
                self.record_exit(exited)

    def close(self) -> Sequence[OwnedJobExit]:
        """Persist reaped exits BEFORE returning; unreaped stay UNKNOWN."""
        exits = self.owner.close()
        for exited in exits:
            self.record_exit(exited)
        with self._transaction():
            for job_id in list_job_ids(self.jobs_dir):
                meta = self._meta(job_id) or {"exit_code": None}
                mine = meta.get("owner_instance_id") == self.owner_instance_id
                if mine and not _terminal(meta):
                    self._mark_unknown(job_id, meta, "owner_restart")
        return exits


def serve_job_manager(
    manager: DarwinJobManager,
    *,
    socket_path: Path,
    lease: ServiceLease,
    stop: threading.Event,
) -> int:
    """Serve until ``stop``; the jobs-dir writer lock spans recovery and close."""
    from binnacle.platform.darwin.ipc_transport import serve_authenticated

    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise RuntimeError("darwin_exclusive_reaper_required")
    with jobs_dir_writer(manager.jobs_dir):
        recovered = manager.recover()
        log.info("event=job_manager_start pid=%d recovered=%d", os.getpid(), recovered)
        halt = threading.Event()
        reaper = threading.Thread(target=manager.reap_forever, args=(halt,))
        reaper.start()
        try:
            handler = manager.handle
            serve_authenticated(socket_path, lease=lease, handler=handler, stop=stop)
        finally:
            halt.set()
            reaper.join()
            manager.close()
    return recovered


class DarwinJobManagerError(RuntimeError):
    """The manager could not accept or complete an ownership operation."""


class DarwinJobClient:
    """``job_client`` over A3: one channel per call; only connect is retried."""

    def __init__(
        self, *, label: str = MANAGER_LABEL, error_type: type[Exception] | None = None
    ) -> None:
        self.label, self.error_type = label, error_type

    def _error(self, message: str) -> Exception:
        return (self.error_type or DarwinJobManagerError)(message)

    def request(
        self, socket_path: Path, payload: dict[str, Any], *, timeout_s: float = 5.0
    ) -> dict[str, Any]:
        from binnacle.platform.darwin.generation_runtime import (
            discover_service_lease as discover,
        )
        from binnacle.platform.darwin.ipc_transport import connect_authenticated

        failure: Exception | None = None
        for _attempt in range(2):  # a rotated generation re-reads credentials
            try:
                lease = discover(root=socket_path.parent, label=self.label)
                channel = connect_authenticated(socket_path, lease=lease, timeout_s=5)
                break
            except (NativeCapabilityError, OSError) as exc:
                failure = exc
        else:
            code = getattr(failure, "code", type(failure).__name__)
            message = f"{pc.JOB_MANAGER_UNAVAILABLE} at {socket_path}: {code}"
            raise self._error(message) from failure
        try:  # a dispatched request is never replayed
            response = channel.request(payload, timeout_s=min(60.0, timeout_s))
        except NativeCapabilityError as exc:
            message = "job manager closed the connection without a response"
            raise self._error(message) from exc
        finally:
            channel.close()
        if response.get("ok") is not True:
            error = response.get("error") or "job manager request failed"
            raise self._error(str(error))
        return dict(response)

    def ping(self, socket_path: Path) -> dict[str, Any]:
        return self.request(socket_path, {"version": PROTOCOL_VERSION, "op": "ping"})

    def start(
        self,
        socket_path: Path,
        *,
        command: str,
        workdir: Path,
        stdin: str | None,
        wait_seconds: float,
        call_id: str,
    ) -> dict[str, Any]:
        payload = {"version": PROTOCOL_VERSION, "op": "start", "command": command}
        payload.update(workdir=str(workdir), stdin=stdin, wait_seconds=wait_seconds)
        payload["call_id"] = call_id
        timeout = max(5.0, wait_seconds + 5.0)
        return self.request(socket_path, payload, timeout_s=timeout)

    def stop(
        self, socket_path: Path, job_id: str, *, call_id: str = "-"
    ) -> dict[str, Any]:
        payload = {"version": PROTOCOL_VERSION, "op": "stop", "job_id": job_id}
        payload["call_id"] = call_id
        return self.request(socket_path, payload, timeout_s=10.0)
