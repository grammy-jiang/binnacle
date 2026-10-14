"""Writer-coordinated raw-log finalization core (never run automatically).

This intentionally has NO production CLI or launchctl orchestration. The
caller must supply a trusted lifetime *hold* granted by the actual producer's
stop/reopen lifecycle, not a point-in-time lsof scan or untrusted token.
Until that service-wide authority exists, raw log deletion is unavailable.
"""

from __future__ import annotations

import bz2
import hashlib
import os
import stat
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from binnacle.companions import darwin_log_archive_stage as stage
from binnacle.companions.darwin_log_privacy import MIN_DISK_FREE_BYTES

_PRODUCERS = {
    "mcp.stderr.log": "system/com.binnacle.mcp",
    "mcp.stdout.log": "system/com.binnacle.mcp",
    "com.binnacle.jobs.err.log": "system/com.binnacle.jobs",
    "com.binnacle.jobs.out.log": "system/com.binnacle.jobs",
    "tunnel.stderr.log": "system/com.binnacle.tunnel",
    "tunnel.stdout.log": "system/com.binnacle.tunnel",
    "service-watchdog.stderr.log": "system/com.binnacle.service-watchdog",
    "service-watchdog.stdout.log": "system/com.binnacle.service-watchdog",
    "resource-monitor.stderr.log": "system/com.binnacle.resource-monitor",
    "resource-monitor.stdout.log": "system/com.binnacle.resource-monitor",
    # The session-observability producer is installed separately from this
    # repository; without an authoritative mapping it MUST remain ineligible.
}


class ArchiveFinalizeRefused(stage.ArchiveStageRefused):
    """Fail closed; a raw source is never deleted on an observed uncertainty."""


class WriterHold(Protocol):
    """A writer-side hold, effective for the entire context lifetime.

    __enter__ must atomically prevent the named service/writer from reopening
    old FDs; verify must check its exact running generation and descriptor
    ownership. Acquisition without producer coordination is not evidence.
    """

    producer: str

    def __enter__(self) -> object: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def verify(self, source: str, info: os.stat_result) -> None: ...


@dataclass(frozen=True)
class FinalizedArchive:
    source: str
    canonical: str
    producer: str
    source_bytes: int
    sha256: str
    resumed_publication: bool


@dataclass(frozen=True)
class FinalizeMilestones:
    """Trusted caller's durable phase receipts, while writer hold is active.

    The first callback is invoked after canonical identity/data verification
    but before raw unlink. The second is invoked ONLY after raw unlink and
    directory fsync. No callback can replace/skip the producer hold or grant
    production authority. Failure before prune leaves raw intact; failure
    after pruning means raw may already be gone and recovery is mandatory.
    """

    canonical_verified: Callable[[FinalizedArchive], None]
    raw_pruned: Callable[[FinalizedArchive], None]


def _verify_hold(hold: WriterHold, name: str, initial: os.stat_result) -> None:
    base = name.rsplit(".", 1)[0]
    expected = _PRODUCERS.get(base)
    if expected is None or hold.producer != expected:
        raise ArchiveFinalizeRefused("unknown or mismatched producer identity")
    try:
        hold.verify(name, initial)
    except Exception as exc:
        raise ArchiveFinalizeRefused("writer quiescence not provable") from exc


def _stable_raw(dfd: int, srcfd: int, name: str, info: os.stat_result) -> None:
    try:
        by_name = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        if (by_name.st_dev, by_name.st_ino) != (info.st_dev, info.st_ino):
            raise ArchiveFinalizeRefused("raw log pathname changed; source retained")
        if stage._identity(by_name) != stage._identity(info):
            raise ArchiveFinalizeRefused("raw log changed; source retained")
        if stage._identity(os.fstat(srcfd)) != stage._identity(info):
            raise ArchiveFinalizeRefused("raw log changed; source retained")
    except OSError as exc:
        raise ArchiveFinalizeRefused(
            "raw log identity unknown; source retained"
        ) from exc


