"""Config-free ripgrep invocation for the Linux list/search paths (r6 W2 X3c).

ripgrep reads extra flags from the file named by RIPGREP_CONFIG_PATH. A
config with --follow, --hidden or --no-ignore would change which objects rg
walks and opens, below the tools' own policy. Every Linux rg call therefore
passes --no-config and runs with an environment that lacks the variable;
all other variables (PATH, LANG, ...) are inherited unchanged.
"""

import functools
import os
import re
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from pathlib import Path
from typing import ParamSpec

from fastmcp.tools.base import ToolResult

from binnacle.features.files.fd_walk import permission_denied

P = ParamSpec("P")

NO_CONFIG = "--no-config"
CONFIG_ENV = "RIPGREP_CONFIG_PATH"


def rg_env() -> dict[str, str]:
    """The current environment without RIPGREP_CONFIG_PATH."""
    return {k: v for k, v in os.environ.items() if k != CONFIG_ENV}


PATTERN_HINT = "Fix the pattern, or use fixed_strings for literal text."


def rejection_message(stderr: str) -> str:
    """The rg_rejected text; a permission-only failure is not a pattern problem."""
    lines = [line for line in stderr.splitlines() if line.strip()]
    if lines and all(
        "permission denied" in line.lower() or "os error 13" in line for line in lines
    ):
        return (
            f"ripgrep could not read part of the search path: {stderr.strip()[-300:]}. "
            "Check the permissions of the path, or search a narrower path."
        )
    return f"ripgrep rejected the search: {stderr.strip()[-300:]}. {PATTERN_HINT}"


# Unreadable paths below a recursive search or glob (r6 W3 PX1, R-OS1-F1/F4).
# Both OSes return the readable part of the result plus one note naming what
# was skipped; only an unreadable base is an error (permission_denied, or
# Darwin's permission_denied_tcc_possible with the same text, SD-77).
UNREADABLE: ContextVar[list[str] | None] = ContextVar(
    "binnacle_unreadable_paths", default=None
)
NOTE_SHOWN = 5
_DENIED = re.compile(
    r"rg: (?P<path>.+?): (?:IO error for operation on .+?: )?"
    r"Permission denied \(os error 13\)"
)


def permission_paths(stderr: str, base: Path) -> list[str] | None:
    """The paths of a permission-only rg stderr, as absolute strings, else None.

    rg exits 2 when it cannot read a directory or a file, after reporting
    everything it could read. Any other stderr line keeps rg's failure.
    """
    found = []
    for line in stderr.splitlines():
        if not line.strip():
            continue
        match = _DENIED.fullmatch(line.strip())
        if match is None:
            return None
        found.append(os.path.normpath(base / match["path"]))
    return found or None


def record_unreadable(paths: Iterable[str]) -> None:
    """Add paths to the current call's note; outside a call they are dropped."""
    collected = UNREADABLE.get()
    if collected is not None:
        collected.extend(paths)


def unreadable_note(paths: Iterable[str]) -> str:
    """One sentence for both OSes: the count, then the first few, sorted."""
    unique = sorted(set(paths))
    shown = ", ".join(unique[:NOTE_SHOWN])
    more = f" and {len(unique) - NOTE_SHOWN} more" if len(unique) > NOTE_SHOWN else ""
    noun = "path" if len(unique) == 1 else "paths"
    return (
        f"Skipped {len(unique)} unreadable {noun} (permission denied): "
        f"{shown}{more}. Results exclude their contents."
    )


def noting_unreadable(impl: Callable[P, ToolResult]) -> Callable[P, ToolResult]:
    """Collect unreadable paths during impl; add the note to its result."""

    @functools.wraps(impl)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> ToolResult:
        token = UNREADABLE.set([])
        try:
            result = impl(*args, **kwargs)
            paths = UNREADABLE.get() or []
        finally:
            UNREADABLE.reset(token)
        if not paths or not isinstance(result.structured_content, dict):
            return result
        note = unreadable_note(paths)
        payload = dict(result.structured_content)
        payload["note"] = f"{payload['note']} {note}" if "note" in payload else note
        text = getattr(result.content[0], "text", "") if result.content else ""
        return ToolResult(content=f"{text} {note}".strip(), structured_content=payload)

    return wrapper


def accept_denied(stderr: str, base: Path) -> bool:
    """A permission-only rg failure below base is a partial result (F1).

    Records the paths for the note and returns True; an unreadable base is
    permission_denied. Any other failure returns False: rg's error stands.
    Outside a tool call (no note collector) nothing could report the skipped
    paths, so the failure stands too: nothing is dropped silently.
    """
    paths = permission_paths(stderr, base)
    if paths is None or UNREADABLE.get() is None:
        return False
    if os.path.normpath(base) in paths:
        raise permission_denied(base)
    record_unreadable(paths)
    return True
