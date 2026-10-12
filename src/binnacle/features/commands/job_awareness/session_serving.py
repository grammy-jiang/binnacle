"""E2 lab serving: owner-scoped selectors, pages, echo, retire. LAB_ONLY.

Owner scope is a hard gate before any global lookup (A2-01): a selector is
resolved only inside the caller key's own in-memory allocations. A selector
that fails the gate reads no ledger, catalog, snapshot or grant state.
Foreign, missing, malformed, retired and route-failure selectors all return
the same ``DENIED``. Three disjoint grammars exist: the handle, the slot and
(g5 §9.2) the canonical key that the reminder prints; the canonical key is an
exact match inside the caller's own allocations. Serving then needs all three: lab ``alloc.state=LIVE`` in
the current epoch, an AUTHORIZED grant, and the unchanged in-memory entry.
"""

import re

from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    Scope,
    Success,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.session_binding import (
    AllocationEntry,
    KeyBinding,
    LabFailure,
)
from binnacle.features.commands.job_awareness.session_lab import (
    LabError,
    SessionLab,
)
from binnacle.features.commands.job_awareness.session_route import (
    KeyDigest,
    RouteOutcome,
)
from binnacle.features.commands.job_awareness.session_snapshot import (
    echo_matches,
    logical_page,
    valid_slot,
)

_HANDLE = re.compile(r"j_[0-9a-f]{12}")
_CANONICAL = re.compile(r"ja1_[0-9a-f]{32}:[0-9a-f]{12}:g1_[0-9a-f]{32}")
_CANONICAL_LENGTH = 85
_READ = frozenset({Scope.READ})
Owned = tuple[KeyDigest, KeyBinding, AllocationEntry]


def owned(lab: SessionLab, outcome: RouteOutcome, selector: object) -> Owned | LabError:
    """Resolve a handle, slot or canonical key within the caller key's
    allocations only."""
    key = lab.keyed(outcome)
    binding = None if key is None else lab.table.get(key.kd)
    if key is None or binding is None or binding.suspended or type(selector) is not str:
        return LabError.DENIED
    entries = tuple(binding.jobs.values())
    if len(selector) == 14 and _HANDLE.fullmatch(selector) is not None:
        matches = [entry for entry in entries if entry.handle == selector]
    elif (
        len(selector) == _CANONICAL_LENGTH
        and _CANONICAL.fullmatch(selector) is not None
    ):
        matches = [entry for entry in entries if entry.job.canonical_key == selector]
    elif valid_slot(selector):
        matches = [entry for entry in entries if entry.slot == selector]
        if len(matches) > 1:
            return LabError.AMBIGUOUS_SLOT
    else:
        return LabError.DENIED
    if len(matches) != 1:
        return LabError.DENIED
    return key, binding, matches[0]


def serving_grant(
    lab: SessionLab,
    key: KeyDigest,
    binding: KeyBinding,
    entry: AllocationEntry,
    scopes: frozenset[Scope],
) -> VerifiedRunGrant | None:
    """Three-way serving rule; any disagreement denies."""
    grant = binding.grant
    if (
        grant is None
        or binding.suspended
        or lab.table.get(key.kd) is not binding
        or binding.jobs.get(entry.job) is not entry
    ):
        return None
    try:
        with lab.ledger.read() as tx:
            row = tx.serving(entry.job, key.kd)
    except LabFailure:
        return None
    if row != ("LIVE", key.epoch, "ACTIVE"):
        return None
    if (
        lab.authority.check(grant, entry.job, scopes)
        is not AuthorityDecision.AUTHORIZED
    ):
        return None
    return grant


def _verified(
    lab: SessionLab, outcome: RouteOutcome, selector: object
) -> bytes | LabError:
    found = owned(lab, outcome, selector)
    if isinstance(found, LabError):
        return found
    key, binding, entry = found
    grant = serving_grant(lab, key, binding, entry, _READ)
    if grant is None:
        return LabError.DENIED
    lease = lab.snapshots.open_verified(grant, entry.snapshot)
    if not isinstance(lease, Success):
        return LabError.DENIED
    with lease.value as held:
        return bytes(held.verified_bytes)


def read_page(
    lab: SessionLab, outcome: RouteOutcome, selector: object, page: object
) -> dict[str, object] | LabError:
    """``fixture_read``: one logical page from one hash-verified lease."""
    data = _verified(lab, outcome, selector)
    if isinstance(data, LabError):
        return data
    result = logical_page(data, page)
    return LabError.DENIED if result is None else result


