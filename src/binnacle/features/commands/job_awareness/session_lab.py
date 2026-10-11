"""E2 lab controller: cold start, binding and the allocation protocol. LAB_ONLY.

Allocation protocol (design §2.5): each step is durable before the next, and
the per-key fence is held for the whole sequence. (1) lab tx: key row + alloc
OWNED, so the owner record is durable first; (2) ReceiptStore: seal the
snapshot, revoke the key's grant, issue the replacement grant (own
transactions); (3) lab tx: GRANTED + emit PENDING; (4) verify credential,
coverage and snapshot hash; (5) publish the in-memory route, then lab tx LIVE.
Any failure drops the route, writes DENY_FOREVER and returns DENIED. A failure
after the old grant was revoked also suspends the key. Nothing here is wired
into production composition; the feature stays default off.
"""

import hashlib
import hmac
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TypeVar

from binnacle.features.commands.job_awareness.grants import (
    SyntheticAuthority,
    TrustedClock,
)
from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    Failure,
    JobRef,
    Observation,
    ObservationState,
    Result,
    Scope,
    Success,
    VerifiedPrincipal,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.ports import ReceiptQueryPort
from binnacle.features.commands.job_awareness.receipt_schema import Limits
from binnacle.features.commands.job_awareness.session_binding import (
    AllocationEntry,
    KeyBinding,
    LabFailure,
    LabLedger,
    SessionBindingTable,
    prepare_layout,
)
from binnacle.features.commands.job_awareness.session_fence import FenceSet
from binnacle.features.commands.job_awareness.session_route import (
    ISSUER_SESSION_V1,
    KeyDigest,
    RouteOutcome,
    RouteStatus,
    SessionKeyer,
)
from binnacle.features.commands.job_awareness.session_snapshot import (
    AllocationSnapshot,
    FrozenTemplate,
    MemoryPayload,
    build_snapshot,
    output_snapshot,
    valid_slot,
)
from binnacle.features.commands.job_awareness.snapshots import (
    SnapshotMemory,
    SnapshotStore,
    TrustedCatalog,
)

CONSENT_VERSION = "lab-session-route-v1"
LAB_SCOPES = frozenset({Scope.OBSERVE, Scope.READ})
Events = Callable[[dict[str, object]], None]
T = TypeVar("T")


class LabError(str, Enum):
    """Uniform lab errors. KEY_FULL/AMBIGUOUS_SLOT are own-scope only."""

    DENIED = "DENIED"
    KEY_FULL = "KEY_FULL"
    AMBIGUOUS_SLOT = "AMBIGUOUS_SLOT"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"


@dataclass(frozen=True)
class LabConfig:
    """Explicit grant TTL (ADV-G4-01): TC phases pass 3600000, A/B 1800000."""

    ttl_ms: int = 1800000
    max_live_per_key: int = 8
    max_per_key: int = 40
    max_per_phase: int = 120
    fence_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if not 1 <= self.ttl_ms <= 3600000 or not 1 <= self.max_live_per_key <= 8:
            raise ValueError("Invalid lab config")


class Deny(Exception):
    """Internal fail-closed signal; ``suspend`` after a revoked grant."""

    def __init__(self, suspend: bool = False) -> None:
        super().__init__("denied")
        self.suspend = suspend


def value(result: Result[T]) -> T:
    if isinstance(result, Success):
        return result.value
    raise Deny()


