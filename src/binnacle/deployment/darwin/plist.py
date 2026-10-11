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


def render_plist(
    label: str,
    *,
    argv: Sequence[str],
    environment: Mapping[str, str],
    workdir: Path,
    log_path: Path,
) -> bytes:
    """Render a launchd job that is not loaded at login and opens no sockets.

    ``RunAtLoad``/``KeepAlive`` are false and there is no ``Sockets`` key, so
    the job starts only when explicitly bootstrapped and kicked by the test.
    """
    validate_test_label(label)
    if not argv or not all(isinstance(a, str) and a for a in argv):
        raise ValueError("argv_invalid")
    if not Path(argv[0]).is_absolute():
        raise ValueError("argv0_not_absolute")
    if not workdir.is_absolute() or not log_path.is_absolute():
        raise ValueError("path_not_absolute")
    body: dict[str, object] = {
        "Label": label,
        "ProgramArguments": list(argv),
        "EnvironmentVariables": dict(sorted(environment.items())),
        "WorkingDirectory": str(workdir),
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
        "RunAtLoad": False,
        "KeepAlive": False,
        "ProcessType": "Background",
    }
    return plistlib.dumps(body, fmt=plistlib.FMT_XML, sort_keys=True)
