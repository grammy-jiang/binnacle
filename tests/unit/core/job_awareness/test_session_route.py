"""E2 S1: session-route parser, HMAC keyer and route outcome (design §2.1-2.2)."""

import hashlib
import hmac
import pickle  # nosec B403 - asserts the keyer refuses serialization
import re

import pytest

from binnacle.features.commands.job_awareness.models import (
    JobRef,
    PrincipalClaims,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.session_route import (
    ISSUER_SESSION_V1,
    SESSION_META,
    SUBJECT_META,
    TENANT_SINGLE_OWNER,
    KeyDigest,
    RouteOutcome,
    RouteStatus,
    SessionKeyer,
    SessionRoute,
    route,
)

RAW_VALUE = re.compile(r"v1/[A-Za-z0-9_-]{40,}")
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
EPOCH = "1" * 32


def synthetic(tag: int, length: int) -> str:
    """Registered synthetic test value; never a real platform value."""
    seed = hashlib.sha256(f"e2-synthetic-{tag}".encode()).digest() * 4
    return "v1/" + "".join(ALPHABET[b % 64] for b in seed[:length])


SESSION_A, SUBJECT_A = synthetic(1, 76), synthetic(2, 54)
SESSION_B = synthetic(3, 76)


def call(keyer, session=SESSION_A, subject=SUBJECT_A, meta=None, **overrides):
    meta = (
        {SESSION_META: session, SUBJECT_META: subject} if meta is None else dict(meta)
    )
    sessions = overrides.get("sessions", [session])
    subjects = overrides.get("subjects", [subject])
    return route(keyer, sessions, subjects, meta)


class _Grant(VerifiedRunGrant):
    @property
    def authority_handle(self):
        return self


def job(index: int) -> JobRef:
    return JobRef("ja1_" + "a" * 32, f"{index:012x}", "g1_" + "b" * 32)


def test_valid_pair_is_keyed_and_stable():
    keyer = SessionKeyer(EPOCH)
    first, second = call(keyer), call(keyer)
    assert first.status is RouteStatus.UNBOUND
    assert first.key == second.key and first.key is not None
    assert first.key.epoch == EPOCH and len(first.key.kd) == 98
    assert first.key.log_key == first.key.d_sess[:16]
    other = call(keyer, session=SESSION_B)
    assert other.key is not None and other.key.d_sess != first.key.d_sess
    assert other.key.d_subj == first.key.d_subj


def test_digest_matches_labelled_hmac_definition():
    keyer = SessionKeyer(EPOCH)
    key = keyer._key  # test-only read of the in-memory epoch key
    outcome = call(keyer)
    expected_sess = hmac.new(
        key, b"binnacle-ja/session/v1\x00" + SESSION_A.encode(), hashlib.sha256
    ).digest()[:16]
    expected_subj = hmac.new(
        key, b"binnacle-ja/subject/v1\x00" + SUBJECT_A.encode(), hashlib.sha256
    ).digest()[:16]
    assert outcome.key == KeyDigest(EPOCH, expected_subj.hex(), expected_sess.hex())
    # Domain separation: the same bytes under the two labels differ.
    assert keyer._digest(b"binnacle-ja/session/v1\x00", "x") != keyer._digest(
        b"binnacle-ja/subject/v1\x00", "x"
    )


def test_principal_mapping_uses_digests_only():
    key = call(SessionKeyer(EPOCH)).key
    assert key is not None
    assert key.principal() == PrincipalClaims(
        ISSUER_SESSION_V1, TENANT_SINGLE_OWNER, key.d_subj, key.d_sess
    )
    assert re.fullmatch("[0-9a-f]{32}", ISSUER_SESSION_V1)
    assert re.fullmatch("[0-9a-f]{32}", TENANT_SINGLE_OWNER)


@pytest.mark.parametrize(
    ("sessions", "subjects"),
    [
        ([], [SUBJECT_A]),
        ([SESSION_A], []),
        ([SESSION_A, SESSION_A], [SUBJECT_A]),  # duplicate rejected even when equal
        ([SESSION_A, SESSION_B], [SUBJECT_A]),
        ([SESSION_A], [SUBJECT_A, SUBJECT_A]),
        (SESSION_A, [SUBJECT_A]),  # a bare string is not a header list
        (SESSION_A.encode(), [SUBJECT_A]),
        (None, [SUBJECT_A]),
        ([SESSION_A.encode()], [SUBJECT_A]),
    ],
)
def test_header_presence(sessions, subjects):
    outcome = call(SessionKeyer(EPOCH), sessions=sessions, subjects=subjects)
    assert outcome == RouteOutcome(RouteStatus.NO_SESSION)


@pytest.mark.parametrize(
    "meta",
    [
        None,
        {},
        {SESSION_META: SESSION_A},
        {SUBJECT_META: SUBJECT_A},
        ["openai/session"],
    ],
)
def test_meta_presence(meta):
    keyer = SessionKeyer(EPOCH)
    outcome = route(keyer, [SESSION_A], [SUBJECT_A], meta)
    assert outcome == RouteOutcome(RouteStatus.NO_META)


BAD_SESSIONS = [
    (SESSION_A[:-1], True),  # 78
    (SESSION_A + "A", True),  # 80
    (SESSION_A + "\n", True),  # a "$" anchor would accept this
    (SESSION_A[:-1] + "=", True),
    (SESSION_A[:-1] + "%", True),
    ("v2/" + SESSION_A[3:], True),
    (" " + SESSION_A[1:], False),
    (SESSION_A[:-1] + "٣", False),  # non-ASCII digit
    (SESSION_A[:-1] + "é", False),
    ("", False),
]


@pytest.mark.parametrize(("bad", "changed"), BAD_SESSIONS)
def test_grammar_rejects_session_everywhere(bad, changed):
    keyer = SessionKeyer(EPOCH)
    header = call(keyer, sessions=[bad])
    meta = call(keyer, meta={SESSION_META: bad, SUBJECT_META: SUBJECT_A})
    assert header == RouteOutcome(RouteStatus.MALFORMED, format_change=changed)
    assert meta == RouteOutcome(RouteStatus.MALFORMED, format_change=changed)


@pytest.mark.parametrize(
    "bad", [SUBJECT_A[:-1], SUBJECT_A + "x", SUBJECT_A + "\n", SESSION_A]
)
def test_grammar_rejects_subject(bad):
    keyer = SessionKeyer(EPOCH)
    assert call(keyer, subjects=[bad]).status is RouteStatus.MALFORMED
    meta = {SESSION_META: SESSION_A, SUBJECT_META: bad}
    assert call(keyer, meta=meta).status is RouteStatus.MALFORMED


@pytest.mark.parametrize("bad", [SESSION_A.encode(), 7, None, ["x"]])
def test_non_string_meta_is_malformed_without_format_change(bad):
    outcome = call(
        SessionKeyer(EPOCH), meta={SESSION_META: bad, SUBJECT_META: SUBJECT_A}
    )
    assert outcome == RouteOutcome(RouteStatus.MALFORMED)


def test_header_and_meta_must_agree():
    keyer = SessionKeyer(EPOCH)
    session_meta = {SESSION_META: SESSION_B, SUBJECT_META: SUBJECT_A}
    assert call(keyer, meta=session_meta) == RouteOutcome(RouteStatus.MISMATCH)
    subject_meta = {SESSION_META: SESSION_A, SUBJECT_META: synthetic(9, 54)}
    assert call(keyer, meta=subject_meta) == RouteOutcome(RouteStatus.MISMATCH)


def test_rotation_changes_digests_and_refuses_reuse():
    keyer = SessionKeyer(EPOCH)
    before = call(keyer).key
    keyer.rotate("2" * 32)
    after = call(keyer).key
    assert before is not None and after is not None
    assert after.epoch == "2" * 32 and after.d_sess != before.d_sess
    for reused in (EPOCH, "2" * 32):
        with pytest.raises(ValueError, match="Invalid private record"):
            keyer.rotate(reused)
    with pytest.raises(ValueError, match="Invalid private record"):
        keyer.rotate("not-hex")
    assert SessionKeyer(EPOCH)._key != keyer._key


def test_keyer_never_reveals_or_serializes_its_key():
    keyer = SessionKeyer(EPOCH)
    assert repr(keyer) == "SessionKeyer(<redacted>)"
    assert keyer.epoch == EPOCH
    with pytest.raises(TypeError):
        pickle.dumps(keyer)
    with pytest.raises(AttributeError):
        keyer.extra = 1
    with pytest.raises(ValueError, match="Invalid private record"):
        keyer.key(SESSION_A[:-1], SUBJECT_A)
    with pytest.raises(ValueError, match="Invalid private record"):
        keyer.key(SESSION_A, SUBJECT_A[:-1])


def test_outcomes_hold_no_raw_value():
    keyer = SessionKeyer(EPOCH)
    outcomes = [
        call(keyer),
        call(keyer, sessions=[SESSION_A + "x"]),
        call(keyer, meta={SESSION_META: SESSION_B, SUBJECT_META: SUBJECT_A}),
    ]
    text = repr(outcomes) + repr(keyer) + repr([o.key for o in outcomes])
    assert RAW_VALUE.search(text) is None
    for outcome in outcomes:
        assert SESSION_A not in repr(vars(outcome))


def test_route_outcome_invariants():
    key = call(SessionKeyer(EPOCH)).key
    assert key is not None
    with pytest.raises(ValueError, match="Invalid private record"):
        RouteOutcome(RouteStatus.BOUND)
    with pytest.raises(ValueError, match="Invalid private record"):
        RouteOutcome(RouteStatus.NO_SESSION, key)
    with pytest.raises(ValueError, match="Invalid private record"):
        RouteOutcome(RouteStatus.MISMATCH, format_change=True)
    with pytest.raises(ValueError, match="Invalid private record"):
        RouteOutcome("BOUND", key)
    with pytest.raises(ValueError, match="Invalid private record"):
        RouteOutcome(RouteStatus.BOUND, "kd")
    with pytest.raises(ValueError, match="Invalid private record"):
        RouteOutcome(RouteStatus.MALFORMED, format_change=1)
    unbound = RouteOutcome(RouteStatus.UNBOUND, key)
    assert unbound.with_status(RouteStatus.BOUND) == RouteOutcome(
        RouteStatus.BOUND, key
    )
    with pytest.raises(ValueError, match="Invalid private record"):
        unbound.with_status(RouteStatus.NO_META)
    with pytest.raises(ValueError, match="Invalid private record"):
        RouteOutcome(RouteStatus.NO_META).with_status(RouteStatus.BOUND)
    for bad in ("x" * 32, "1" * 31):
        with pytest.raises(ValueError, match="Invalid private record"):
            KeyDigest(EPOCH, bad, key.d_sess)


def test_session_route_is_bounded_and_typed():
    key = call(SessionKeyer(EPOCH)).key
    assert key is not None
    grant = _Grant()
    route_value = SessionRoute(key, grant, (job(1), job(2)))
    assert route_value.jobs == (job(1), job(2))
    for jobs in ((), (job(1), job(2), job(3)), (job(1), job(1)), [job(1)], ("j",)):
        with pytest.raises(ValueError, match="Invalid private record"):
            SessionRoute(key, grant, jobs)
    with pytest.raises(ValueError, match="Invalid private record"):
        SessionRoute(key, object(), (job(1),))
    with pytest.raises(ValueError, match="Invalid private record"):
        SessionRoute(key.kd, grant, (job(1),))
