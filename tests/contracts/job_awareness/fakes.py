"""Trusted synthetic fixture registries. No credentials, jobs or durable store.

Fixture controllers alone call issue/register/rotate methods. These are not
public verification APIs. Deterministic IDs are test data, never capabilities.
Object identity lookup, not authority_handle or class membership, admits calls.
"""

from dataclasses import dataclass, replace

from binnacle.features.commands.job_awareness.identifiers import (
    job_ref_from_wire,
    job_ref_to_wire,
)
from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    BoundaryError,
    ConsumerReceipt,
    ErrorCode,
    Failure,
    JobRef,
    OutputSnapshot,
    PrincipalClaims,
    ReceiptQueryResult,
    ReceiptState,
    RunGrantClaims,
    Scope,
    Success,
    VerifiedPrincipal,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.ports import HandleAuthorityPort


class _Principal(VerifiedPrincipal):
    @property
    def authority_handle(self) -> object:
        return self


class _Grant(VerifiedRunGrant):
    @property
    def authority_handle(self) -> object:
        return self


@dataclass(frozen=True)
class _Entry:
    handle: VerifiedRunGrant
    principal: VerifiedPrincipal
    claims: RunGrantClaims


class FakeHandleAuthority:
    """Single-threaded trusted state for testing the shared authority contract.

    No backend/catalog exists in this fake. Epoch and grant IDs never repeat in
    this instance. Revocation precedes expiry. Unsafe clocks and missing storage
    deny even known handles. No durable or hostile-process guarantee is claimed.
    """

    def __init__(self) -> None:
        self.now_ms = 1000
        self.available = True
        self.clock_safe = True
        self.check_calls = 0
        self._high_water = self.now_ms
        self._epoch = 1
        self._sequence = 0
        self._entries: dict[int, _Entry] = {}
        self._principals: dict[int, tuple[VerifiedPrincipal, PrincipalClaims]] = {}
        self._revoked: set[tuple[str, str]] = set()
        self._generations: set[tuple[str, str]] = set()

    def issue(
        self,
        jobs: tuple[JobRef, ...],
        *,
        scopes: frozenset[Scope] = frozenset(Scope),
        ttl_ms: int = 3600000,
    ) -> VerifiedRunGrant:
        """Trusted fixture enrollment only, with a new principal and generation."""
        self._sequence += 1
        principal = _Principal()
        claims = RunGrantClaims(
            PrincipalClaims("1" * 32, "2" * 32, f"{self._sequence:032x}", "4" * 32),
            f"{self._epoch:032x}",
            f"{self._sequence:032x}",
            jobs[0].run_namespace if jobs else "ja1_" + "0" * 32,
            jobs,
            scopes,
            self.now_ms,
            self.now_ms + ttl_ms,
            1,
        )
        return self._register(principal, claims)

    def _register(
        self, principal: VerifiedPrincipal, claims: RunGrantClaims
    ) -> VerifiedRunGrant:
        generation = (claims.issuer_epoch, claims.grant_id)
        if generation in self._generations:
            raise ValueError("Generation reuse")
        grant = _Grant()
        self._generations.add(generation)
        self._principals[id(principal)] = (principal, claims.principal)
        self._entries[id(grant)] = _Entry(grant, principal, claims)
        return grant

    def claims(self, grant: VerifiedRunGrant) -> RunGrantClaims:
        return self._entries[id(grant)].claims

    def principal(self, grant: VerifiedRunGrant) -> VerifiedPrincipal:
        return self._entries[id(grant)].principal

    def revoke(self, grant: VerifiedRunGrant) -> None:
        claims = self.claims(grant)
        self._revoked.add((claims.issuer_epoch, claims.grant_id))

    def retire_principal(self, grant: VerifiedRunGrant) -> None:
        del self._principals[id(self.principal(grant))]

    def rotate_epoch(self) -> None:
        self._epoch += 1

    def reissue(self, grant: VerifiedRunGrant) -> VerifiedRunGrant:
        self.revoke(grant)
        self._sequence += 1
        claims = replace(
            self.claims(grant),
            issuer_epoch=f"{self._epoch:032x}",
            grant_id=f"{self._sequence:032x}",
            issued_at_ms=self.now_ms,
            expires_at_ms=self.now_ms + 3600000,
        )
        return self._register(self.principal(grant), claims)

    def check(
        self, grant: VerifiedRunGrant, job: JobRef, required_scopes: frozenset[Scope]
    ) -> AuthorityDecision:
        self.check_calls += 1
        if (
            not self.available
            or not self.clock_safe
            or type(self.now_ms) is not int
            or self.now_ms < self._high_water
        ):
            return AuthorityDecision.DENIED
        self._high_water = self.now_ms
        if (
            type(required_scopes) is not frozenset
            or not required_scopes
            or not all(type(s) is Scope for s in required_scopes)
        ):
            return AuthorityDecision.DENIED
        if type(job) is not JobRef:
            return AuthorityDecision.DENIED
        try:
            job_ref_from_wire(job_ref_to_wire(job))
        except (AttributeError, ValueError):
            return AuthorityDecision.DENIED
        entry = self._entries.get(id(grant))
        if entry is None or entry.handle is not grant:
            return AuthorityDecision.DENIED
        bound = self._principals.get(id(entry.principal))
        if (
            bound is None
            or bound[0] is not entry.principal
            or bound[1] != entry.claims.principal
        ):
            return AuthorityDecision.DENIED
        claims = entry.claims
        generation = (claims.issuer_epoch, claims.grant_id)
        if (
            claims.issuer_epoch != f"{self._epoch:032x}"
            or generation in self._revoked
            or generation not in self._generations
        ):
            return AuthorityDecision.REVOKED
        if self.now_ms >= claims.expires_at_ms:
            return AuthorityDecision.EXPIRED
        if not required_scopes <= claims.scopes or job not in claims.jobs:
            return AuthorityDecision.DENIED
        return AuthorityDecision.AUTHORIZED


