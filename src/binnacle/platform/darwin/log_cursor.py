"""Epoch identity, cursor validation and bounded reads for private service logs.

A cursor names one writer stream epoch of one service generation plus the
device/inode and byte offset of that epoch's file. Any mismatch expires the
cursor; callers restart from a fresh read, which reports a gap. Size alone can
not detect truncate-and-regrow, so writers never truncate: restart, rotation
and replacement always issue a new epoch. Durable cursor files are private
(0600 in an owner-only directory), bounded, strictly parsed and atomically
replaced; malformed, oversized, foreign or symlinked state is refused. The
epoch manifest is strictly parsed: unreadable or contradictory bookkeeping is
UNKNOWN coverage, never an empty log.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import math
import os
import re
import secrets
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    BudgetExceeded,
    Capability,
    CapabilityState,
    CursorExpired,
    UnsafePath,
)
from binnacle.platform.contracts.metric_log_contracts import LogCursor

CURSOR_SCHEMA = "binnacle-darwin-log-cursor-v1"
MAX_CURSOR_FILE_BYTES = 1024
CURSOR_SCOPE = "private_service_log_cursor"
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,64}")
MANIFEST_SCHEMA = "binnacle-darwin-log-manifest-v1"
MAX_MANIFEST_BYTES = 256 << 10
MAX_MANIFEST_ENTRIES = 256
MAX_READ_BYTES = 1 << 20
MAX_READ_LINES = 10_000
IDENTIFIER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")
CLEAN_ENDS = frozenset({"closed", "rotated"})
_EPOCH = re.compile(r"[0-9a-f]{32}")
_ENDS = frozenset({"open", "closed", "rotated", "crashed"})
_FIELDS = ("service_generation", "stream_epoch", "device", "inode", "offset")
_PRIVATE_BITS = stat.S_IRWXG | stat.S_IRWXO


def expired(reason: str) -> CursorExpired:
    capability = Capability(CapabilityState.UNKNOWN, reason, CURSOR_SCOPE)
    return CursorExpired("log_cursor_expired", capability)


def _unknown(reason: str) -> AuthorityUnknown:
    capability = Capability(CapabilityState.UNKNOWN, reason, "private_service_log")
    return AuthorityUnknown("log_coverage_unknown", capability)


def _unsafe(reason: str) -> UnsafePath:
    capability = Capability(CapabilityState.UNAVAILABLE, reason, CURSOR_SCOPE)
    return UnsafePath("log_cursor_unsafe", capability)


def _is_count(value: object) -> bool:
    return type(value) is int and value >= 0


def _check_shape(cursor: LogCursor) -> None:
    if not isinstance(cursor, LogCursor):
        raise expired("cursor_malformed")
    for token in (cursor.service_generation, cursor.stream_epoch):
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise expired("cursor_malformed")
    if not (_is_count(cursor.device) and _is_count(cursor.inode)):
        raise expired("cursor_malformed")
    if type(cursor.offset) is not int:
        raise expired("cursor_malformed")


def validate_cursor(
    cursor: LogCursor,
    *,
    generation: str,
    epoch: str,
    device: int,
    inode: int,
    size: int,
) -> None:
    """Raise CursorExpired unless the cursor addresses this exact open epoch."""

    _check_shape(cursor)
    if cursor.service_generation != generation:
        raise expired("generation_mismatch")
    if cursor.stream_epoch != epoch:
        raise expired("epoch_mismatch")
    if cursor.device != device or cursor.inode != inode:
        raise expired("inode_mismatch")
    if cursor.offset < 0:
        raise expired("offset_negative")
    if cursor.offset > size:
        # The epoch file shrank below a delivered offset: truncation, not EOF.
        raise expired("offset_beyond_end")


def check_private_directory(path: Path) -> os.stat_result:
    """Require an owner-only real directory; never follow a final symlink."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise _unsafe("private_directory_missing") from None
    except OSError:
        raise _unsafe("private_directory_unreadable") from None
    if not stat.S_ISDIR(info.st_mode):
        raise _unsafe("private_directory_not_directory")
    if info.st_uid != os.geteuid() or info.st_mode & _PRIVATE_BITS:
        raise _unsafe("private_directory_not_private")
    return info


