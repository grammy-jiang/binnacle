"""Inert LAB_ONLY values. Parsed records never establish authority.

Opaque handles require identity lookup by an injected trusted registry on every
operation. Python classes do not sandbox hostile code in the same process.
"""

import base64
import binascii
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from binnacle.features.commands.job_awareness.identifiers import (
    bounded_int,
    canonical_hex,
    require,
)

MAX_INTEGER = 9007199254740991
MAX_SNAPSHOT_BYTES = 1048576
PAGE_BYTES = 16384
# CA-1: the E2 lab session route is a separate, explicit consent version.
CONSENT_VERSIONS = frozenset({"lab-user-run-v1", "lab-session-route-v1"})
T_co = TypeVar("T_co", covariant=True)


class Scope(str, Enum):
    OBSERVE = "observe"
    READ = "read"
    ACK = "ack"


class AuthorityDecision(str, Enum):
    AUTHORIZED = "authorized"
    DENIED = "denied"
    EXPIRED = "expired"
    REVOKED = "revoked"


class TerminalKind(str, Enum):
    EXIT_CODE = "EXIT_CODE"
    SIGNAL = "SIGNAL"


class SourceKind(str, Enum):
    CONTROLLER_SEALED_SYNTHETIC = "CONTROLLER_SEALED_SYNTHETIC"