def _check_compressed(fd: int, digest: str, size: int) -> None:
    """Independent bounded decompression catches stale/corrupt archives."""
    os.lseek(fd, 0, os.SEEK_SET)
    h = hashlib.sha256()
    count = 0
    try:
        with os.fdopen(os.dup(fd), "rb") as source, bz2.BZ2File(source) as reader:
            while True:
                chunk = reader.read(min(stage.BLOCK_BYTES, size - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                if count > size:
                    raise ArchiveFinalizeRefused("compressed archive length mismatch")
                h.update(chunk)
    except (OSError, EOFError, ValueError) as exc:
        raise ArchiveFinalizeRefused("compressed archive is unreadable") from exc
    if h.hexdigest() != digest or count != size:
        raise ArchiveFinalizeRefused("compressed archive checksum mismatch")


def _validate_published(fd: int) -> None:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ArchiveFinalizeRefused("canonical archive is not private and single-link")


def _stable_canonical(
    dfd: int,
    name: str,
    expected: os.stat_result,
    *,
    links: int,
) -> None:
    """Fail closed if a verified compressed pathname was switched.

    A resumed archive must have one link. A freshly published archive has
    two links until its unique private temp sibling is removed in finally.
    The opened inode's full identity, mode and link count must still match
    the name immediately before pruning the original raw source.
    """
    try:
        current = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        if (
            stage._identity(current) != stage._identity(expected)
            or not stat.S_ISREG(current.st_mode)
            or current.st_uid != os.getuid()
            or current.st_nlink != links
            or stat.S_IMODE(current.st_mode) != 0o600
        ):
            raise ArchiveFinalizeRefused("canonical archive pathname changed")
    except OSError as exc:
        raise ArchiveFinalizeRefused("canonical archive identity unavailable") from exc


def _unlink_owned_temp(dfd: int, temp: str, fd: int) -> None:
    """Prune only the opened temporary inode, never a foreign pathname.

    An O_EXCL collision produces no owned FD and must not trigger cleanup.
    If another actor swapped the pathname after creation, retain it.
    """
    try:
        named = os.stat(temp, dir_fd=dfd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stage._identity(named) != stage._identity(os.fstat(fd)):
        raise ArchiveFinalizeRefused("temporary archive pathname changed")
    os.unlink(temp, dir_fd=dfd)


def _make_temp(
    dfd: int, srcfd: int, temp: str, initial: os.stat_result
) -> tuple[int, str, int]:
    fd = os.open(
        temp,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=dfd,
    )
    try:
        compressor = bz2.BZ2Compressor(6)
        h = hashlib.sha256()
        size = 0
        while chunk := os.read(srcfd, stage.BLOCK_BYTES):
            size += len(chunk)
            if size > initial.st_size:
                raise ArchiveFinalizeRefused("raw log grew while compressing")
            h.update(chunk)
            packed = compressor.compress(chunk)
            if packed:
                stage._write_all(fd, packed)
        tail = compressor.flush()
        if tail:
            stage._write_all(fd, tail)
        os.fsync(fd)
        return fd, h.hexdigest(), size
    except BaseException:
        # O_EXCL already succeeded, so this is the temp that this attempt
        # created. Its inode must still match before cleanup.
        try:
            _unlink_owned_temp(dfd, temp, fd)
        finally:
            os.close(fd)
        raise


def finalize_archive(
    root: Path,
    name: str,
    *,
    hold: WriterHold,
    max_bytes: int = stage.DEFAULT_MAX_BYTES,
    min_free_bytes: int = MIN_DISK_FREE_BYTES,
    milestones: FinalizeMilestones | None = None,
) -> FinalizedArchive:
    """Finalize a raw archive only under an authoritative held producer stop.

    Crash recovery: if a previously published canonical .bz2 exactly matches
    the stable raw inode and the writer is still held, finish pruning the raw.
    A mismatching canonical archive is never overwritten or silently removed.

    Failure after publication may leave *both* raw and compressed; the stats
    reader always prefers the raw generation until unlink succeeds.
    """
    stage._name(name)
    if hold is None or min_free_bytes < 0 or not 0 < max_bytes <= 100 * 1024**3:
        raise ArchiveFinalizeRefused("missing writer hold or invalid limits")
    try:
        dfd = stage._safe_directory(root)
    except stage.ArchiveStageRefused as exc:
        raise ArchiveFinalizeRefused(str(exc)) from exc
    srcfd = -1
    tempfd = -1
    temp = "." + name + "." + uuid.uuid4().hex + ".bz2.tmp"
    canonical = name + ".bz2"
    resumed = False
    canonical_reference: os.stat_result | None = None
    try:
        srcfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
        initial = os.fstat(srcfd)
        stage._validate_source(initial, max_bytes=max_bytes)
        with hold:
            _verify_hold(hold, name, initial)
            _stable_raw(dfd, srcfd, name, initial)
            disk = os.fstatvfs(dfd)
            if disk.f_bavail * disk.f_frsize < min_free_bytes + initial.st_size:
                raise ArchiveFinalizeRefused("insufficient disk reserve")
            # Always hash the actual opened raw inode under the hold, never a
            # staged *.bz2.pending copy (which may be stale).
            digest, total = stage._hash_open_file(srcfd)
            if total != initial.st_size:
                raise ArchiveFinalizeRefused("raw source size changed")
            _stable_raw(dfd, srcfd, name, initial)
            _verify_hold(hold, name, initial)
            try:
                canonical_fd = os.open(
                    canonical, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd
                )
            except FileNotFoundError:
                canonical_fd = -1
            if canonical_fd >= 0:
                resumed = True
                try:
                    _validate_published(canonical_fd)
                    _check_compressed(canonical_fd, digest, total)
                    canonical_reference = os.fstat(canonical_fd)
                finally:
                    os.close(canonical_fd)
            else:
                os.lseek(srcfd, 0, os.SEEK_SET)
                tempfd, compressed_digest, compressed_bytes = _make_temp(
                    dfd, srcfd, temp, initial
                )
                if compressed_digest != digest or compressed_bytes != total:
                    raise ArchiveFinalizeRefused("source changed during compression")
                _check_compressed(tempfd, digest, total)
                _stable_raw(dfd, srcfd, name, initial)
                again, again_len = stage._hash_open_file(srcfd)
                if again != digest or again_len != total:
                    raise ArchiveFinalizeRefused("source bytes changed; raw retained")
                _verify_hold(hold, name, initial)
                _stable_raw(dfd, srcfd, name, initial)
                # Hardlink publication is atomic create-only. The temp is
                # unlinked in finally, leaving one canonical private inode.
                os.link(
                    temp,
                    canonical,
                    src_dir_fd=dfd,
                    dst_dir_fd=dfd,
                    follow_symlinks=False,
                )
                os.fsync(dfd)
                canonical_reference = os.fstat(tempfd)
            # A cooperative writer must be unable to resume until after the
            # source has been removed. Re-verify just before pruning.
            _verify_hold(hold, name, initial)
            _stable_raw(dfd, srcfd, name, initial)
            if canonical_reference is None:
                raise ArchiveFinalizeRefused("canonical verification incomplete")
            _stable_canonical(
                dfd, canonical, canonical_reference, links=1 if resumed else 2
            )
            result = FinalizedArchive(
                name, canonical, hold.producer, total, digest, resumed
            )
            if milestones is not None:
                # A prepared durable record MUST precede the irreversible
                # raw-unlink boundary; the callback cannot be an observer
                # which is called only after deletion.
                milestones.canonical_verified(result)
                _verify_hold(hold, name, initial)
                _stable_raw(dfd, srcfd, name, initial)
                _stable_canonical(
                    dfd, canonical, canonical_reference, links=1 if resumed else 2
                )
            os.unlink(name, dir_fd=dfd)
            os.fsync(dfd)
            if milestones is not None:
                milestones.raw_pruned(result)
            return result
    except stage.ArchiveStageRefused as exc:
        if isinstance(exc, ArchiveFinalizeRefused):
            raise
        raise ArchiveFinalizeRefused(str(exc)) from exc
    except (OSError, EOFError, ValueError) as exc:
        raise ArchiveFinalizeRefused(
            "finalization refused; raw retained unless canonical already published"
        ) from exc
    finally:
        try:
            if tempfd >= 0:
                try:
                    _unlink_owned_temp(dfd, temp, tempfd)
                finally:
                    os.close(tempfd)
        finally:
            if srcfd >= 0:
                os.close(srcfd)
            os.close(dfd)
