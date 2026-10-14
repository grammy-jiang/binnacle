"""Config-free ripgrep invocation for the Linux list/search paths (r6 W2 X3c).

ripgrep reads extra flags from the file named by RIPGREP_CONFIG_PATH. A
config with --follow, --hidden or --no-ignore would change which objects rg
walks and opens, below the tools' own policy. Every Linux rg call therefore
passes --no-config and runs with an environment that lacks the variable;
all other variables (PATH, LANG, ...) are inherited unchanged.
"""

import bisect
import functools
import hashlib
import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, ParamSpec

import orjson
from fastmcp.tools.base import ToolResult

from binnacle.errors import CodedToolError
from binnacle.features.files.fd_walk import permission_denied

P = ParamSpec("P")

NO_CONFIG = "--no-config"
CONFIG_ENV = "RIPGREP_CONFIG_PATH"


def rg_env() -> dict[str, str]:
    """The current environment without RIPGREP_CONFIG_PATH."""
    return {k: v for k, v in os.environ.items() if k != CONFIG_ENV}


PATTERN_HINT = "Fix the pattern, or use fixed_strings for literal text."


def shown(text: str) -> str:
    """text for a model-visible message: a non-UTF-8 byte as a \\x escape.

    rg output is decoded with os.fsdecode (surrogateescape), as the search
    path decodes names (R-PX1-3); a lone surrogate cannot be sent as JSON.
    """
    return os.fsencode(text).decode("utf-8", "backslashreplace")


def rejection_message(stderr: str) -> str:
    """The rg_rejected text; a permission-only failure is not a pattern problem."""
    lines = [line for line in stderr.splitlines() if line.strip()]
    tail = shown(stderr.strip()[-300:])
    if lines and all(
        "permission denied" in line.lower() or "os error 13" in line for line in lines
    ):
        return (
            f"ripgrep could not read part of the search path: {tail}. "
            "Check the permissions of the path, or search a narrower path."
        )
    return f"ripgrep rejected the search: {tail}. {PATTERN_HINT}"


# Unreadable paths below a recursive search or glob (r6 W3 PX1, R-OS1-F1/F4).
# Both OSes return the readable part of the result plus one note naming what
# was skipped; only an unreadable base is an error (permission_denied, or
# Darwin's permission_denied_tcc_possible with the same text, SD-77).
UNREADABLE: ContextVar[list[str] | None] = ContextVar(
    "binnacle_unreadable_paths", default=None
)
# Unreadable paths counted but not named (beyond the NOTE_SHOWN smallest).
UNNAMED: ContextVar[int] = ContextVar("binnacle_unreadable_unnamed", default=0)
NOTE_SHOWN = 5
# rg stderr is parsed whole, never a tail (R-PX1-1). Past this size rg's
# failure stands (fail closed); the scan itself keeps bounded memory.
STDERR_SCAN_CAP = 16 * 1024 * 1024
_DENIED = re.compile(
    r"rg: (?P<path>.+?): (?:IO error for operation on .+?: )?"
    r"Permission denied \(os error 13\)"
)


class DeniedScan:
    """One bounded pass over ALL of rg's stderr (R-PX1-1).

    Every permission line is counted; only the NOTE_SHOWN smallest paths are
    kept, so memory stays bounded however much rg printed. Any other
    non-empty line, anywhere, keeps rg's failure. Bytes are decoded with
    os.fsdecode (surrogateescape), never strictly (R-PX1-3). rg reports each
    unreadable path once; a repeat is not counted again while it is named.
    """

    def __init__(self, base: Path) -> None:
        self.base = os.path.normpath(base)
        self.count = 0
        self.names: list[str] = []
        self.base_denied = False
        self.other = False

    def feed(self, line: str | bytes) -> None:
        text = (os.fsdecode(line) if isinstance(line, bytes) else line).strip()
        if not text or self.other:
            return
        match = _DENIED.fullmatch(text)
        if match is None:
            self.other = True
            return
        path = os.path.normpath(os.path.join(self.base, match["path"]))
        if path in self.names:
            return
        self.count += 1
        self.base_denied = self.base_denied or path == self.base
        bisect.insort(self.names, path)
        del self.names[NOTE_SHOWN:]


def scan_denied(stderr: str | bytes | BinaryIO, base: Path) -> DeniedScan | None:
    """The scan of a permission-only rg stderr, else None (fail closed).

    A str or bytes stderr is split into lines; a spooled stderr file is read
    from its start, line by line. Above STDERR_SCAN_CAP nothing is parsed.
    """
    scan = DeniedScan(base)
    if isinstance(stderr, (str, bytes)):
        if len(stderr) > STDERR_SCAN_CAP:
            return None
        for line in stderr.splitlines():
            scan.feed(line)
    else:
        stderr.flush()
        if stderr.seek(0, os.SEEK_END) > STDERR_SCAN_CAP:
            return None
        stderr.seek(0)
        for raw in stderr:
            scan.feed(raw)
    return None if scan.other or not scan.count else scan


