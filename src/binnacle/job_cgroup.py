"""Low-overhead cgroup-v2 accounting for durable command jobs.

The job cgroup carries no limits. It is an accounting/identity boundary only:
the stable job manager lives in a delegated subgroup, creates one sibling
``job-<id>`` cgroup, and moves the command shell there before it execs the user
command. Descendants inherit the cgroup naturally. Monitoring must never make
``run_command`` unavailable, so every operation is best-effort.
"""

from __future__ import annotations

import logging
import os
import re
import select
from pathlib import Path

log = logging.getLogger("binnacle.jobs")
CGROUP_FS = Path("/sys/fs/cgroup")
MANAGER_SUBGROUP = "binnacle-manager"
ACCOUNTING_CONTROLLERS = ("cpu", "memory", "pids")
_JOB_ID = re.compile(r"^[0-9a-f]{12}$")


def process_cgroup(
    pid: int | None = None, *, proc_root: Path = Path("/proc")
) -> str | None:
    """Return one process's unified-cgroup path, or ``None`` off cgroup v2."""
    who = "self" if pid is None else str(pid)
    try:
        lines = (proc_root / who / "cgroup").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
            return parts[2]
    return None


def _fs_path(cgroup: str, *, cgroup_fs: Path = CGROUP_FS) -> Path:
    return cgroup_fs / cgroup.lstrip("/")


def accounting_root(
    *, cgroup_fs: Path = CGROUP_FS, proc_root: Path = Path("/proc")
) -> str | None:
    """Return the delegated service root used for per-job children.

    ``DelegateSubgroup=binnacle-manager`` moves the manager process below the
    service root so domain controllers can be enabled for sibling job cgroups.
    Off managed systemd deployments we fall back to the process's own cgroup.
    """
    current = process_cgroup(proc_root=proc_root)
    if not current:
        return None
    path = Path(current)
    if path.name == MANAGER_SUBGROUP:
        parent = path.parent
        return "/" if str(parent) == "." else "/" + str(parent).lstrip("/")
    return current


def prepare(
    *,
    cgroup_fs: Path = CGROUP_FS,
    proc_root: Path = Path("/proc"),
    log_ready: bool = False,
) -> str | None:
    """Enable available accounting controllers for per-job child cgroups.

    This is idempotent. A non-delegated environment may reject the write; that
    is logged and the historical process-group-only behaviour remains usable.
    """
    root_rel = accounting_root(cgroup_fs=cgroup_fs, proc_root=proc_root)
    if not root_rel:
        return None
    root = _fs_path(root_rel, cgroup_fs=cgroup_fs)
    try:
        available = set((root / "cgroup.controllers").read_text().split())
        enabled = set((root / "cgroup.subtree_control").read_text().split())
    except OSError:
        # Synthetic tests and non-cgroup-v2 environments can still exercise
        # best-effort child creation without controller delegation.
        return root_rel
    wanted = [name for name in ACCOUNTING_CONTROLLERS if name in available]
    missing = [name for name in wanted if name not in enabled]
    if missing:
        try:
            (root / "cgroup.subtree_control").write_text(
                " ".join(f"+{name}" for name in missing)
            )
        except OSError as exc:
            log.info(
                "event=job_cgroup_controller_unavailable root=%s controllers=%s "
                "error_class=%s",
                root_rel,
                ",".join(missing),
                type(exc).__name__,
            )
        try:
            enabled = set((root / "cgroup.subtree_control").read_text().split())
        except OSError:
            pass
    if log_ready:
        log.info(
            "event=job_cgroup_ready root=%s available=%s enabled=%s",
            root_rel,
            ",".join(sorted(available)) or "-",
            ",".join(sorted(enabled)) or "-",
        )
    return root_rel


def create(job_id: str, *, cgroup_fs: Path = CGROUP_FS) -> str | None:
    """Create a delegated per-job cgroup, preserving best-effort semantics."""
    if not _JOB_ID.fullmatch(job_id):
        return None
    parent = prepare(cgroup_fs=cgroup_fs)
    if not parent:
        return None
    child_rel = f"{parent.rstrip('/')}/job-{job_id}"
    child = _fs_path(child_rel, cgroup_fs=cgroup_fs)
    try:
        child.mkdir(exist_ok=True)
    except OSError as exc:
        log.info(
            "event=job_cgroup_unavailable job_id=%s error_class=%s",
            job_id,
            type(exc).__name__,
        )
        return None
    return child_rel


def launch_argv(
    command: str, cgroup: str | None, *, cgroup_fs: Path = CGROUP_FS
) -> list[str]:
    """Shell argv that enters *cgroup* before executing ``command``.

    The bootstrap shell moves itself, then ``exec`` replaces it with the normal
    ``bash -c`` process at the same PID. There is no polling race for children.
    """
    if not cgroup:
        return ["bash", "-c", command]
    procs = _fs_path(cgroup, cgroup_fs=cgroup_fs) / "cgroup.procs"
    bootstrap = 'printf "%s\\n" "$$" > "$1" 2>/dev/null || true; exec bash -c "$2"'
    return ["bash", "-c", bootstrap, "binnacle-cgroup", str(procs), command]


