"""Pure, deterministic launchd plist rendering for test-owned Darwin services."""

from __future__ import annotations

import plistlib
from collections.abc import Mapping, Sequence
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
