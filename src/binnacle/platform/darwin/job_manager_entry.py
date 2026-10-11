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
import secrets
import signal
import struct
import sys
import threading
from collections.abc import Sequence
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
_OVERRIDES = ("BINNACLE_JOBS__", "BINNACLE_RUN_COMMAND__")  # env_nested_delimiter


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
    """``kern.boottime`` plus ``kern.uuid`` (design); a recovery reason only.

    It labels ``host_reboot`` versus ``owner_restart`` and is never authority.
    """
    libc = ctypes.CDLL(None, use_errno=True)

    def sysctl(name: str, size: int) -> bytes:
        value, length = ctypes.create_string_buffer(size), ctypes.c_size_t(size)
        if libc.sysctlbyname(name.encode(), value, ctypes.byref(length), None, 0):
            raise OSError(ctypes.get_errno(), f"sysctl {name} failed")
        return value.raw[: length.value]

    seconds, micros = struct.unpack("=qi", sysctl("kern.boottime", 16)[:12])
    kernel = sysctl("kern.uuid", 64).rstrip(b"\0").decode("ascii")
    if seconds <= 0 or not kernel:
        raise OSError("darwin_boot_identity_unavailable")
    return f"{seconds}.{micros:06d}-{kernel}"


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
