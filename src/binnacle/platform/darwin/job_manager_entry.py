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
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import secrets
import signal
import sys
import threading
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.darwin.generation_runtime import (
    bounded_json,
    check_socket_path,
    open_private_root,
    open_service_lease,
    private_file,
    resolve_runtime_paths,
)
from binnacle.platform.darwin.job_group_fence import WAITID_REQUIRED
from binnacle.platform.darwin.job_manager_service import (
    MANAGER_LABEL,
    DarwinJobManager,
    jobs_dir_writer,
)
from binnacle.platform.darwin.job_process_owner import DarwinJobProcessOwner

log = logging.getLogger("binnacle.job_manager")
EX_FAILED, EX_USAGE, EX_TEMPFAIL, EX_CONFIG = 1, 64, 75, 78  # sysexits.h
STOP_MARKER_SUFFIX = ".stop"
CONFIG_FILE_ENV = "BINNACLE_CONFIG_FILE"
# env_nested_delimiter overrides, and the runtime root the client would not share
_OVERRIDES = ("BINNACLE_JOBS__", "BINNACLE_RUN_COMMAND__", "BINNACLE_RUNTIME_DIR")
BOOT_SESSION = re.compile(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}")


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
    # JCRP-F2: SIGTERM (or a reaper death) sets ``stop``; sharing it as the
    # manager's stopping event releases every waiting handler at once, so the
    # serving drain never delays close() past launchd's ExitTimeOut.
    manager.stopping = stop
    with jobs_dir_writer(manager.jobs_dir):
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
            handler = manager.handle
            serve_authenticated(socket_path, lease=lease, handler=handler, stop=stop)
        finally:
            halt.set()
            reaper.join()
            manager.close()
    if died.is_set():
        raise RuntimeError("job_manager_reaper_stopped")  # exit non-zero; restart
    return recovered


class _Jobs(BaseModel):
    socket_path: Path | None = None
    dir: Path = Field(
        default_factory=lambda: Path.home() / ".local" / "state" / "binnacle" / "jobs"
    )
    keep_newest: int = Field(50, ge=1)


class _RunCommand(BaseModel):
    wait_max_s: int = 50


class ManagerConfig(BaseSettings):
    """The ``binnacle.config`` keys the manager needs, from the config file only.

    Layering forbids ``binnacle.platform`` importing ``binnacle.config`` (the
    top-level acyclic contract), so these keys and defaults are restated with
    the same TOML source and pinned to ``Settings`` by tests.
    """

    model_config = SettingsConfigDict(extra="ignore")

    jobs: _Jobs = Field(default_factory=_Jobs)
    run_command: _RunCommand = Field(default_factory=_RunCommand)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        default = Path.home() / ".config" / "binnacle" / "config.toml"
        toml_file = Path(os.environ.get(CONFIG_FILE_ENV, default))
        return (TomlConfigSettingsSource(settings_cls, toml_file=toml_file),)


def read_config() -> ManagerConfig:
    """Refuse environment overrides: the config file is the only input."""
    if any(name.startswith(_OVERRIDES) for name in os.environ):
        raise ValueError("job manager settings come from the config file only")
    return ManagerConfig()


def boot_id() -> str:
    """``kern.bootsessionuuid``: a public sysctl, new per boot, fixed within one.

    STEER-10: ``kern.boottime`` moves whenever the wall clock is set, so it
    cannot prove a reboot (``prior_boot``); ``kern.uuid`` is the kernel build.
    It is never process authority. The J1 owner is composed with this same id.
    """
    libc = ctypes.CDLL(None, use_errno=True)

    def sysctl(name: str, size: int) -> bytes:
        value, length = ctypes.create_string_buffer(size), ctypes.c_size_t(size)
        if libc.sysctlbyname(name.encode(), value, ctypes.byref(length), None, 0):
            raise OSError(ctypes.get_errno(), f"sysctl {name} failed")
        return value.raw[: length.value]

    session = sysctl("kern.bootsessionuuid", 64).rstrip(b"\0").decode("ascii")
    if not BOOT_SESSION.fullmatch(session.upper()):
        raise OSError("darwin_boot_identity_unavailable")
    return session.upper()


def prior_boot(meta: Mapping[str, object], current: str) -> bool:
    """STEER-10: the record's ``boot_id`` is provably an earlier boot's.

    Both ids must be boot sessions and differ. An absent, unreadable or
    other-format id proves nothing: the record stays UNKNOWN (fail closed).
    """
    ids = (meta.get("boot_id"), current)
    known = all(isinstance(i, str) and BOOT_SESSION.fullmatch(i) for i in ids)
    return known and ids[0] != ids[1]


def inherited_fds_cloexec() -> None:
    """RJ1-F6: no descriptor inherited at start (fd >= 3) may reach a job."""
    for name in os.listdir("/dev/fd"):
        if name.isdigit() and int(name) > 2:
            with suppress(OSError):
                os.set_inheritable(int(name), False)


def compose_owner(boot: str) -> DarwinJobProcessOwner:
    """The J1 owner, without its own reaper thread: ``reap_forever`` is the one."""
    return DarwinJobProcessOwner(boot_id=boot, start_reaper=False)


def provisioner_stop(socket_path: Path, owner_instance_id: str) -> bool:
    """Consume the quiet-window stop marker; it must name this incarnation."""
    name = socket_path.name + STOP_MARKER_SUFFIX
    try:
        root = open_private_root(socket_path.parent)
    except NativeCapabilityError:
        return False
    try:
        try:
            with os.fdopen(private_file(root, name), "rb") as stream:
                value = bounded_json(stream.read(65537))
        except (OSError, ValueError, NativeCapabilityError):
            return False
        with suppress(OSError):
            os.unlink(name, dir_fd=root)
    finally:
        os.close(root)
    return value.get("owner_instance_id") == owner_instance_id


