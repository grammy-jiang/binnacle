"""Temporary fixtures only: never mutate installed launchd service logs."""

from __future__ import annotations

import bz2
import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.companions import darwin_log_archive_stage as stage

NAME = "mcp.stderr.log.0"


def root_dir(tmp_path: Path) -> Path:
    path = tmp_path / "logs"
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def raw_archive(root: Path, payload: bytes = b"first\n" * 35) -> Path:
    item = root / NAME
    item.write_bytes(payload)
    item.chmod(0o600)
    return item


def stage_now(root: Path):
    return stage.stage_archive(root, NAME, min_free_bytes=0)


def test_staged_snapshot_retains_original_and_cannot_be_implicitly_ingested(tmp_path):
    root = root_dir(tmp_path)
    raw = raw_archive(root, b"before\nafter\n" * 20)
    first = raw.read_bytes()
    before = raw.stat()
    result = stage_now(root)
    staged = root / result.snapshot
    assert staged.name == NAME + ".bz2.pending"
    assert staged.read_bytes() != first
    assert bz2.decompress(staged.read_bytes()) == first
    assert raw.read_bytes() == first
    assert raw.stat().st_ino == before.st_ino
    assert raw.stat().st_mtime_ns == before.st_mtime_ns
    assert result.source_bytes == len(first)
    assert result.snapshot_bytes == staged.stat().st_size
    assert stat.S_IMODE(staged.stat().st_mode) == 0o600
    assert staged.stat().st_nlink == 1
    assert not list(root.glob("*.tmp"))
    assert stage.discover(root) == (NAME,)
    from binnacle.platform.darwin.daemon_logstats import DarwinDaemonLogStatsSource

    # Pending files are not selected by the production reader.
    (root / "mcp.stderr.log").write_text(
        "2026-10-13T15:10:00 INFO event=tool_call call=active\n"
    )
    raw.write_text("2026-10-13T15:09:00 INFO event=tool_call call=raw\n")
    text = DarwinDaemonLogStatsSource(root=root).read_spec(
        "binnacle-mcp", "2026-10-13 15:00", "2026-10-13 15:20"
    )
    assert text.count("call=raw") == 1
    assert text.count("call=active") == 1


def test_staging_is_create_only_never_overwrites_an_existing_snapshot(tmp_path):
    root = root_dir(tmp_path)
    source = raw_archive(root)
    first = stage_now(root)
    existing = (root / first.snapshot).read_bytes()
    with pytest.raises(stage.ArchiveStageRefused, match="failed safely"):
        stage_now(root)
    assert (root / first.snapshot).read_bytes() == existing
    assert source.exists()
    assert not list(root.glob(".*.tmp"))


def test_hardlinks_symlinks_and_nonprivate_logs_refused(tmp_path):
    root = root_dir(tmp_path)
    file = raw_archive(root)
    file.chmod(0o644)
    with pytest.raises(stage.ArchiveStageRefused, match="private"):
        stage_now(root)
    assert not (root / (NAME + ".bz2.pending")).exists()
    file.chmod(0o600)
    os.link(file, root / "other")
    with pytest.raises(stage.ArchiveStageRefused, match="private"):
        stage_now(root)
    (root / "other").unlink()
    file.unlink()
    file.symlink_to(tmp_path / "other-target")
    with pytest.raises(stage.ArchiveStageRefused):
        stage_now(root)


def test_symlink_root_and_world_readable_directory_refused(tmp_path):
    root = root_dir(tmp_path)
    raw_archive(root)
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    with pytest.raises(stage.ArchiveStageRefused):
        stage_now(alias)
    root.chmod(0o755)
    with pytest.raises(stage.ArchiveStageRefused, match="unsafe"):
        stage_now(root)


@pytest.mark.parametrize(
    "filename",
    [
        "mcp.stderr.log",
        "other.log.0",
        "mcp.stderr.log.00",
        "mcp.stderr.log.1000",
        "mcp.stderr.log.0.bz2",
        "../mcp.stderr.log.0",
        "/etc/passwd",
        "com.binnacle.jobs.err.log.0/payload",
        "mcp.stderr.log.-1",
    ],
)
def test_disallowed_names_never_read_other_files(tmp_path, filename):
    root = root_dir(tmp_path)
    with pytest.raises(stage.ArchiveStageRefused, match="not in"):
        stage.stage_archive(root, filename, min_free_bytes=0)
    assert list(root.iterdir()) == []


