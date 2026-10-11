"""Synthetic identity controls and private record invariants, never live jobs."""

import json
from copy import copy
from dataclasses import FrozenInstanceError, replace

import pytest

from binnacle.features.commands.job_awareness import models as m
from binnacle.features.commands.job_awareness.identifiers import (
    receipt_result_from_wire,
    receipt_result_to_wire,
    snapshot_from_wire,
    snapshot_to_wire,
)
from tests.contracts.job_awareness.fakes import FakeHandleAuthority, FakeReceiptQuery

JOB = m.JobRef("ja1_" + "1" * 32, "abcdef012345", "g1_" + "2" * 32)
SCOPES = frozenset({m.Scope.OBSERVE})


def snapshot():
    return m.OutputSnapshot(
        JOB,
        "0" * 64,
        0,
        m.TerminalOutcome(m.TerminalKind.EXIT_CODE, 0),
        1000,
        2000,
        m.SourceKind.CONTROLLER_SEALED_SYNTHETIC,
        "3" * 32,
    )


def test_claims_are_not_verified_grant():
    authority = FakeHandleAuthority()
    grant = authority.issue((JOB,))
    claims = authority.claims(grant)
    for forged in (claims, {"chat_id": "trusted"}, "chat-id", object(), copy(grant)):
        assert authority.check(forged, JOB, SCOPES) is m.AuthorityDecision.DENIED
    with pytest.raises(TypeError):
        m.VerifiedRunGrant()
    with pytest.raises(TypeError):
        m.VerifiedPrincipal()
    for handle in (grant, authority.principal(grant)):
        with pytest.raises(TypeError):
            json.dumps(handle)


def test_shared_handle_authority_fake():
    authority = FakeHandleAuthority()
    grant = authority.issue((JOB,))
    assert authority.check(grant, JOB, SCOPES) is m.AuthorityDecision.AUTHORIZED
    assert FakeHandleAuthority().check(grant, JOB, SCOPES) is m.AuthorityDecision.DENIED
    authority.now_ms = authority.claims(grant).expires_at_ms
    assert authority.check(grant, JOB, SCOPES) is m.AuthorityDecision.EXPIRED
    authority.revoke(grant)
    assert authority.check(grant, JOB, SCOPES) is m.AuthorityDecision.REVOKED


@pytest.mark.parametrize(
    "change", ["epoch", "generation", "principal", "storage", "clock", "rollback"]
)
def test_current_authority_is_rechecked(change):
    authority = FakeHandleAuthority()
    grant = authority.issue((JOB,))
    assert authority.check(grant, JOB, SCOPES) is m.AuthorityDecision.AUTHORIZED
    expected = m.AuthorityDecision.DENIED
    if change == "epoch":
        authority.rotate_epoch()
        expected = m.AuthorityDecision.REVOKED
    elif change == "generation":
        new = authority.reissue(grant)
        assert authority.claims(new).grant_id != authority.claims(grant).grant_id
        assert authority.check(new, JOB, SCOPES) is m.AuthorityDecision.AUTHORIZED
        expected = m.AuthorityDecision.REVOKED
    elif change == "principal":
        authority.retire_principal(grant)
    elif change == "storage":
        authority.available = False
    elif change == "clock":
        authority.clock_safe = False
    else:
        authority.now_ms -= 1
    assert authority.check(grant, JOB, SCOPES) is expected


@pytest.mark.parametrize(
    "scopes",
    [
        frozenset(),
        frozenset({"observe"}),
        frozenset({"chat"}),
        {m.Scope.OBSERVE},
        frozenset({m.Scope.READ, m.Scope.ACK}),
    ],
)
def test_required_scopes_are_closed_and_all_required(scopes):
    authority = FakeHandleAuthority()
    grant = authority.issue((JOB,), scopes=SCOPES)
    assert authority.check(grant, JOB, scopes) is m.AuthorityDecision.DENIED


def test_copied_token_property_is_not_registry_identity():
    authority = FakeHandleAuthority()
    grant = authority.issue((JOB,))

    class Forged(m.VerifiedRunGrant):
        @property
        def authority_handle(self):
            return grant.authority_handle

    assert authority.check(Forged(), JOB, SCOPES) is m.AuthorityDecision.DENIED


