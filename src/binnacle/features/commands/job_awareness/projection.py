"""Bounded authorized selector ring and metadata-only reminder projection."""

from threading import RLock

from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    CandidateCategory,
    ErrorCode,
    Failure,
    JobRef,
    ObservationState,
    ReceiptState,
    ReminderCandidate,
    Result,
    Scope,
    Success,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.ports import (
    HandleAuthorityPort,
    JobObservationPort,
    ReceiptQueryPort,
)
from binnacle.features.commands.job_awareness.snapshots import failure


class CandidateRing:
    """One controller-enrolled grant, <=100 exact selectors, <=8 per call.

    Registration is explicit and atomic, not discovery. No arbitrary iterable
    is consumed. Each selector gets fresh authority before observation; the
    observation and receipt ports also enforce their own admission contracts.
    No payload reads, cleanup, receipt mutation or retries occur here.
    """

    def __init__(
        self,
        authority: HandleAuthorityPort,
        observer: JobObservationPort,
        receipts: ReceiptQueryPort,
    ) -> None:
        self._authority = authority
        self._observer = observer
        self._receipts = receipts
        self._grant: VerifiedRunGrant | None = None
        self._jobs: tuple[JobRef, ...] = ()
        self._cursor = 0
        self._lock = RLock()

    def register(
        self, grant: VerifiedRunGrant, jobs: tuple[JobRef, ...]
    ) -> Result[None]:
        if (
            type(jobs) is not tuple
            or len(jobs) > 100
            or any(type(job) is not JobRef for job in jobs)
            or len(set(jobs)) != len(jobs)
        ):
            return failure(ErrorCode.QUOTA_EXCEEDED)
        for job in jobs:
            if (
                self._authority.check(grant, job, frozenset({Scope.OBSERVE}))
                is not AuthorityDecision.AUTHORIZED
            ):
                return failure(ErrorCode.DENIED)
        with self._lock:
            self._grant, self._jobs, self._cursor = grant, jobs, 0
        return Success(None)

    def candidates(self, grant: VerifiedRunGrant) -> tuple[ReminderCandidate, ...]:
        with self._lock:
            if grant is not self._grant or not self._jobs:
                return ()
            jobs = tuple(
                self._jobs[(self._cursor + i) % len(self._jobs)]
                for i in range(min(8, len(self._jobs)))
            )
            self._cursor = (self._cursor + len(jobs)) % len(self._jobs)
        candidates = []
        for job in jobs:
            if (
                self._authority.check(grant, job, frozenset({Scope.OBSERVE}))
                is not AuthorityDecision.AUTHORIZED
            ):
                continue
            result = self._observer.observe(grant, job)
            if isinstance(result, Failure) or result.value.job != job:
                continue
            observation = result.value
            if observation.state is ObservationState.RUNNING:
                candidates.append(
                    ReminderCandidate(
                        job, CandidateCategory.RUNNING, job.incarnation[3:], None
                    )
                )
                continue
            snapshot = observation.snapshot
            if snapshot is None:
                continue
            receipt = self._receipts.query(grant, snapshot)
            if (
                isinstance(receipt, Failure)
                or receipt.value.job != job
                or receipt.value.snapshot_sha256 != snapshot.sha256
            ):
                continue
            state = receipt.value.state
            if state not in (ReceiptState.UNCONFIRMED, ReceiptState.PARTIAL):
                continue
            category = (
                CandidateCategory.TERMINAL_UNCONFIRMED
                if state is ReceiptState.UNCONFIRMED
                else CandidateCategory.TERMINAL_PARTIAL
            )
            candidates.append(
                ReminderCandidate(job, category, snapshot.seal_id, snapshot.sha256)
            )
        return tuple(candidates)
