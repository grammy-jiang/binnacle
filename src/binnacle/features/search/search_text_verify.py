"""Verify-after-open for reported search_text matches (r6 W2 X3c, SD-76).

ripgrep walks and opens files by path string, so a same-uid swap of a
component for a symlink between rg's directory read and its open can make
rg read an object outside the roots. Before a match is reported, its file
is opened again here: every component from '/' is opened no-follow relative
to its opened parent (fd_walk), the file itself with READ_FLAGS (O_NOFOLLOW,
O_NONBLOCK), and it must be a regular file. Each reported line is then read
from that descriptor and must equal the line rg reported. A file that fails
any step is omitted with all its lines. The reported path is canonical and
lies below the resolved search base, so a descriptor walk of its lexical
components keeps the opened object at that in-root path; no path string is
reopened after the walk.
"""

import os
import stat
from collections.abc import Iterable, Iterator
from contextlib import ExitStack
from pathlib import PurePosixPath

from binnacle.features.files import fd_walk
from binnacle.features.search.search_text_stream_reduce import ExactScanResult

_CHUNK = 1 << 20
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
_UTF8_BOM = b"\xef\xbb\xbf"


class DirectoryCache:
    """Descriptors of directories walked no-follow from '/', shared per call."""

    def __init__(self, stack: ExitStack) -> None:
        self._stack = stack
        self._fds: dict[tuple[str, ...], int] = {}

    def directory(self, parts: tuple[str, ...]) -> int:
        """The descriptor of /parts; every component is opened no-follow."""
        if parts in self._fds:
            return self._fds[parts]
        if not parts:
            fd = os.open("/", fd_walk.TRAVERSE_FLAGS)
        else:
            parent = self.directory(parts[:-1])
            fd = os.open(parts[-1], fd_walk.TRAVERSE_FLAGS, dir_fd=parent)
        self._stack.callback(os.close, fd)
        self._fds[parts] = fd
        return fd


def split(path: str) -> tuple[tuple[str, ...], str] | None:
    """(parent components below '/', final name), or None if not canonical."""
    pure = PurePosixPath(path)
    parts = pure.parts
    if not pure.is_absolute() or len(parts) < 2 or ".." in parts:
        return None
    return tuple(parts[1:-1]), parts[-1]


def open_regular(cache: DirectoryCache, path: str) -> int | None:
    """A read descriptor of the regular file at path, or None."""
    where = split(path)
    if where is None:
        return None
    parts, name = where
    try:
        fd = os.open(name, fd_walk.READ_FLAGS, dir_fd=cache.directory(parts))
    except OSError:
        return None
    try:
        if stat.S_ISREG(os.fstat(fd).st_mode):
            return fd
    except OSError:
        pass
    os.close(fd)
    return None


def _read_all(fd: int) -> bytes:
    chunks = []
    while chunk := os.read(fd, _CHUNK):
        chunks.append(chunk)
    return b"".join(chunks)


def _raw_lines(fd: int) -> Iterator[bytes]:
    """Lines as rg numbers them: BOM sniffed, split on b'\\n' only."""
    pending = b""
    while len(pending) < len(_UTF8_BOM) and (chunk := os.read(fd, _CHUNK)):
        pending += chunk  # a short read must not hide a BOM
    utf16 = pending[:2] in _UTF16_BOMS
    if utf16:
        pending += _read_all(fd)
        pending = pending.decode("utf-16", "replace").encode("utf-8")
    pending = pending.removeprefix(_UTF8_BOM)
    while True:
        *complete, pending = pending.split(b"\n")
        for line in complete:
            yield line + b"\n"
        chunk = b"" if utf16 else os.read(fd, _CHUNK)
        if not chunk:
            break
        pending += chunk
    if pending:
        yield pending


def _text(raw: bytes) -> str:
    # The reported form: rg sends invalid UTF-8 as 'bytes', collected as "".
    try:
        return raw.decode("utf-8").rstrip("\n")
    except UnicodeDecodeError:
        return ""


def fd_lines(fd: int, wanted: Iterable[int]) -> dict[int, str]:
    """The reported text of each wanted line number read from fd."""
    numbers = set(wanted)
    found: dict[int, str] = {}
    if not numbers:
        return found
    last = max(numbers)
    for number, raw in enumerate(_raw_lines(fd), 1):
        if number > last:
            break
        if number in numbers:
            found[number] = _text(raw)
    return found


def verified_files(
    lines_by_file: dict[str, dict[int, str]],
    *,
    snippet: bool = False,
) -> set[str]:
    """The files whose reported lines all equal the lines read after open.

    With snippet, a reported text ending in '…' may be a prefix of the line
    (adaptive discovery clips snippets).
    """
    good: set[str] = set()
    with ExitStack() as stack:
        cache = DirectoryCache(stack)
        for path, lines in lines_by_file.items():
            fd = open_regular(cache, path)
            if fd is None:
                continue
            try:
                found = fd_lines(fd, lines)
            except OSError:
                continue
            finally:
                os.close(fd)
            if all(
                _same(found.get(number), text, snippet)
                for number, text in lines.items()
            ):
                good.add(path)
    return good


def _same(found: str | None, text: str, snippet: bool) -> bool:
    if found is None:
        return False
    if found == text:
        return True
    return snippet and text.endswith("…") and found.startswith(text[:-1])


def verify_scan(
    matches: list[dict],
    line_map: dict[str, dict[int, str]],
    total: int,
) -> tuple[list[dict], dict[str, dict[int, str]], int]:
    """Drop the matches and lines of every reported file that fails."""
    reported = {match["file"] for match in matches}
    good = verified_files({file: line_map.get(file, {}) for file in reported})
    if good == reported:
        return matches, line_map, total
    kept = [match for match in matches if match["file"] in good]
    dropped = len(matches) - len(kept)
    kept_map = {
        file: lines
        for file, lines in line_map.items()
        if file in good or file not in reported
    }
    return kept, kept_map, total - dropped


def verify_exact_scan(scan: ExactScanResult) -> ExactScanResult:
    """verify_scan applied to an exact scan; adaptive events stay rg's."""
    scan.matches, scan.line_map, scan.total = verify_scan(
        scan.matches, scan.line_map, scan.total
    )
    return scan


def verify_adaptive(payload: dict) -> dict:
    """Drop the adaptive entries of every file that fails (lines or tail)."""
    entries = payload.get("entries", [])
    lines_by_file: dict[str, dict[int, str]] = {}
    for entry in entries:
        file = entry.get("file")
        if not isinstance(file, str):
            continue
        lines = lines_by_file.setdefault(file, {})
        if isinstance(entry.get("line"), int):
            lines[entry["line"]] = str(entry.get("text", ""))
    good = verified_files(lines_by_file, snippet=True)
    if good == set(lines_by_file):
        return payload
    return {
        **payload,
        "entries": [entry for entry in entries if entry.get("file") in good],
    }
