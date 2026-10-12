"""Path checks for reported search_text matches (r6 W2 X3c-a3, SD-78).

ripgrep walks and opens files by path string, so a same-uid swap of a
component for a symlink between rg's directory read and its open can make
rg read an object outside the roots. Before a match is reported, its path
is checked twice; rg's text is reported as in r6, and the content is not
read again (the content race is a documented residual, SD-78):

1. Prefix: the path must be absolute with no '..' component, and its
   components must start with those of the resolved search base (exactly
   the base when the base is a file). rg is told to search only the base,
   but this does not rely on it.
2. Object: every directory component from '/' is opened no-follow relative
   to its opened parent (fd_chain, fd_walk.TRAVERSE_FLAGS), and the final
   component is stat-ed relative to that descriptor without following a
   symlink. It must be a regular file.

A file that fails either check is omitted with all its lines, and its
retained matches are subtracted from count.
"""

import os
import stat
from collections.abc import Iterable
from pathlib import Path

from binnacle.errors import CodedToolError
from binnacle.features.search.fd_chain import EXHAUSTED, DirectoryChain
from binnacle.features.search.search_text_stream_reduce import ExactScanResult


def components(path: str) -> list[str] | None:
    """The components of an absolute canonical path, or None.

    Plain string splitting (PurePosixPath costs more than the walk itself):
    a relative path, an empty, '.' or '..' component, or '/' is refused.
    """
    if not path.startswith("/"):
        return None
    parts = path[1:].split("/")
    for part in parts:
        if part in ("", ".", ".."):
            return None
    return parts


def below_base(parts: list[str], base: list[str], base_is_file: bool) -> bool:
    """True if parts are base (a file base) or lie below base (a directory)."""
    if base_is_file:
        return parts == base
    return len(parts) > len(base) and parts[: len(base)] == base


def is_regular(chain: DirectoryChain, parts: list[str]) -> bool:
    """True if /parts is a regular file reached by a no-follow walk from '/'."""
    try:
        info = os.stat(
            parts[-1], dir_fd=chain.directory(tuple(parts[:-1])), follow_symlinks=False
        )
    except OSError as exc:
        if exc.errno in EXHAUSTED:
            raise CodedToolError(
                "too_many_open_files",
                "search_text could not check the reported files: the server "
                "has too many open files. Retry, or narrow the search.",
            ) from exc
        return False
    return stat.S_ISREG(info.st_mode)


def checked_files(files: Iterable[str], base: Path) -> set[str]:
    """The reported files that pass the prefix and the object check."""
    base_parts = [part for part in str(base).split("/") if part]
    base_is_file = os.path.isfile(base)
    good: set[str] = set()
    with DirectoryChain() as chain:
        for path in files:
            parts = components(path)
            if (
                parts is not None
                and below_base(parts, base_parts, base_is_file)
                and is_regular(chain, parts)
            ):
                good.add(path)
    return good


def verify_scan(
    matches: list[dict],
    line_map: dict[str, dict[int, str]],
    total: int,
    base: Path,
) -> tuple[list[dict], dict[str, dict[int, str]], int]:
    """Drop the matches and lines of every reported file that fails."""
    reported = list(dict.fromkeys(match["file"] for match in matches))
    good = checked_files(reported, base)
    if len(good) == len(reported):
        return matches, line_map, total
    kept = [match for match in matches if match["file"] in good]
    dropped = len(matches) - len(kept)
    kept_map = {
        file: lines
        for file, lines in line_map.items()
        if file in good or file not in reported
    }
    return kept, kept_map, total - dropped


def verify_exact_scan(scan: ExactScanResult, base: Path) -> ExactScanResult:
    """verify_scan applied to an exact scan; adaptive events stay rg's."""
    scan.matches, scan.line_map, scan.total = verify_scan(
        scan.matches, scan.line_map, scan.total, base
    )
    return scan


def verify_adaptive(payload: dict, base: Path) -> dict:
    """Drop the adaptive entries of every file that fails.

    Like the exact path, the dropped matches leave the payload count. Every
    entry of a file carries that file's match count, so one entry per
    dropped file is subtracted.
    """
    entries = payload.get("entries", [])
    files = list(
        dict.fromkeys(
            entry["file"] for entry in entries if isinstance(entry.get("file"), str)
        )
    )
    good = checked_files(files, base)
    if len(good) == len(files):
        return payload
    counted: dict[str, int] = {}
    for entry in entries:
        file = entry.get("file")
        if isinstance(file, str) and file not in good and file not in counted:
            counted[file] = entry.get("count", 0)
    dropped = sum(counted.values())
    adjusted = {
        **payload,
        "entries": [entry for entry in entries if entry.get("file") in good],
    }
    if isinstance(payload.get("count"), int):
        adjusted["count"] = payload["count"] - dropped
        note = payload.get("note")
        if isinstance(note, str):
            adjusted["note"] = note.replace(
                f"for {payload['count']} matches", f"for {adjusted['count']} matches", 1
            )
    return adjusted


def candidate_files(payload: dict) -> int:
    """The distinct files left in an adaptive payload."""
    return len(
        {
            entry.get("file")
            for entry in payload.get("entries", [])
            if isinstance(entry, dict) and isinstance(entry.get("file"), str)
        }
    )