def test_snapshot_roundtrip_is_metadata_only_and_frozen():
    value = snapshot()
    wire = snapshot_to_wire(value)
    assert snapshot_from_wire(json.loads(json.dumps(wire))) == value
    assert set(wire) == {
        "job",
        "sha256",
        "byte_length",
        "terminal",
        "sealed_at_ms",
        "retained_until_ms",
        "source_kind",
        "seal_id",
    }
    with pytest.raises(FrozenInstanceError):
        value.byte_length = 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("byte_length", True),
        ("byte_length", 1048577),
        ("byte_length", -1),
        ("sha256", "A" * 64),
        ("retained_until_ms", 1000),
        ("retained_until_ms", 86401001),
        ("sealed_at_ms", True),
        ("seal_id", "bad"),
        ("source_kind", "CONTROLLER_SEALED_SYNTHETIC"),
    ],
)
def test_snapshot_invalid_records(field, value):
    with pytest.raises(ValueError):
        replace(snapshot(), **{field: value})


@pytest.mark.parametrize(
    "kind,value",
    [
        (m.TerminalKind.SIGNAL, 0),
        (m.TerminalKind.SIGNAL, 256),
        (m.TerminalKind.EXIT_CODE, -1),
        (m.TerminalKind.EXIT_CODE, True),
        ("EXIT_CODE", 0),
    ],
)
def test_terminal_invalid_records(kind, value):
    with pytest.raises(ValueError):
        m.TerminalOutcome(kind, value)


def test_terminal_failures_remain_distinct():
    assert m.TerminalOutcome(m.TerminalKind.EXIT_CODE, 1) != m.TerminalOutcome(
        m.TerminalKind.SIGNAL, 1
    )


def test_receipt_union_explicit_wire_envelope():
    receipt = m.ConsumerReceipt(
        m.ReceiptState.UNCONFIRMED, JOB, "0" * 64, (), False, 0, 1
    )
    for result in (m.Success(receipt), m.Failure(m.BoundaryError(m.ErrorCode.DENIED))):
        wire = receipt_result_to_wire(result)
        assert receipt_result_from_wire(json.loads(json.dumps(wire))) == result
        assert "value" not in wire
    with pytest.raises(ValueError):
        receipt_result_from_wire({"ok": 1, "receipt": {}})
    with pytest.raises(ValueError):
        receipt_result_from_wire({"ok": False, "error": {"code": "NEW"}})


def test_query_fake_rechecks_authority_and_exact_snapshot_without_mutation():
    authority = FakeHandleAuthority()
    grant = authority.issue((JOB,))
    query = FakeReceiptQuery(authority)
    snap = snapshot()
    receipt = m.ConsumerReceipt(
        m.ReceiptState.UNCONFIRMED, JOB, snap.sha256, (), False, 0, 1
    )
    query.register(grant, snap, receipt)
    assert query.query(grant, snap) == m.Success(receipt)
    assert query.query(grant, replace(snap, seal_id="4" * 32)) == m.Failure(
        m.BoundaryError(m.ErrorCode.SOURCE_UNAVAILABLE)
    )
    foreign = authority.issue((JOB,))
    assert query.query(foreign, snap) == m.Failure(
        m.BoundaryError(m.ErrorCode.SOURCE_UNAVAILABLE)
    )
    authority.now_ms = snap.retained_until_ms
    assert query.query(grant, snap).value.state is m.ReceiptState.OUTPUT_EXPIRED
    authority.revoke(grant)
    assert query.query(grant, snap) == m.Failure(m.BoundaryError(m.ErrorCode.DENIED))
    assert query.records == ((grant, snap, receipt),)


@pytest.mark.parametrize("start,stop", [(-1, 0), (2, 1), (0, 1048577), (True, 1)])
def test_invalid_byte_ranges(start, stop):
    with pytest.raises(ValueError):
        m.ByteRange(start, stop)


def test_claim_records_do_not_accept_wrong_namespace_or_mutable_scopes():
    authority = FakeHandleAuthority()
    claims = authority.claims(authority.issue((JOB,)))
    for changes in (
        {"jobs": ()},
        {"jobs": (JOB, JOB)},
        {"jobs": (replace(JOB, run_namespace="ja1_" + "f" * 32),)},
        {"scopes": {m.Scope.READ}},
        {"scopes": frozenset()},
        {"expires_at_ms": claims.issued_at_ms},
        {"expires_at_ms": claims.issued_at_ms + 3600001},
        {"authority_revision": True},
        {"consent_version": "chat"},
    ):
        with pytest.raises(ValueError):
            replace(claims, **changes)


def test_observation_cannot_claim_running_snapshot_or_wrong_job():
    snap = snapshot()
    for args in [
        (JOB, m.ObservationState.RUNNING, snap.terminal, snap),
        (JOB, m.ObservationState.TERMINAL, None, None),
        (
            replace(JOB, job_id="1" * 12),
            m.ObservationState.TERMINAL,
            snap.terminal,
            snap,
        ),
    ]:
        with pytest.raises(ValueError):
            m.Observation(*args)
    assert m.Observation(JOB, m.ObservationState.UNKNOWN, None, None).snapshot is None


