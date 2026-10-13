"""Synthetic writer-hold and inode fixtures only: no production launchd touch."""

from __future__ import annotations

import bz2
import hashlib
import os
import stat
from pathlib import Path

import pytest

from binnacle.companions import darwin_log_archive_finalize as finish
from binnacle.platform.darwin.daemon_logstats import DarwinDaemonLogStatsSource

NAME = "mcp.stderr.log.0"
EVENTS = (
    b"2026-10-13T09:10:00 INFO event=tool_call call=archived\n"
    b"2026-10-13T09:11:00 INFO event=tool_result call=archived\n"
)


class FixtureWriterHold:
    """Cooperative test writer: exclusive hold prevents future appends."""

    producer = "system/com.binnacle.mcp"

    def __init__(self):
        self.running = False
        self.held = False
        self.calls = 0

    def __enter__(self):
        if self.running or self.held:
            raise finish.ArchiveFinalizeRefused("writer still running")
        self.held = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.held = False

    def verify(self, source, info):
        self.calls += 1
        if source != NAME or not self.held or self.running:
            raise finish.ArchiveFinalizeRefused("writer not quiescent")

    def append(self, path: Path, data: bytes):
        if self.held:
            raise RuntimeError("writer may not reopen under held maintenance")
        with path.open("ab") as stream:
            stream.write(data)


def fixture(tmp_path):
    root = tmp_path / "private-logs"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    raw = root / NAME
    raw.write_bytes(EVENTS)
    raw.chmod(0o600)
    (root / "mcp.stderr.log").write_text(
        "2026-10-13T09:12:00 INFO event=tool_call call=active\n"
    )
    return root, raw, FixtureWriterHold()


def finalize(root, hold):
    return finish.finalize_archive(root, NAME, hold=hold, min_free_bytes=0)


def _stat_count(root):
    return DarwinDaemonLogStatsSource(root=root).read_spec(
        "binnacle-mcp", "2026-10-13 09:00", "2026-10-13 09:20"
    )


def test_unheld_or_running_writer_cannot_trigger_cleanup(tmp_path):
    root, raw, hold = fixture(tmp_path)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="hold"):
        finish.finalize_archive(root, NAME, hold=None, min_free_bytes=0)
    hold.running = True
    with pytest.raises(finish.ArchiveFinalizeRefused, match="running"):
        finalize(root, hold)
    assert raw.read_bytes() == EVENTS
    assert not (root / (NAME + ".bz2")).exists()
    assert not hold.held


def test_quiescent_archive_integrity_private_mode_and_reader_exactly_once(tmp_path):
    root, raw, hold = fixture(tmp_path)
    original = raw.stat()
    receipt = finalize(root, hold)
    canonical = root / receipt.canonical
    assert receipt.producer == hold.producer
    assert receipt.source_bytes == len(EVENTS)
    assert receipt.sha256 == hashlib.sha256(EVENTS).hexdigest()
    assert not receipt.resumed_publication
    assert bz2.decompress(canonical.read_bytes()) == EVENTS
    assert not raw.exists()
    assert stat.S_IMODE(canonical.stat().st_mode) == 0o600
    assert canonical.stat().st_uid == original.st_uid
    assert canonical.stat().st_nlink == 1
    assert hold.calls >= 3 and not hold.held
    assert _stat_count(root).count("call=archived") == 2
    assert _stat_count(root).count("call=active") == 1
    assert not list(root.glob(".*.tmp"))


def test_observed_uncooperative_append_during_compression_refuses(
    tmp_path, monkeypatch
):
    root, raw, hold = fixture(tmp_path)
    original = finish._make_temp

    def append_behind_hold(*args, **kwargs):
        result = original(*args, **kwargs)
        with raw.open("ab") as stream:  # deliberately bypass fixture lock
            stream.write(b"arrived after source copied")
        return result

    monkeypatch.setattr(finish, "_make_temp", append_behind_hold)
    with pytest.raises(
        finish.ArchiveFinalizeRefused, match="source changed|raw log changed"
    ):
        finalize(root, hold)
    assert raw.read_bytes().endswith(b"arrived after source copied")
    assert not (root / (NAME + ".bz2")).exists()
    assert not list(root.glob(".*.tmp"))
    assert not hold.held


