"""Pure, bounded selection of synthetic terminal reminder candidates.

The caller supplies an already validated native result and an injected grant.
This module never constructs authority from a selector or client metadata.
"""

from dataclasses import replace

from binnacle.features.commands.job_awareness.identifiers import require
from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    CandidateCategory,
    ConsumerReceipt,
    JobRef,
    Observation,
    ObservationState,
    OutputSnapshot,
    ReceiptState,
    ReminderCandidate,
    Scope,
    Success,
    TerminalOutcome,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.ports import (
    HandleAuthorityPort,
    ReceiptQueryPort,
)

MAX_OBSERVED = 8
MAX_HINT_JOBS = 2
_OBSERVE = frozenset({Scope.OBSERVE})


def _validated_observation(observation: Observation) -> Observation:
    """Rebuild nested values: frozen records can still arrive corrupted."""
    require(type(observation) is Observation)
    require(type(observation.job) is JobRef)
    job = replace(observation.job)
    terminal = observation.terminal
    if terminal is not None:
        require(type(terminal) is TerminalOutcome)
        terminal = replace(terminal)
    snapshot = observation.snapshot
    if snapshot is not None:
        require(type(snapshot) is OutputSnapshot)
        require(type(snapshot.job) is JobRef)
        require(type(snapshot.terminal) is TerminalOutcome)
        snapshot = replace(
            snapshot, job=replace(snapshot.job), terminal=replace(snapshot.terminal)
        )
    require(observation.state is not ObservationState.TERMINAL or snapshot is not None)
    return replace(observation, job=job, terminal=terminal, snapshot=snapshot)


def _validated_receipt(receipt: ConsumerReceipt) -> ConsumerReceipt:
    require(type(receipt) is ConsumerReceipt)
    # Validate the tuple type and length before traversing its bounded ranges.
    receipt = replace(receipt)
    return replace(
        receipt,
        job=replace(receipt.job),
        ranges=tuple(replace(item) for item in receipt.ranges),
    )


def select_candidates(
    grant: VerifiedRunGrant | None,
    observations: tuple[Observation, ...],
    authority: HandleAuthorityPort,
    receipts: ReceiptQueryPort,
) -> tuple[ReminderCandidate, ...]:
    """Return ranked candidates, or none if any boundary is uncertain.

    A result error or invalid success at the native boundary must prevent this
    function from being called. I2-2 owns that independent preflight.
    """
    if (
        not isinstance(grant, VerifiedRunGrant)
        or type(observations) is not tuple
        or not 1 <= len(observations) <= MAX_OBSERVED
    ):
        return ()

    ranked: list[tuple[int, str, ReminderCandidate]] = []
    seen = set()
    try:
        validated = tuple(_validated_observation(item) for item in observations)
    except (AttributeError, ValueError):
        return ()
    for observation in validated:
        if observation.job in seen:
            return ()
        seen.add(observation.job)

    for observation in validated:
        if observation.state is not ObservationState.TERMINAL:
            continue
        snapshot = observation.snapshot
        if snapshot is None:
            return ()  # Defensive fail-closed guard; do not rely on assertions.
        try:
            if (
                authority.check(grant, observation.job, _OBSERVE)
                is not AuthorityDecision.AUTHORIZED
            ):
                return ()
            result = receipts.query(grant, snapshot)
        except Exception:  # noqa: BLE001 - injected ports must fail closed
            return ()
        if type(result) is not Success:
            return ()
        try:
            receipt = _validated_receipt(result.value)
        except (AttributeError, ValueError):
            return ()
        if receipt.job != observation.job or receipt.snapshot_sha256 != snapshot.sha256:
            return ()
        if receipt.state in (ReceiptState.COMPLETE, ReceiptState.OUTPUT_EXPIRED):
            continue
        if receipt.state is ReceiptState.UNCONFIRMED:
            category = CandidateCategory.TERMINAL_UNCONFIRMED
            priority = 0
        elif receipt.state is ReceiptState.PARTIAL:
            category = CandidateCategory.TERMINAL_PARTIAL
            priority = 1
        else:
            return ()  # type: ignore[unreachable]  # Runtime corrupt-record guard.
        try:
            candidate = ReminderCandidate(
                observation.job, category, snapshot.seal_id, snapshot.sha256
            )
        except (AttributeError, ValueError):
            return ()
        ranked.append((priority, observation.job.canonical_key, candidate))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return tuple(row[2] for row in ranked[:MAX_HINT_JOBS])