def main(argv: Sequence[str] | None = None) -> int:
    """Run com.binnacle.jobs: no CLI arguments; configuration is the only input."""
    if list(sys.argv[1:] if argv is None else argv):
        print(
            "usage: python -m binnacle.platform.darwin.job_manager_service",
            file=sys.stderr,
        )
        return EX_USAGE
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not hasattr(os, "waitid"):  # JCR-F1: refuse before any lease or spawn
        log.error("event=job_manager_refused reason=%s", WAITID_REQUIRED)
        return EX_CONFIG
    inherited_fds_cloexec()
    try:
        settings = read_config()
        socket_path = settings.jobs.socket_path or resolve_runtime_paths().jobs_socket
        check_socket_path(socket_path)
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


# SD-59: only p_stat values with one Linux letter. SRUN is kept by XNU for a
# sleeping process too (R or S needs libproc thread states) and SIDL has no
# Linux state, so both stay unknown; SSTOP of a traced process may be Linux t.
_STATE_LETTERS = {3: "S", 4: "T", 5: "Z"}  # SSLEEP, SSTOP, SZOMB
_UNKNOWN_STATE = "?"  # D-2: not a state letter, never invented
_P_TRACED = 0x800  # kinfo_proc p_flag (offset 32)


def _sysctl(mib: Sequence[int], limit: int) -> bytes:
    """Public sysctl(3) read (KERN_PROC_PGRP / KERN_PROCARGS2); never libproc."""
    query = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True).sysctl
    query.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p]
    query.argtypes += [
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    query.restype = ctypes.c_int
    names, size = (ctypes.c_int * len(mib))(*mib), ctypes.c_size_t()
    if query(names, len(mib), None, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), "sysctl size failed")
    if size.value > limit:
        raise OSError("sysctl size over limit")
    buffer = ctypes.create_string_buffer(size.value + 648 * 4)
    size.value = len(buffer)
    if query(names, len(mib), buffer, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), "sysctl read failed")
    return buffer.raw[: min(size.value, len(buffer))]


def command_line(pid: int, max_cmd_chars: int) -> str | None:
    """argv ONLY from KERN_PROCARGS2, like Linux /proc/<pid>/cmdline (PRE-J1g-F1).

    Layout: int argc, exec path, NUL padding to an 8-byte boundary, argv[argc],
    then envp, which is never read. Empty argv fields are kept and exactly
    argc are taken. Any doubt (short buffer, padding that does not match the
    aligned start, e.g. an empty argv[0], too few fields, undecodable bytes)
    returns None so the caller falls back to comm: fail closed.
    """
    try:
        data = _sysctl((1, 49, pid), 1 << 20)
    except OSError:
        return None
    argc = int.from_bytes(data[:4], sys.byteorder) if len(data) >= 4 else 0
    end = data.find(b"\0", 4)
    if argc <= 0 or end < 0:
        return None
    start = 4 + ((end - 4 + 1 + 7) & ~7)  # exec path + NUL, 8-byte aligned
    skipped = end
    while skipped < len(data) and data[skipped] == 0:
        skipped += 1
    if skipped != start:
        return None
    fields = data[start:].split(b"\0", argc)  # [argc fields..., rest: envp]
    if len(fields) <= argc:  # argv[argc - 1] not NUL-terminated: truncated
        return None
    try:
        argv = [field.decode("utf-8") for field in fields[:argc]]
    except UnicodeDecodeError:
        return None
    return " ".join(argv)[:max_cmd_chars]  # bounded after the join


def _state_letter(entry: bytes, state: int) -> str:
    """The Linux /proc state letter kinfo_proc determines, else ``?``."""
    if state == 4 and int.from_bytes(entry[32:36], sys.byteorder) & _P_TRACED:
        return _UNKNOWN_STATE
    return _STATE_LETTERS.get(state, _UNKNOWN_STATE)


def group_listing(pgid: int, max_cmd_chars: int) -> list[dict]:
    """JCRP-F6 (Linux job_processes shape): pid, state, etime_s and cmd.

    ``etime_s`` is the age from kinfo_proc p_starttime, rounded like Linux.
    ``cmd`` is the KERN_PROCARGS2 argv bounded by ``max_cmd_chars``, else the
    kinfo_proc comm when PROCARGS2 is denied, else empty like an empty Linux
    cmdline: never invented. ``cpu_s`` has no public per-process source here
    (SD-59 ruling 2 is pending). The owner calls this only for its verified
    group; it grants no signal right.
    """
    import time

    from binnacle.platform.darwin.process_authority import _decode_process_records

    try:
        raw = _sysctl((1, 14, 2, pgid), 648 * 65536)
    except OSError:
        return []
    listing: list[dict] = []
    now = time.time()  # p_starttime is wall clock (microtime at fork)
    for offset in range(0, len(raw) - len(raw) % 648, 648):
        entry = raw[offset : offset + 648]
        try:
            (member,) = _decode_process_records(entry)
        except OSError:
            continue
        if member.group != pgid:
            continue
        cmd = command_line(member.pid, max_cmd_chars)
        if cmd is None:  # p_comm (MAXCOMLEN + 1) at kinfo_proc offset 243
            cmd = entry[243:260].split(b"\0", 1)[0].decode(errors="replace")
        started = member.birth[0] + member.birth[1] / 1_000_000
        listing.append(
            {
                "pid": member.pid,
                "state": _state_letter(entry, member.state),
                "etime_s": round(max(now - started, 0.0), 1),
                "cmd": cmd[:max_cmd_chars],
            }
        )
    return sorted(listing, key=lambda item: int(item["pid"]))
