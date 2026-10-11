"""Synchronous, bounded, injected contracts. No backend is constructed here."""

from types import TracebackType
from typing import Protocol

from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    Failure,
    GrantVerificationResult,
    JobRef,
    ObservationResult,
    OutputSnapshot,
    PageResult,
    ReceiptQueryResult,
    Scope,
    Success,
    VerifiedRunGrant,
)


class SnapshotLease(Protocol):
    """Worker-owned pin of verified immutable bytes; close through context exit.

    Cancellation of an awaiting coroutine cannot release the worker's lease.
    A lease is never serialized or reconstructed from caller claims.
    """

    @property
    def snapshot(self) -> OutputSnapshot: ...
    @property
    def verified_bytes(self) -> bytes: ...
    def __enter__(self) -> "SnapshotLease": ...  # noqa: PYI034 - Python 3.10
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


SnapshotLeaseResult = Success[SnapshotLease] | Failure


class HandleAuthorityPort(Protocol):
    """Fresh trusted handle/principal/epoch/generation/revocation/expiry check.

    Require a nonempty closed scope set and exact allowlist match before source
    access. Unknown storage or clock denies. Never look up job existence here.
    Map all nonauthorized decisions to external DENIED. ACK must repeat this
    policy inside its mutation transaction; a prior check is not a ticket.
    """

    def check(
        self, grant: VerifiedRunGrant, job: JobRef, required_scopes: frozenset[Scope]
    ) -> AuthorityDecision: ...


class ReceiptQueryPort(Protocol):
    """Fresh read-only authority and snapshot check; no ACK, cleanup or proof."""

    def query(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot
    ) -> ReceiptQueryResult: ...


class JobObservationPort(Protocol):
    """One exact selector, OBSERVE admission before all source access."""

    def observe(self, grant: VerifiedRunGrant, job: JobRef) -> ObservationResult: ...


class SnapshotReadPort(Protocol):
    """READ admission before catalog/payload reads; deny unsealed sources."""

    def open_verified(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot
    ) -> SnapshotLeaseResult: ...


class GrantVerifierPort(Protocol):
    """Separate synthetic principal credential and capability; no chat labels."""

    def verify(
        self, principal_credential: bytes, capability: bytes, required_scope: Scope
    ) -> GrantVerificationResult: ...


class ReceiptCommandPort(Protocol):
    """I1 API only. READ+ACK, <=16 proofs, atomic transaction-local admission."""

    def acknowledge(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot, proofs: tuple[str, ...]
    ) -> ReceiptQueryResult: ...


class PageIssuePort(Protocol):
    """Persist canonical page proof before returning; never infer a receipt."""

    def issue(
        self, grant: VerifiedRunGrant, snapshot: OutputSnapshot, start: int
    ) -> PageResult: ...