def test_page_uses_exact_bytes_and_canonical_range():
    import base64
    import hashlib

    data = b"\xff\x80"
    snap = replace(snapshot(), byte_length=2, sha256=hashlib.sha256(data).hexdigest())
    page = m.PageEnvelope(
        snap,
        m.ByteRange(0, 2),
        snap.sha256,
        base64.b64encode(data).decode(),
        "a" * 64,
        1500,
    )
    for changes in (
        {"range": m.ByteRange(0, 1)},
        {"data_base64": "/4B="},
        {"page_sha256": "0" * 64},
        {"expires_at_ms": 2001},
    ):
        with pytest.raises(ValueError):
            replace(page, **changes)


def test_rendered_hint_counts_utf8_bytes():
    assert m.RenderedHint(m.HintCarrier.META, "é", 2).utf8_bytes == 2
    for text, count in [("é", 1), ("é" * 257, 514), ("", 0), ("\ud800", 1)]:
        with pytest.raises(ValueError):
            m.RenderedHint(m.HintCarrier.TEXT, text, count)


@pytest.mark.parametrize("state", list(m.ReceiptState))
def test_all_receipt_states_and_ranges_roundtrip(state):
    value = m.ConsumerReceipt(
        state, JOB, "a" * 64, (m.ByteRange(0, 16384),), False, 7, 2
    )
    assert receipt_result_from_wire(
        receipt_result_to_wire(m.Success(value))
    ) == m.Success(value)


@pytest.mark.parametrize("code", list(m.ErrorCode))
def test_all_failure_codes_roundtrip(code):
    failure = m.Failure(m.BoundaryError(code))
    assert receipt_result_from_wire(receipt_result_to_wire(failure)) == failure


@pytest.mark.parametrize(
    "value",
    [
        [],
        None,
        {"ok": True},
        {"ok": True, "extra": {}},
        {"ok": False, "error": {"code": "DENIED", "chat": "secret"}},
    ],
)
def test_receipt_envelopes_are_closed(value):
    with pytest.raises(ValueError, match="^Invalid private record$"):
        receipt_result_from_wire(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ranges", [{"start": 0, "stop": 0}] * 65),
        ("ranges", ()),
        ("empty_confirmed", 1),
        ("state", "UNKNOWN"),
        ("state", "a" * 1000),
        ("commit_version", True),
        ("authority_revision", 0),
    ],
)
def test_receipt_parser_rejects_malformed_fields(field, value):
    receipt = m.ConsumerReceipt(m.ReceiptState.COMPLETE, JOB, "0" * 64, (), True, 1, 1)
    raw = receipt_result_to_wire(m.Success(receipt))
    raw["receipt"][field] = value
    with pytest.raises(ValueError, match="^Invalid private record$"):
        receipt_result_from_wire(raw)


@pytest.mark.parametrize(
    "change",
    [
        {"source_kind": "LEGACY"},
        {"terminal": {"kind": "unknown", "value": 0}},
        {"terminal": {"kind": "SIGNAL", "value": 0}},
        {"path": "private"},
        {"byte_length": True},
    ],
)
def test_snapshot_parser_rejects_malformed_fields(change):
    with pytest.raises(ValueError, match="^Invalid private record$"):
        snapshot_from_wire({**snapshot_to_wire(snapshot()), **change})


def test_forged_job_record_is_rejected_at_authority_boundary():
    authority = FakeHandleAuthority()
    grant = authority.issue((JOB,))
    # This tests corrupt local data. It does not claim to sandbox hostile code.
    broken = object.__new__(m.JobRef)
    assert authority.check(grant, broken, SCOPES) is m.AuthorityDecision.DENIED
    assert (
        authority.check(grant, {"job_id": JOB.job_id}, SCOPES)
        is m.AuthorityDecision.DENIED
    )


def test_exact_scope_superset_and_expiry_boundary():
    authority = FakeHandleAuthority()
    grant = authority.issue((JOB,))
    authority.now_ms = authority.claims(grant).expires_at_ms - 1
    assert (
        authority.check(grant, JOB, frozenset({m.Scope.READ, m.Scope.ACK}))
        is m.AuthorityDecision.AUTHORIZED
    )
    authority.rotate_epoch()
    authority.now_ms += 1
    assert authority.check(grant, JOB, SCOPES) is m.AuthorityDecision.REVOKED
