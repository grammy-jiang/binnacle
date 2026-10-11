"""Pure, deterministic launchd plist rendering for Darwin services.

Test-owned user-domain jobs plus the plan (never the install) for the
production ``com.binnacle.jobs`` LaunchDaemon.
"""

from __future__ import annotations

import os
import plistlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

TEST_LABEL_PREFIX = "com.binnacle.r3test."
_LABEL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_"
)


def validate_test_label(label: str) -> str:
    """Accept only labels in the test-owned namespace; never a bare prefix."""
    if (
        not label.startswith(TEST_LABEL_PREFIX)
        or len(label) == len(TEST_LABEL_PREFIX)
        or len(label) > 120
        or not set(label) <= _LABEL_CHARS
    ):
        raise ValueError("label_not_test_owned")
    return label


SERVICE_ROLES = ("frontend", "probe", "manager")
DEFAULT_ROLE = "probe"
_FORBIDDEN_KEYS = (
    "Program",
    "UserName",
    "GroupName",
    "Sockets",
    "MachServices",
    "StandardOutPath",
    "StandardErrorPath",
)


def render_plist(
    label: str,
    *,
    argv: Sequence[str],
    environment: Mapping[str, str],
    workdir: Path,
    runtime_dir: Path,
    role: str = DEFAULT_ROLE,
) -> bytes:
    """Render a launchd job that is not loaded at login and opens no sockets.

    The format is the one A3's ``LaunchdUserServices`` accepts: the plist lives
    directly in the private runtime root, carries ``BINNACLE_SERVICE_ROLE`` and
    ``BINNACLE_RUNTIME_DIR`` (the root) and ``LimitLoadToSessionType=Background``.

    Log contract (B0 wires it): the plist deliberately has no
    ``StandardOutPath``/``StandardErrorPath``. launchd therefore discards raw
    stdout/stderr, and the service entrypoint must write its records through
    A5's ``PrivateServiceLogWriter(root=BINNACLE_RUNTIME_DIR, ...)`` so they are
    redacted and carry stream epochs.

    ``RunAtLoad``/``KeepAlive`` are false and there is no ``Sockets`` key, so
    the job starts only when explicitly bootstrapped and kicked by the test.
    """
    validate_test_label(label)
    if not argv or not all(isinstance(a, str) and a for a in argv):
        raise ValueError("argv_invalid")
    if not Path(argv[0]).is_absolute():
        raise ValueError("argv0_not_absolute")
    if not workdir.is_absolute() or not runtime_dir.is_absolute():
        raise ValueError("path_not_absolute")
    if role not in SERVICE_ROLES:
        raise ValueError("service_role_invalid")
    env = dict(environment)
    env["BINNACLE_SERVICE_ROLE"] = role
    env["BINNACLE_RUNTIME_DIR"] = str(runtime_dir)
    body: dict[str, object] = {
        "Label": label,
        "ProgramArguments": list(argv),
        "EnvironmentVariables": dict(sorted(env.items())),
        "WorkingDirectory": str(workdir),
        "RunAtLoad": False,
        "KeepAlive": False,
        "ProcessType": "Background",
        "LimitLoadToSessionType": "Background",
    }
    return plistlib.dumps(body, fmt=plistlib.FMT_XML, sort_keys=True)


def validate_plist_bytes(data: bytes, *, label: str, runtime_dir: Path) -> None:
    """Refuse any plist bytes that are not an inert, A3-acceptable test job."""
    try:
        value = plistlib.loads(data)
    except (ValueError, plistlib.InvalidFileException):
        raise ValueError("plist_invalid") from None
    if not isinstance(value, dict):
        raise ValueError("plist_invalid")  # noqa: TRY004 - one error type
    env = value.get("EnvironmentVariables")
    argv = value.get("ProgramArguments")
    if (
        value.get("Label") != label
        or not isinstance(argv, list)
        or not argv
        or not all(isinstance(a, str) and a for a in argv)
        or not Path(argv[0]).is_absolute()
        or value.get("RunAtLoad") is not False
        or value.get("KeepAlive") is not False
        or value.get("LimitLoadToSessionType") != "Background"
        or not isinstance(env, dict)
        or env.get("BINNACLE_SERVICE_ROLE") not in SERVICE_ROLES
        or env.get("BINNACLE_RUNTIME_DIR") != str(runtime_dir)
        or any(k in value for k in _FORBIDDEN_KEYS)
    ):
        raise ValueError("plist_scope_refused")


