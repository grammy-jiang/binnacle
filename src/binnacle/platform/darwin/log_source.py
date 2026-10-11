"""Private, epoch-addressed Darwin service logs with bounded reads.

One writer per service directory (an advisory ``flock``) owns a manifest of
stream epochs. Each start, rotation or crash recovery issues a new random
epoch with its own 0600 file whose header names the epoch; files are never
truncated or reused. Records are redacted and sanitized *before* they reach
disk. Readers address bytes by generation, epoch, device/inode and offset,
bound every read by bytes and lines, and report crash or pruning
discontinuities as a gap; ``read_window`` raises ``ServiceLogError`` instead
of returning text whose completeness it cannot establish. Missing records never
prove that an event did not happen. Same-UID privacy only: a malicious process
of the same account can still read or replace these files.
"""

from __future__ import annotations

import contextlib
import fcntl
import math
import os
import re
import secrets
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from pathlib import Path

from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    Capability,
    CapabilityState,
    NativeCapabilityError,
)
from binnacle.platform.contracts.metric_log_contracts import LogBatch, LogCursor
from binnacle.platform.contracts.service_log_contracts import ServiceLogError
from binnacle.platform.darwin.log_cursor import (
    CLEAN_ENDS,
    HEADER_LEN,
    IDENTIFIER,
    MAX_MANIFEST_ENTRIES,
    MAX_READ_BYTES,
    MAX_READ_LINES,
    EpochEntry,
    Manifest,
    bounded_read,
    check_budget,
    check_private_directory,
    check_private_file,
    epoch_header,
    expired,
    finite_number,
    load_manifest,
    lstat_or_none,
    open_epoch,
    save_manifest,
    service_directory,
    validate_cursor,
    writer_active,
)

# Same marker as observability.log_safety; platform must not import observability.
REDACTED = "[redacted]"
WINDOW_MAX_BYTES = 8 << 20
WINDOW_MAX_LINES = 100_000
MAX_RECORD_BYTES = 16 << 10
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.DOTALL), REDACTED),
    (re.compile(r"(?i)\b(authorization|proxy-authorization)(\s*[:=]\s*)\S+(\s+[A-Za-z0-9._~+/=-]+)?"), rf"\1\2{REDACTED}"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), f"Bearer {REDACTED}"),
    (re.compile(r"(?i)\b([A-Za-z0-9_]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)s?)(\"?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"), rf"\1\2{REDACTED}"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), rf"\1{REDACTED}@"),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
)  # fmt: skip


def redact_log_text(text: str, values: Iterable[str] = ()) -> str:
    """Remove known credentials and registered literal secrets from one record."""

    for value in sorted({v for v in values if v}, key=len, reverse=True):
        text = text.replace(value, REDACTED)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _sanitize(text: str) -> str:
    """One physical line per record; no terminal control sequences on disk."""

    text = text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return _CONTROL.sub(lambda m: f"\\x{ord(m.group()):02x}", text)


def _service_error(reason: str) -> ServiceLogError:
    return ServiceLogError(f"private service log unavailable: {reason}")


