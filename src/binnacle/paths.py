"""Path guard and glob matcher shared by every file-facing tool.

Design: docs/agent-toolset-design.md §6.7 (what this defends and what it
does not) and §7.11. Sanitization details: docs/tools/read_file.md §3.
"""

import fnmatch
import re
from functools import lru_cache
from pathlib import Path, PurePath, PurePosixPath

from fastmcp.exceptions import ToolError

from binnacle.config import get_settings

DEFAULT_ROOT = get_settings().roots.default_root
ALLOWED_ROOTS = get_settings().roots.allowed


def resolve_path(raw: str) -> Path:
    """Sanitize a model-supplied path and resolve it inside ALLOWED_ROOTS."""
    cleaned = raw.replace("\0", "").strip()
    # Models occasionally emit a hallucinated "@" reference prefix.
    cleaned = cleaned.removeprefix("@")
    try:
        candidate = Path(cleaned).expanduser()
        if not candidate.is_absolute():
            candidate = DEFAULT_ROOT / candidate
        resolved = candidate.resolve()
    except (RuntimeError, OSError) as e:
        # expanduser() raises RuntimeError for `~nosuchuser`; resolve() can
        # raise OSError on pathological names. Found by the property test
        # 2026-09-13: either would reach the client as an internal error.
        raise ToolError(f"Cannot resolve path {raw!r}: {e}") from None
    if not any(resolved.is_relative_to(root) for root in ALLOWED_ROOTS):
        roots = ", ".join(str(r) for r in ALLOWED_ROOTS)
        raise ToolError(f"Path outside allowed roots ({roots}): {resolved}")
    return resolved


def _unwrap_fnmatch_translation(translated: str) -> str | None:
    """Return the regex body from fnmatch.translate's DOTALL wrapper.

    Python 3.14 changed the terminal anchor from ``\\Z`` to ``\\z``.
    Treat both as stdlib wrappers without compiling either anchor here, so this
    compatibility path itself also runs on Python 3.10-3.13.
    """
    prefix = "(?s:"
    for suffix in (r")\Z", r")\z"):
        if translated.startswith(prefix) and translated.endswith(suffix):
            return translated[len(prefix) : -len(suffix)]
    return None


def _class_regex(inner: str) -> str:
    """Regex fragment for the character class `[inner]`, exactly as fnmatch
    would emit it: a reversed range like `[a-.]` becomes the never-matching
    `(?!)` rather than a compile error, `^` is a literal (only `!` negates),
    and `\\` / `--` are escaped the stdlib's way. Found by the differential
    property test on 2026-09-13; delegating keeps every quirk identical."""
    translated = fnmatch.translate(f"[{inner}]")
    fragment = _unwrap_fnmatch_translation(translated)
    if fragment is not None:
        return fragment
    # Unknown wrapper format (a future Python): fall back to the class as is.
    return f"[{inner}]"


def _glob_segment_regex(seg: str) -> str:
    """One glob segment as a regex fragment; * and ? never cross a slash."""
    res = []
    i = 0
    n = len(seg)
    while i < n:
        c = seg[i]
        if c == "*":
            res.append("[^/]*")
        elif c == "?":
            res.append("[^/]")
        elif c == "[":
            # The same boundary scan as fnmatch.translate: an optional `!`,
            # then a `]` that is part of the class, then up to the closing `]`.
            j = i + 1
            if j < n and seg[j] == "!":
                j += 1
            if j < n and seg[j] == "]":
                j += 1
            while j < n and seg[j] != "]":
                j += 1
            if j >= n:
                res.append(r"\[")  # unterminated class is a literal bracket
            else:
                res.append(_class_regex(seg[i + 1 : j]))
                i = j
        else:
            res.append(re.escape(c))
        i += 1
    return "".join(res)


@lru_cache(maxsize=256)
def _glob_regex(pattern: str) -> "re.Pattern[str]":
    # PurePath-normalize first, as the stdlib matcher does: doubled or
    # trailing slashes and "." segments vanish, so "**/" means "**".
    parts = str(PurePosixPath(pattern)).split("/")
    out = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "**":
            # The stdlib's own translation (glob.translate): a trailing ** is
            # `.*`, any other is `(?:.+/)?` -- "nothing, or at least one
            # character then a slash". The `.+` may span the root of an
            # absolute path, so "/a/a" matches "**/a" but "/a" does not;
            # a per-segment `(?:[^/]+/)*` got the first case wrong
            # (found by the differential test under mutmut, 2026-09-13).
            out.append(".*" if last else "(?:.+/)?")
            continue
        out.append(_glob_segment_regex(part) + ("" if last else "/"))
    try:
        # DOTALL as the stdlib's `(?s:...)` wrapper: a newline in a name is
        # an ordinary character for `.*` and `.+`.
        return re.compile("".join(out), re.DOTALL)
    except re.error as e:
        raise ValueError(str(e)) from None


def full_match(path: "PurePath | str", pattern: str) -> bool:
    """PurePath.full_match for Python 3.10+ (the stdlib method needs 3.13).

    POSIX rules, case-sensitive: * and ? stay inside one segment, a
    whole-segment ** spans any number of segments, [seq] classes as in
    fnmatch, embedded ** degrades to *. Raises ValueError for a pattern
    whose character class does not compile, matching the callers'
    except ValueError -> ToolError contract.
    """
    # Normalize the path as the stdlib does ("a/." is "a", "./a" is "a").
    # An empty path (".") has no segments, so only a pattern made of `**`
    # segments -- or an empty pattern -- can match it (2026-09-13).
    normalized = PurePosixPath(str(path))
    if not normalized.parts:
        return all(part == "**" for part in PurePosixPath(pattern).parts)
    return _glob_regex(pattern).fullmatch(str(normalized)) is not None


def nearby_hint(parent: Path) -> str:
    """Not-found helper: up to 10 sibling names, when the parent is browsable."""
    try:
        if not any(parent.is_relative_to(root) for root in ALLOWED_ROOTS):
            return ""
        names = sorted(p.name + ("/" if p.is_dir() else "") for p in parent.iterdir())
    except OSError:
        return ""
    if not names:
        return f" Directory {parent} is empty."
    shown = ", ".join(names[:10])
    more = " …" if len(names) > 10 else ""
    return f" Files in {parent}: {shown}{more}. Use list_files for more."