def test_source_path_inode_swap_refuses_even_with_matching_bytes(tmp_path, monkeypatch):
    root, raw, hold = fixture(tmp_path)
    original = finish._check_compressed
    moved = root / "older-inode"

    def moved_path(*args, **kwargs):
        result = original(*args, **kwargs)
        raw.rename(moved)
        raw.write_bytes(EVENTS)
        raw.chmod(0o600)
        return result

    monkeypatch.setattr(finish, "_check_compressed", moved_path)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="pathname changed"):
        finalize(root, hold)
    assert raw.read_bytes() == EVENTS
    assert moved.read_bytes() == EVENTS
    assert not (root / (NAME + ".bz2")).exists()


def test_existing_conflicting_canonical_archive_never_overwritten(tmp_path):
    root, raw, hold = fixture(tmp_path)
    published = root / (NAME + ".bz2")
    prior = bz2.compress(b"older generation")
    published.write_bytes(prior)
    published.chmod(0o600)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="checksum mismatch"):
        finalize(root, hold)
    assert published.read_bytes() == prior
    assert raw.read_bytes() == EVENTS
    assert _stat_count(root).count("call=archived") == 2


def test_interruption_after_publication_preserves_raw_and_resumes(
    tmp_path, monkeypatch
):
    root, raw, hold = fixture(tmp_path)
    actual = finish.os.unlink

    def failed_unlink(path, *args, **kwargs):
        if path == NAME:
            raise PermissionError("simulated transient refusal")
        return actual(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(finish.os, "unlink", failed_unlink)
        with pytest.raises(finish.ArchiveFinalizeRefused, match="refused"):
            finalize(root, hold)
    canonical = root / (NAME + ".bz2")
    assert raw.exists() and canonical.exists()
    assert canonical.stat().st_nlink == 1
    assert _stat_count(root).count("call=archived") == 2
    recovered = finalize(root, hold)
    assert recovered.resumed_publication
    assert not raw.exists()
    assert bz2.decompress(canonical.read_bytes()) == EVENTS
    assert _stat_count(root).count("call=archived") == 2


@pytest.mark.parametrize(
    "violation", ["symlink", "hardlink", "public_mode", "wrong_owner"]
)
def test_unsafe_source_refused_without_cleaning(tmp_path, violation, monkeypatch):
    root, raw, hold = fixture(tmp_path)
    if violation == "symlink":
        raw.rename(root / "real.log")
        raw.symlink_to(root / "real.log")
    elif violation == "hardlink":
        os.link(raw, root / "other-link")
    elif violation == "public_mode":
        raw.chmod(0o644)
    elif violation == "wrong_owner":
        real = finish.os.getuid
        monkeypatch.setattr(finish.os, "getuid", lambda: real() + 1)
    with pytest.raises(finish.ArchiveFinalizeRefused):
        finalize(root, hold)
    assert raw.exists()
    assert not (root / (NAME + ".bz2")).exists()


def test_unknown_producer_or_unverified_hold_refused(tmp_path):
    root, raw, hold = fixture(tmp_path)
    hold.producer = "system/com.other.service"
    with pytest.raises(finish.ArchiveFinalizeRefused, match="producer"):
        finalize(root, hold)
    assert raw.exists()
    hold.producer = "system/com.binnacle.mcp"

    def unverified(*_args):
        raise RuntimeError("generation unknown")

    hold.verify = unverified
    with pytest.raises(finish.ArchiveFinalizeRefused, match="not provable"):
        finalize(root, hold)
    assert raw.exists()


def test_pending_snapshot_ignored_even_when_stale(tmp_path):
    root, raw, hold = fixture(tmp_path)
    (root / (NAME + ".bz2.pending")).write_bytes(bz2.compress(b"stale"))
    (root / (NAME + ".bz2.pending")).chmod(0o600)
    result = finalize(root, hold)
    assert bz2.decompress((root / result.canonical).read_bytes()) == EVENTS
    assert bz2.decompress((root / (NAME + ".bz2.pending")).read_bytes()) == b"stale"
    assert not raw.exists()
    assert _stat_count(root).count("call=archived") == 2


def test_failed_short_write_does_not_publish_or_leak_temp(tmp_path, monkeypatch):
    root, raw, hold = fixture(tmp_path)
    monkeypatch.setattr(
        finish.stage,
        "_write_all",
        lambda *_args: (_ for _ in ()).throw(OSError("no disk")),
    )
    with pytest.raises(finish.ArchiveFinalizeRefused, match="refused"):
        finalize(root, hold)
    assert raw.read_bytes() == EVENTS
    assert not list(root.glob(".*.tmp"))
    assert not (root / (NAME + ".bz2")).exists()


def test_100gib_disk_reserve_remains_enforced(tmp_path, monkeypatch):
    root, raw, hold = fixture(tmp_path)

    class Disk:
        f_bavail = 1
        f_frsize = 1

    monkeypatch.setattr(finish.os, "fstatvfs", lambda *_: Disk())
    with pytest.raises(finish.ArchiveFinalizeRefused, match="insufficient"):
        finish.finalize_archive(root, NAME, hold=hold)
    assert raw.read_bytes() == EVENTS


def test_separately_installed_observability_writer_has_no_accepted_mapping(tmp_path):
    root, raw, hold = fixture(tmp_path)
    raw.rename(root / "session-observability.stderr.log.0")
    hold.producer = "system/com.binnacle.session-observability"
    with pytest.raises(finish.ArchiveFinalizeRefused, match="producer"):
        finish.finalize_archive(
            root,
            "session-observability.stderr.log.0",
            hold=hold,
            min_free_bytes=0,
        )
    assert (root / "session-observability.stderr.log.0").exists()


def test_separate_process_retains_fd_after_rename_until_writer_exits(tmp_path):
    """Native OS descriptor behavior; process/paths wholly test-owned."""
    import subprocess
    import sys

    root, raw, hold = fixture(tmp_path)
    raw.unlink()
    active = root / "mcp.stderr.log"
    active.write_bytes(EVENTS)
    active.chmod(0o600)
    child_code = (
        "import os,sys\n"
        "fd=os.open(sys.argv[1],os.O_WRONLY|os.O_APPEND)\n"
        "print('READY',flush=True)\n"
        "sys.stdin.readline()\n"
        "os.write(fd,b'2026-10-13T09:11:59 INFO event=tool_call call=late\\n')\n"
        "os.close(fd)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", child_code, str(active)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "READY"
        active.rename(raw)  # newsyslog GN on a temporary fixture
        active.write_text("")
        hold.running = True
        with pytest.raises(finish.ArchiveFinalizeRefused, match="running"):
            finalize(root, hold)
        assert proc.stdin is not None
        proc.stdin.write("go\n")
        proc.stdin.flush()
        proc.wait(timeout=10)
        assert proc.returncode == 0
        hold.running = False
        assert b"call=late" in raw.read_bytes()
        result = finalize(root, hold)
        assert b"call=late" in bz2.decompress((root / result.canonical).read_bytes())
        assert not raw.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        if proc.stdin is not None:
            proc.stdin.close()
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()


def test_hold_revoked_after_publication_keeps_raw_for_recovery(tmp_path, monkeypatch):
    root, raw, hold = fixture(tmp_path)
    original_link = finish.os.link

    def revocation(*args, **kwargs):
        result = original_link(*args, **kwargs)
        hold.running = True
        return result

    monkeypatch.setattr(finish.os, "link", revocation)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="quiescence"):
        finalize(root, hold)
    assert raw.read_bytes() == EVENTS
    assert (root / (NAME + ".bz2")).exists()
    assert _stat_count(root).count("call=archived") == 2
    hold.running = False
    # Restore the real linker and finish interrupted publication.
    monkeypatch.setattr(finish.os, "link", original_link)
    assert finalize(root, hold).resumed_publication
    assert not raw.exists()


def test_matching_canonical_but_public_permissions_cannot_be_recovered(tmp_path):
    root, raw, hold = fixture(tmp_path)
    published = root / (NAME + ".bz2")
    published.write_bytes(bz2.compress(EVENTS))
    published.chmod(0o644)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="not private"):
        finalize(root, hold)
    assert raw.read_bytes() == EVENTS
    assert bz2.decompress(published.read_bytes()) == EVENTS


