"""Bounded ripgrep stdin search over opened Files capabilities.

Ignore discovery is confined to the grant: .gitignore/.ignore/.rgignore above
it and global policies are never read. NUL files are searched as text (rg
--text, as Linux; binary_files_skipped stays 0). As on Linux every file is
searched whole and all rg output consumed: bytes stream from the opened
descriptor into rg stdin by CHUNK, and rg JSON is parsed per line without
holding an oversize line. Each match yields one event; only the first
KEEP_MATCHES (and their context window) keep text, clipped to KEEP_CHARS + 1.
``truncated`` comes only from a capped file list. True limits are explicit
stats: skipped_io_error and skipped_text_over_memory_limit (text blanked).
Files use rg --sort path order. The helper owns one direct rg child, closes
pipes and reaps on every exit. This is not general process-tree control.
B0 alone enables reviewed tool wiring; full macOS parity remains unavailable.
"""

from __future__ import annotations

import base64
import json
import os
import re
import selectors
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from typing import cast

from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    BudgetExceeded,
    PermissionDenied,
    UnsafePath,
)
from binnacle.platform.contracts.file_access_contracts import (
    FileAccess,
    ListRequest,
    OpenedFile,
    RootGrant,
    SearchBatch,
    SearchRequest,
)
from binnacle.platform.darwin.file_traversal import (
    MAX_BYTES,
    MAX_VISITED,
    capability,
    deadline_after,
    glob_matches,
    native_errors,
    require_positive,
    unavailable,
    validate_relative_path,
)


def _command(rg_bin: str, request: SearchRequest) -> list[str]:
    argv = [rg_bin, "--no-config", "--json", "--smart-case", "--text"]
    if request.fixed_strings:
        argv.append("--fixed-strings")
    if request.context_lines:
        argv += ["--context", str(request.context_lines)]
    return [*argv, "--regexp", request.pattern, "--", "-"]


CHUNK = 65536
LINE_LIMIT = 1 << 20  # Larger rg JSON lines are scanned, never held whole.
KEEP_CHARS = 8192  # Retained line text; must exceed the shared max_line_chars.
KEEP_MATCHES = 10_000  # Must cover the shared max_results cap; later ones count.
_MARKER = b'"},"line_number":'  # Unique: '"' inside a JSON string is escaped.
_TEXT = b'"lines":{"text":"'
_NUMBER = re.compile(rb"(\d+),")
Source = Callable[[], bytes]
Event = dict[str, object]


class _SourceReadFailed(Exception):
    """A read on the opened descriptor failed mid-stream (not an rg failure)."""


def _descriptor_source(opened: OpenedFile) -> Source:
    """Read the already-opened descriptor CHUNK bytes at a time until EOF."""

    def chunk() -> bytes:
        try:
            return opened.read(CHUNK)
        except AuthorityUnknown as exc:
            # PermissionDenied/UnsafePath keep their open-time handling.
            raise _SourceReadFailed(exc.code) from None

    return chunk


def _decode(raw: bytes, complete: bool) -> str:
    """Decode a JSON string body; a cut prefix may end in an escape or a pair."""
    for cut in range(len(raw), max(-1, len(raw) - (1 if complete else 12)), -1):
        try:
            text = str(json.loads(b'"' + raw[:cut] + b'"'))[: KEEP_CHARS + 1]
        except (ValueError, UnicodeError):
            continue
        return text[:-1] if text and "\ud800" <= text[-1] <= "\udbff" else text
    raise unavailable("rg_invalid_output")