def permission_paths(stderr: str | bytes, base: Path) -> list[str] | None:
    """The first NOTE_SHOWN paths (sorted) of a permission-only rg stderr, else None.

    rg exits 2 when it cannot read a directory or a file, after reporting
    everything it could read. Any other stderr line keeps rg's failure.
    """
    scan = scan_denied(stderr, base)
    return None if scan is None else scan.names


def record_unreadable(paths: Iterable[str], unnamed: int = 0) -> None:
    """Add paths (and a count of unnamed ones) to the current call's note.

    Outside a call they are dropped.
    """
    collected = UNREADABLE.get()
    if collected is not None:
        collected.extend(paths)
        if unnamed:
            UNNAMED.set(UNNAMED.get() + unnamed)


def unreadable_note(paths: Iterable[str], unnamed: int = 0) -> str:
    """One sentence for both OSes: the count, then the first few, sorted."""
    unique = sorted(set(paths))
    total = len(unique) + unnamed
    names = ", ".join(shown(path) for path in unique[:NOTE_SHOWN])
    more = f" and {total - NOTE_SHOWN} more" if total > NOTE_SHOWN else ""
    noun = "path" if total == 1 else "paths"
    return (
        f"Skipped {total} unreadable {noun} (permission denied): "
        f"{names}{more}. Results exclude their contents."
    )


def noting_unreadable(impl: Callable[P, ToolResult]) -> Callable[P, ToolResult]:
    """Collect unreadable paths during impl; add the note to its result."""

    @functools.wraps(impl)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> ToolResult:
        token, unnamed_token = UNREADABLE.set([]), UNNAMED.set(0)
        try:
            result = impl(*args, **kwargs)
            paths, unnamed = UNREADABLE.get() or [], UNNAMED.get()
        finally:
            UNREADABLE.reset(token)
            UNNAMED.reset(unnamed_token)
        if not paths or not isinstance(result.structured_content, dict):
            return result
        note = unreadable_note(paths, unnamed)
        payload = dict(result.structured_content)
        payload["note"] = f"{payload['note']} {note}" if "note" in payload else note
        text = getattr(result.content[0], "text", "") if result.content else ""
        return ToolResult(content=f"{text} {note}".strip(), structured_content=payload)

    return wrapper


def accept_denied(stderr: str | bytes | BinaryIO, base: Path) -> bool:
    """A permission-only rg failure below base is a partial result (F1).

    Records the paths for the note and returns True; an unreadable base is
    permission_denied. Any other failure returns False: rg's error stands.
    Outside a tool call (no note collector) nothing could report the skipped
    paths, so the failure stands too: nothing is dropped silently. The whole
    stderr is scanned (R-PX1-1); glob and search give the same answer.
    """
    scan = scan_denied(stderr, base)
    if scan is None or UNREADABLE.get() is None:
        return False
    if scan.base_denied:
        raise permission_denied(base)
    record_unreadable(scan.names, scan.count - len(scan.names))
    return True


# PX1B-F4: search-specific non-UTF-8 result omissions share this
# config-free rg metadata boundary; no new startup import is required.
MAX_NAME_IDENTITIES = 4096


@dataclass
class _Observed:
    digests: set[bytes] = field(default_factory=set)
    over_limit: bool = False


_ACTIVE: ContextVar[_Observed | None] = ContextVar(
    "search_unrepresentable", default=None
)


def observe_rg_event(event: dict) -> None:
    """Count distinct byte-name match events before glob or result truncation.

    The digest, not the filename, is retained; bound memory even if rg scans
    millions of distinct filenames. Context lines and duplicate matches in
    one file do not raise its distinct-file count.
    """
    active = _ACTIVE.get()
    if active is None or event.get("type") != "match":
        return
    data = event.get("data")
    if not isinstance(data, dict):
        return
    path = data.get("path")
    if not isinstance(path, dict) or isinstance(path.get("text"), str):
        return
    encoded = path.get("bytes")
    if not isinstance(encoded, str) or not encoded.isascii():
        return
    identity = hashlib.sha256(encoded.encode("ascii")).digest()[:16]
    if identity in active.digests:
        return
    if len(active.digests) >= MAX_NAME_IDENTITIES:
        active.over_limit = True
    else:
        active.digests.add(identity)


def noting_non_utf8_search(impl: Callable[P, ToolResult]) -> Callable[P, ToolResult]:
    """Extend one exact search result without granting authority to bad paths."""

    @functools.wraps(impl)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> ToolResult:
        state = _Observed()
        token = _ACTIVE.set(state)
        try:
            result = impl(*args, **kwargs)
        finally:
            _ACTIVE.reset(token)
        if not state.digests or not isinstance(result.structured_content, dict):
            return result
        count = len(state.digests)
        word = "filename" if count == 1 else "filenames"
        count_text = f"at least {count}" if state.over_limit else str(count)
        note = (
            f"Skipped {count_text} non-UTF-8 {word} from search results "
            "before glob filtering."
        )
        payload = dict(result.structured_content)
        payload["note"] = f"{payload['note']} {note}" if "note" in payload else note
        text = getattr(result.content[0], "text", "") if result.content else ""
        return ToolResult(content=f"{text} {note}".strip(), structured_content=payload)

    return wrapper


