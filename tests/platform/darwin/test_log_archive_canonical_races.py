"""Writer-held canonical archive pathname identity must survive until raw unlink."""

from __future__ import annotations

import bz2
from pathlib import Path

import pytest

from binnacle.companions import darwin_log_archive_finalize as finish
from tests.platform.darwin.test_log_archive_finalize import EVENTS, NAME, fixture


def _canonical(root: Path) -> Path:
    return root / (NAME + ".bz2")


def _already_verified(root: Path) -> Path:
    canonical = _canonical(root)
    canonical.write_bytes(bz2.compress(EVENTS))
    canonical.chmod(0o600)
    return canonical


@pytest.mark.parametrize("change", ["replace", "symlink", "rewrite"])
def test_resumed_archive_mutated_after_hash_must_not_prune_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root, raw, hold = fixture(tmp_path)
    original = raw.read_bytes()
    canonical = _already_verified(root)
    original_stable = finish._stable_raw
    calls = [0]
    archived = canonical.read_bytes()

    def swap_after_verification(*args, **kwargs):
        result = original_stable(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 3:
            if change == "replace":
                canonical.rename(root / "old-canonical")
                canonical.write_bytes(archived)  # identical content, new inode
                canonical.chmod(0o600)
            elif change == "symlink":
                canonical.rename(root / "old-canonical")
                canonical.symlink_to(root / "old-canonical")
            else:
                canonical.write_bytes(bz2.compress(b"forged different bytes"))
                canonical.chmod(0o600)
        return result

    monkeypatch.setattr(finish, "_stable_raw", swap_after_verification)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="canonical archive"):
        finish.finalize_archive(root, NAME, hold=hold, min_free_bytes=0)
    assert calls[0] >= 3
    assert raw.read_bytes() == original
    assert not hold.held


@pytest.mark.parametrize("change", ["replace", "symlink"])
def test_new_canonical_swapped_after_atomic_link_preserves_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root, raw, hold = fixture(tmp_path)
    original = raw.read_bytes()
    canonical = _canonical(root)
    link = finish.os.link
    flips = [0]

    def change_published_link(*args, **kwargs):
        link(*args, **kwargs)
        if canonical.exists():
            flips[0] += 1
            canonical.rename(root / "verified-but-moved")
            if change == "replace":
                canonical.write_bytes(bz2.compress(b"foreign"))
                canonical.chmod(0o600)
            else:
                canonical.symlink_to(root / "verified-but-moved")

    monkeypatch.setattr(finish.os, "link", change_published_link)
    with pytest.raises(finish.ArchiveFinalizeRefused, match="canonical archive"):
        finish.finalize_archive(root, NAME, hold=hold, min_free_bytes=0)
    assert flips == [1]
    assert raw.read_bytes() == original
    assert not hold.held
    assert not list(root.glob(".*.bz2.tmp"))


def test_successful_resumed_archive_still_prunes_exact_raw(tmp_path: Path) -> None:
    root, raw, hold = fixture(tmp_path)
    _already_verified(root)
    result = finish.finalize_archive(root, NAME, hold=hold, min_free_bytes=0)
    assert result.resumed_publication
    assert not raw.exists()
    assert bz2.decompress(_canonical(root).read_bytes()) == EVENTS


def test_successful_fresh_archive_still_prunes_exact_raw(tmp_path: Path) -> None:
    root, raw, hold = fixture(tmp_path)
    result = finish.finalize_archive(root, NAME, hold=hold, min_free_bytes=0)
    assert not result.resumed_publication
    assert not raw.exists()
    assert bz2.decompress(_canonical(root).read_bytes()) == EVENTS
