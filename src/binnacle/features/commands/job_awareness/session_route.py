"""E2 lab session-route parser and keyed digest. LAB_ONLY, default off.

The platform asserts ``X-OpenAI-Session`` / ``_meta["openai/session"]`` and the
matching subject pair. They are a conversation correlation key, not
authentication. Caller-controlled claims (tool arguments, ``clientInfo``,
``Mcp-Session-Id``, ``X-Request-Id``) are never identity. Platform values enter
the lab only as HMAC digests under an in-memory epoch key. Raw values are never
stored, logged, returned or kept in any object built here.
"""

import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import NoReturn, cast

from binnacle.features.commands.job_awareness.identifiers import canonical_hex, require
from binnacle.features.commands.job_awareness.models import (
    JobRef,
    PrincipalClaims,
    VerifiedRunGrant,
)

SESSION_HEADER = "x-openai-session"
SUBJECT_HEADER = "x-openai-subject"
SESSION_META = "openai/session"
SUBJECT_META = "openai/subject"
SESSION_LENGTH = 79
SUBJECT_LENGTH = 57
_SESSION_GRAMMAR = re.compile(r"v1/[A-Za-z0-9_-]{76}")
_SUBJECT_GRAMMAR = re.compile(r"v1/[A-Za-z0-9_-]{54}")
_SESSION_LABEL = b"binnacle-ja/session/v1\x00"
_SUBJECT_LABEL = b"binnacle-ja/subject/v1\x00"
ISSUER_SESSION_V1 = hashlib.sha256(b"binnacle-ja/issuer/session-v1").hexdigest()[:32]
TENANT_SINGLE_OWNER = hashlib.sha256(b"binnacle-ja/tenant/single-owner").hexdigest()[
    :32
]
LOG_KEY_HEX = 16
MAX_ROUTE_JOBS = 2


class RouteStatus(str, Enum):
    """Fail-closed route outcomes. Only BOUND may reach a lab allocation."""

    BOUND = "BOUND"
    UNBOUND = "UNBOUND"  # Well-formed and keyed; no binding resolved yet.
    NO_SESSION = "NO_SESSION"
    NO_META = "NO_META"
    MALFORMED = "MALFORMED"
    MISMATCH = "MISMATCH"
    KEY_FULL = "KEY_FULL"
    KEY_NAMESPACE = "KEY_NAMESPACE"
    SUSPENDED = "SUSPENDED"


@dataclass(frozen=True)
class KeyDigest:
    """Key-pair digest ``kd = (epoch, d_subj, d_sess)``; 128-bit digests."""

    epoch: str
    d_subj: str
    d_sess: str

    def __post_init__(self) -> None:
        canonical_hex(self.epoch, 32)
        canonical_hex(self.d_subj, 32)
        canonical_hex(self.d_sess, 32)

    @property
    def kd(self) -> str:
        return f"{self.epoch}:{self.d_subj}:{self.d_sess}"

    @property
    def log_key(self) -> str:
        """Export prefix only (``ja_key``). In-process comparisons use ``kd``."""
        return self.d_sess[:LOG_KEY_HEX]

    def principal(self) -> PrincipalClaims:
        return PrincipalClaims(
            ISSUER_SESSION_V1, TENANT_SINGLE_OWNER, self.d_subj, self.d_sess
        )


@dataclass(frozen=True)
class RouteOutcome:
    """Digest-only result of one ``tools/call`` identity extraction.

    ``key`` is present only for UNBOUND/BOUND/KEY_FULL/KEY_NAMESPACE/SUSPENDED.
    ``format_change`` flags a present string value that fails the grammar.
    """

    status: RouteStatus
    key: KeyDigest | None = None
    format_change: bool = False

    def __post_init__(self) -> None:
        require(type(self.status) is RouteStatus)
        require(type(self.format_change) is bool)
        keyed = self.status not in _UNKEYED
        require((self.key is not None) == keyed)
        require(self.key is None or type(self.key) is KeyDigest)
        require(not self.format_change or self.status is RouteStatus.MALFORMED)

    def with_status(self, status: RouteStatus) -> "RouteOutcome":
        """Binding-layer transition; never adds or removes the key."""
        require(self.key is not None and status not in _UNKEYED)
        return RouteOutcome(status, self.key)


_UNKEYED = frozenset(
    {
        RouteStatus.NO_SESSION,
        RouteStatus.NO_META,
        RouteStatus.MALFORMED,
        RouteStatus.MISMATCH,
    }
)


