"""Stage verified, non-destructive compressed snapshots of Darwin raw logs.

This is an explicit offline maintenance tool, NOT an automatic rotator.
It never changes, truncates, compresses-in-place or unlinks the source.
Published *.bz2.pending snapshots are intentionally excluded from stats.
Deletion/publication as canonical history requires separately proven writer
quiescence and is NOT implemented here.
"""

from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import os
import platform
import re
import stat
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from binnacle.companions.darwin_log_privacy import MIN_DISK_FREE_BYTES

_LOGS = frozenset(
    (
        "mcp.stderr.log",
        "mcp.stdout.log",
        "com.binnacle.jobs.err.log",
        "com.binnacle.jobs.out.log",
        "tunnel.stderr.log",
        "tunnel.stdout.log",
        "service-watchdog.stderr.log",
        "service-watchdog.stdout.log",
        "resource-monitor.stderr.log",
        "resource-monitor.stdout.log",
        "session-observability.stderr.log",
        "session-observability.stdout.log",
    )
)
_ARCHIVE_RE = re.compile(r"^([a-zA-Z0-9._-]+\.log)\.([0-9]{1,3})$")
BLOCK_BYTES = 1 << 20
DEFAULT_MAX_BYTES = 64 * 1024**3


class ArchiveStageRefused(RuntimeError):
    """Stage refused without deleting or overwriting source data."""


@dataclass(frozen=True)
class StagedArchive:
    source: str
    snapshot: str
    source_bytes: int
    snapshot_bytes: int
    sha256: str
    source_mtime_ns: int


def _name(value: str) -> str:
    match = _ARCHIVE_RE.fullmatch(value)
    if (
        match is None
        or match.group(1) not in _LOGS
        or (match.group(2).startswith("0") and match.group(2) != "0")
    ):
        raise ArchiveStageRefused("source name not in Binnacle raw log allowlist")
    return value


def _safe_directory(root: Path) -> int:
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            s = os.fstat(fd)
        except OSError:
            os.close(fd)
            raise
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
            os.close(fd)
            raise ArchiveStageRefused("unsafe private log directory")
        return fd
    except OSError as exc:
        raise ArchiveStageRefused("private log directory unavailable") from exc


def _validate_source(info: os.stat_result, *, max_bytes: int) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_mode & 0o077
        or not 0 < info.st_size <= max_bytes
    ):
        raise ArchiveStageRefused("source is not a private bounded regular log")


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_nlink,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _write_all(fd: int, content: bytes) -> None:
    """Never assume one os.write finishes an entire compressed block."""
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise ArchiveStageRefused("compressed snapshot write failed")
        view = view[written:]


def _hash_open_file(fd: int) -> tuple[str, int]:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while chunk := os.read(fd, BLOCK_BYTES):
        digest.update(chunk)
        total += len(chunk)
    return digest.hexdigest(), total


def _compressed_hash(fd: int) -> tuple[str, int]:
    """Verify decompressed bytes rather than trusting a completed .bz2 write."""
    os.lseek(fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(fd), "rb") as source, bz2.BZ2File(source) as reader:
        digest = hashlib.sha256()
        total = 0
        while chunk := reader.read(BLOCK_BYTES):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def discover(root: Path) -> tuple[str, ...]:
    """Read-only, allowlisted raw archives; no log paths or file data modified."""
    dfd = _safe_directory(root)
    try:
        result: list[str] = []
        for name in sorted(os.listdir(dfd)):
            if not _eligible(name):
                continue
            try:
                info = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            except OSError as exc:
                raise ArchiveStageRefused("archive metadata unreadable") from exc
            _validate_source(info, max_bytes=DEFAULT_MAX_BYTES)
            result.append(name)
        return tuple(result)
    finally:
        os.close(dfd)


def _eligible(value: str) -> bool:
    try:
        _name(value)
    except ArchiveStageRefused:
        return False
    return True


