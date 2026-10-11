"""Trusted synthetic controller authority. No public tools or real chat identity.

Controller methods enroll explicit lab principals and jobs only. Credentials and
capabilities are independent 256-bit secrets. Handles require exact registered
object identity on every use. Copying both secrets transfers user/run authority;
this does not establish chat isolation. Local controller code and storage are
trusted. A cold controller must commit a new epoch before admitting any action.
"""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, RLock

from binnacle.features.commands.job_awareness.identifiers import (
    bounded_int,
    canonical_hex,
)
from binnacle.features.commands.job_awareness.models import (
    MAX_INTEGER,
    AuthorityDecision,
    BoundaryError,
    ErrorCode,
    Failure,
    GrantVerificationResult,
    JobRef,
    PrincipalClaims,
    Result,
    RunGrantClaims,
    Scope,
    Success,
    VerifiedPrincipal,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.receipt_schema import Limits
from binnacle.features.commands.job_awareness.receipt_store import (
    AuthorityReader,
    GrantRecord,
    ReceiptStore,
    ReceiptTransaction,
    StoreFailure,
)

DENIED = Failure(BoundaryError(ErrorCode.DENIED))


class TrustedClock:
    """Latched fail-closed UTC plus monotonic duration; no caller timestamps.

    Reads advance the controller's in-memory high-water, while write transactions
    advance the ledger's durable high-water. Backward UTC/monotonic samples or a
    failed source permanently disable this controller. Restart needs a new epoch.
    Frozen UTC cannot extend a grant because monotonic elapsed time also counts.
    """

    def __init__(self, wall_ms: Callable[[], int], monotonic_ns: Callable[[], int]):
        self._wall, self._mono = wall_ms, monotonic_ns
        self._lock = Lock()
        self._last: tuple[int, int, int] | None = None
        self._anchor: tuple[int, int] | None = None
        self._unsafe = False

    def now(self) -> int:
        with self._lock:
            try:
                if self._unsafe:
                    raise ValueError("Unsafe clock")
                wall = bounded_int(self._wall(), 0, MAX_INTEGER)
                mono = bounded_int(self._mono(), 0, MAX_INTEGER * 1000000)
                if self._last and (wall < self._last[0] or mono < self._last[1]):
                    raise ValueError("Unsafe clock")
                if self._anchor is None:
                    self._anchor = wall, mono
                projected = self._anchor[0] + (mono - self._anchor[1]) // 1000000
                # A forward UTC jump must move the monotonic anchor too, or
                # frozen UTC after that jump could extend a newly issued TTL.
                if wall > projected:
                    self._anchor = wall, mono
                effective = max(wall, projected)
                effective = bounded_int(effective, 0, MAX_INTEGER)
                self._last = wall, mono, effective
                return effective
            except Exception:  # noqa: BLE001 - a failed trusted source disables authority
                self._unsafe = True
                raise StoreFailure(ErrorCode.CLOCK_UNSAFE) from None


class _PrincipalHandle(VerifiedPrincipal):
    @property
    def authority_handle(self) -> object:
        return self


class _GrantHandle(VerifiedRunGrant):
    @property
    def authority_handle(self) -> object:
        return self


@dataclass(frozen=True)
class _PrincipalBinding:
    handle: VerifiedPrincipal
    claims: PrincipalClaims
    credential_sha256: str


@dataclass(frozen=True)
class _GrantBinding:
    handle: VerifiedRunGrant
    record: GrantRecord
    principal: _PrincipalBinding


def _secret_digest(secret: bytes) -> str | None:
    if type(secret) is not bytes or len(secret) != 32:
        return None
    return hashlib.sha256(secret).hexdigest()


class SyntheticAuthority:
    """Durable HandleAuthorityPort and synthetic GrantVerifierPort adapter.

    Constructing this object admits nothing. start() is a controller cold start,
    not a ledger-worker restart. Share this authority with workers; never rebuild
    identity from serialized handle fields or an untrusted chat/session label.
    All registry populations are bounded by the ledger's grant ceiling (128).
    """

    def __init__(
        self,
        path: Path,
        issuer_id: str,
        clock: TrustedClock,
        *,
        limits: Limits | None = None,
    ):
        self._issuer = canonical_hex(issuer_id, 32)
        self.clock = clock
        self._epoch: str | None = None
        self._started = False
        self._lock = RLock()
        self._principals: dict[str, _PrincipalBinding] = {}
        self._grants: dict[int, _GrantBinding] = {}
        self._capacity = (limits or Limits()).grants
        self.store = ReceiptStore(
            path, clock=clock.now, resolve=self.resolve, limits=limits
        )

    @property
    def epoch(self) -> str | None:
        """Committed controller epoch; None before a successful cold start."""
        return self._epoch

    def start(self) -> Result[None]:
        """Commit a never-reused random epoch before publishing readiness."""
        with self._lock:
            if self._started:
                return DENIED
            self._started = True
        initialized = self.store.initialize()
        if isinstance(initialized, Failure):
            return initialized
        epoch = secrets.token_hex(16)
        result = self.store.controller_transaction(
            lambda tx: tx.rotate_epoch(self._issuer, epoch)
        )
        if isinstance(result, Success):
            self._epoch = epoch
        return result

    def register_principal(self, claims: PrincipalClaims) -> Result[bytes]:
        """Trusted controller enrollment; never called with client identity claims."""
        if (
            self._epoch is None
            or type(claims) is not PrincipalClaims
            or claims.issuer_id != self._issuer
        ):
            return DENIED
        with self._lock:
            if len(self._principals) >= self._capacity:
                return Failure(BoundaryError(ErrorCode.QUOTA_EXCEEDED))
            if any(binding.claims == claims for binding in self._principals.values()):
                return DENIED
            credential = secrets.token_bytes(32)
            digest = hashlib.sha256(credential).hexdigest()
            if digest in self._principals:
                return DENIED
            self._principals[digest] = _PrincipalBinding(
                _PrincipalHandle(), claims, digest
            )
            return Success(credential)

    def verify_principal(self, credential: bytes) -> Result[VerifiedPrincipal]:
        digest = _secret_digest(credential)
        with self._lock:
            binding = self._principals.get(digest) if digest else None
        if self._epoch is None or binding is None:
            return DENIED
        return Success(binding.handle)

    def issue_grant(
        self,
        principal: VerifiedPrincipal,
        jobs: tuple[JobRef, ...],
        scopes: frozenset[Scope],
        *,
        ttl_ms: int = 3600000,
        consent_version: str = "lab-user-run-v1",
    ) -> Result[bytes]:
        """Controller-only explicit run consent; generation never updated in place.

        ``consent_version`` must be allowlisted (CA-1); the E2 lab session route
        passes ``lab-session-route-v1``. Unknown versions deny.
        """
        with self._lock:
            binding = next(
                (p for p in self._principals.values() if p.handle is principal), None
            )
        if binding is None or self._epoch is None:
            return DENIED
        if (
            type(jobs) is not tuple
            or not 1 <= len(jobs) <= 100
            or any(type(job) is not JobRef for job in jobs)
        ):
            return DENIED
        try:
            bounded_int(ttl_ms, 1, 3600000)
            now = self.clock.now()
            claims = RunGrantClaims(
                binding.claims,
                self._epoch,
                secrets.token_hex(16),
                jobs[0].run_namespace,
                jobs,
                scopes,
                now,
                now + ttl_ms,
                1,
                consent_version,
            )
        except (ValueError, StoreFailure):
            return DENIED
        capability = secrets.token_bytes(32)
        digest = hashlib.sha256(capability).hexdigest()
        # Independent secrets, even under a broken/injected randomness source.
        if hmac.compare_digest(digest, binding.credential_sha256):
            return DENIED
        result = self.store.controller_transaction(
            lambda tx: tx.register_grant(claims, digest, binding.credential_sha256)
        )
        return result if isinstance(result, Failure) else Success(capability)

    def _registered(
        self, reader: AuthorityReader, handle: VerifiedRunGrant
    ) -> GrantRecord | None:
        with self._lock:
            binding = self._grants.get(id(handle))
            if binding is None or binding.handle is not handle:
                return None
            principal = self._principals.get(binding.principal.credential_sha256)
        if principal is not binding.principal:
            return None
        expected = binding.record
        claims = expected.claims
        record = reader.grant(
            claims.principal.issuer_id, claims.issuer_epoch, claims.grant_id
        )
        if (
            record is None
            or record.claims != claims
            or record.claims.principal != principal.claims
            or not hmac.compare_digest(
                record.capability_sha256, expected.capability_sha256
            )
            or not hmac.compare_digest(
                record.credential_sha256, principal.credential_sha256
            )
        ):
            return None
        return record

    def _state(self, reader: AuthorityReader, record: GrantRecord) -> AuthorityDecision:
        claims = record.claims
        now = max(reader.now_ms, self.clock.now())
        if self._epoch is None:
            return AuthorityDecision.DENIED
        if (
            record.revoked
            or claims.issuer_epoch != self._epoch
            or reader.current_epoch(self._issuer) != claims.issuer_epoch
        ):
            return AuthorityDecision.REVOKED
        if now >= claims.expires_at_ms:
            return AuthorityDecision.EXPIRED
        if now < claims.issued_at_ms:
            return AuthorityDecision.DENIED
        return AuthorityDecision.AUTHORIZED

    def resolve(
        self, reader: AuthorityReader, grant: VerifiedRunGrant
    ) -> RunGrantClaims | None:
        """ReceiptStore resolver: identity and durable authority in its transaction."""
        record = self._registered(reader, grant)
        if (
            record is not None
            and self._state(reader, record) is AuthorityDecision.AUTHORIZED
        ):
            return record.claims
        return None

    def verify(
        self, principal_credential: bytes, capability: bytes, required_scope: Scope
    ) -> GrantVerificationResult:
        credential_digest, capability_digest = (
            _secret_digest(principal_credential),
            _secret_digest(capability),
        )
        if (
            self._epoch is None
            or type(required_scope) is not Scope
            or credential_digest is None
            or capability_digest is None
        ):
            return DENIED
        with self._lock:
            principal = self._principals.get(credential_digest)
        if principal is None or hmac.compare_digest(
            credential_digest, capability_digest
        ):
            return DENIED

        def verify_tx(tx: ReceiptTransaction) -> GrantRecord:
            record = tx.grant_for_capability(capability_digest)
            if (
                record is None
                or record.claims.principal != principal.claims
                or not hmac.compare_digest(record.credential_sha256, credential_digest)
                or not hmac.compare_digest(record.capability_sha256, capability_digest)
                or required_scope not in record.claims.scopes
                or self._state(tx, record) is not AuthorityDecision.AUTHORIZED
            ):
                raise StoreFailure(ErrorCode.DENIED)
            return record

        result = self.store.read_transaction(verify_tx)
        if isinstance(result, Failure):
            return DENIED
        with self._lock:
            for binding in self._grants.values():
                if binding.record.claims == result.value.claims:
                    return Success(binding.handle)
            if len(self._grants) >= self._capacity:
                return Failure(BoundaryError(ErrorCode.QUOTA_EXCEEDED))
            handle = _GrantHandle()
            self._grants[id(handle)] = _GrantBinding(handle, result.value, principal)
            return Success(handle)

    def check(
        self, grant: VerifiedRunGrant, job: JobRef, required_scopes: frozenset[Scope]
    ) -> AuthorityDecision:
        if (
            type(job) is not JobRef
            or type(required_scopes) is not frozenset
            or not required_scopes
            or any(type(scope) is not Scope for scope in required_scopes)
        ):
            return AuthorityDecision.DENIED

        def check_tx(tx: ReceiptTransaction) -> AuthorityDecision:
            record = self._registered(tx, grant)
            if record is None:
                return AuthorityDecision.DENIED
            state = self._state(tx, record)
            if state is not AuthorityDecision.AUTHORIZED:
                return state
            if (
                job not in record.claims.jobs
                or not required_scopes <= record.claims.scopes
            ):
                return AuthorityDecision.DENIED
            return AuthorityDecision.AUTHORIZED

        result = self.store.read_transaction(check_tx)
        return result.value if isinstance(result, Success) else AuthorityDecision.DENIED

    def revoke(self, grant: VerifiedRunGrant) -> Result[None]:
        """Trusted controller action, serialized with ACK by BEGIN IMMEDIATE."""

        def revoke_tx(tx: ReceiptTransaction) -> None:
            record = self._registered(tx, grant)
            if record is None:
                raise StoreFailure(ErrorCode.DENIED)
            tx.revoke_grant(record.claims)

        return self.store.controller_transaction(revoke_tx)