class FakeReceiptQuery:
    """Read-only exact records injected by a test controller; no implicit ACK."""

    def __init__(
        self,
        authority: HandleAuthorityPort,
        *,
        clock: FakeHandleAuthority | None = None,
    ) -> None:
        self.authority = authority
        # A separate trusted clock can be supplied when wrapping the authority.
        self.clock = (
            clock
            if clock is not None
            else authority
            if isinstance(authority, FakeHandleAuthority)
            else None
        )
        self._records: list[
            tuple[VerifiedRunGrant, OutputSnapshot, ConsumerReceipt]
        ] = []

    @property
    def records(
        self,
    ) -> tuple[tuple[VerifiedRunGrant, OutputSnapshot, ConsumerReceipt], ...]:
        return tuple(self._records)

    def register(
        self,
        grant: VerifiedRunGrant,
        snapshot: OutputSnapshot,
        receipt: ConsumerReceipt,
    ) -> None:
        if receipt.job != snapshot.job or receipt.snapshot_sha256 != snapshot.sha256:
            raise ValueError("Snapshot binding mismatch")
        self._records.append((grant, snapshot, receipt))

    def query(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot
    ) -> ReceiptQueryResult:
        if (
            self.authority.check(grant, snapshot.job, frozenset({Scope.OBSERVE}))
            is not AuthorityDecision.AUTHORIZED
        ):
            return Failure(BoundaryError(ErrorCode.DENIED))
        if self.clock is None:
            return Failure(BoundaryError(ErrorCode.CLOCK_UNSAFE))
        for handle, registered, receipt in self._records:
            if handle is grant and registered == snapshot:
                if self.clock.now_ms >= snapshot.retained_until_ms:
                    return Success(replace(receipt, state=ReceiptState.OUTPUT_EXPIRED))
                return Success(receipt)
        return Failure(BoundaryError(ErrorCode.SOURCE_UNAVAILABLE))