def test_reject_empty_or_oversized_archive_and_invalid_limits(tmp_path):
    root = root_dir(tmp_path)
    path = raw_archive(root, b"")
    with pytest.raises(stage.ArchiveStageRefused, match="bounded"):
        stage_now(root)
    path.write_bytes(b"more than four bytes")
    with pytest.raises(stage.ArchiveStageRefused, match="bounded"):
        stage.stage_archive(root, NAME, max_bytes=4, min_free_bytes=0)
    for size, free in ((0, 0), (1024**5, 0), (1024, -1)):
        with pytest.raises(stage.ArchiveStageRefused, match="invalid"):
            stage.stage_archive(root, NAME, max_bytes=size, min_free_bytes=free)
    assert list(root.iterdir()) == [path]


def test_statvfs_budget_blocks_extra_disk_growth(tmp_path, monkeypatch):
    root = root_dir(tmp_path)
    item = raw_archive(root)
    used = item.stat().st_size
    monkeypatch.setattr(
        stage.os,
        "statvfs",
        lambda path: SimpleNamespace(f_bavail=used - 1, f_frsize=1),
    )
    with pytest.raises(stage.ArchiveStageRefused, match="insufficient"):
        stage_now(root)
    assert list(root.iterdir()) == [item]


def test_mutating_source_during_compression_fails_closed(tmp_path, monkeypatch):
    root = root_dir(tmp_path)
    item = raw_archive(root)
    before = item.read_bytes()
    original = stage.bz2.BZ2Compressor

    class Mutator:
        def __init__(self, level=6):
            self.compressor = original(level)
            self.did_change = False

        def compress(self, data):
            if not self.did_change:
                with item.open("ab") as stream:
                    stream.write(b"new concurrently written tail")
                self.did_change = True
            return self.compressor.compress(data)

        def flush(self):
            return self.compressor.flush()

    monkeypatch.setattr(stage.bz2, "BZ2Compressor", Mutator)
    with pytest.raises(stage.ArchiveStageRefused, match="source changed"):
        stage_now(root)
    assert item.read_bytes().startswith(before)
    assert not list(root.glob("*.pending"))
    assert len(list(root.iterdir())) == 1


def test_replaced_source_inode_before_publication_is_refused(tmp_path, monkeypatch):
    root = root_dir(tmp_path)
    item = raw_archive(root)
    original = stage._compressed_hash

    def replace(fd):
        result = original(fd)
        data = item.read_bytes()
        item.unlink()
        item.write_bytes(data)
        item.chmod(0o600)
        return result

    monkeypatch.setattr(stage, "_compressed_hash", replace)
    with pytest.raises(stage.ArchiveStageRefused, match="source"):
        stage_now(root)
    assert not list(root.glob("*.pending"))


def test_corrupt_compressed_bytes_never_published(tmp_path, monkeypatch):
    root = root_dir(tmp_path)
    raw_archive(root)
    monkeypatch.setattr(stage, "_compressed_hash", lambda fd: ("bad", 0))
    with pytest.raises(stage.ArchiveStageRefused, match="validation failed"):
        stage_now(root)
    assert not list(root.glob("*.pending"))


def test_stage_does_not_remove_source_even_when_it_changes_after_publication(tmp_path):
    root = root_dir(tmp_path)
    item = raw_archive(root)
    receipt = stage_now(root)
    item.write_bytes(item.read_bytes() + b"still being written\n")
    assert b"still being written" in item.read_bytes()
    assert bz2.decompress((root / receipt.snapshot).read_bytes()) != item.read_bytes()
    assert item.exists()


def test_discover_returns_allowlisted_candidates_without_writing(tmp_path):
    root = root_dir(tmp_path)
    raw_archive(root)
    (root / "mcp.stderr.log.0.bz2.pending").write_bytes(b"pending")
    (root / "totally-unrelated.log.0").write_bytes(b"unrelated")
    (root / "mcp.stderr.log").write_bytes(b"current")
    names_before = sorted(x.name for x in root.iterdir())
    assert stage.discover(root) == (NAME,)
    assert sorted(x.name for x in root.iterdir()) == names_before


