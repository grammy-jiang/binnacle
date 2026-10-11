"""Darwin setup: the test-owned launchd CLI and the ``com.binnacle.jobs`` plan.

The CLI is test-only and unprivileged: no global install, login item,
privileged helper or account change; everything lives under an explicit
private ``--root`` and a ``com.binnacle.r3test.`` label. A3's launchd lifecycle
is injected by composition; without one, apply and rollback report
CapabilityUnavailable rather than shelling out to launchctl.

The ``com.binnacle.jobs`` LaunchDaemon plan is pure data plus read-only
checks; nothing here writes /Library, runs launchctl or needs privileges.
Installation is the separate, gated deploy lane (J7).
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import grp
import json
import os
import pwd
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from binnacle.deployment.darwin.plist import (
    DEFAULT_ROLE,
    JOBS_DAEMON_LABEL,
    JOBS_DAEMON_PLIST_PATH,
    MCP_DAEMON_LABEL,
    SERVICE_ROLES,
    JobsDaemonSpec,
    _account,
    _load_dict,
    _normal_absolute,
    _process_limit,
    render_jobs_daemon_plist,
    search_path,
    validate_jobs_daemon_plist_bytes,
    validate_test_label,
)
from binnacle.deployment.darwin.provisioner import (
    _LIMITED,
    Capability,
    DarwinProvisioner,
    LaunchdLifecycle,
    ProvisionError,
    ServiceLease,
    ServicePlan,
    UnsafePath,
    pinned_root,
    pinned_subdir,
    read_regular_at,
    sha256_hex,
    write_atomic_at,
)


def _lease(root: Path, label: str) -> ServiceLease:
    with pinned_root(root, os.getuid()) as fd:
        st = os.fstat(fd)
    return ServiceLease(os.getuid(), label, "r3test", st.st_dev, st.st_ino)


def _save_plan(root: Path, plan: ServicePlan) -> None:
    doc = {
        "label": plan.lease.label,
        "plist_b64": base64.b64encode(plan.plist_bytes).decode(),
        "plist_sha256": sha256_hex(plan.plist_bytes),
        "expected_previous_sha256": plan.expected_previous_sha256,
    }
    uid = os.getuid()
    with pinned_root(root, uid) as root_fd, pinned_subdir(root_fd, "plans", uid) as fd:
        write_atomic_at(
            fd, f"{plan.lease.label}.json", json.dumps(doc, sort_keys=True).encode()
        )


def _load_plan(root: Path, label: str) -> ServicePlan:
    uid = os.getuid()
    with pinned_root(root, uid) as root_fd:
        st = os.fstat(root_fd)
        with pinned_subdir(root_fd, "plans", uid) as fd:
            raw = read_regular_at(fd, f"{label}.json", private_uid=uid)
    if raw is None:
        raise FileNotFoundError("plan_file_missing")
    doc = json.loads(raw)
    data = base64.b64decode(doc["plist_b64"])
    if doc.get("label") != label or doc.get("plist_sha256") != sha256_hex(data):
        raise UnsafePath("plan_file_tampered", _LIMITED)
    # The plist path is derived, never taken from the (editable) plan file.
    return ServicePlan(
        ServiceLease(uid, label, "r3test", st.st_dev, st.st_ino),
        data,
        root / f"{label}.plist",
        doc["expected_previous_sha256"],
    )


def _emit(root: Path, label: str, doc: dict[str, object]) -> None:
    text = json.dumps(doc, sort_keys=True, indent=1)
    uid = os.getuid()
    with (
        pinned_root(root, uid) as root_fd,
        pinned_subdir(root_fd, "receipts", uid) as fd,
    ):
        write_atomic_at(fd, f"{label}.{doc['action']}.json", text.encode())
    print(text)


# --- com.binnacle.jobs: the stable Darwin Job Manager plan (design R4 section 2) ---

_JOBS_SCOPE = (
    "com.binnacle.jobs LaunchDaemon plan only; install is the gated deploy lane"
)
_PLAN_ONLY = Capability("LIMITED", "jobs_daemon_plan_only", _JOBS_SCOPE)
JOBS_LOG_NAMES = (f"{JOBS_DAEMON_LABEL}.out.log", f"{JOBS_DAEMON_LABEL}.err.log")
JOBS_LOG_SUBDIR = Path("Library/Logs/binnacle")
# SD-31: jobs log rotation extends the deployed MCP entry; no new conf file.
MCP_NEWSYSLOG_PATH = Path("/etc/newsyslog.d/com.binnacle.mcp.conf")
_MCP_ENV_KEYS = frozenset({"HOME", "BINNACLE_CONFIG_FILE", "PATH"})
JOBS_INSTALL_OWNER = (0, 0)
JOBS_INSTALL_MODE = 0o644


class JobsDaemonRefused(ProvisionError):
    """The jobs daemon plan was refused; nothing was written or loaded."""


@dataclass(frozen=True)
class McpDaemonIdentity:
    user_name: str
    group_name: str
    home: Path
    config_file: Path
    path: str


def mcp_daemon_identity(data: bytes) -> McpDaemonIdentity:
    """Read the run-as identity from caller-supplied ``com.binnacle.mcp`` bytes.

    Pure: the caller decides where the bytes come from. A daemon without an
    explicit non-root ``UserName``/``GroupName`` or without an absolute
    ``PATH`` is refused, never defaulted (launchd's bare /usr/bin:/bin would
    hide uv, rg and brew tools from jobs). Any other MCP environment key is
    refused too: it could move the runtime root or socket away from what the
    jobs daemon resolves.
    """
    value = _load_dict(data)
    env = value.get("EnvironmentVariables")
    if value.get("Label") != MCP_DAEMON_LABEL or not isinstance(env, dict):
        raise ValueError("mcp_identity_invalid")
    if not env.keys() <= _MCP_ENV_KEYS:
        raise ValueError("mcp_identity_env_unexpected")
    home, config = env.get("HOME"), env.get("BINNACLE_CONFIG_FILE")
    if not isinstance(home, str) or not isinstance(config, str):
        raise ValueError("mcp_identity_invalid")  # noqa: TRY004 - one error type
    if not _normal_absolute(Path(home)) or not _normal_absolute(Path(config)):
        raise ValueError("mcp_identity_invalid")
    try:
        path = search_path(env.get("PATH"))
    except ValueError:
        raise ValueError("mcp_identity_path_invalid") from None
    return McpDaemonIdentity(
        _account(value.get("UserName")),
        _account(value.get("GroupName")),
        Path(home),
        Path(config),
        path,
    )


def per_user_process_limit() -> int:
    """``kern.maxprocperuid`` via sysctlbyname(3), never the caller's ulimit.

    On Darwin ``sysconf(_SC_CHILD_MAX)`` is the caller's soft RLIMIT_NPROC, so
    a provisioner run under ``ulimit -u`` would pin the wrong value. No fork
    is needed, so a low RLIMIT_NPROC cannot break the read. Any failure
    refuses the plan rather than guessing.
    """
    value = ctypes.c_int(0)
    size = ctypes.c_size_t(ctypes.sizeof(value))
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        rc = libc.sysctlbyname(
            b"kern.maxprocperuid",
            ctypes.byref(value),
            ctypes.byref(size),
            None,
            ctypes.c_size_t(0),
        )
    except (AttributeError, OSError):
        rc = -1
    if rc != 0 or size.value != ctypes.sizeof(value):
        raise ValueError("jobs_daemon_process_limit_unavailable")
    return _process_limit(value.value)


AccountLookup = Callable[[str, str], tuple[int, int]]
PathStat = Callable[[Path], os.stat_result]


def lookup_account(user_name: str, group_name: str) -> tuple[int, int]:
    """Resolve ``(uid, gid)`` read-only from the local account databases."""
    try:
        return pwd.getpwnam(user_name).pw_uid, grp.getgrnam(group_name).gr_gid
    except KeyError:
        raise JobsDaemonRefused("jobs_daemon_account_missing", _PLAN_ONLY) from None


def _private_to(st: os.stat_result, uid: int) -> bool:
    return st.st_uid == uid and not st.st_mode & 0o022


def check_log_dir(log_dir: Path, uid: int, lstat: PathStat = os.lstat) -> None:
    """launchd opens ``Standard*Path`` for the daemon, so ``log_dir`` must be
    the run-as user's own non-symlink directory, not group/world-writable, and
    an existing log a single-link regular file of that user (no planted link).
    """
    try:
        st = lstat(log_dir)
    except OSError:
        raise ValueError("jobs_daemon_log_dir_invalid") from None
    if not stat.S_ISDIR(st.st_mode) or not _private_to(st, uid):
        raise ValueError("jobs_daemon_log_dir_invalid")
    for name in JOBS_LOG_NAMES:
        try:
            log = lstat(log_dir / name)
        except FileNotFoundError:
            continue
        except OSError:
            raise ValueError("jobs_daemon_log_file_invalid") from None
        if not stat.S_ISREG(log.st_mode) or not _private_to(log, uid):
            raise ValueError("jobs_daemon_log_file_invalid")
        if log.st_nlink != 1:
            raise ValueError("jobs_daemon_log_file_invalid")


def _jobs_logs(spec: JobsDaemonSpec) -> tuple[str, str]:
    logs = (str(spec.stdout_path), str(spec.stderr_path))
    if any(char.isspace() for log in logs for char in log):
        raise ValueError("jobs_daemon_log_dir_invalid")
    return logs


def jobs_newsyslog_lines(spec: JobsDaemonSpec) -> str:
    """The exact jobs lines to APPEND to ``com.binnacle.mcp.conf`` (SD-31).

    Same policy as the deployed MCP entry (mode 600, 7 kept, 10 MiB, ``NJ``):
    ``N`` because launchd, not a pid file, owns the descriptors and reopens
    the path on every spawn, which bounds the crash-loop (disk-fill) case.
    Only needed when ``newsyslog_covers_jobs_logs`` is false.
    """
    owner = f"{spec.user_name}:{spec.group_name}"
    return "".join(
        f"{log}\t{owner}\t600\t7\t10240\t*\tNJ\n" for log in _jobs_logs(spec)
    )


def _covers(fields: list[str], log: str, owner: str) -> bool:
    if len(fields) < 6 or fields[1] != owner or fields[2] != "600":
        return False
    if not fields[4].isdigit() or int(fields[4]) <= 0:
        return False  # rotation must be size-bounded
    if fields[0] == log:
        return True
    flags = fields[6] if len(fields) > 6 else ""
    return "G" in flags.upper() and PurePosixPath(log).match(fields[0])


def newsyslog_covers_jobs_logs(conf_text: str, spec: JobsDaemonSpec) -> bool:
    """True if ``conf_text`` already rotates both planned jobs logs.

    An entry covers a log when it names it exactly, or as a ``G`` glob, with
    owner ``<run-as user>:<group>``, mode 600 and a positive size bound.
    """
    owner = f"{spec.user_name}:{spec.group_name}"
    entries = [
        line.split()
        for line in conf_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return all(
        any(_covers(fields, log, owner) for fields in entries)
        for log in _jobs_logs(spec)
    )


@dataclass(frozen=True)
class JobsDaemonPlan:
    """A rendered production plan; this lane never installs or loads it.

    J7 installs ``plist_bytes`` at ``target_path`` as ``install_owner``
    (root:wheel) with ``install_mode`` 0644; ``verify_installed_jobs_daemon``
    checks the result. Log rotation never gets its own conf file: if
    ``newsyslog_covers_jobs_logs`` is false for the deployed
    ``MCP_NEWSYSLOG_PATH`` text, ``newsyslog_lines`` are appended to it.
    """

    spec: JobsDaemonSpec
    uid: int
    gid: int
    plist_bytes: bytes
    plist_sha256: str
    target_path: Path
    capability: Capability
    newsyslog_lines: str
    install_owner: tuple[int, int] = JOBS_INSTALL_OWNER
    install_mode: int = JOBS_INSTALL_MODE


def plan_jobs_daemon(
    mcp_plist: bytes,
    *,
    python: Path,
    log_dir: Path | None = None,
    number_of_processes: int | None = None,
    lookup: AccountLookup = lookup_account,
    lstat: PathStat = os.lstat,
) -> JobsDaemonPlan:
    """Plan ``com.binnacle.jobs`` to run as the deployed ``com.binnacle.mcp``.

    The run-as identity, ``HOME``, config and ``PATH`` come only from the
    supplied MCP daemon plist. An account that resolves to uid or gid 0 is
    refused: the manager never runs as root. ``log_dir`` defaults to
    ``<MCP HOME>/Library/Logs/binnacle`` and must already be the run-as
    user's private directory (planning reads only; it creates nothing).

    ``number_of_processes`` is the seam for the process limit: ``None`` reads
    ``kern.maxprocperuid``, which is refused off Darwin. Refusal order (the
    first failing check names the code): MCP identity, ``log_dir`` path,
    process limit, rendered plist (python, paths, limits), account lookup,
    root ids, then the ``lstat`` log checks.
    """
    try:
        identity = mcp_daemon_identity(mcp_plist)
        logs = identity.home / JOBS_LOG_SUBDIR if log_dir is None else log_dir
        if not _normal_absolute(logs):
            raise ValueError("path_not_absolute")
        spec = JobsDaemonSpec(
            user_name=identity.user_name,
            group_name=identity.group_name,
            python=python,
            home=identity.home,
            config_file=identity.config_file,
            path=identity.path,
            stdout_path=logs / JOBS_LOG_NAMES[0],
            stderr_path=logs / JOBS_LOG_NAMES[1],
            number_of_processes=(
                per_user_process_limit()
                if number_of_processes is None
                else number_of_processes
            ),
        )
        data = render_jobs_daemon_plist(spec)
        if validate_jobs_daemon_plist_bytes(data) != spec:
            raise ValueError("plist_scope_refused")
        newsyslog = jobs_newsyslog_lines(spec)
        uid, gid = lookup(spec.user_name, spec.group_name)
        if uid == 0 or gid == 0:
            raise ValueError("jobs_daemon_root_refused")
        check_log_dir(logs, uid, lstat)
    except ValueError as exc:
        raise JobsDaemonRefused(str(exc), _PLAN_ONLY) from None
    return JobsDaemonPlan(
        spec,
        uid,
        gid,
        data,
        sha256_hex(data),
        JOBS_DAEMON_PLIST_PATH,
        _PLAN_ONLY,
        newsyslog,
    )


def verify_installed_jobs_daemon(
    st: os.stat_result, data: bytes, plan: JobsDaemonPlan
) -> None:
    """Pure check of an installed plist from its ``lstat`` result and bytes.

    launchd refuses, and a non-root writer could hijack, a LaunchDaemon that
    is not a single-link root:wheel 0644 regular file; the bytes must be
    exactly the planned ones.
    """
    if (
        not stat.S_ISREG(st.st_mode)
        or (st.st_uid, st.st_gid) != plan.install_owner
        or stat.S_IMODE(st.st_mode) != plan.install_mode
        or st.st_nlink != 1
        or sha256_hex(data) != plan.plist_sha256
    ):
        raise JobsDaemonRefused("jobs_daemon_install_unverified", _PLAN_ONLY)


def main(
    argv: Sequence[str] | None = None, *, lifecycle: LaunchdLifecycle | None = None
) -> int:
    ap = argparse.ArgumentParser(prog="binnacle-darwin-test-setup")
    ap.add_argument("command", choices=("plan", "apply", "rollback"))
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--workdir", type=Path)
    ap.add_argument("--role", choices=SERVICE_ROLES, default=DEFAULT_ROLE)
    ap.add_argument("--exec", dest="exec_argv", nargs="+", default=None)
    args = ap.parse_args(argv)
    root: Path = args.root
    try:
        validate_test_label(args.label)
        if not root.is_absolute():
            raise ValueError("root_not_absolute")
        prov = DarwinProvisioner(
            root,
            uid=os.getuid(),
            lifecycle=lifecycle,
        )
        if args.command == "plan":
            if not args.exec_argv:
                raise ValueError("exec_required")
            plan = prov.plan(
                _lease(root, args.label),
                argv=args.exec_argv,
                environment={},
                workdir=args.workdir or root,
                role=args.role,
            )
            _save_plan(root, plan)
            receipt: dict[str, object] = {
                "action": "plan",
                "label": args.label,
                "plist_sha256": sha256_hex(plan.plist_bytes),
                "expected_previous_sha256": plan.expected_previous_sha256,
            }
        else:
            plan = _load_plan(root, args.label)
            r = (prov.apply if args.command == "apply" else prov.rollback)(plan)
            receipt = {
                "action": r.action,
                "label": args.label,
                "capability": r.capability.state,
                "scope": r.capability.scope,
                "absent": r.absent,
                "full_parity": False,
            }
            if args.command == "rollback" and not r.absent:
                _emit(root, args.label, {**receipt, "error": "teardown_unverified"})
                return 3
        _emit(root, args.label, receipt)
        return 0
    except ProvisionError as exc:
        print(json.dumps({"error": exc.code}), file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(
            json.dumps({"error": type(exc).__name__, "detail": str(exc)}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