def stage_archive(
    root: Path,
    name: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    min_free_bytes: int = MIN_DISK_FREE_BYTES,
) -> StagedArchive:
    """Publish only an intact private .bz2.pending snapshot; retain raw input.

    Never claim to have reclaimed space: this is an additive snapshot that
    the live stats reader deliberately does not ingest. A concurrent writer
    causes refusal if observed, but cannot cause raw-data loss because the
    original inode is never modified or removed even after publication.
    """
    _name(name)
    if not 0 < max_bytes <= 100 * 1024**3 or min_free_bytes < 0:
        raise ArchiveStageRefused("invalid snapshot size or reserve budget")
    dfd = _safe_directory(root)
    srcfd = -1
    tmpfd = -1
    temp = "." + name + "." + uuid.uuid4().hex + ".bz2.tmp"
    target = name + ".bz2.pending"
    made_temp = False
    try:
        srcfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
        initial = os.fstat(srcfd)
        _validate_source(initial, max_bytes=max_bytes)
        disk = os.statvfs(root)
        if disk.f_bavail * disk.f_frsize < min_free_bytes + initial.st_size:
            raise ArchiveStageRefused("insufficient disk reserve for snapshot")
        tmpfd = os.open(
            temp,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=dfd,
        )
        made_temp = True
        compressor = bz2.BZ2Compressor(6)
        digest = hashlib.sha256()
        total = 0
        while chunk := os.read(srcfd, BLOCK_BYTES):
            total += len(chunk)
            if total > max_bytes:
                raise ArchiveStageRefused("log grew beyond snapshot limit")
            digest.update(chunk)
            encoded = compressor.compress(chunk)
            if encoded:
                _write_all(tmpfd, encoded)
        tail = compressor.flush()
        if tail:
            _write_all(tmpfd, tail)
        os.fsync(tmpfd)
        # Never publish if the source grew, changed inode or was rewritten.
        first_hash = digest.hexdigest()
        if total != initial.st_size or _identity(os.fstat(srcfd)) != _identity(initial):
            raise ArchiveStageRefused("source changed during snapshot")
        verified_hash, verified_bytes = _compressed_hash(tmpfd)
        again_hash, again_bytes = _hash_open_file(srcfd)
        if (
            verified_hash != first_hash
            or again_hash != first_hash
            or verified_bytes != total
            or again_bytes != total
            or _identity(os.fstat(srcfd)) != _identity(initial)
        ):
            raise ArchiveStageRefused("snapshot validation failed; source retained")
        by_name = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        if _identity(by_name) != _identity(initial):
            raise ArchiveStageRefused("source path changed before publish")
        # Atomic create-without-replace: never overwrite an earlier snapshot.
        os.link(temp, target, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
        os.fsync(dfd)
        snapshot_bytes = os.fstat(tmpfd).st_size
        return StagedArchive(
            source=name,
            snapshot=target,
            source_bytes=total,
            snapshot_bytes=snapshot_bytes,
            sha256=first_hash,
            source_mtime_ns=initial.st_mtime_ns,
        )
    except (OSError, EOFError, ValueError) as exc:
        raise ArchiveStageRefused(
            "snapshot failed safely; raw source retained"
        ) from exc
    finally:
        if tmpfd >= 0:
            os.close(tmpfd)
        if srcfd >= 0:
            os.close(srcfd)
        if made_temp:
            os.unlink(temp, dir_fd=dfd)
        os.close(dfd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path.home() / "Library/Logs/binnacle"
    )
    parser.add_argument("--stage", help="explicit raw archive basename; no deletion")
    args = parser.parse_args(argv)
    if platform.system() != "Darwin":
        parser.error("Darwin-only maintenance tool")
    try:
        output = (
            asdict(stage_archive(args.root, args.stage))
            if args.stage
            else {"candidates": discover(args.root)}
        )
    except ArchiveStageRefused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
