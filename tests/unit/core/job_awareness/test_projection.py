"""Bounded round-robin candidates contain no output or private command text."""

import pytest

from binnacle.features.commands.job_awareness.models import (
    CandidateCategory,
    ConsumerReceipt,
    ErrorCode,
    Observation,
    ObservationState,
    ReceiptState,
    Success,
)
from binnacle.features.commands.job_awareness.observation import JobObserver
from binnacle.features.commands.job_awareness.projection import CandidateRing
from tests.contracts.job_awareness.fakes import FakeHandleAuthority, FakeReceiptQuery
from tests.unit.core.job_awareness.test_snapshots import (
    CountingCatalog,
    assert_error,
    enroll,
    job_ref,
)


@pytest.mark.parametrize("count", [0, 1, 10, 100])
def test_bounded_selection(count):
    authority = FakeHandleAuthority()
    jobs = tuple(job_ref(i + 1) for i in range(count))
    grant = authority.issue(jobs or (job_ref(),))
    catalog = CountingCatalog()
    for job in jobs:
        catalog.register(Observation(job, ObservationState.RUNNING, None, None))
    ring = CandidateRing(
        authority,
        JobObserver(authority, catalog, lambda: 1000),
        FakeReceiptQuery(authority),
    )
    assert isinstance(ring.register(grant, jobs), Success)
    selected = ring.candidates(grant)
    assert tuple(c.job for c in selected) == jobs[:8]
    assert catalog.lookups == min(count, 8)
    assert all(c.category is CandidateCategory.RUNNING for c in selected)
    if count == 10:
        assert tuple(c.job for c in ring.candidates(grant)) == jobs[8:] + jobs[:6]
    authority.revoke(grant)
    catalog.lookups = 0
    assert ring.candidates(grant) == ()
    assert catalog.lookups == 0


def test_oversized_and_lazy_registration():
    authority = FakeHandleAuthority()
    grant = authority.issue((job_ref(),))
    ring = CandidateRing(
        authority,
        JobObserver(authority, CountingCatalog(), lambda: 1000),
        FakeReceiptQuery(authority),
    )

    class Trap:
        def __iter__(self):
            raise AssertionError("must not iterate")

    for jobs in (Trap(), tuple(job_ref(i) for i in range(101)), (job_ref(), job_ref())):
        assert_error(ring.register(grant, jobs), ErrorCode.QUOTA_EXCEEDED)
    assert ring.candidates(grant) == ()


@pytest.mark.parametrize(
    "state,category",
    [
        (ReceiptState.UNCONFIRMED, CandidateCategory.TERMINAL_UNCONFIRMED),
        (ReceiptState.PARTIAL, CandidateCategory.TERMINAL_PARTIAL),
        (ReceiptState.COMPLETE, None),
        (ReceiptState.OUTPUT_EXPIRED, None),
    ],
)
def test_receipt_projection_and_no_payload(tmp_path, state, category):
    authority = FakeHandleAuthority()
    catalog = CountingCatalog()
    snap, source = enroll(catalog, tmp_path, payload=b"private /path command secret")
    grant = authority.issue((snap.job,))
    query = FakeReceiptQuery(authority)
    query.register(
        grant, snap, ConsumerReceipt(state, snap.job, snap.sha256, (), False, 0, 1)
    )
    ring = CandidateRing(
        authority, JobObserver(authority, catalog, lambda: 1000), query
    )
    ring.register(grant, (snap.job,))
    for _ in range(12):
        candidates = ring.candidates(grant)
        assert len(candidates) == (1 if category else 0)
        if category:
            assert candidates[0].category is category
            assert candidates[0].snapshot_sha256 == snap.sha256
            assert "private" not in repr(candidates)
    assert source.reads == source.bytes_read == 0
    other = authority.issue((snap.job,))
    assert ring.candidates(other) == ()


def test_failed_and_mismatched_receipts_suppress(tmp_path):
    from dataclasses import replace

    authority = FakeHandleAuthority()
    catalog = CountingCatalog()
    snap, source = enroll(catalog, tmp_path)
    grant = authority.issue((snap.job,))
    query = FakeReceiptQuery(authority)
    ring = CandidateRing(
        authority, JobObserver(authority, catalog, lambda: 1000), query
    )
    ring.register(grant, (snap.job,))
    assert ring.candidates(grant) == ()  # Missing is not UNCONFIRMED.
    foreign = authority.issue((job_ref(2),))
    assert_error(ring.register(foreign, (snap.job,)), ErrorCode.DENIED)
    assert source.reads == 0
    receipt = ConsumerReceipt(
        ReceiptState.UNCONFIRMED, snap.job, snap.sha256, (), False, 0, 1
    )

    class WrongQuery:
        def query(self, grant, snapshot):
            return Success(replace(receipt, snapshot_sha256="f" * 64))

    ring = CandidateRing(
        authority, JobObserver(authority, catalog, lambda: 1000), WrongQuery()
    )
    ring.register(grant, (snap.job,))
    assert ring.candidates(grant) == ()
