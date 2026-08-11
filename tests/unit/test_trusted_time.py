"""Trusted-time rollback, reboot, and deadline tests."""

from __future__ import annotations

from datetime import timedelta

from tests.phase4_support import NOW

from binnacle.domain.trusted_time import (
    DeadlineStatus,
    TrustedTimeEvidence,
    TrustedTimeSnapshot,
    evaluate_deadline,
)


def _evidence() -> TrustedTimeEvidence:
    return TrustedTimeEvidence(NOW, "a" * 64, 100, 1)


def test_same_boot_monotonic_deadline_is_authoritative() -> None:
    result = evaluate_deadline(
        snapshot=TrustedTimeSnapshot(NOW - timedelta(days=1), 201, "a" * 64, False),
        evidence=_evidence(),
        expires_at=NOW + timedelta(hours=1),
        registered_boot_id_digest="a" * 64,
        monotonic_deadline_ns=200,
    )
    assert result.status is DeadlineStatus.EXPIRED


def test_cross_boot_requires_trusted_non_rollback_wall_time() -> None:
    untrusted = evaluate_deadline(
        snapshot=TrustedTimeSnapshot(NOW, 1, "b" * 64, False),
        evidence=_evidence(),
        expires_at=NOW + timedelta(hours=1),
        registered_boot_id_digest="a" * 64,
        monotonic_deadline_ns=200,
    )
    rollback = evaluate_deadline(
        snapshot=TrustedTimeSnapshot(NOW - timedelta(seconds=1), 1, "b" * 64, True),
        evidence=_evidence(),
        expires_at=NOW + timedelta(hours=1),
        registered_boot_id_digest="a" * 64,
        monotonic_deadline_ns=200,
    )
    assert untrusted.status is DeadlineStatus.UNAVAILABLE
    assert rollback.status is DeadlineStatus.UNAVAILABLE


def test_valid_new_boot_advances_generation_and_high_watermark() -> None:
    snapshot = TrustedTimeSnapshot(NOW + timedelta(seconds=1), 5, "b" * 64, True)
    result = evaluate_deadline(
        snapshot=snapshot,
        evidence=_evidence(),
        expires_at=NOW + timedelta(hours=1),
        registered_boot_id_digest="a" * 64,
        monotonic_deadline_ns=200,
    )
    assert result.status is DeadlineStatus.VALID
    assert result.accepted_evidence is not None
    assert result.accepted_evidence.generation == 2
    assert result.accepted_evidence.high_watermark == snapshot.wall_time


def test_same_boot_monotonic_rollback_and_untrusted_wall_fail() -> None:
    rollback = evaluate_deadline(
        snapshot=TrustedTimeSnapshot(NOW, 99, "a" * 64, True),
        evidence=_evidence(),
        expires_at=NOW + timedelta(hours=1),
        registered_boot_id_digest="a" * 64,
        monotonic_deadline_ns=200,
    )
    untrusted = evaluate_deadline(
        snapshot=TrustedTimeSnapshot(NOW, 101, "a" * 64, False),
        evidence=_evidence(),
        expires_at=NOW + timedelta(hours=1),
        registered_boot_id_digest="a" * 64,
        monotonic_deadline_ns=200,
    )
    assert rollback.status is DeadlineStatus.UNAVAILABLE
    assert untrusted.status is DeadlineStatus.UNAVAILABLE


def test_wall_deadline_expiry_is_reported_when_trusted() -> None:
    result = evaluate_deadline(
        snapshot=TrustedTimeSnapshot(NOW + timedelta(hours=2), 101, "a" * 64, True),
        evidence=_evidence(),
        expires_at=NOW + timedelta(hours=1),
        registered_boot_id_digest="a" * 64,
        monotonic_deadline_ns=10_000,
    )
    assert result.status is DeadlineStatus.EXPIRED