def echo(
    lab: SessionLab, outcome: RouteOutcome, selector: object, values: object
) -> dict[str, bool] | LabError:
    """``fixture_echo``: fixed ``{ok}`` or DENIED; never reflects arguments."""
    data = _verified(lab, outcome, selector)
    if isinstance(data, LabError):
        return data
    return {"ok": echo_matches(data, values)}


def suspend_unfenced(lab: SessionLab, key: KeyDigest) -> None:
    """SUSPEND body; production callers hold the key's fence."""
    binding = lab.table.get(key.kd)
    if binding is not None:
        binding.suspended = True
        if binding.grant is not None:
            lab.authority.revoke(binding.grant)
    try:
        with lab.ledger.write("suspend") as tx:
            if tx.key_row(key.kd) is not None:
                tx.suspend(key.kd)
    except LabFailure:
        lab.event("ja_suspend_unwritten", key)
    lab.event("ja_suspended", key)


def _replace_after_retire(lab: SessionLab, key: KeyDigest, binding: KeyBinding) -> None:
    """Revoke-first replacement over the remaining live allocations."""
    try:
        lab.revoke_current(binding)
        remaining = tuple(binding.jobs)
        if not remaining:
            binding.capability = binding.grant = None
            return
        credential, principal = lab.principal(key)
        capability, grant_id = lab.issue(principal, remaining)
        grant = lab.verify(credential, capability, remaining)
        with lab.ledger.write("regrant") as tx:
            tx.regrant_live(key.kd, grant_id)
        binding.capability, binding.grant = capability, grant
    except Exception:  # noqa: BLE001 - replacement failure suspends the key
        suspend_unfenced(lab, key)


def _retire_entries(
    lab: SessionLab,
    key: KeyDigest,
    binding: KeyBinding,
    entries: tuple[AllocationEntry, ...],
) -> int:
    """Routes first, then lab RETIRED, then one grant revoke/replacement."""
    for entry in entries:
        binding.jobs.pop(entry.job, None)
    try:
        with lab.ledger.write("retire") as tx:
            for entry in entries:
                tx.retire(entry.job, key.kd)
    except LabFailure:
        suspend_unfenced(lab, key)
        return 0
    lab.hook("retire:lab")
    _replace_after_retire(lab, key, binding)
    lab.event("ja_retired", key, retired=len(entries), live=len(binding.jobs))
    return len(entries)


def retire_unfenced(lab: SessionLab, key: KeyDigest, handle: str) -> bool:
    """RETIRE body: alloc RETIRED + grant revoke (and replacement).

    Production callers hold the key's fence. Tests call this directly only to
    model a retire that bypasses the fence.
    """
    binding = lab.table.get(key.kd)
    entries = () if binding is None else tuple(binding.jobs.values())
    entry = next((e for e in entries if e.handle == handle), None)
    if binding is None or entry is None:
        return False
    return _retire_entries(lab, key, binding, (entry,)) == 1


async def retire(lab: SessionLab, key: KeyDigest, handle: str) -> bool:
    async with lab.fences.hold(key.kd) as held:
        return held and retire_unfenced(lab, key, handle)


async def close(lab: SessionLab, key: KeyDigest) -> int:
    """Arm or sub-phase close: retire every live allocation of the key."""
    async with lab.fences.hold(key.kd) as held:
        binding = lab.table.get(key.kd)
        if not held or binding is None:
            return 0
        entries = tuple(binding.jobs.values())
        return _retire_entries(lab, key, binding, entries) if entries else 0


async def seal(lab: SessionLab, key: KeyDigest, handle: str) -> bool:
    """Controller terminal point: one LIVE entry of the key becomes hint-eligible.

    Held under the key's fence like every other state change. Only a
    ``deferred_seal`` allocation that is not terminal yet changes.
    """
    async with lab.fences.hold(key.kd) as held:
        binding = lab.table.get(key.kd)
        if not held or binding is None or binding.suspended:
            return False
        entry = next((e for e in binding.jobs.values() if e.handle == handle), None)
        if entry is None or entry.terminal:
            return False
        entry.terminal = True
    lab.event("ja_sealed", key)
    return True


async def suspend(lab: SessionLab, key: KeyDigest) -> bool:
    async with lab.fences.hold(key.kd) as held:
        if held:
            suspend_unfenced(lab, key)
        return held