def wrap_argv(
    argv: list[str], cgroup: str | None, *, cgroup_fs: Path = CGROUP_FS
) -> list[str]:
    """Attach before exec without choosing or changing the supplied command argv.

    A failed attach still reaches exec, preserving the wrapper PID and normal
    execution when accounting is unavailable. The caller's list is not mutated.
    """
    if not cgroup:
        return argv
    procs = _fs_path(cgroup, cgroup_fs=cgroup_fs) / "cgroup.procs"
    bootstrap = 'printf "%s\\n" "$$" > "$1" 2>/dev/null || true; shift; exec "$@"'
    return ["bash", "-c", bootstrap, "binnacle-cgroup", str(procs), *argv]


def _kv(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            out[parts[0]] = int(parts[1])
        except ValueError:
            continue
    return out


def _io(path: Path) -> dict[str, int]:
    total: dict[str, int] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return total
    for line in lines:
        for item in line.split()[1:]:
            key, sep, raw = item.partition("=")
            if not sep:
                continue
            try:
                total[key] = total.get(key, 0) + int(raw)
            except ValueError:
                continue
    return total


def snapshot(cgroup: str | None, *, cgroup_fs: Path = CGROUP_FS) -> dict[str, object]:
    """Read cumulative counters for a job cgroup; absent controllers are omitted."""
    if not cgroup:
        return {}
    root = _fs_path(cgroup, cgroup_fs=cgroup_fs)
    if not root.is_dir():
        return {}
    out: dict[str, object] = {}
    cpu = _kv(root / "cpu.stat")
    if cpu:
        out["cpu"] = cpu
    io = _io(root / "io.stat")
    if io:
        out["io"] = io
    memory_stat = _kv(root / "memory.stat")
    if memory_stat:
        out["memory_stat"] = memory_stat
    memory_events = _kv(root / "memory.events")
    if memory_events:
        out["memory_events"] = memory_events
    swap_events = _kv(root / "memory.swap.events")
    if swap_events:
        out["memory_swap_events"] = swap_events
    for name in (
        "memory.current",
        "memory.peak",
        "memory.swap.current",
        "memory.swap.peak",
        "pids.current",
        "pids.peak",
    ):
        path = root / name
        try:
            out[name.replace(".", "_")] = int(path.read_text().strip())
        except (OSError, ValueError):
            pass
    try:
        out["processes"] = len(
            [p for p in (root / "cgroup.procs").read_text().splitlines() if p]
        )
    except OSError:
        pass
    return out


def wait_empty(cgroup: str, *, cgroup_fs: Path = CGROUP_FS) -> bool:
    """Block without polling until a populated cgroup becomes empty.

    ``cgroup.events`` supports poll notifications.  This is used only for the
    uncommon shell-exited/descendant-still-running case; ordinary jobs clean up
    synchronously and never allocate a waiter thread.
    """
    events = _fs_path(cgroup, cgroup_fs=cgroup_fs) / "cgroup.events"
    try:
        fd = os.open(events, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return False

    def populated() -> bool | None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            data = os.read(fd, 4096).decode("ascii", errors="replace")
        except OSError:
            return None
        for line in data.splitlines():
            key, _, value = line.partition(" ")
            if key == "populated":
                return value.strip() == "1"
        return None

    try:
        state = populated()
        if state is None:
            return False
        if not state:
            return True
        poller = select.poll()
        poller.register(fd, select.POLLPRI | select.POLLERR)
        while True:
            poller.poll()  # no timeout: kernel event only
            state = populated()
            if state is None:
                return False
            if not state:
                return True
    finally:
        os.close(fd)


def cleanup(cgroup: str | None, *, cgroup_fs: Path = CGROUP_FS) -> bool:
    """Remove an empty job cgroup. A populated group is deliberately retained."""
    if not cgroup:
        return True
    root = _fs_path(cgroup, cgroup_fs=cgroup_fs)
    try:
        root.rmdir()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def move_pid(pid: int, cgroup: str, *, cgroup_fs: Path = CGROUP_FS) -> bool:
    """Best-effort helper for explicit cgroup migration."""
    try:
        (_fs_path(cgroup, cgroup_fs=cgroup_fs) / "cgroup.procs").write_text(f"{pid}\n")
        return True
    except OSError:
        return False


class CgroupResourceAccounting:
    """Unused accounting port over the existing best-effort Linux helpers."""

    __slots__ = ()

    def prepare(self, *, log_ready: bool = False) -> str | None:
        return prepare(log_ready=log_ready)

    def create(self, job_id: str) -> str | None:
        return create(job_id)

    def wrap_argv(self, argv: list[str], identity: str | None) -> list[str]:
        return wrap_argv(argv, identity)

    def snapshot(self, identity: str | None) -> dict[str, object]:
        return snapshot(identity)

    def wait_empty(self, identity: str) -> bool:
        return wait_empty(identity)

    def cleanup(self, identity: str | None) -> bool:
        return cleanup(identity)