class ReceiptState(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    OUTPUT_EXPIRED = "OUTPUT_EXPIRED"


class ObservationState(str, Enum):
    RUNNING = "RUNNING"
    UNKNOWN = "UNKNOWN"
    TERMINAL = "TERMINAL"


class CandidateCategory(str, Enum):
    TERMINAL_UNCONFIRMED = "TERMINAL_UNCONFIRMED"
    TERMINAL_PARTIAL = "TERMINAL_PARTIAL"
    RUNNING = "RUNNING"


class HintCarrier(str, Enum):
    META = "META"
    TEXT = "TEXT"


class ErrorCode(str, Enum):
    DENIED = "DENIED"
    INVALID_SELECTOR = "INVALID_SELECTOR"
    SOURCE_UNSEALED = "SOURCE_UNSEALED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    OUTPUT_CHANGED = "OUTPUT_CHANGED"
    OUTPUT_EXPIRED = "OUTPUT_EXPIRED"
    INVALID_PROOF = "INVALID_PROOF"
    CLOCK_UNSAFE = "CLOCK_UNSAFE"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    BUSY = "BUSY"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    UNSUPPORTED_RESULT = "UNSUPPORTED_RESULT"


@dataclass(frozen=True)
class JobRef:
    run_namespace: str
    job_id: str
    incarnation: str

    def __post_init__(self) -> None:
        canonical_hex(self.run_namespace, 32, "ja1_")
        canonical_hex(self.job_id, 12)
        canonical_hex(self.incarnation, 32, "g1_")

    @property
    def canonical_key(self) -> str:
        return f"{self.run_namespace}:{self.job_id}:{self.incarnation}"


@dataclass(frozen=True)
class PrincipalClaims:
    """Private data, not an authenticated principal."""

    issuer_id: str
    tenant_id: str
    subject_id: str
    consumer_id: str
    audience: str = "binnacle-ja-lab-v1"

    def __post_init__(self) -> None:
        for value in (
            self.issuer_id,
            self.tenant_id,
            self.subject_id,
            self.consumer_id,
        ):
            canonical_hex(value, 32)
        require(type(self.audience) is str and self.audience == "binnacle-ja-lab-v1")


@dataclass(frozen=True)
class RunGrantClaims:
    """Private persisted claims only. Capability generation is immutable."""

    principal: PrincipalClaims
    issuer_epoch: str
    grant_id: str
    run_namespace: str
    jobs: tuple[JobRef, ...]
    scopes: frozenset[Scope]
    issued_at_ms: int
    expires_at_ms: int
    authority_revision: int
    consent_version: str = "lab-user-run-v1"

    def __post_init__(self) -> None:
        require(type(self.principal) is PrincipalClaims)
        canonical_hex(self.issuer_epoch, 32)
        canonical_hex(self.grant_id, 32)
        canonical_hex(self.run_namespace, 32, "ja1_")
        require(type(self.jobs) is tuple and 1 <= len(self.jobs) <= 100)
        require(
            all(
                type(job) is JobRef and job.run_namespace == self.run_namespace
                for job in self.jobs
            )
        )
        require(len(set(self.jobs)) == len(self.jobs))
        require(type(self.scopes) is frozenset and 1 <= len(self.scopes) <= 3)
        require(all(type(scope) is Scope for scope in self.scopes))
        bounded_int(self.issued_at_ms, 0, MAX_INTEGER)
        bounded_int(self.expires_at_ms, 0, MAX_INTEGER)
        require(self.issued_at_ms < self.expires_at_ms <= self.issued_at_ms + 3600000)
        bounded_int(self.authority_revision, 1, MAX_INTEGER)
        require(
            type(self.consent_version) is str
            and self.consent_version in CONSENT_VERSIONS
        )


class VerifiedPrincipal(ABC):
    """Opaque local identity; only a registry can establish its validity."""

    @property
    @abstractmethod
    def authority_handle(self) -> object: ...


class VerifiedRunGrant(ABC):
    """Opaque local identity, never a JSON constructor or authorization ticket."""

    @property
    @abstractmethod
    def authority_handle(self) -> object: ...


@dataclass(frozen=True)
class TerminalOutcome:
    kind: TerminalKind
    value: int

    def __post_init__(self) -> None:
        require(type(self.kind) is TerminalKind)
        bounded_int(self.value, 1 if self.kind is TerminalKind.SIGNAL else 0, 255)


@dataclass(frozen=True)
class OutputSnapshot:
    """Metadata only; constructing it does not seal or verify output bytes."""

    job: JobRef
    sha256: str
    byte_length: int
    terminal: TerminalOutcome
    sealed_at_ms: int
    retained_until_ms: int
    source_kind: SourceKind
    seal_id: str

    def __post_init__(self) -> None:
        require(type(self.job) is JobRef and type(self.terminal) is TerminalOutcome)
        canonical_hex(self.sha256, 64)
        canonical_hex(self.seal_id, 32)
        bounded_int(self.byte_length, 0, MAX_SNAPSHOT_BYTES)
        bounded_int(self.sealed_at_ms, 0, MAX_INTEGER)
        bounded_int(self.retained_until_ms, 0, MAX_INTEGER)
        require(
            self.sealed_at_ms < self.retained_until_ms <= self.sealed_at_ms + 86400000
        )
        require(type(self.source_kind) is SourceKind)


@dataclass(frozen=True)
class ByteRange:
    start: int
    stop: int

    def __post_init__(self) -> None:
        bounded_int(self.start, 0, MAX_SNAPSHOT_BYTES)
        bounded_int(self.stop, self.start, MAX_SNAPSHOT_BYTES)


@dataclass(frozen=True)
class ConsumerReceipt:
    """Private assertion history, not evidence of model comprehension.

    Snapshot-dependent completeness and canonical page union belong to I1 policy.
    """

    state: ReceiptState
    job: JobRef
    snapshot_sha256: str
    ranges: tuple[ByteRange, ...]
    empty_confirmed: bool
    commit_version: int
    authority_revision: int

    def __post_init__(self) -> None:
        require(type(self.state) is ReceiptState and type(self.job) is JobRef)
        canonical_hex(self.snapshot_sha256, 64)
        require(type(self.ranges) is tuple and len(self.ranges) <= 64)
        require(all(type(item) is ByteRange for item in self.ranges))
        require(type(self.empty_confirmed) is bool)
        bounded_int(self.commit_version, 0, MAX_INTEGER)
        bounded_int(self.authority_revision, 1, MAX_INTEGER)


@dataclass(frozen=True)
class Observation:
    job: JobRef
    state: ObservationState
    terminal: TerminalOutcome | None
    snapshot: OutputSnapshot | None

    def __post_init__(self) -> None:
        require(type(self.job) is JobRef and type(self.state) is ObservationState)
        if self.state is ObservationState.TERMINAL:
            require(type(self.terminal) is TerminalOutcome)
        else:
            require(self.terminal is None and self.snapshot is None)
        if self.snapshot is not None:
            require(type(self.snapshot) is OutputSnapshot)
            require(
                self.snapshot.job == self.job
                and self.snapshot.terminal == self.terminal
            )


@dataclass(frozen=True)
class PageEnvelope:
    snapshot: OutputSnapshot
    range: ByteRange
    page_sha256: str
    data_base64: str
    proof: str
    expires_at_ms: int

    def __post_init__(self) -> None:
        require(type(self.snapshot) is OutputSnapshot and type(self.range) is ByteRange)
        canonical_hex(self.page_sha256, 64)
        canonical_hex(self.proof, 64)
        bounded_int(self.expires_at_ms, 0, MAX_INTEGER)
        require(
            self.snapshot.sealed_at_ms
            <= self.expires_at_ms
            <= self.snapshot.retained_until_ms
        )
        start, stop, length = (
            self.range.start,
            self.range.stop,
            self.snapshot.byte_length,
        )
        require(start % PAGE_BYTES == 0 and stop == min(start + PAGE_BYTES, length))
        require(start < length or start == stop == length == 0)
        require(type(self.data_base64) is str and len(self.data_base64) <= 21848)
        try:
            data = base64.b64decode(self.data_base64, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Invalid private record") from None
        require(base64.b64encode(data).decode("ascii") == self.data_base64)
        require(
            len(data) == stop - start
            and hashlib.sha256(data).hexdigest() == self.page_sha256
        )


@dataclass(frozen=True)
class ReceiptProofRecord:
    """Private storage record; never the proof token returned on the wire."""

    proof_sha256: str
    principal: PrincipalClaims
    issuer_epoch: str
    grant_id: str
    job: JobRef
    snapshot_sha256: str
    range: ByteRange
    page_sha256: str
    expires_at_ms: int
    consumed: bool

    def __post_init__(self) -> None:
        for digest in (self.proof_sha256, self.snapshot_sha256, self.page_sha256):
            canonical_hex(digest, 64)
        canonical_hex(self.issuer_epoch, 32)
        canonical_hex(self.grant_id, 32)
        require(type(self.principal) is PrincipalClaims and type(self.job) is JobRef)
        require(type(self.range) is ByteRange and type(self.consumed) is bool)
        bounded_int(self.expires_at_ms, 0, MAX_INTEGER)


@dataclass(frozen=True)
class ReminderCandidate:
    job: JobRef
    category: CandidateCategory
    observation_epoch: str
    snapshot_sha256: str | None

    def __post_init__(self) -> None:
        require(type(self.job) is JobRef and type(self.category) is CandidateCategory)
        canonical_hex(self.observation_epoch, 32)
        if self.snapshot_sha256 is not None:
            canonical_hex(self.snapshot_sha256, 64)
        require(
            (self.category is CandidateCategory.RUNNING)
            == (self.snapshot_sha256 is None)
        )


@dataclass(frozen=True)
class RenderedHint:
    carrier: HintCarrier
    text: str
    utf8_bytes: int

    def __post_init__(self) -> None:
        require(type(self.carrier) is HintCarrier)
        require(type(self.text) is str and 1 <= len(self.text) <= 512)
        bounded_int(self.utf8_bytes, 1, 512)
        try:
            require(len(self.text.encode("utf-8")) == self.utf8_bytes)
        except UnicodeError:
            raise ValueError("Invalid private record") from None


@dataclass(frozen=True)
class BoundaryError:
    code: ErrorCode

    def __post_init__(self) -> None:
        require(type(self.code) is ErrorCode)


@dataclass(frozen=True)
class Success(Generic[T_co]):
    value: T_co


@dataclass(frozen=True)
class Failure:
    error: BoundaryError

    def __post_init__(self) -> None:
        require(type(self.error) is BoundaryError)


Result = Success[T_co] | Failure
ReceiptQueryResult = Success[ConsumerReceipt] | Failure
ObservationResult = Success[Observation] | Failure
GrantVerificationResult = Success[VerifiedRunGrant] | Failure
PageResult = Success[PageEnvelope] | Failure
