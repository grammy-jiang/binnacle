"""Serve a ``DarwinJobManager`` over A3 for one manager process lifetime.

The jobs-dir writer lock spans recovery, serving and close. The sole reaper
thread must outlive serving; if it ends early the manager stops (non-zero), so
launchd restarts it and D-1 recovery applies.

``main`` is the com.binnacle.jobs entry point (launchd KeepAlive
SuccessfulExit=false). Its only input is the Binnacle config named by
``BINNACLE_CONFIG_FILE``. It exits 0 only for the provisioner's quiet-window
stop: the provisioner checks the ping counts, writes the private stop marker
``<runtime root>/<socket name>.stop`` holding ``{"owner_instance_id": ...}``
from that ping, then boots the manager out. Every other stop exits non-zero.

D1: a removed, replaced or stale socket endpoint (or a removed runtime root)
never ends serving while this incarnation owns jobs: ``serve_endpoint``
recreates the private 0700 root and publishes a fresh generation.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path

from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.contracts.process_contracts import JOB_MANAGER_UNAVAILABLE
from binnacle.platform.darwin.generation_runtime import (
    bounded_json,
    check_socket_path,
    open_private_root,
    open_service_lease,
    private_file,
    release_lease,
    resolve_runtime_paths,
    unlink_owned,
)
from binnacle.platform.darwin.job_group_fence import WAITID_REQUIRED
from binnacle.platform.darwin.job_manager_config import read_config
from binnacle.platform.darwin.job_manager_procinfo import (
    boot_id,
    group_listing,  # noqa: F401 - job_group_fence imports it from here (MS1 split)
)
from binnacle.platform.darwin.job_manager_records import (
    jobs_dir_writer,
    list_job_ids,
    read_meta,
)
from binnacle.platform.darwin.job_manager_service import (
    MANAGER_LABEL,
    DarwinJobManager,
)
from binnacle.platform.darwin.job_manager_telemetry import configure_job_manager_logging
from binnacle.platform.darwin.job_process_owner import DarwinJobProcessOwner
from binnacle.startup_imports import (
    StartupImportFailed,
    clear_record,
    import_manager_modules,
    record_start_failure,
    state_root_of,
)

log = logging.getLogger("binnacle.job_manager")
EX_FAILED, EX_USAGE, EX_TEMPFAIL, EX_CONFIG = 1, 64, 75, 78  # sysexits.h
STOP_MARKER_SUFFIX = ".stop"
STOP_PENDING_CODE = "manager_stopping"  # D2: typed, retryable start refusal
STOP_MARKER_AGE_S = (-5.0, 300.0)  # SR6-F1: honored only for -5 s <= age < 300 s
SUN_PATH_MAX = 104  # Darwin sockaddr_un.sun_path bytes, terminating NUL included
REBIND_DELAY_S = (0.1, 5.0)  # D1: first and longest wait before an endpoint rebind
REBIND_WARN_S = 60.0  # SR6-F4: one endpoint-loss warning per code per 60 s


def serve_job_manager(
    manager: DarwinJobManager,
    *,
    socket_path: Path,
    lease: ServiceLease,
    stop: threading.Event,
) -> int:
    """Serve until ``stop``; the jobs-dir writer lock spans recovery and close."""
    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise RuntimeError("darwin_exclusive_reaper_required")
    # JCRP-F2: SIGTERM (or a reaper death) sets ``stop``; sharing it as the
    # manager's stopping event releases every waiting handler at once, so the
    # serving drain never delays close() past launchd's ExitTimeOut.
    manager.stopping = stop
    manager.stop_pending = lambda: stop_pending_refusal(
        socket_path, manager.owner_instance_id
    )
    with jobs_dir_writer(manager.jobs_dir) as lock_fd:
        manager.hold_jobs_dir(lock_fd)  # M1-2, STEER-01; R-M1-N1: fail closed
        recovered = manager.recover()
        log.info("event=job_manager_start pid=%d recovered=%d", os.getpid(), recovered)
        halt, died = threading.Event(), threading.Event()

        def reap() -> None:
            try:
                manager.reap_forever(halt)
            except Exception:
                log.exception("event=job_manager_reaper_error")
            finally:
                if not halt.is_set():  # never serve without a reaper (D-1 on restart)
                    log.error("event=job_manager_reaper_stopped")
                    died.set()
                    stop.set()

        reaper = threading.Thread(target=reap, name="job-manager-reaper")
        reaper.start()
        try:
            serve_endpoint(manager, socket_path=socket_path, lease=lease, stop=stop)
        finally:
            halt.set()
            reaper.join()
            manager.close()
    if died.is_set():
        raise RuntimeError("job_manager_reaper_stopped")  # exit non-zero; restart
    return recovered


def require_socket_path(socket_path: Path) -> None:
    """D1: fail closed, clearly, when ``sun_path`` cannot hold the path + NUL."""
    size = len(os.fsencode(socket_path))
    if size >= SUN_PATH_MAX:
        limit = SUN_PATH_MAX - 1
        raise ValueError(
            f"darwin_socket_path_too_long: {size} bytes > {limit}: {socket_path}"
        )
    check_socket_path(socket_path)


def owns_jobs(manager: DarwinJobManager) -> bool:
    """Any doubt counts as owning (SR6-F3: running or unknown, this incarnation's)."""
    try:
        jobs, me = manager.jobs_dir, manager.owner_instance_id
        metas = {i: read_meta(jobs, i) or {} for i in list_job_ids(jobs)}
        mine = [i for i, meta in metas.items() if meta.get("owner_instance_id") == me]
        return any(manager.state(i) != "exited" for i in mine)
    except Exception:  # noqa: BLE001 - fail safe: keep serving the jobs
        return True


def fresh_lease(socket_path: Path, label: str) -> ServiceLease:
    """D1: recreate the private 0700 runtime root if gone; a new generation."""
    require_socket_path(socket_path)
    root, generation = socket_path.parent, secrets.token_hex(16)
    os.close(open_private_root(root, create=True))
    return open_service_lease(root=root, label=label, generation=generation)


def serve_endpoint(
    manager: DarwinJobManager,
    *,
    socket_path: Path,
    lease: ServiceLease,
    stop: threading.Event,
) -> None:
    """D1: serve until ``stop``, rebinding a lost endpoint while owning jobs.

    A first-binding failure while owning no job raises (startup contract). Any
    other loss of socket, .auth or root rebinds under a fresh lease after a
    capped backoff, even without jobs once rebound (SR6-N1). The jobs-dir writer
    lock is held throughout; foreign debris is never adopted (A3 reclaim).
    SR6-F4: a superseded fresh lease is released before the next is minted."""
    from binnacle.platform.darwin.ipc_transport import serve_authenticated as serve

    current: ServiceLease | None = lease
    delay, quiet = REBIND_DELAY_S[0], dict[str, tuple[float, int]]()
    while True:
        started = time.monotonic()
        try:
            if current is None:
                current = fresh_lease(socket_path, lease.label)
            serve(socket_path, lease=current, handler=manager.handle, stop=stop)
            return  # serving ends only once ``stop`` is set
        except (NativeCapabilityError, OSError, ValueError) as exc:
            if stop.is_set() or (current is lease and not owns_jobs(manager)):
                raise
            code = getattr(exc, "code", type(exc).__name__)
            warned_at, suppressed = quiet.get(code, (float("-inf"), 0))
            if time.monotonic() - warned_at >= REBIND_WARN_S:  # per code (SR6-F4)
                event = "event=job_manager_endpoint_lost code=%s rebind_in_s=%.1f"
                log.warning(event + " suppressed=%d", code, delay, suppressed)
                warned_at, suppressed = time.monotonic(), -1  # this one is logged
            quiet[code] = (warned_at, suppressed + 1)
        if time.monotonic() - started > REBIND_DELAY_S[1]:
            delay = REBIND_DELAY_S[0]  # a long-served endpoint restarts the backoff
        if current is not None and current is not lease:
            release_lease(current, None)  # the live (first) lease is never released
        current = None
        if stop.wait(delay):
            return
        delay = min(delay * 2, REBIND_DELAY_S[1])


def inherited_fds_cloexec() -> None:
    """RJ1-F6: no descriptor inherited at start (fd >= 3) may reach a job."""
    for name in os.listdir("/dev/fd"):
        if name.isdigit() and int(name) > 2:
            with suppress(OSError):
                os.set_inheritable(int(name), False)


def compose_owner(boot: str) -> DarwinJobProcessOwner:
    """The J1 owner, without its own reaper thread: ``reap_forever`` is the one."""
    return DarwinJobProcessOwner(boot_id=boot, start_reaper=False)


def stop_marker_names(socket_path: Path, owner: str, *, consume: bool = False) -> bool:
    """D2 peek (``consume``: remove it). SR6-F1: only a FRESH own marker counts.

    Fresh: ``STOP_MARKER_AGE_S`` by the read file's ``st_mtime`` (format as
    before). A stale own marker logs a warning and is removed (the inode read)."""
    name = socket_path.name + STOP_MARKER_SUFFIX
    try:
        root = open_private_root(socket_path.parent)
    except NativeCapabilityError:
        return False
    try:
        try:
            with os.fdopen(private_file(root, name), "rb") as stream:
                info = os.fstat(stream.fileno())
                value = bounded_json(stream.read(65537))
        except (OSError, ValueError, NativeCapabilityError):
            return False
        age, mine = time.time() - info.st_mtime, value.get("owner_instance_id") == owner
        fresh = STOP_MARKER_AGE_S[0] <= age < STOP_MARKER_AGE_S[1]
        if mine and not fresh:
            log.warning("event=stop_marker_stale age_s=%.0f", age)
        if consume or (mine and not fresh):
            with suppress(OSError):  # never another entry, never a link target
                unlink_owned(root, name, (info.st_dev, info.st_ino))
    finally:
        os.close(root)
    return mine and fresh


def stop_pending_refusal(socket_path: Path, owner: str) -> dict[str, object] | None:
    """D2: typed, retryable; the existing manager-unavailable text, no record."""
    if not stop_marker_names(socket_path, owner):
        return None
    log.info("event=job_start_refused reason=stop_marker")
    error = f"{JOB_MANAGER_UNAVAILABLE} at {socket_path}: {STOP_PENDING_CODE}"
    return {"ok": False, "error": error, "code": STOP_PENDING_CODE, "retryable": True}


def provisioner_stop(socket_path: Path, owner_instance_id: str) -> bool:
    """Consume the quiet-window stop marker; it must name this incarnation."""
    return stop_marker_names(socket_path, owner_instance_id, consume=True)


def record_import_failure(failure: StartupImportFailed) -> None:
    """E1-a5: the entry's own record write; the config may be what failed."""
    try:
        root = state_root_of(read_config().jobs.dir)
    except Exception:  # noqa: BLE001 - no configured root: the log line remains
        log.error("event=startup_import_record_error process=job-manager")
        return
    record_start_failure("job-manager", failure, root)


def clear_record_when_published(
    socket_path: Path,
    lease: ServiceLease,
    stop: threading.Event,
    clear: Callable[[], None],
) -> threading.Thread:
    """E1-a5: run ``clear`` once THIS process has published its endpoint.

    The published ``.auth`` credentials carry this process's pid and its lease
    generation; only then is the start successful (never at entry, never on a
    stale endpoint of an earlier incarnation). Only those two fields are read.
    """
    auth = socket_path.with_name(socket_path.name + ".auth")

    def published() -> bool:
        try:
            data = json.loads(auth.read_bytes())
            return data["pid"] == os.getpid() and data["generation"] == lease.generation
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def watch() -> None:
        while not stop.wait(0.05):
            if published():
                clear()
                return

    thread = threading.Thread(
        target=watch, name="job-manager-start-record", daemon=True
    )
    thread.start()
    return thread


def main(argv: Sequence[str] | None = None) -> int:
    """Run com.binnacle.jobs: no CLI arguments; configuration is the only input."""
    if list(sys.argv[1:] if argv is None else argv):
        print(
            "usage: python -m binnacle.platform.darwin.job_manager_service",
            file=sys.stderr,
        )
        return EX_USAGE
    configure_job_manager_logging()
    # E1: never first-import a later deploy's source. E1-a4: a required import
    # failure raises StartupImportFailed (exit EX_STARTUP_IMPORT, 70) before
    # the lease and the socket. E1-a5: this entry writes the record.
    try:
        import_manager_modules()
    except StartupImportFailed as failure:
        record_import_failure(failure)
        raise
    if not hasattr(os, "waitid"):  # JCR-F1: refuse before any lease or spawn
        log.error("event=job_manager_refused reason=%s", WAITID_REQUIRED)
        return EX_CONFIG
    inherited_fds_cloexec()
    try:
        settings = read_config()
        socket_path = settings.jobs.socket_path or resolve_runtime_paths().jobs_socket
        require_socket_path(socket_path)
        generation = secrets.token_hex(16)
        lease = open_service_lease(
            root=socket_path.parent, label=MANAGER_LABEL, generation=generation
        )
    except Exception:
        log.exception("event=job_manager_config_error")
        return EX_CONFIG
    try:
        boot = boot_id()
        owner = compose_owner(boot)
        manager = DarwinJobManager(
            owner=owner,
            jobs_dir=settings.jobs.dir,
            boot_id=boot,
            wait_max_s=settings.run_command.wait_max_s,
            keep_newest=settings.jobs.keep_newest,
        )
    except Exception:
        log.exception("event=job_manager_owner_unavailable")
        return EX_FAILED
    reaper = owner.reaper_running
    log.info("event=job_manager_compose owner_reaper_thread=%s", reaper)
    stop = threading.Event()
    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, lambda *_: stop.set())
    clear_record_when_published(
        socket_path,
        lease,
        stop,
        # E1-a5: cleared only once this process has published its endpoint.
        lambda: clear_record("job-manager", state_root_of(settings.jobs.dir)),
    )
    try:
        serve_job_manager(manager, socket_path=socket_path, lease=lease, stop=stop)
    except Exception as exc:
        busy = "already owns" in str(exc)
        busy = busy or getattr(exc, "code", None) == "ipc_duplicate_starter"
        log.exception("event=job_manager_stopped_failed busy=%s", busy)
        return EX_TEMPFAIL if busy else EX_FAILED
    if provisioner_stop(socket_path, manager.owner_instance_id):
        log.info("event=job_manager_stopped reason=provisioner_quiet_window")
        return 0
    log.warning("event=job_manager_stopped reason=unrequested")
    return EX_FAILED