def test_injected_source_hash_size_drift_refuses_before_publishing(
    tmp_path, monkeypatch
):
    root, raw, hold = fixture(tmp_path)
    original = finish.stage._hash_open_file

    def wrong_size(fd):
        digest, length = original(fd)
        return digest, length + 1

    monkeypatch.setattr(finish.stage, "_hash_open_file", wrong_size)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="size changed"):
        finalize(root, hold)
    assert raw.read_bytes() == EVENTS
    assert not (root / (NAME + ".bz2")).exists()


def test_raw_digest_changes_during_compression_refuses(tmp_path, monkeypatch):
    root, raw, hold = fixture(tmp_path)
    original = finish.stage._hash_open_file
    calls = [0]

    def stale_second(fd):
        digest, length = original(fd)
        calls[0] += 1
        if calls[0] >= 2:
            return "0" * 64, length
        return digest, length

    monkeypatch.setattr(finish.stage, "_hash_open_file", stale_second)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="source bytes changed"):
        finalize(root, hold)
    assert raw.read_bytes() == EVENTS
    assert not (root / (NAME + ".bz2")).exists()
    assert calls[0] >= 2


def test_compression_receipt_must_match_original_raw_bytes(tmp_path, monkeypatch):
    root, raw, hold = fixture(tmp_path)
    original = finish._make_temp

    def fake_receipt(*args):
        fd, digest, count = original(*args)
        return fd, digest, count - 1

    monkeypatch.setattr(finish, "_make_temp", fake_receipt)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="source changed"):
        finalize(root, hold)
    assert raw.read_bytes() == EVENTS
    assert not list(root.glob(".*.tmp"))