# --- com.binnacle.jobs: the stable Darwin Job Manager (design R4 section 2) ---
#
# Pure renderers only: nothing here writes /Library/LaunchDaemons, runs
# launchctl or needs privileges. Installation is a separate, gated lane.

JOBS_DAEMON_LABEL = "com.binnacle.jobs"
MCP_DAEMON_LABEL = "com.binnacle.mcp"
JOBS_DAEMON_PLIST_PATH = Path("/Library/LaunchDaemons") / f"{JOBS_DAEMON_LABEL}.plist"
JOBS_PROGRAM_NAME = "binnacle-jobs"
JOBS_EXIT_TIMEOUT_S = 30
JOBS_THROTTLE_INTERVAL_S = 10
JOBS_NUMBER_OF_FILES = 8192
_MAX_PROCESS_LIMIT = 1 << 20
_ACCOUNT_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)
_PRIVILEGED_ACCOUNTS = frozenset({"root", "wheel", "admin", "daemon"})
_JOBS_DAEMON_KEYS = frozenset(
    {
        "Label",
        "UserName",
        "GroupName",
        "ProgramArguments",
        "EnvironmentVariables",
        "RunAtLoad",
        "KeepAlive",
        "ThrottleInterval",
        "ProcessType",
        "AbandonProcessGroup",
        "ExitTimeOut",
        "SoftResourceLimits",
        "HardResourceLimits",
        "StandardOutPath",
        "StandardErrorPath",
    }
)
_JOBS_TEST_KEYS = frozenset(
    {
        "Label",
        "ProgramArguments",
        "EnvironmentVariables",
        "WorkingDirectory",
        "RunAtLoad",
        "KeepAlive",
        "ThrottleInterval",
        "ProcessType",
        "AbandonProcessGroup",
        "ExitTimeOut",
        "SoftResourceLimits",
        "HardResourceLimits",
        "LimitLoadToSessionType",
    }
)


@dataclass(frozen=True)
class JobsDaemonSpec:
    """Inputs for the production ``com.binnacle.jobs`` LaunchDaemon plist.

    ``user_name``/``group_name``, ``home`` and ``config_file`` are those of the
    deployed ``com.binnacle.mcp`` daemon; ``program`` is the absolute
    ``<installed venv>/bin/binnacle-jobs`` (never a development checkout that
    auto-reloads, mirroring Linux's stable job owner).
    """

    user_name: str
    group_name: str
    program: Path
    home: Path
    config_file: Path
    stdout_path: Path
    stderr_path: Path
    number_of_processes: int


def _normal_absolute(path: Path) -> bool:
    text = str(path)
    return path.is_absolute() and os.path.normpath(text) == text and "\x00" not in text


def _account(name: object) -> str:
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 64
        or name.startswith("-")
        or not set(name) <= _ACCOUNT_CHARS
    ):
        raise ValueError("jobs_daemon_account_invalid")
    if name in _PRIVILEGED_ACCOUNTS:
        raise ValueError("jobs_daemon_privileged_account_refused")
    return name


def _process_limit(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 < value <= _MAX_PROCESS_LIMIT
    ):
        raise ValueError("jobs_daemon_process_limit_invalid")
    return value


def user_default_process_limit() -> int:
    """The per-user process ceiling (``kern.maxprocperuid``) set explicitly.

    launchd otherwise hands the daemon whatever it inherits; the design pins
    it so job behaviour is deterministic.
    """
    return _process_limit(os.sysconf("SC_CHILD_MAX"))


def _resource_limits(number_of_processes: object) -> dict[str, int]:
    return {
        "NumberOfFiles": JOBS_NUMBER_OF_FILES,
        "NumberOfProcesses": _process_limit(number_of_processes),
    }


def _jobs_lifecycle(
    argv: Sequence[str], number_of_processes: object
) -> dict[str, object]:
    """Keys shared by the production daemon and its user-domain test variant."""
    limits = _resource_limits(number_of_processes)
    return {
        "ProgramArguments": list(argv),
        "RunAtLoad": True,
        "ThrottleInterval": JOBS_THROTTLE_INTERVAL_S,
        # Background would throttle job CPU; Linux parity needs normal QoS.
        "ProcessType": "Standard",
        # Jobs run in their own setsid sessions, so a bootout kills only the
        # manager's group and leaves jobs to D-1 (UNKNOWN), never adopted.
        "AbandonProcessGroup": False,
        "ExitTimeOut": JOBS_EXIT_TIMEOUT_S,
        "SoftResourceLimits": dict(limits),
        "HardResourceLimits": dict(limits),
    }