class PrivateServiceLogWriter:
    """Sole redacting writer for one service; issues a new epoch per start.

    One owning thread; ``close`` seals the epoch and releases every descriptor.
    """

    def __init__(
        self,
        *,
        root: Path,
        generation: str,
        service: str,
        max_epoch_bytes: int = 4 << 20,
        retain_epochs: int = 8,
        redact_values: Iterable[str] = (),
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not IDENTIFIER.fullmatch(generation) or not IDENTIFIER.fullmatch(service):
            raise _service_error("identifier_invalid")
        if max_epoch_bytes <= HEADER_LEN + MAX_RECORD_BYTES or retain_epochs < 1:
            raise ValueError("log writer budget too small")
        self._root, self._generation, self._service = root, generation, service
        self._max_epoch_bytes, self._retain = max_epoch_bytes, retain_epochs
        self._secrets = tuple(redact_values)
        self._clock = clock
        self._dir = root / service
        self._lock_fd: int | None = None
        self._fd: int | None = None
        self._manifest = Manifest(service, (), None)
        self._size = 0
        self._last_at: float | None = None

    @property
    def epoch(self) -> str | None:
        if self._fd is None:
            return None
        return self._manifest.entries[-1].epoch

    def _mkdir_private(self, path: Path) -> None:
        with contextlib.suppress(FileExistsError):
            os.mkdir(path, 0o700)
        check_private_directory(path)

    def _lock(self) -> None:
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(self._dir / "writer.lock", flags, 0o600)
        try:
            check_private_file(os.fstat(fd))
            for _ in range(50):  # a reader's probe holds LOCK_SH only briefly
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.01)
            else:
                raise _service_error("writer_already_active")
        except BaseException:
            os.close(fd)
            raise
        self._lock_fd = fd

    def start(self) -> None:
        if self._lock_fd is not None:
            raise _service_error("writer_already_started")
        self._mkdir_private(self._root)
        self._mkdir_private(self._dir)
        self._lock()
        try:
            loaded = load_manifest(self._dir, self._service)
            self._manifest = loaded or Manifest(self._service, (), None)
            self._mark_crashed()
            self._open_new_epoch()
        except BaseException:
            self._release()
            raise

    def _mark_crashed(self) -> None:
        """Earlier writers that never closed cleanly end in a crash gap."""

        entries = []
        for entry in self._manifest.entries:
            if entry.end == "open":
                info = lstat_or_none(self._dir / entry.file_name)
                if info is not None and (info.st_dev, info.st_ino) == (
                    entry.device,
                    entry.inode,
                ):
                    entry = replace(
                        entry,
                        end="crashed",
                        final_size=info.st_size,
                        last_at=info.st_mtime,
                    )
                else:  # missing or replaced: its records are lost coverage
                    entry = replace(entry, end="crashed", pruned=True)
            entries.append(entry)
        self._manifest = replace(self._manifest, entries=tuple(entries))

    def _open_new_epoch(self) -> None:
        epoch = secrets.token_hex(16)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_NOFOLLOW
        fd = os.open(self._dir / f"{epoch}.log", flags | os.O_CLOEXEC, 0o600)
        try:
            os.write(fd, epoch_header(epoch))
            os.fsync(fd)
            info = os.fstat(fd)
        except BaseException:
            os.close(fd)
            raise
        self._fd, self._size, self._last_at = fd, HEADER_LEN, None
        entry = EpochEntry(
            self._generation, epoch, info.st_dev, info.st_ino, self._clock(),
            None, "open", None, False,
        )  # fmt: skip
        self._manifest = replace(
            self._manifest, entries=(*self._manifest.entries, entry)
        )
        self._prune()
        save_manifest(self._dir, self._manifest)

    def _prune(self) -> None:
        entries = list(self._manifest.entries)
        live = [i for i, e in enumerate(entries) if not e.pruned]
        for i in live[: max(0, len(live) - self._retain)]:
            entry = entries[i]
            path = self._dir / entry.file_name
            with contextlib.suppress(FileNotFoundError):
                info = os.lstat(path)
                if (info.st_dev, info.st_ino) == (entry.device, entry.inode):
                    path.unlink()  # never unlink a foreign replacement
            entries[i] = replace(entry, pruned=True)
        lost = self._manifest.coverage_lost_before
        while len(entries) > MAX_MANIFEST_ENTRIES and entries[0].pruned:
            dropped = entries.pop(0)
            mark = (
                dropped.last_at if dropped.last_at is not None else dropped.started_at
            )
            lost = mark if lost is None else max(lost, mark)
        self._manifest = Manifest(self._service, tuple(entries), lost)

    def _active_fd(self) -> int:
        if self._fd is None:
            raise _service_error("writer_not_active")
        return self._fd

    def _finish_epoch(self, end: str) -> None:
        fd = self._active_fd()
        os.fsync(fd)
        os.close(fd)
        self._fd = None
        current = replace(
            self._manifest.entries[-1],
            end=end,
            final_size=self._size,
            last_at=self._last_at,
        )
        self._manifest = replace(
            self._manifest, entries=(*self._manifest.entries[:-1], current)
        )

    def rotate(self) -> None:
        self._finish_epoch("rotated")
        self._open_new_epoch()

    def write(self, message: str) -> None:
        """Redact, sanitize and append one bounded record."""

        self._active_fd()
        text = _sanitize(redact_log_text(str(message), self._secrets))
        now = self._clock()
        record = f"{now:.6f} {text}".encode()
        if len(record) >= MAX_RECORD_BYTES:
            record = record[: MAX_RECORD_BYTES - 16].decode(errors="ignore").encode()
            record += b" [truncated]"
        record += b"\n"
        if self._size + len(record) > self._max_epoch_bytes:
            self.rotate()
        fd = self._active_fd()
        view = memoryview(record)
        while view:
            view = view[os.write(fd, view) :]
        self._size += len(record)
        self._last_at = now

    def sync(self) -> None:
        if self._fd is not None:
            os.fsync(self._fd)

    def _release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self._lock_fd is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None

    def close(self) -> None:
        """Seal the epoch durably, then release every descriptor and the lock."""

        try:
            if self._fd is not None:
                self._finish_epoch("closed")
                save_manifest(self._dir, self._manifest)
        finally:
            self._release()


