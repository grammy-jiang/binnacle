"""E2 once-only hint emission under the per-key fence (design §2.6). LAB_ONLY.

Only the native witnessed ``fixture_unrelated_read`` result reaches here.
Sequence: route -> eligible set (LIVE, sealed, emit PENDING, receipt
UNCONFIRMED/PARTIAL, ``select_candidates`` order, at most two) -> reserve
(one lab tx, fresh ``rid``) -> ``adapt_routed`` -> final validation inside the
commit tx (LIVE in the current epoch, AUTHORIZED, unchanged in-memory entry,
key not SUSPENDED) -> EMITTED for rendered jobs, PENDING for the rest. Any
validation, rowcount, commit, adapter or cancellation failure returns the
original result (hint suppressed) and aborts the reservation. A stuck
RESERVED row is never re-hintable; the cold-start sweep aborts it.
"""

import secrets
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar

from binnacle.features.commands.job_awareness.hint_policy import MAX_HINT_JOBS
from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    JobRef,
    ReceiptState,
    Scope,
    Success,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.session_binding import (
    ABORT,
    EMIT,
    RESERVE,
    RESET,
    AllocationEntry,
    KeyBinding,
    LabFailure,
    LabTx,
)
from binnacle.features.commands.job_awareness.session_lab import SessionLab
from binnacle.features.commands.job_awareness.session_route import (
    KeyDigest,
    RouteOutcome,
    SessionRoute,
)

T = TypeVar("T")
Checkpoint = Callable[[str], Awaitable[None]]
_OBSERVE = frozenset({Scope.OBSERVE})
_PRIORITY = {ReceiptState.UNCONFIRMED: 0, ReceiptState.PARTIAL: 1}


class RoutedResult(Protocol):
    """CA-2 ``RoutedOutcome``: ``rendered`` is exactly what ``render_hint`` got.

    ``rendered`` is typed ``object`` because the MCP adapter may not import
    ``JobRef`` (acyclic contract). It is only compared with the reserved jobs.
    """

    @property
    def result(self) -> Any: ...
    @property
    def rendered(self) -> tuple[object, ...]: ...


class RoutedAdapter(Protocol):
    async def adapt_routed(
        self, original: Any, *, execution: object, route: SessionRoute
    ) -> RoutedResult: ...


class _Suppress(Exception):
    pass


def _priority(
    lab: SessionLab, grant: VerifiedRunGrant, entry: AllocationEntry
) -> int | None:
    """Read-only receipt state: UNCONFIRMED 0, PARTIAL 1, else not eligible."""
    try:
        receipt = lab.receipts.query(grant, entry.snapshot)
    except Exception:  # noqa: BLE001 - injected port fails closed
        return None
    if not isinstance(receipt, Success) or receipt.value.job != entry.job:
        return None
    return _PRIORITY.get(receipt.value.state)


def _eligible(
    lab: SessionLab, key: KeyDigest, binding: KeyBinding, grant: VerifiedRunGrant
) -> list[JobRef]:
    with lab.ledger.read() as tx:
        pending = tx.pending_live(key.kd)
    ranked: list[tuple[int, str, JobRef]] = []
    for job, entry in binding.jobs.items():
        eligible = entry.terminal and job.canonical_key in pending
        priority = _priority(lab, grant, entry) if eligible else None
        if priority is not None:
            ranked.append((priority, job.canonical_key, job))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in ranked[:MAX_HINT_JOBS]]


def _reserve(
    lab: SessionLab, key: KeyDigest, jobs: list[JobRef], rid: str
) -> tuple[JobRef, ...]:
    reserved: list[JobRef] = []
    with lab.ledger.write("reserve") as tx:
        for job in jobs:
            if tx.transition(RESERVE, job, key.kd, rid) == 1:
                reserved.append(job)
            else:
                lab.event("ja_anomaly", key, rid=rid, reason="reserve_rowcount")
    return tuple(reserved)