def _jobs_program(program: Path) -> str:
    if (
        not _normal_absolute(program)
        or program.name != JOBS_PROGRAM_NAME
        or program.parent.name != "bin"
    ):
        raise ValueError("jobs_daemon_program_invalid")
    return str(program)


def render_jobs_daemon_plist(spec: JobsDaemonSpec) -> bytes:
    """Render the system LaunchDaemon plan for ``com.binnacle.jobs``.

    It runs as the ``com.binnacle.mcp`` account (never root), starts at load,
    restarts only after an unsuccessful exit (a clean ``bootout`` keeps it
    down) and carries explicit resource limits. Rendering never installs.
    """
    paths = (spec.home, spec.config_file, spec.stdout_path, spec.stderr_path)
    if not all(_normal_absolute(p) for p in paths):
        raise ValueError("path_not_absolute")
    body = _jobs_lifecycle([_jobs_program(spec.program)], spec.number_of_processes)
    body.update(
        {
            "Label": JOBS_DAEMON_LABEL,
            "UserName": _account(spec.user_name),
            "GroupName": _account(spec.group_name),
            "KeepAlive": {"SuccessfulExit": False},
            "EnvironmentVariables": {
                "BINNACLE_CONFIG_FILE": str(spec.config_file),
                "HOME": str(spec.home),
            },
            "StandardOutPath": str(spec.stdout_path),
            "StandardErrorPath": str(spec.stderr_path),
        }
    )
    return plistlib.dumps(body, fmt=plistlib.FMT_XML, sort_keys=True)


def _load_dict(data: bytes) -> dict[str, object]:
    try:
        value = plistlib.loads(data)
    except (ValueError, plistlib.InvalidFileException):
        raise ValueError("plist_invalid") from None
    if not isinstance(value, dict):
        raise ValueError("plist_invalid")  # noqa: TRY004 - one error type
    return value


def _lifecycle_matches(value: Mapping[str, object]) -> bool:
    """True only if every shared lifecycle key has exactly the planned value."""
    argv = value.get("ProgramArguments")
    soft = value.get("SoftResourceLimits")
    if not isinstance(argv, list) or not isinstance(soft, dict):
        return False
    try:
        expected = _jobs_lifecycle(argv, soft.get("NumberOfProcesses"))
    except ValueError:
        return False
    if not expected.keys() <= value.keys():
        return False
    # Serialised comparison: plist <true/>, <integer> and <real> must not alias.
    try:
        actual = plistlib.dumps({key: value[key] for key in expected}, sort_keys=True)
    except (TypeError, OverflowError):
        return False
    return actual == plistlib.dumps(expected, sort_keys=True)


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("plist_scope_refused")  # noqa: TRY004 - one error type
    return value


def validate_jobs_daemon_plist_bytes(data: bytes) -> JobsDaemonSpec:
    """Refuse any bytes that are not exactly a design-conformant jobs daemon.

    The bytes must re-render identically from the spec they encode, so no
    extra key, trigger or value survives. The spec is returned so callers can
    compare it to the deployed ``com.binnacle.mcp`` identity.
    """
    value = _load_dict(data)
    argv = value.get("ProgramArguments")
    env = value.get("EnvironmentVariables")
    soft = value.get("SoftResourceLimits")
    if (
        value.keys() != _JOBS_DAEMON_KEYS
        or not isinstance(argv, list)
        or len(argv) != 1
        or not isinstance(env, dict)
        or env.keys() != {"HOME", "BINNACLE_CONFIG_FILE"}
        or not isinstance(soft, dict)
        or not _lifecycle_matches(value)
    ):
        raise ValueError("plist_scope_refused")
    try:
        spec = JobsDaemonSpec(
            user_name=_str(value["UserName"]),
            group_name=_str(value["GroupName"]),
            program=Path(_str(argv[0])),
            home=Path(_str(env["HOME"])),
            config_file=Path(_str(env["BINNACLE_CONFIG_FILE"])),
            stdout_path=Path(_str(value["StandardOutPath"])),
            stderr_path=Path(_str(value["StandardErrorPath"])),
            number_of_processes=_process_limit(soft["NumberOfProcesses"]),
        )
        canonical = render_jobs_daemon_plist(spec)
    except ValueError:
        raise ValueError("plist_scope_refused") from None
    if canonical != plistlib.dumps(value, fmt=plistlib.FMT_XML, sort_keys=True):
        raise ValueError("plist_scope_refused")
    return spec