class PrivateServiceLogSource:
    """Generation-bound reader for ``PrivateServiceLogWriter`` streams."""

    def __init__(self, *, root: Path, generation: str) -> None:
        if not isinstance(generation, str) or not IDENTIFIER.fullmatch(generation):
            raise _service_error("identifier_invalid")
        self._root = root
        self._generation = generation

    def _own(self, service: str) -> tuple[Path, Manifest, list[EpochEntry]]:
        service_dir = service_directory(self._root, service)
        manifest = load_manifest(service_dir, service)
        own = [] if manifest is None else [
            e for e in manifest.entries if e.generation == self._generation
        ]  # fmt: skip
        if manifest is None or not own:
            capability = Capability(
                CapabilityState.UNKNOWN, "log_coverage_unknown", self._scope(service)
            )
            raise AuthorityUnknown("log_coverage_unknown", capability)
        return service_dir, manifest, own

    def _scope(self, service: str) -> str:
        return f"private_service_log:{service}:generation_bound"

    def read_cursor(
        self, service: str, cursor: LogCursor | None, *, max_bytes: int, max_lines: int
    ) -> LogBatch:
        """Return the next bounded bytes of one epoch, marking any discontinuity."""

        check_budget(max_bytes, max_lines, MAX_READ_BYTES, MAX_READ_LINES)
        if cursor is not None and cursor.service_generation != self._generation:
            raise expired("generation_mismatch")
        service_dir, manifest, own = self._own(service)
        active = writer_active(service_dir)
        if cursor is None:
            index, offset = 0, HEADER_LEN
            gap = manifest.coverage_lost_before is not None
        else:
            index = next(
                (i for i, e in enumerate(own) if e.epoch == cursor.stream_epoch), -1
            )
            if index < 0 or own[index].pruned:
                raise expired("epoch_unknown" if index < 0 else "epoch_pruned")
            offset, gap = cursor.offset, False
        while True:
            entry = own[index]
            last = index + 1 == len(own)
            if entry.pruned:
                if last:
                    raise expired("epoch_pruned")
                gap, index, offset = True, index + 1, HEADER_LEN
                continue
            with open_epoch(service_dir, entry) as (fd, size):
                if cursor is not None and entry.epoch == cursor.stream_epoch:
                    validate_cursor(
                        cursor,
                        generation=self._generation,
                        epoch=entry.epoch,
                        device=entry.device,
                        inode=entry.inode,
                        size=size,
                    )
                if offset < HEADER_LEN:
                    raise expired("offset_inside_header")
                finished = entry.end != "open" or not active
                if offset == size and finished and not last:
                    gap = gap or entry.end not in CLEAN_ENDS
                    index, offset = index + 1, HEADER_LEN
                    continue
                data, truncated = bounded_read(
                    fd, offset, size, max_bytes, max_lines, whole=finished
                )
            state, reason = (
                (CapabilityState.UNKNOWN, "log_gap_coverage_unknown")
                if gap
                else (CapabilityState.LIMITED, "bounded_private_log_read")
            )
            next_cursor = LogCursor(
                self._generation, entry.epoch, entry.device, entry.inode,
                offset + len(data),
            )  # fmt: skip
            capability = Capability(state, reason, self._scope(service))
            return LogBatch(data, next_cursor, capability, gap, truncated)

    def read_window(
        self,
        services: Sequence[str],
        since_epoch: float,
        until_epoch: float | None = None,
    ) -> str:
        """Bounded semantic epoch window; raise unless coverage is established."""

        if isinstance(services, str) or not services:
            raise _service_error("services_required")
        if not finite_number(since_epoch) or not finite_number(
            until_epoch, nullable=True
        ):
            raise _service_error("window_invalid")
        low = int(since_epoch)
        high = math.inf if until_epoch is None else int(until_epoch) + 1
        budget = [WINDOW_MAX_BYTES, WINDOW_MAX_LINES]
        records: list[tuple[float, bytes]] = []
        try:
            for service in services:
                records += self._window(service, since_epoch, low, high, budget)
        except NativeCapabilityError as exc:
            raise _service_error(exc.capability.reason_code) from None
        except OSError:
            raise _service_error("io_error") from None
        records.sort(key=lambda item: item[0])
        return "".join(text.decode("utf-8", "replace") + "\n" for _, text in records)

    def _window(
        self, service: str, since: float, low: int, high: float, budget: list[int]
    ) -> list[tuple[float, bytes]]:
        service_dir, manifest, own = self._own(service)
        lost = manifest.coverage_lost_before
        if since < own[0].started_at or (lost is not None and since <= lost):
            raise _service_error("window_precedes_coverage")
        active = writer_active(service_dir)
        found: list[tuple[float, bytes]] = []
        for index, entry in enumerate(own):
            following = own[index + 1].started_at if index + 1 < len(own) else math.inf
            crashed = entry.end == "crashed" or (entry.end == "open" and not active)
            # Records stop at a crash; the outage until the next epoch is uncovered.
            if crashed and _crashed_at(service_dir, entry) < high and following >= low:
                raise _service_error("window_overlaps_crash_gap")
            if entry.end == "open":
                span_end = following
            else:
                span_end = entry.last_at if entry.last_at is not None else 0.0
            if not (entry.started_at < high and max(span_end, entry.started_at) >= low):
                continue
            if entry.pruned:
                raise _service_error("window_overlaps_pruned_epoch")
            with open_epoch(service_dir, entry) as (fd, size):
                if size - HEADER_LEN > budget[0]:
                    raise _service_error("window_exceeds_read_budget")
                budget[0] -= size - HEADER_LEN
                data = os.pread(fd, size - HEADER_LEN, HEADER_LEN)
            found += _window_records(data, low, high, budget, whole=entry.end != "open")
        return found


def _crashed_at(service_dir: Path, entry: EpochEntry) -> float:
    """Last write of a crashed epoch; its start when that is unobservable."""

    if entry.end == "crashed" and entry.last_at is not None:
        return entry.last_at
    info = lstat_or_none(service_dir / entry.file_name)
    return entry.started_at if info is None else info.st_mtime


def _window_records(
    data: bytes, low: int, high: float, budget: list[int], *, whole: bool
) -> list[tuple[float, bytes]]:
    lines = data.split(b"\n")
    tail = lines.pop()
    if tail and whole:
        lines.append(tail)
    budget[1] -= len(lines)
    if budget[1] < 0:
        raise _service_error("window_exceeds_read_budget")
    found = []
    for line in lines:
        stamp, sep, text = line.partition(b" ")
        try:
            at = float(stamp)
        except ValueError:
            raise _service_error("record_malformed") from None
        if not sep or not math.isfinite(at):
            raise _service_error("record_malformed")
        if low <= at < high:
            found.append((at, text))
    return found