def noting_search_with_budget(impl: Callable[P, ToolResult]) -> Callable[P, ToolResult]:
    """Finalize search after BOTH safe-omission and denied-path annotations.

    Keep a compact wire-size upper bound even if a near-cap result acquires a
    late note. A whole entry is removed at a time; the real total stays
    unchanged. Do not drop safety notes to squeeze out one more match.
    """
    noted = noting_unreadable(noting_non_utf8_search(impl))

    @functools.wraps(impl)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> ToolResult:
        token = _SEARCH_METRICS.set(None)
        logger = logging.getLogger("binnacle.search_text")
        annotated: ToolResult | None = None
        try:
            try:
                annotated = noted(*args, **kwargs)
                start = time.perf_counter_ns()
                try:
                    result, trimmed = _close_search_budget(annotated, dict(kwargs))
                finally:
                    metrics = _SEARCH_METRICS.get()
                    if metrics is not None:
                        metrics.budget_ms += (
                            time.perf_counter_ns() - start
                        ) / 1_000_000
            except Exception as exc:
                metrics = _SEARCH_METRICS.get()
                if metrics is not None:
                    if (
                        annotated is not None
                        and getattr(exc, "telemetry_code", None)
                        == "response_budget_exceeded"
                    ):
                        payload = annotated.structured_content
                        if isinstance(payload, dict):
                            # This is the attempted fully annotated result
                            # size, not an emitted result (failure is fail-closed).
                            metrics.result_bytes = len(orjson.dumps(payload))
                            metrics.mark_result(payload, strategy=metrics.strategy)
                        metrics.budget_outcome = "final_note_metadata_error"
                    metrics.log_terminal(logger, exc)
                raise
            metrics = _SEARCH_METRICS.get()
            if metrics is not None:
                payload = result.structured_content
                if isinstance(payload, dict):
                    metrics.result_bytes = len(orjson.dumps(payload))
                    metrics.mark_result(payload, strategy=metrics.strategy)
                if trimmed:
                    metrics.budget_outcome = "final_note_entries_trimmed"
                metrics.log_terminal(logger)
            return result
        finally:
            _SEARCH_METRICS.reset(token)

    return wrapper


_SEARCH_METRICS: ContextVar[Any] = ContextVar("search_final_metrics", default=None)


def start_search_metrics(metrics: Any) -> None:
    """Hand exact-search terminal metrics to the outer, final response gate."""
    _SEARCH_METRICS.set(metrics)


def _close_search_budget(
    result: ToolResult, kwargs: dict[str, Any]
) -> tuple[ToolResult, bool]:
    payload = result.structured_content
    if not isinstance(payload, dict):
        return result, False
    # Lazy config access prevents a circular import during application
    # composition. The caller already resolved this same settings object.
    from binnacle.config import SearchTextSettings, get_settings

    supplied = kwargs.get("settings")
    settings = (
        supplied
        if isinstance(supplied, SearchTextSettings)
        else get_settings().search_text
    )
    limit = settings.result_max_bytes
    current_bytes = len(orjson.dumps(payload))
    if current_bytes <= limit:
        return result, False
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise CodedToolError(
            "response_budget_exceeded",
            "Search result metadata exceeds the configured response budget. "
            "Use a shorter pattern or a more specific path.",
        )
    original_note = str(payload.get("note", ""))
    total = payload.get("count", len(entries))

    def candidate(n: int) -> dict:
        message = (
            f"{original_note} Additional entries trimmed to {n} "
            "to satisfy the response budget."
        )
        return {
            **payload,
            "entries": entries[:n],
            "truncated": True,
            "note": message.strip(),
        }

    lo, hi = 0, len(entries)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(orjson.dumps(candidate(mid))) <= limit:
            lo = mid
        else:
            hi = mid - 1
    fitted = candidate(lo)
    final_bytes = len(orjson.dumps(fitted))
    if final_bytes > limit:
        raise CodedToolError(
            "response_budget_exceeded",
            "Search result metadata exceeds the configured response budget. "
            "Use a shorter pattern or a more specific path.",
        )
    logging.getLogger("binnacle.search_text").info(
        "event=search_final_output_budget count=%s returned_entries=%d "
        "result_bytes=%d result_budget_bytes=%d",
        total,
        lo,
        final_bytes,
        limit,
    )
    original_text = getattr(result.content[0], "text", "") if result.content else ""
    return (
        ToolResult(
            content=(
                f"{original_text} Additional entries trimmed to {lo} "
                "to satisfy the response budget."
            ),
            structured_content=fitted,
        ),
        True,
    )