@dataclass(frozen=True)
class SessionRoute:
    """Frozen request-local route passed to ``adapt_routed``; never stored."""

    key: KeyDigest
    grant: VerifiedRunGrant
    jobs: tuple[JobRef, ...]

    def __post_init__(self) -> None:
        require(type(self.key) is KeyDigest)
        require(isinstance(self.grant, VerifiedRunGrant))
        require(type(self.jobs) is tuple and 1 <= len(self.jobs) <= MAX_ROUTE_JOBS)
        require(all(type(job) is JobRef for job in self.jobs))
        require(len(set(self.jobs)) == len(self.jobs))


class SessionKeyer:
    """In-memory epoch key ``K_e``. Never written, logged, pickled or returned.

    Build a new keyer in the same step as the issuer-epoch rotation (cold
    start). ``rotate`` replaces the key and refuses a reused epoch.
    """

    __slots__ = ("_epoch", "_key", "_retired")

    def __init__(self, epoch: str) -> None:
        self._epoch = canonical_hex(epoch, 32)
        self._key = secrets.token_bytes(32)
        self._retired: set[str] = set()

    @property
    def epoch(self) -> str:
        return self._epoch

    def rotate(self, epoch: str) -> None:
        canonical_hex(epoch, 32)
        require(epoch != self._epoch and epoch not in self._retired)
        self._retired.add(self._epoch)
        self._epoch, self._key = epoch, secrets.token_bytes(32)

    def _digest(self, label: bytes, value: str) -> str:
        mac = hmac.new(self._key, label + value.encode("ascii"), hashlib.sha256)
        return mac.digest()[:16].hex()

    def key(self, session: str, subject: str) -> KeyDigest:
        """Digest already validated values; callers use ``route`` instead."""
        require(_valid(session, SESSION_LENGTH, _SESSION_GRAMMAR))
        require(_valid(subject, SUBJECT_LENGTH, _SUBJECT_GRAMMAR))
        return KeyDigest(
            self._epoch,
            self._digest(_SUBJECT_LABEL, subject),
            self._digest(_SESSION_LABEL, session),
        )

    def __repr__(self) -> str:
        return "SessionKeyer(<redacted>)"

    def __reduce__(self) -> NoReturn:
        raise TypeError("SessionKeyer is not serializable")


def _valid(value: object, length: int, grammar: "re.Pattern[str]") -> bool:
    """Exact length, ASCII and fullmatch; no decoding and no ``$`` anchor."""
    return (
        type(value) is str
        and len(value) == length
        and value.isascii()
        and grammar.fullmatch(value) is not None
    )


def _single(values: object) -> str | None:
    """Exactly one raw header value; duplicates are rejected even when equal."""
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        return None
    if len(values) != 1 or type(values[0]) is not str:
        return None
    return values[0]


def _looks_like_value(value: object) -> bool:
    return type(value) is str and value.isascii() and value.startswith("v")


def route(
    keyer: SessionKeyer,
    session_headers: Sequence[str],
    subject_headers: Sequence[str],
    meta: Mapping[str, object] | None,
) -> RouteOutcome:
    """Classify one ``tools/call``. Inputs come from the same request only.

    ``*_headers`` are raw ``headers.getlist()`` results; ``meta`` is the
    request ``params._meta`` mapping. The result holds digests only.
    """
    session, subject = _single(session_headers), _single(subject_headers)
    if session is None or subject is None:
        return RouteOutcome(RouteStatus.NO_SESSION)
    if not isinstance(meta, Mapping):
        return RouteOutcome(RouteStatus.NO_META)
    if SESSION_META not in meta or SUBJECT_META not in meta:
        return RouteOutcome(RouteStatus.NO_META)
    meta_session, meta_subject = meta[SESSION_META], meta[SUBJECT_META]
    pairs = (
        (session, SESSION_LENGTH, _SESSION_GRAMMAR),
        (meta_session, SESSION_LENGTH, _SESSION_GRAMMAR),
        (subject, SUBJECT_LENGTH, _SUBJECT_GRAMMAR),
        (meta_subject, SUBJECT_LENGTH, _SUBJECT_GRAMMAR),
    )
    if not all(_valid(value, length, grammar) for value, length, grammar in pairs):
        changed = any(
            _looks_like_value(value) and not _valid(value, length, grammar)
            for value, length, grammar in pairs
        )
        return RouteOutcome(RouteStatus.MALFORMED, format_change=changed)
    checked_session, checked_subject = cast(str, meta_session), cast(str, meta_subject)
    if not (
        hmac.compare_digest(session.encode("ascii"), checked_session.encode("ascii"))
        and hmac.compare_digest(
            subject.encode("ascii"), checked_subject.encode("ascii")
        )
    ):
        return RouteOutcome(RouteStatus.MISMATCH)
    return RouteOutcome(RouteStatus.UNBOUND, keyer.key(session, subject))
