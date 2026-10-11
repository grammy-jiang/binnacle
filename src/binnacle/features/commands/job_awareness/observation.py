"""Exact, metadata-only observation. Terminal status alone never seals output."""

from collections.abc import Callable

from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    ErrorCode,
    Failure,
    JobRef,
    ObservationResult,
    ObservationState,
    Scope,
    Success,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.ports import HandleAuthorityPort
from binnacle.features.commands.job_awareness.snapshots import (
    SnapshotClock,
    TrustedCatalog,
    failure,
)


class JobObserver:
    def __init__(
        self,
        authority: HandleAuthorityPort,
        catalog: TrustedCatalog,
        clock: Callable[[], int],
    ) -> None:
        self._authority = authority
        self._catalog = catalog
        self._clock = SnapshotClock(clock)

    def observe(self, grant: VerifiedRunGrant, job: JobRef) -> ObservationResult:
        if (
            self._authority.check(grant, job, frozenset({Scope.OBSERVE}))
            is not AuthorityDecision.AUTHORIZED
        ):
            return failure(ErrorCode.DENIED)
        entry = self._catalog.lookup(job)
        if entry is None:
            return failure(ErrorCode.SOURCE_UNAVAILABLE)
        observation = entry.observation
        if (
            observation.state is ObservationState.TERMINAL
            and observation.snapshot is None
        ):
            return failure(ErrorCode.SOURCE_UNSEALED)
        now = self._clock.read()
        if isinstance(now, Failure):
            return now
        if (
            observation.snapshot is not None
            and now.value < observation.snapshot.sealed_at_ms
        ):
            return failure(ErrorCode.CLOCK_UNSAFE)
        invalid = self._catalog.status(entry, now.value)
        if invalid is not None:
            return failure(invalid)
        return Success(observation)