def check_private_file(info: os.stat_result) -> None:
    """An opened log or cursor file must be an owner-only regular file."""

    if not stat.S_ISREG(info.st_mode):
        raise _unsafe("private_file_not_regular")
    if info.st_uid != os.geteuid() or info.st_mode & _PRIVATE_BITS:
        raise _unsafe("private_file_not_private")


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_private_atomic(path: Path, payload: bytes) -> None:
    """Write, fsync, atomically replace and directory-sync one private file."""

    check_private_directory(path.parent)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(temp, flags, 0o600)
    try:
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    fsync_directory(path.parent)


def read_private_bounded(path: Path, limit: int) -> bytes | None:
    """Read a private regular file without following symlinks; None if absent."""

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError:
        raise _unsafe("private_file_unopenable") from None
    try:
        info = os.fstat(fd)
        check_private_file(info)
        if info.st_size > limit:
            raise _unsafe("private_file_oversized")
        data = os.pread(fd, limit + 1, 0)
    finally:
        os.close(fd)
    if len(data) > limit:
        raise _unsafe("private_file_oversized")
    return data


def cursor_to_json(cursor: LogCursor) -> bytes:
    _check_shape(cursor)
    if cursor.offset < 0:
        raise expired("offset_negative")
    body = {
        "schema": CURSOR_SCHEMA,
        **{name: getattr(cursor, name) for name in _FIELDS},
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")


def cursor_from_json(data: bytes) -> LogCursor:
    """Strictly parse one serialized cursor; anything unexpected expires it."""

    if len(data) > MAX_CURSOR_FILE_BYTES:
        raise expired("cursor_oversized")
    try:
        body = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise expired("cursor_malformed") from None
    if not isinstance(body, dict) or set(body) != {"schema", *_FIELDS}:
        raise expired("cursor_malformed")
    if body["schema"] != CURSOR_SCHEMA:
        raise expired("cursor_schema_unknown")
    cursor = LogCursor(**{name: body[name] for name in _FIELDS})
    _check_shape(cursor)
    if cursor.offset < 0:
        raise expired("offset_negative")
    return cursor


def save_cursor(path: Path, cursor: LogCursor) -> None:
    """Durably persist a cursor in an owner-only directory (0600 file)."""

    write_private_atomic(path, cursor_to_json(cursor))


def load_cursor(path: Path) -> LogCursor | None:
    """Return the durable cursor, None if never saved, or raise if unusable."""

    check_private_directory(path.parent)
    data = read_private_bounded(path, MAX_CURSOR_FILE_BYTES)
    return None if data is None else cursor_from_json(data)


def epoch_header(epoch: str) -> bytes:
    return f"#binnacle-log-epoch {epoch}\n".encode("ascii")


HEADER_LEN = len(epoch_header("0" * 32))


@dataclass(frozen=True)
class EpochEntry:
    generation: str
    epoch: str
    device: int
    inode: int
    started_at: float
    last_at: float | None
    end: str
    final_size: int | None
    pruned: bool

    @property
    def file_name(self) -> str:
        return f"{self.epoch}.log"


@dataclass(frozen=True)
class Manifest:
    service: str
    entries: tuple[EpochEntry, ...]
    coverage_lost_before: float | None


def finite_number(value: object, *, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    return type(value) in (int, float) and math.isfinite(value)  # type: ignore[arg-type]


def _entry(raw: object) -> EpochEntry:
    fields = set(EpochEntry.__dataclass_fields__)
    if not isinstance(raw, dict) or set(raw) != fields:
        raise _unknown("manifest_malformed")
    entry = EpochEntry(**raw)
    valid = (
        isinstance(entry.generation, str)
        and IDENTIFIER.fullmatch(entry.generation) is not None
        and isinstance(entry.epoch, str)
        and _EPOCH.fullmatch(entry.epoch) is not None
        and all(type(v) is int and v >= 0 for v in (entry.device, entry.inode))
        and finite_number(entry.started_at)
        and finite_number(entry.last_at, nullable=True)
        and entry.end in _ENDS
        and (entry.final_size is None or type(entry.final_size) is int)
        and (entry.final_size or 0) >= 0
        and type(entry.pruned) is bool
    )
    if not valid:
        raise _unknown("manifest_malformed")
    return entry


def load_manifest(service_dir: Path, service: str) -> Manifest | None:
    data = read_private_bounded(service_dir / "manifest.json", MAX_MANIFEST_BYTES)
    if data is None:
        return None
    try:
        body = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _unknown("manifest_malformed") from None
    keys = {"schema", "service", "entries", "coverage_lost_before"}
    if not isinstance(body, dict) or set(body) != keys:
        raise _unknown("manifest_malformed")
    if body["schema"] != MANIFEST_SCHEMA or body["service"] != service:
        raise _unknown("manifest_foreign")
    if not isinstance(body["entries"], list) or not finite_number(
        body["coverage_lost_before"], nullable=True
    ):
        raise _unknown("manifest_malformed")
    entries = tuple(_entry(raw) for raw in body["entries"])
    if len({e.epoch for e in entries}) != len(entries):
        raise _unknown("manifest_malformed")
    return Manifest(service, entries, body["coverage_lost_before"])


def save_manifest(service_dir: Path, manifest: Manifest) -> None:
    body = {
        "schema": MANIFEST_SCHEMA,
        "service": manifest.service,
        "entries": [e.__dict__ for e in manifest.entries],
        "coverage_lost_before": manifest.coverage_lost_before,
    }
    write_private_atomic(service_dir / "manifest.json", json.dumps(body).encode())


def service_directory(root: Path, service: str) -> Path:
    if not isinstance(service, str) or not IDENTIFIER.fullmatch(service):
        raise _unsafe("service_name_invalid")
    check_private_directory(root)
    path = root / service
    check_private_directory(path)
    return path


@contextlib.contextmanager
def open_epoch(service_dir: Path, entry: EpochEntry) -> Iterator[tuple[int, int]]:
    """Open an epoch file without following links; yield (fd, size)."""

    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(service_dir / entry.file_name, flags)
    except OSError:
        raise expired("epoch_file_missing") from None
    try:
        info = os.fstat(fd)
        check_private_file(info)
        if (info.st_dev, info.st_ino) != (entry.device, entry.inode):
            raise expired("epoch_file_replaced")
        if os.pread(fd, HEADER_LEN, 0) != epoch_header(entry.epoch):
            raise expired("epoch_header_mismatch")
        if entry.final_size is not None and info.st_size != entry.final_size:
            raise expired("epoch_size_mismatch")
        yield fd, info.st_size
    finally:
        os.close(fd)


def lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def writer_active(service_dir: Path) -> bool:
    """True while some writer holds the service lock; never takes it exclusively."""

    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(service_dir / "writer.lock", flags)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            return True
        raise
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def bounded_read(
    fd: int, offset: int, size: int, max_bytes: int, max_lines: int, *, whole: bool
) -> tuple[bytes, bool]:
    """Read complete records within budget; ``whole`` also returns a tail."""

    available = size - offset
    data = os.pread(fd, min(available, max_bytes), offset) if available > 0 else b""
    budget_hit = available > max_bytes
    end = 0
    for _ in range(max_lines):
        nl = data.find(b"\n", end)
        if nl < 0:
            break
        end = nl + 1
    else:
        if end < len(data):
            return data[:end], True
    if end < len(data) and (budget_hit or not whole):
        if end:
            return data[:end], budget_hit
        # One record longer than the budget is split; an in-progress record of
        # the live epoch is withheld until its newline is written.
        return (data, True) if budget_hit else (b"", False)
    return data, budget_hit


def check_budget(max_bytes: int, max_lines: int, byte_cap: int, line_cap: int) -> None:
    """Positive integer budgets only; a request above the cap is refused."""

    for value in (max_bytes, max_lines):
        if type(value) is not int or value < 1:
            raise ValueError("log read budget must be a positive integer")
    if max_bytes > byte_cap or max_lines > line_cap:
        capability = Capability(
            CapabilityState.UNAVAILABLE,
            "log_read_budget_exceeded",
            f"private_service_log:max_bytes={byte_cap}:max_lines={line_cap}",
        )
        raise BudgetExceeded("log_read_budget_exceeded", capability)