def test_large_incompressible_archive_streams_partial_blocks(tmp_path):
    root, raw, hold = fixture(tmp_path)
    content = os.urandom(2 * 1024 * 1024)
    raw.write_bytes(content)
    archive = finalize(root, hold)
    assert bz2.decompress((root / archive.canonical).read_bytes()) == content
    assert archive.source_bytes == len(content)
    assert not raw.exists()


def test_compressor_fails_on_raw_growing_past_initial_stat(tmp_path):
    root, raw, _ = fixture(tmp_path)
    parent = finish.stage._safe_directory(root)
    stream = os.open(NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
    temp = ".growing.bz2.tmp"
    initial = os.fstat(stream)
    try:
        with raw.open("ab") as append:
            append.write(b"more bytes")
        with pytest.raises(finish.ArchiveFinalizeRefused, match="raw log grew"):
            finish._make_temp(parent, stream, temp, initial)
        assert not (root / temp).exists()  # the owning compressor cleans on error
    finally:
        os.close(stream)
        os.close(parent)
        (root / temp).unlink(missing_ok=True)


def test_compressed_output_exceeding_expected_budget_rejected(tmp_path):
    root, _, _ = fixture(tmp_path)
    archive = root / "manual.bz2"
    archive.write_bytes(bz2.compress(b"abcdef"))
    archive.chmod(0o600)
    fd = os.open(archive, os.O_RDONLY)
    try:
        with pytest.raises(finish.ArchiveFinalizeRefused, match="length mismatch"):
            finish._check_compressed(fd, hashlib.sha256(b"ab").hexdigest(), 2)
    finally:
        os.close(fd)


def test_corrupt_matching_canonical_retains_raw_source(tmp_path):
    root, raw, hold = fixture(tmp_path)
    published = root / (NAME + ".bz2")
    published.write_bytes(b"not a bzip2 stream")
    published.chmod(0o600)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="unreadable"):
        finalize(root, hold)
    assert raw.read_bytes() == EVENTS
    assert published.read_bytes() == b"not a bzip2 stream"