def test_cli_readonly_darwin_preview_does_not_stage(tmp_path, monkeypatch, capsys):
    root = root_dir(tmp_path)
    raw_archive(root)
    monkeypatch.setattr(stage.platform, "system", lambda: "Darwin")
    assert stage.main(["--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == {"candidates": [NAME]}
    assert not list(root.glob("*.pending"))


def test_cli_explicit_darwin_stage_and_missing_source_refusal(
    tmp_path, monkeypatch, capsys
):
    root = root_dir(tmp_path)
    raw_archive(root)
    monkeypatch.setattr(stage.platform, "system", lambda: "Darwin")
    # CI Linux runners may have less than the 100 GiB *production* reserve.
    # Only this temp-fixture CLI test bypasses the reserve; the real CLI
    # and stage_archive defaults remain fail-closed.
    actual_stage = stage.stage_archive
    monkeypatch.setattr(
        stage,
        "stage_archive",
        lambda path, name: actual_stage(path, name, min_free_bytes=0),
    )
    assert stage.main(["--root", str(root), "--stage", NAME]) == 0
    assert json.loads(capsys.readouterr().out)["snapshot"] == NAME + ".bz2.pending"
    assert stage.main(["--root", str(root), "--stage", "tunnel.stdout.log.0"]) == 2
    assert "refused" in json.loads(capsys.readouterr().out)


def test_cli_refuses_nondarwin_without_mutations(tmp_path, monkeypatch):
    root = root_dir(tmp_path)
    raw_archive(root)
    monkeypatch.setattr(stage.platform, "system", lambda: "Linux")
    with pytest.raises(SystemExit) as exc:
        stage.main(["--root", str(root), "--stage", NAME])
    assert exc.value.code == 2
    assert not list(root.glob("*.pending"))


def test_stage_does_not_invoke_launchctl_news_rotate_or_process_kill(
    tmp_path, monkeypatch
):
    root = root_dir(tmp_path)
    raw_archive(root)
    monkeypatch.setattr(
        stage.subprocess if hasattr(stage, "subprocess") else subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("no process command permitted")
        ),
    )
    assert stage_now(root).snapshot.endswith(".pending")


def test_short_os_writes_are_retried_without_truncated_snapshot(tmp_path, monkeypatch):
    root = root_dir(tmp_path)
    payload = bytes(range(256)) * 240
    raw_archive(root, payload)
    original = stage.os.write
    attempts = []

    def short_write(fd, data):
        attempts.append(len(data))
        return original(fd, data[: max(1, len(data) // 3)])

    monkeypatch.setattr(stage.os, "write", short_write)
    receipt = stage_now(root)
    assert len(attempts) > 2
    assert bz2.decompress((root / receipt.snapshot).read_bytes()) == payload


def test_zero_length_os_write_refuses_without_partial_snapshot(tmp_path, monkeypatch):
    root = root_dir(tmp_path)
    item = raw_archive(root)
    initial = item.read_bytes()
    monkeypatch.setattr(stage.os, "write", lambda fd, data: 0)
    with pytest.raises(stage.ArchiveStageRefused, match="write failed"):
        stage_now(root)
    assert item.read_bytes() == initial
    assert not list(root.glob("*.pending"))
    assert not list(root.glob(".*.tmp"))


def test_discover_does_not_trust_a_symlinked_raw_archive(tmp_path):
    root = root_dir(tmp_path)
    target = tmp_path / "outside"
    target.write_bytes(b"outside bytes")
    (root / NAME).symlink_to(target)
    with pytest.raises(stage.ArchiveStageRefused, match="private bounded"):
        stage.discover(root)
    assert target.read_bytes() == b"outside bytes"


def test_discover_does_not_offer_archives_with_public_permissions(tmp_path):
    root = root_dir(tmp_path)
    archive = raw_archive(root)
    archive.chmod(0o644)
    with pytest.raises(stage.ArchiveStageRefused, match="private"):
        stage.discover(root)


def test_wrong_owner_refused_and_raw_log_unchanged(tmp_path, monkeypatch):
    root = root_dir(tmp_path)
    item = raw_archive(root)
    before = item.read_bytes()
    original_uid = stage.os.getuid
    values = iter([original_uid(), -1])

    def uid():
        return next(values, -1)

    monkeypatch.setattr(stage.os, "getuid", uid)
    with pytest.raises(stage.ArchiveStageRefused, match="private"):
        stage_now(root)
    assert item.read_bytes() == before
    assert not list(root.glob("*.pending"))