class _Reader:
    """Split rg stdout into events; an oversize line keeps only a short head."""

    def __init__(self, emit: Callable[[Event], None]) -> None:
        self.emit, self.buf, self.raw = emit, bytearray(), b""
        self.kind: str | None = None  # Set while skipping an oversize line.
        self.text: str | None = None
        self.number: int | None = None

    def feed(self, data: bytes) -> None:
        while data:
            if self.kind is not None:
                data = self._scan(data)
                continue
            cut = data.find(b"\n")
            if cut < 0:
                self.buf += data
                if len(self.buf) > LINE_LIMIT:
                    self._oversize()
                return
            self.buf += data[:cut]
            data = data[cut + 1 :]
            self._line(bytes(self.buf))
            self.buf.clear()

    def finish(self) -> None:
        if self.kind is not None:
            raise unavailable("rg_invalid_output")
        if self.buf:  # One reader per file: no reuse after finish().
            self._line(bytes(self.buf))

    def _line(self, line: bytes) -> None:
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            raise unavailable("rg_invalid_output") from None
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            raise unavailable("rg_invalid_output")
        self.emit(event)

    def _oversize(self) -> None:
        head = bytes(self.buf)
        self.buf.clear()
        self.kind = head[9:17].split(b'"')[0].decode("ascii", "replace")
        if not head.startswith(b'{"type":"') or self.kind not in ("match", "context"):
            raise unavailable("rg_invalid_output")
        start, end = head.find(_TEXT), head.find(_MARKER)
        if start >= 0:
            start += len(_TEXT)
            body = head[start:end] if end >= 0 else head[start : start + 7 * KEEP_CHARS]
            self.text = _decode(body, end >= 0)
        self.raw = head[end:] if end >= 0 else head[-64:]
        self._scan(b"")

    def _scan(self, data: bytes) -> bytes:
        if self.number is None:
            window = self.raw + data
            at = window.find(_MARKER)
            found = _NUMBER.match(window, at + len(_MARKER)) if at >= 0 else None
            if found is None:
                self.raw = window[at:] if at >= 0 else window[-64:]
                return b""
            self.number, data = int(found.group(1)), window[found.end() :]
        cut = data.find(b"\n")
        if cut < 0:
            return b""
        lines = {"bytes": ""} if self.text is None else {"text": self.text}
        data_ = {"path": {"text": "<stdin>"}, "lines": lines}
        self.emit({"type": self.kind, "data": {**data_, "line_number": self.number}})
        self.kind = self.text = self.number = None
        return data[cut + 1 :]


class _Collector:
    """Per-search events: every match counted, text only where it can show."""

    def __init__(self, budget: int, span: int) -> None:
        self.events: list[Event] = []
        self.budget, self.span = budget, span
        self.matches = self.kept = self.over_limit = 0

    def begin(self, display: str) -> _Reader:
        """Start one file; its fresh reader feeds add()."""
        self.pending: list[Event] = []
        self.saved = (self.matches, self.kept, self.over_limit)
        self.window = -1  # Last line still shown as context of match KEEP_MATCHES.
        try:
            display.encode("utf-8")
            self.path: dict[str, str] = {"text": display}
        except UnicodeError:
            encoded = base64.b64encode(os.fsencode(display)).decode("ascii")
            self.path = {"bytes": encoded}
        self.blank = {"path": self.path, "lines": {"text": ""}}
        return _Reader(self.add)

    def rollback(self) -> None:
        self.matches, self.kept, self.over_limit = self.saved

    def commit(self) -> None:
        self.events.extend(self.pending)

    def add(self, event: Event) -> None:
        data = cast("dict[str, object]", event["data"])  # Checked by _Reader.
        if "path" in data:
            data["path"] = self.path
        kind, line = event.get("type"), data.get("line_number")
        if kind in ("match", "context"):
            if not isinstance(line, int) or not isinstance(data.get("lines"), dict):
                raise unavailable("rg_invalid_output")
            if kind == "match":
                self.matches += 1
                if self.matches == KEEP_MATCHES:
                    self.window = line + self.span
            past = self.matches - (kind == "match") >= KEEP_MATCHES
            if past and line > self.window:
                if kind == "context":
                    return  # Never displayed; Linux keeps it only in memory.
                event = {"type": kind, "data": {**self.blank, "line_number": line}}
            else:
                self._keep(data)
        self.pending.append(event)

    def _keep(self, data: dict[str, object]) -> None:
        lines = cast("dict[str, object]", data["lines"])  # Checked by add().
        for key in ("text", "bytes"):
            value = lines.get(key)
            if isinstance(value, str) and len(value) > KEEP_CHARS + 1:
                data["lines"], data["submatches"] = {key: value[: KEEP_CHARS + 1]}, []
            if isinstance(value, str):
                self.kept += min(len(value), KEEP_CHARS + 1)
        if self.kept > self.budget:
            # A true memory limit, reported explicitly in the stats.
            self.over_limit += 1
            data["lines"], data["submatches"] = {"text": ""}, []