def _valid(
    lab: SessionLab,
    tx: LabTx,
    key: KeyDigest,
    binding: KeyBinding,
    grant: VerifiedRunGrant,
    entries: dict[JobRef, AllocationEntry],
) -> bool:
    """Final validation; runs inside the commit transaction."""
    if (
        lab.table.get(key.kd) is not binding
        or binding.suspended
        or binding.grant is not grant
    ):
        return False
    for job, entry in entries.items():
        if binding.jobs.get(job) is not entry:
            return False
        if tx.serving(job, key.kd) != ("LIVE", key.epoch, "ACTIVE"):
            return False
        if (
            lab.authority.check(grant, job, _OBSERVE)
            is not AuthorityDecision.AUTHORIZED
        ):
            return False
    return True


def _abort(
    lab: SessionLab, key: KeyDigest, reserved: tuple[JobRef, ...], rid: str
) -> None:
    try:
        with lab.ledger.write("abort") as tx:
            for job in reserved:
                if tx.transition(ABORT, job, key.kd, rid) != 1:
                    lab.event("ja_anomaly", key, rid=rid, reason="abort_rowcount")
    except LabFailure:
        lab.event("ja_abort_unwritten", key, rid=rid, emit_state="RESERVED")
        return
    lab.event("ja_hint", key, rid=rid, emit_state="ABORTED", jobs=len(reserved))


async def _deliver(
    lab: SessionLab,
    key: KeyDigest,
    binding: KeyBinding,
    grant: VerifiedRunGrant,
    original: T,
    execution: object,
    adapter: RoutedAdapter,
    reserved: tuple[JobRef, ...],
    rid: str,
    checkpoint: Checkpoint,
) -> T:
    captured = {job: binding.jobs[job] for job in reserved}
    await checkpoint("after_reserve")
    routed = await adapter.adapt_routed(
        original, execution=execution, route=SessionRoute(key, grant, reserved)
    )
    result, rendered = routed.result, routed.rendered
    if (
        type(rendered) is not tuple
        or len(set(rendered)) != len(rendered)
        or not set(rendered) <= set(reserved)
        or (result is original) != (rendered == ())
    ):
        raise _Suppress
    await checkpoint("after_adapt")
    if rendered:
        with lab.ledger.read() as tx:
            if not _valid(lab, tx, key, binding, grant, captured):
                raise _Suppress
    await checkpoint("after_validation")
    await checkpoint("before_commit")
    with lab.ledger.write("commit") as tx:
        if rendered and not _valid(lab, tx, key, binding, grant, captured):
            raise _Suppress
        for job in reserved:
            sql = EMIT if job in rendered else RESET
            if tx.transition(sql, job, key.kd, rid) != 1:
                raise _Suppress
    state = "EMITTED" if rendered else "PENDING"
    lab.event("ja_hint", key, rid=rid, emit_state=state, jobs=len(rendered))
    return result if rendered else original


async def _no_checkpoint(point: str) -> None:
    return None


async def emit_hint(
    lab: SessionLab,
    outcome: RouteOutcome,
    original: T,
    *,
    execution: object,
    adapter: RoutedAdapter,
    checkpoint: Checkpoint | None = None,
) -> T:
    """Return a hinted result only after its jobs are committed EMITTED."""
    key = lab.keyed(outcome)
    if key is None or lab.table.get(key.kd) is None:
        return original
    async with lab.fences.hold(key.kd) as held:
        binding = lab.table.get(key.kd)
        if not held or binding is None or binding.suspended:
            return original
        grant = binding.grant
        if grant is None:
            return original
        try:
            chosen = _eligible(lab, key, binding, grant)
            rid = secrets.token_hex(16)
            reserved = _reserve(lab, key, chosen, rid) if chosen else ()
        except LabFailure:
            return original
        if not reserved:
            return original
        try:
            return await _deliver(
                lab,
                key,
                binding,
                grant,
                original,
                execution,
                adapter,
                reserved,
                rid,
                checkpoint or _no_checkpoint,
            )
        except BaseException as exc:
            _abort(lab, key, reserved, rid)
            if isinstance(exc, Exception):
                return original
            raise