@dataclass(frozen=True)
class McpDaemonIdentity:
    user_name: str
    group_name: str
    home: Path
    config_file: Path


def mcp_daemon_identity(data: bytes) -> McpDaemonIdentity:
    """Read the run-as identity from caller-supplied ``com.binnacle.mcp`` bytes.

    Pure: the caller decides where the bytes come from. A daemon without an
    explicit non-root ``UserName``/``GroupName`` is refused, never defaulted.
    """
    value = _load_dict(data)
    env = value.get("EnvironmentVariables")
    if value.get("Label") != MCP_DAEMON_LABEL or not isinstance(env, dict):
        raise ValueError("mcp_identity_invalid")
    home, config = env.get("HOME"), env.get("BINNACLE_CONFIG_FILE")
    if not isinstance(home, str) or not isinstance(config, str):
        raise ValueError("mcp_identity_invalid")  # noqa: TRY004 - one error type
    if not _normal_absolute(Path(home)) or not _normal_absolute(Path(config)):
        raise ValueError("mcp_identity_invalid")
    return McpDaemonIdentity(
        _account(value.get("UserName")),
        _account(value.get("GroupName")),
        Path(home),
        Path(config),
    )


def jobs_test_label(label: str) -> str:
    """A test-owned manager label: the A3 role suffix must be ``.manager``."""
    validate_test_label(label)
    if not label.endswith(".manager"):
        raise ValueError("label_not_manager_role")
    return label


def render_jobs_test_plist(
    label: str,
    *,
    argv: Sequence[str],
    environment: Mapping[str, str],
    workdir: Path,
    runtime_dir: Path,
    number_of_processes: int,
) -> bytes:
    """User-domain test variant of ``com.binnacle.jobs`` for owned test labels.

    It shares every lifecycle key with the production plan (RunAtLoad,
    Standard QoS, AbandonProcessGroup=false, ExitTimeOut, throttle, limits)
    but stays in A3's accepted test scope: a ``com.binnacle.r3test.*.manager``
    label, ``KeepAlive=false`` (the test owns every restart),
    ``LimitLoadToSessionType=Background``, no ``UserName``/``GroupName`` and
    no raw log paths. It is never valid for the system domain.
    """
    jobs_test_label(label)
    if not argv or not all(isinstance(a, str) and a for a in argv):
        raise ValueError("argv_invalid")
    if not Path(argv[0]).is_absolute():
        raise ValueError("argv0_not_absolute")
    if not workdir.is_absolute() or not runtime_dir.is_absolute():
        raise ValueError("path_not_absolute")
    env = dict(environment)
    env["BINNACLE_SERVICE_ROLE"] = "manager"
    env["BINNACLE_RUNTIME_DIR"] = str(runtime_dir)
    body = _jobs_lifecycle(argv, number_of_processes)
    body.update(
        {
            "Label": label,
            "EnvironmentVariables": dict(sorted(env.items())),
            "WorkingDirectory": str(workdir),
            "KeepAlive": False,
            "LimitLoadToSessionType": "Background",
        }
    )
    return plistlib.dumps(body, fmt=plistlib.FMT_XML, sort_keys=True)


def validate_jobs_test_plist_bytes(
    data: bytes, *, label: str, runtime_dir: Path
) -> None:
    """Refuse bytes that are not the user-domain test variant for ``label``."""
    jobs_test_label(label)
    value = _load_dict(data)
    env = value.get("EnvironmentVariables")
    argv = value.get("ProgramArguments")
    if (
        not value.keys() <= _JOBS_TEST_KEYS
        or value.get("Label") != label
        or not isinstance(argv, list)
        or not argv
        or not all(isinstance(a, str) and a for a in argv)
        or not Path(argv[0]).is_absolute()
        or value.get("KeepAlive") is not False
        or value.get("LimitLoadToSessionType") != "Background"
        or not _lifecycle_matches(value)
        or not isinstance(env, dict)
        or env.get("BINNACLE_SERVICE_ROLE") != "manager"
        or env.get("BINNACLE_RUNTIME_DIR") != str(runtime_dir)
    ):
        raise ValueError("plist_scope_refused")