def _events(output: bytes, display: str, truncated: bool) -> list[Event]:
    """One file's rg JSON as remapped events; a capped tail line is dropped."""
    collector = _Collector(MAX_BYTES, 0)
    reader = collector.begin(display)
    reader.feed(output)
    if not truncated:
        reader.finish()
    return collector.pending


@native_errors()
def _pump(
    child: subprocess.Popen[bytes], source: Source, deadline: float, reader: _Reader
) -> None:
    """Concurrent bounded input/output: one CHUNK in, rg lines parsed as read."""
    if child.stdin is None or child.stdout is None or child.stderr is None:
        raise unavailable("rg_pipes_unavailable")
    pending = source()
    offset = 0
    with selectors.DefaultSelector() as selector:
        for stream in (child.stdin, child.stdout, child.stderr):
            os.set_blocking(stream.fileno(), False)
        if pending:
            selector.register(child.stdin, selectors.EVENT_WRITE)
        else:
            child.stdin.close()
        selector.register(child.stdout, selectors.EVENT_READ)
        selector.register(child.stderr, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BudgetExceeded("rg_timeout", capability("rg_timeout"))
            for key, _ in selector.select(min(remaining, 0.1)):
                pipe = key.fileobj
                if pipe is child.stdin:
                    try:
                        offset += os.write(key.fd, pending[offset:])
                    except BrokenPipeError:
                        # rg stopped reading; the rest of the file is moot.
                        pending, offset = b"", 0
                    else:
                        if offset == len(pending):
                            pending, offset = source(), 0
                    if not pending:
                        selector.unregister(pipe)
                        child.stdin.close()
                else:
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(pipe)
                    elif pipe is child.stdout:
                        reader.feed(chunk)
                    # stderr is drained but never exposed or accumulated.
    reader.finish()


@native_errors()
def _run_rg(argv: list[str], source: Source, deadline: float, reader: _Reader) -> None:
    try:
        child = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
    except OSError:
        raise unavailable("rg_unavailable") from None
    try:
        _pump(child, source, deadline, reader)
        try:
            returncode = child.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise BudgetExceeded("rg_timeout", capability("rg_timeout")) from None
        if returncode not in (0, 1):
            raise unavailable("rg_rejected")
    finally:
        # Popen owns the unreaped direct child; never signal a saved numeric PID.
        if child.poll() is None:
            child.kill()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            raise unavailable("rg_cleanup_failed") from None
        finally:
            for pipe in (child.stdin, child.stdout, child.stderr):
                if pipe is not None:
                    pipe.close()


def _duration(nanos: int) -> dict[str, int | str]:
    return {
        "secs": nanos // 10**9,
        "nanos": nanos % 10**9,
        "human": f"{nanos / 10**9:.6f}s",
    }


def _aggregate(
    events: Sequence[Mapping[str, object]], elapsed: int, counts: dict[str, int]
) -> list[Mapping[str, object]]:
    """Reduce child summaries once; match/context/end records retain rg shape."""
    totals = dict.fromkeys(
        (
            "searches",
            "searches_with_match",
            "bytes_searched",
            "bytes_printed",
            "matched_lines",
            "matches",
        ),
        0,
    )
    kept: list[Mapping[str, object]] = []
    search_nanos = 0
    for event in events:
        if event["type"] != "summary":
            kept.append(event)
            continue
        payload = event["data"]
        if not isinstance(payload, dict) or not isinstance(payload.get("stats"), dict):
            raise unavailable("rg_invalid_output")
        stats = payload["stats"]
        for key in totals:
            value = stats.get(key)
            if not isinstance(value, int) or value < 0:
                raise unavailable("rg_invalid_output")
            totals[key] += value
        duration = stats.get("elapsed", {})
        if isinstance(duration, dict):
            search_nanos += int(duration.get("secs", 0)) * 10**9 + int(
                duration.get("nanos", 0)
            )
    kept.append(
        {
            "type": "summary",
            "data": {
                "elapsed_total": _duration(elapsed),
                "stats": {**totals, "elapsed": _duration(search_nanos), **counts},
            },
        }
    )
    return kept


class DarwinSearchAccess:
    def __init__(self, files: FileAccess, *, rg_bin: str) -> None:
        self._files = files
        resolved = rg_bin if os.path.isabs(rg_bin) else shutil.which(rg_bin)
        if resolved is None:
            raise unavailable("rg_unavailable")
        # Composition captures PATH once; calls never resolve it again.
        self._rg_bin = os.path.abspath(resolved)

    def _paths(
        self, grant: RootGrant, request: SearchRequest
    ) -> tuple[list[str], bool]:
        parts = validate_relative_path(request.relative_path)
        if parts:
            try:
                with closing(self._files.open_read(grant, request.relative_path)):
                    paths = ["/".join(parts)]
                    if request.glob and not glob_matches(parts[-1], request.glob):
                        paths = []
                    return paths, False
            except UnsafePath as exc:
                if exc.code != "path_is_directory":
                    raise
        listing = self._files.list_entries(
            grant,
            ListRequest(
                request.relative_path,
                request.glob or "**/*",
                False,
                MAX_VISITED,
                MAX_VISITED,
                request.timeout_s,
            ),
        )
        paths = sorted(
            (entry.relative_path for entry in listing.entries if entry.kind == "file"),
            key=os.fsencode,
        )
        return paths[: request.max_files], listing.truncated or len(
            paths
        ) > request.max_files

    def search(self, grant: RootGrant, request: SearchRequest) -> SearchBatch:
        require_positive(request.max_bytes, MAX_BYTES)
        require_positive(request.max_files, MAX_VISITED)
        started = time.monotonic_ns()
        deadline = deadline_after(request.timeout_s)
        if not 0 <= request.context_lines <= 10000 or len(request.pattern) > 65536:
            raise BudgetExceeded(
                "invalid_search_budget", capability("invalid_search_budget")
            )
        if "\0" in request.pattern:
            raise unavailable("rg_invalid_pattern")
        argv = _command(self._rg_bin, request)
        paths, truncated = self._paths(grant, request)
        collector = _Collector(request.max_bytes, request.context_lines)
        files_searched = unreadable_files_skipped = 0
        binary_files_skipped = 0  # NUL files are searched as text
        skipped_changed = skipped_io_error = 0
        for path in paths:
            if time.monotonic() >= deadline:
                raise BudgetExceeded("rg_timeout", capability("rg_timeout"))
            reader = collector.begin(path)
            try:
                with closing(self._files.open_read(grant, path)) as opened:
                    # The whole file streams through this descriptor (CR2).
                    _run_rg(argv, _descriptor_source(opened), deadline, reader)
            except PermissionDenied:
                collector.rollback()
                if path == request.relative_path:
                    raise
                unreadable_files_skipped += 1
                continue
            except UnsafePath as exc:
                collector.rollback()
                if path == request.relative_path or exc.code not in {
                    "path_not_found",
                    "symlink_or_wrong_path_type",
                    "entry_changed",
                    "special_file_unsupported",
                    "path_is_directory",
                }:
                    raise
                skipped_changed += 1
                continue
            except _SourceReadFailed as exc:
                # A true I/O limit: rg saw a partial stream, so drop its output.
                collector.rollback()
                if path == request.relative_path:
                    code = str(exc)
                    raise AuthorityUnknown(code, capability(code)) from None
                skipped_io_error += 1
                continue
            collector.commit()
            files_searched += 1
        # Binary-only, unreadable-only and empty trees still validate rg/pattern.
        if files_searched == 0:
            _run_rg(argv, bytes, deadline, _Reader(lambda event: None))
        events = _aggregate(
            collector.events,
            time.monotonic_ns() - started,
            {
                "files_searched": files_searched,
                "skipped_changed": skipped_changed,
                "skipped_io_error": skipped_io_error,
                "skipped_text_over_memory_limit": collector.over_limit,
                "binary_files_skipped": binary_files_skipped,
                "unreadable_files_skipped": unreadable_files_skipped,
            },
        )
        return SearchBatch(
            events, truncated, files_searched, capability("darwin_search_limited")
        )