class SessionLab:
    """Lab-only composition of ReceiptStore v1, the lab ledger and the table.

    ``faults`` is a test seam: called after each committed step with a point
    name, and inside each lab write (``lab:<op>``) before commit. ``events``
    receives digest-only records (``ja_key`` is the 16-hex export prefix).
    """

    def __init__(
        self,
        phase_dir: Path,
        templates: Mapping[str, FrozenTemplate],
        clock: TrustedClock,
        *,
        config: LabConfig | None = None,
        limits: Limits | None = None,
        receipts: ReceiptQueryPort | None = None,
        faults: Callable[[str], None] | None = None,
        events: Events | None = None,
    ) -> None:
        if any(slot != t.slot for slot, t in templates.items()):
            raise ValueError("Invalid lab templates")
        self._phase, self._templates = Path(phase_dir), dict(templates)
        self.clock, self.config = clock, config or LabConfig()
        self._limits, self._receipts, self._fault = limits, receipts, faults
        self._events = events
        self.table = SessionBindingTable()
        self.fences = FenceSet(self.config.fence_timeout_s)
        self._principals: dict[str, tuple[bytes, VerifiedPrincipal]] = {}
        self._authority: SyntheticAuthority | None = None
        self._ledger: LabLedger | None = None
        self._snapshots: SnapshotStore | None = None
        self._keyer: SessionKeyer | None = None
        self.ready = False

    @property
    def authority(self) -> SyntheticAuthority:
        if self._authority is None:
            raise LabFailure()
        return self._authority

    @property
    def ledger(self) -> LabLedger:
        if self._ledger is None:
            raise LabFailure()
        return self._ledger

    @property
    def snapshots(self) -> SnapshotStore:
        if self._snapshots is None:
            raise LabFailure()
        return self._snapshots

    @property
    def keyer(self) -> SessionKeyer:
        if self._keyer is None:
            raise LabFailure()
        return self._keyer

    @property
    def receipts(self) -> ReceiptQueryPort:
        return self._receipts or self.authority.store

    def hook(self, point: str) -> None:
        if self._fault is not None:
            self._fault(point)

    def event(self, name: str, key: KeyDigest | None, **fields: object) -> None:
        if self._events is not None:
            record: dict[str, object] = {"event": name}
            record["ja_key"] = None if key is None else key.log_key
            record.update(fields)
            self._events(record)

    def start(self) -> bool:
        """Cold start before readiness; refuse layout, SQLite or sweep failure."""
        if self._authority is not None:
            return False
        try:
            receipt_path, lab_path = prepare_layout(self._phase)
        except (LabFailure, OSError):
            return False
        authority = SyntheticAuthority(
            receipt_path, ISSUER_SESSION_V1, self.clock, limits=self._limits
        )
        self._authority = authority
        if isinstance(authority.start(), Failure) or authority.epoch is None:
            return False
        # K_e is made in the same step as the issuer-epoch rotation, and the
        # rotation already REVOKED every grant of an older epoch.
        keyer = SessionKeyer(authority.epoch)
        ledger = LabLedger(lab_path, self.clock.now, fault=self._lab_fault)
        try:
            ledger.initialize()
            with ledger.write("sweep") as tx:
                tx.sweep(keyer.epoch)
        except LabFailure:
            return False
        self._keyer, self._ledger = keyer, ledger
        self._snapshots = SnapshotStore(
            authority, TrustedCatalog(), self.clock.now, memory=SnapshotMemory()
        )
        self.ready = True
        return True

    def _lab_fault(self, op: str) -> None:
        self.hook("lab:" + op)

    def keyed(self, outcome: RouteOutcome) -> KeyDigest | None:
        """Key of a well-formed outcome in the current epoch, else None."""
        if (
            not self.ready
            or type(outcome) is not RouteOutcome
            or outcome.status not in (RouteStatus.UNBOUND, RouteStatus.BOUND)
            or outcome.key is None
            or outcome.key.epoch != self.keyer.epoch
        ):
            return None
        return outcome.key

    def bind(self, outcome: RouteOutcome) -> RouteOutcome:
        key = self.keyed(outcome)
        binding = None if key is None else self.table.get(key.kd)
        if binding is None:
            return outcome
        status = RouteStatus.SUSPENDED if binding.suspended else RouteStatus.BOUND
        return outcome.with_status(status)

    async def start_fixture(
        self, outcome: RouteOutcome, slot: object
    ) -> str | LabError:
        """``fixture_start``: a new JobRef in the caller key's namespace."""
        key = self.keyed(outcome)
        if key is None or not valid_slot(slot) or slot not in self._templates:
            return LabError.DENIED
        async with self.fences.hold(key.kd) as held:
            if not held:
                return LabError.DENIED
            return self._allocate(key, self._templates[slot])

    def _owner_record(self, key: KeyDigest, slot: str, tag: str) -> JobRef | LabError:
        """Step 1: the owner record is durable before any grant exists."""
        binding = self.table.get(key.kd)
        refusal: LabError | None = None
        job: JobRef | None = None
        with self.ledger.write("owner") as tx:
            row = tx.key_row(key.kd)
            total, live, phase = tx.counts(key.kd)
            if (binding is not None and binding.suspended) or (
                row is not None and row[2] != "ACTIVE"
            ):
                refusal = LabError.DENIED
            elif live >= self.config.max_live_per_key:
                refusal = LabError.KEY_FULL
            elif total >= self.config.max_per_key or phase >= self.config.max_per_phase:
                refusal = LabError.QUOTA_EXCEEDED
            else:
                ns = tx.ensure_key(key)
                used = {job.job_id for job in binding.jobs} if binding else set()
                job_id = secrets.token_hex(6)
                while job_id in used:  # pragma: no cover - 48-bit collision
                    job_id = secrets.token_hex(6)
                job = JobRef(ns, job_id, "g1_" + secrets.token_hex(16))
                tx.insert_alloc(job, key.kd, slot, tag)
        if job is None:
            refusal = refusal or LabError.DENIED
            self.event("ja_refused", key, error=refusal.value)
            return refusal
        return job

    def _allocate(self, key: KeyDigest, template: FrozenTemplate) -> str | LabError:
        allocation = build_snapshot(template)
        if allocation is None:
            return LabError.DENIED
        try:
            owned = self._owner_record(key, template.slot, allocation.alloc_tag)
        except Exception:  # noqa: BLE001 - nothing durable yet: plain denial
            return LabError.DENIED
        if isinstance(owned, LabError):
            return owned
        try:
            return self._grant_and_publish(key, owned, allocation)
        except Deny as deny:
            return self.fail_allocation(key, owned, suspend=deny.suspend)
        except Exception:  # noqa: BLE001 - unknown failure: fail closed, suspend
            return self.fail_allocation(key, owned, suspend=True)

    def principal(self, key: KeyDigest) -> tuple[bytes, VerifiedPrincipal]:
        cached = self._principals.get(key.kd)
        if cached is None:
            credential = value(self.authority.register_principal(key.principal()))
            principal = value(self.authority.verify_principal(credential))
            cached = self._principals[key.kd] = (credential, principal)
        return cached

    def _seal(self, job: JobRef, allocation: AllocationSnapshot) -> Observation:
        snapshot = output_snapshot(job, allocation, self.clock.now())
        value(
            self.authority.store.controller_transaction(
                lambda tx: tx.register_snapshot(snapshot, allocation.data)
            )
        )
        observation = Observation(
            job, ObservationState.TERMINAL, snapshot.terminal, snapshot
        )
        payload = MemoryPayload(allocation.data)
        value(self.snapshots.catalog.register(observation, payload))
        return observation

    def _grant_and_publish(
        self, key: KeyDigest, job: JobRef, allocation: AllocationSnapshot
    ) -> str:
        try:
            self.hook("alloc:1")
            snapshot = self._seal(job, allocation).snapshot
            if snapshot is None:  # pragma: no cover - _seal always builds one
                raise Deny()
            self.hook("alloc:2:seal")
            binding = self.table.get(key.kd)
            credential, principal = self.principal(key)
        except Exception:  # noqa: BLE001 - before any revoke: deny this job only
            raise Deny() from None
        revoked = self.revoke_current(binding)
        if revoked:
            self.hook("alloc:2:revoke")
        live = tuple(binding.jobs) if binding is not None else ()
        try:
            capability, grant_id = self.issue(principal, (*live, job))
            self.hook("alloc:2:issue")
            with self.ledger.write("granted") as tx:
                tx.mark_granted(job, key.kd, snapshot.sha256, grant_id)
            self.hook("alloc:3")
            grant = self.verify(credential, capability, (*live, job))
            lease = value(self.snapshots.open_verified(grant, snapshot))
            with lease as held:
                digest = hashlib.sha256(held.verified_bytes).hexdigest()
            if not hmac.compare_digest(digest, allocation.sha256):
                raise Deny()
            self.hook("alloc:4")
        except Exception:  # noqa: BLE001 - any step 2-4 failure denies
            raise Deny(suspend=revoked) from None
        if binding is None:
            binding = KeyBinding(key, job.run_namespace, credential, principal)
            self.table.add(binding)
        entry = AllocationEntry(job, allocation.slot, snapshot)
        binding.capability, binding.grant = capability, grant
        binding.jobs[job] = entry
        self.hook("alloc:5:publish")
        try:
            with self.ledger.write("live") as tx:
                tx.mark_live(job, key.kd)
        except LabFailure:
            raise Deny() from None
        self.hook("alloc:5:live")
        self.event("ja_alloc", key, slot=allocation.slot, live=len(binding.jobs))
        return entry.handle

    def grant_remaining_ms(self, key: KeyDigest) -> int | None:
        """``grant_remaining_ms`` log field (ADV-G4-01); None without a grant."""
        binding = self.table.get(key.kd)
        if binding is None or binding.capability is None:
            return None
        digest = hashlib.sha256(binding.capability).hexdigest()
        try:
            record = value(
                self.authority.store.read_transaction(
                    lambda tx: tx.grant_for_capability(digest)
                )
            )
            now = self.clock.now()
        except Exception:  # noqa: BLE001 - a log field never fails a call
            return None
        return None if record is None else max(0, record.claims.expires_at_ms - now)

    def revoke_current(self, binding: KeyBinding | None) -> bool:
        """Revoke-first replacement. A revoke failure suspends the key."""
        if binding is None or binding.grant is None:
            return False
        if isinstance(self.authority.revoke(binding.grant), Failure):
            raise Deny(suspend=True)
        return True

    def issue(
        self, principal: VerifiedPrincipal, jobs: tuple[JobRef, ...]
    ) -> tuple[bytes, str]:
        capability = value(
            self.authority.issue_grant(
                principal,
                jobs,
                LAB_SCOPES,
                ttl_ms=self.config.ttl_ms,
                consent_version=CONSENT_VERSION,
            )
        )
        digest = hashlib.sha256(capability).hexdigest()
        record = value(
            self.authority.store.read_transaction(
                lambda tx: tx.grant_for_capability(digest)
            )
        )
        if record is None:
            raise Deny()
        return capability, record.claims.grant_id

    def verify(
        self, credential: bytes, capability: bytes, jobs: tuple[JobRef, ...]
    ) -> VerifiedRunGrant:
        grant = value(self.authority.verify(credential, capability, Scope.OBSERVE))
        for job in jobs:
            decision = self.authority.check(grant, job, LAB_SCOPES)
            if decision is not AuthorityDecision.AUTHORIZED:
                raise Deny()
        return grant

    def fail_allocation(
        self, key: KeyDigest, job: JobRef, *, suspend: bool
    ) -> LabError:
        """Drop the route, then DENY_FOREVER (and SUSPENDED) when writable."""
        binding = self.table.get(key.kd)
        if binding is not None:
            binding.jobs.pop(job, None)
            binding.suspended = binding.suspended or suspend
        try:
            with self.ledger.write("deny") as tx:
                tx.deny(job, key.kd)
                if suspend and tx.key_row(key.kd) is not None:
                    tx.suspend(key.kd)
        except LabFailure:
            self.event("ja_deny_unwritten", key)
        self.event("ja_alloc_denied", key, suspended=suspend)
        return LabError.DENIED
