"""Durable pre-unlink and post-fsync hook order under a verified writer hold."""

from __future__ import annotations

import bz2
from pathlib import Path

import pytest

from binnacle.companions import darwin_log_archive_finalize as finalizer
from tests.platform.darwin.test_log_archive_finalize import (
    EVENTS,
    NAME,
    fixture,
)


def test_real_bz2_compression_has_canonical_receipt_before_raw_unlink(
    tmp_path: Path,
) -> None:
    root, raw, hold = fixture(tmp_path)
    order: list[str] = []

    def canonical(info: finalizer.FinalizedArchive) -> None:
        assert hold.held
        assert raw.read_bytes() == EVENTS
        assert bz2.decompress((root / info.canonical).read_bytes()) == EVENTS
        assert not info.resumed_publication
        order.append("canonical_verified")

    def pruned(info: finalizer.FinalizedArchive) -> None:
        assert hold.held
        assert not raw.exists()
        assert bz2.decompress((root / info.canonical).read_bytes()) == EVENTS
        order.append("raw_pruned")

    result = finalizer.finalize_archive(
        root,
        NAME,
        hold=hold,
        min_free_bytes=0,
        milestones=finalizer.FinalizeMilestones(canonical, pruned),
    )
    assert result.sha256
    assert order == ["canonical_verified", "raw_pruned"]
    assert not hold.held


def test_canonical_milestone_failure_preserves_source_and_verified_archive(
    tmp_path: Path,
) -> None:
    root, raw, hold = fixture(tmp_path)
    seen = [0]

    def refused(_info: finalizer.FinalizedArchive) -> None:
        seen[0] += 1
        raise finalizer.ArchiveFinalizeRefused("durable journal fsync failed")

    def must_not_run(_info: finalizer.FinalizedArchive) -> None:
        pytest.fail("raw-pruned cannot occur if canonical ACK failed")

    with pytest.raises(finalizer.ArchiveFinalizeRefused, match="journal fsync"):
        finalizer.finalize_archive(
            root,
            NAME,
            hold=hold,
            min_free_bytes=0,
            milestones=finalizer.FinalizeMilestones(refused, must_not_run),
        )
    assert seen == [1]
    assert raw.read_bytes() == EVENTS
    assert bz2.decompress((root / (NAME + ".bz2")).read_bytes()) == EVENTS
    assert not hold.held


def test_callback_mutating_raw_inode_causes_second_hold_verification_failure(
    tmp_path: Path,
) -> None:
    root, raw, hold = fixture(tmp_path)
    injected = b"uncooperative bytes\n"

    def bad_canonical(_info: finalizer.FinalizedArchive) -> None:
        with raw.open("ab") as file:
            file.write(injected)

    with pytest.raises(finalizer.ArchiveFinalizeRefused, match="raw log changed"):
        finalizer.finalize_archive(
            root,
            NAME,
            hold=hold,
            min_free_bytes=0,
            milestones=finalizer.FinalizeMilestones(
                bad_canonical,
                lambda _: pytest.fail("pruned after mutation"),
            ),
        )
    assert raw.read_bytes() == EVENTS + injected
    assert not hold.held


def test_callback_swapping_canonical_inode_refuses_raw_unlink(
    tmp_path: Path,
) -> None:
    root, raw, hold = fixture(tmp_path)
    foreign = b"replacement compressed data"

    def swap(info: finalizer.FinalizedArchive) -> None:
        path = root / info.canonical
        path.rename(root / "prior-canonical")
        path.write_bytes(foreign)
        path.chmod(0o600)

    with pytest.raises(finalizer.ArchiveFinalizeRefused, match="canonical archive"):
        finalizer.finalize_archive(
            root,
            NAME,
            hold=hold,
            min_free_bytes=0,
            milestones=finalizer.FinalizeMilestones(
                swap,
                lambda _: pytest.fail("raw deleted after canonical swap"),
            ),
        )
    assert raw.read_bytes() == EVENTS
    assert (root / (NAME + ".bz2")).read_bytes() == foreign


def test_raw_pruned_ack_failure_reports_uncertain_post_delete_state(
    tmp_path: Path,
) -> None:
    root, raw, hold = fixture(tmp_path)
    seen: list[str] = []

    def canonical(_info: finalizer.FinalizedArchive) -> None:
        seen.append("canonical")

    def raw_pruned(_info: finalizer.FinalizedArchive) -> None:
        assert not raw.exists()
        seen.append("raw_pruned")
        raise finalizer.ArchiveFinalizeRefused(
            "simulated durable raw-pruned receipt failure"
        )

    with pytest.raises(finalizer.ArchiveFinalizeRefused, match="receipt failure"):
        finalizer.finalize_archive(
            root,
            NAME,
            hold=hold,
            min_free_bytes=0,
            milestones=finalizer.FinalizeMilestones(canonical, raw_pruned),
        )
    assert seen == ["canonical", "raw_pruned"]
    assert not raw.exists()  # MUST NOT claim rollback after unlink
    assert bz2.decompress((root / (NAME + ".bz2")).read_bytes()) == EVENTS
    assert not hold.held


def test_milestones_can_recheck_existing_canonical_after_preunlink_failure(
    tmp_path: Path,
) -> None:
    root, raw, hold = fixture(tmp_path)
    attempts = [0]

    def maybe_fail(_info: finalizer.FinalizedArchive) -> None:
        attempts[0] += 1
        if attempts[0] == 1:
            raise finalizer.ArchiveFinalizeRefused("simulate controller outage")

    def verified(_info: finalizer.FinalizedArchive) -> None:
        assert not raw.exists()

    hooks = finalizer.FinalizeMilestones(maybe_fail, verified)
    with pytest.raises(finalizer.ArchiveFinalizeRefused, match="controller outage"):
        finalizer.finalize_archive(
            root, NAME, hold=hold, min_free_bytes=0, milestones=hooks
        )
    assert raw.exists() and (root / (NAME + ".bz2")).exists()
    second = finalizer.finalize_archive(
        root, NAME, hold=hold, min_free_bytes=0, milestones=hooks
    )
    assert second.resumed_publication
    assert attempts == [2]
    assert not raw.exists()
