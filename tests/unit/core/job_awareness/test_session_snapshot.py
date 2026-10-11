"""E2 S2: allocation snapshot, template hash rules and logical pages (§2.4)."""

import hashlib
import json
from dataclasses import replace

import pytest

from binnacle.features.commands.job_awareness.models import (
    ErrorCode,
    Failure,
    JobRef,
    SourceKind,
    Success,
    TerminalKind,
)
from binnacle.features.commands.job_awareness.session_snapshot import (
    RETENTION_MS,
    SNAPSHOT_SCHEMA,
    FrozenTemplate,
    MemoryPayload,
    build_snapshot,
    echo_matches,
    logical_page,
    output_snapshot,
    valid_slot,
)
from tests.unit.core.job_awareness.session_support import template, template_bytes

JOB = JobRef("ja1_" + "1" * 32, "a" * 12, "g1_" + "2" * 32)
VALUES = ["synthetic-r3-01-00", "synthetic-r3-01-01", "synthetic-r3-01-02"]


def rebuilt(body: dict[str, object], slot: str = "R3-SYN-JOB-01") -> FrozenTemplate:
    data = json.dumps(body).encode()
    nonce = body.get("nonce")
    nonce_hash = hashlib.sha256(str(nonce).encode()).hexdigest()
    return FrozenTemplate(slot, data, hashlib.sha256(data).hexdigest(), nonce_hash)


def body() -> dict[str, object]:
    return json.loads(template_bytes(1))


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("R3-SYN-JOB-01", True),
        ("R3-SYN-JOB-12", True),
        ("R3-SYN-JOB-00", False),
        ("R3-SYN-JOB-13", False),
        ("R3-SYN-JOB-1", False),
        ("R3-SYN-JOB-01\n", False),
        ("j_000000000000", False),
        (1, False),
    ],
)
def test_slot_grammar_is_disjoint_from_handles(value, ok):
    assert valid_slot(value) is ok


def test_snapshot_seals_private_items_and_drops_owner():
    frozen = template(1)
    first, second = build_snapshot(frozen), build_snapshot(frozen)
    assert first is not None and second is not None
    assert first.data != second.data and first.alloc_tag != second.alloc_tag
    assert hashlib.sha256(first.data).hexdigest() == first.sha256
    parsed = json.loads(first.data)
    assert set(parsed) == {
        "schema",
        "slot",
        "template_sha256",
        "nonce",
        "records",
        "alloc_tag",
    }
    assert parsed["schema"] == SNAPSHOT_SCHEMA
    assert parsed["template_sha256"] == frozen.payload_sha256
    assert b"owner" not in first.data
    canaries = [r["canary"] for r in parsed["records"]]
    assert len(set(canaries)) == 3 and all(len(c) == 32 for c in canaries)
    assert [r["value"] for r in parsed["records"]] == VALUES
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode()
    assert canonical == first.data
    assert first.alloc_tag not in repr(first) and canaries[0] not in repr(first)


def test_template_hash_rules_are_checked_before_allocation():
    frozen = template(1)
    assert build_snapshot(replace(frozen, payload_sha256="0" * 64)) is None
    assert build_snapshot(replace(frozen, nonce_sha256="0" * 64)) is None
    assert build_snapshot(replace(frozen, slot="R3-SYN-JOB-02")) is None
    assert build_snapshot(object()) is None
    bad_json = b"{not json"
    assert (
        build_snapshot(
            replace(
                frozen,
                payload=bad_json,
                payload_sha256=hashlib.sha256(bad_json).hexdigest(),
            )
        )
        is None
    )


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "other"},
        {"contains_real_user_data": True},
        {"job_id": "R3-SYN-JOB-02"},
        {"nonce": "XYZ"},
        {"nonce": 5},
        {"records": []},
        {"records": "x"},
        {"extra": 1},
        {
            "records": [
                {"seq": 0, "value": "a"},
                {"seq": 2, "value": "b"},
                {"seq": 2, "value": "c"},
            ]
        },
        {
            "records": [
                {"seq": 0, "value": "é"},
                {"seq": 1, "value": "b"},
                {"seq": 2, "value": "c"},
            ]
        },
        {
            "records": [
                {"seq": 0, "value": ""},
                {"seq": 1, "value": "b"},
                {"seq": 2, "value": "c"},
            ]
        },
        {"records": [{"seq": 0}, {"seq": 1, "value": "b"}, {"seq": 2, "value": "c"}]},
        {"records": [[0], {"seq": 1, "value": "b"}, {"seq": 2, "value": "c"}]},
        {
            "records": [
                {"seq": True, "value": "a"},
                {"seq": 1, "value": "b"},
                {"seq": 2, "value": "c"},
            ]
        },
    ],
)
def test_template_shape_is_exact(change):
    value = body()
    value.update(change)
    assert build_snapshot(rebuilt(value)) is None
    missing = body()
    del missing["owner"]
    assert build_snapshot(rebuilt(missing)) is None


def test_template_record_rejects_bad_frozen_inputs():
    for args in [
        ("R3-SYN-JOB-00", b"", "0" * 64, "0" * 64),
        ("R3-SYN-JOB-01", "x", "0" * 64, "0" * 64),
        ("R3-SYN-JOB-01", b"x" * 4097, "0" * 64, "0" * 64),
        ("R3-SYN-JOB-01", b"", "0" * 63, "0" * 64),
        ("R3-SYN-JOB-01", b"", "0" * 64, "G" * 64),
    ]:
        with pytest.raises(ValueError, match="Invalid private record"):
            FrozenTemplate(*args)


def test_logical_pages_come_from_verified_bytes():
    allocation = build_snapshot(template(1))
    assert allocation is not None
    parsed = json.loads(allocation.data)
    for page in range(3):
        result = logical_page(allocation.data, page)
        assert result is not None
        assert result["seq"] == page and result["value"] == VALUES[page]
        assert result["canary"] == parsed["records"][page]["canary"]
        assert result["slot"] == "R3-SYN-JOB-01"
        assert ("nonce" in result) is (page == 0)
        assert ("alloc_tag" in result) is (page == 0)
    assert logical_page(allocation.data, 0)["alloc_tag"] == allocation.alloc_tag
    for page in (3, -1, True, "0", 1.0, None):
        assert logical_page(allocation.data, page) is None
    for data in (
        b"\xff",
        b"[]",
        b'{"schema":"x"}',
        json.dumps({"schema": SNAPSHOT_SCHEMA, "records": [1]}).encode(),
    ):
        assert logical_page(data, 0) is None
    broken = json.dumps({"schema": SNAPSHOT_SCHEMA, "records": [1, 2, 3]}).encode()
    assert logical_page(broken, 1) is None


def test_echo_compares_without_reflection():
    allocation = build_snapshot(template(1))
    assert allocation is not None
    assert echo_matches(allocation.data, list(VALUES)) is True
    for values in (
        VALUES[:2],
        VALUES + ["x"],
        tuple(VALUES),
        ["x", *VALUES[1:]],
        [1, 2, 3],
        None,
    ):
        assert echo_matches(allocation.data, values) is False
    assert echo_matches(b"\xff", list(VALUES)) is False
    broken = json.dumps({"schema": SNAPSHOT_SCHEMA, "records": [1, 2, 3]}).encode()
    assert echo_matches(broken, list(VALUES)) is False


def test_output_snapshot_and_payload():
    allocation = build_snapshot(template(1))
    assert allocation is not None
    snapshot = output_snapshot(JOB, allocation, 1000)
    assert snapshot.sha256 == allocation.sha256
    assert snapshot.byte_length == len(allocation.data)
    assert (
        snapshot.terminal.kind is TerminalKind.EXIT_CODE
        and snapshot.terminal.value == 0
    )
    assert snapshot.retained_until_ms == 1000 + RETENTION_MS
    assert snapshot.source_kind is SourceKind.CONTROLLER_SEALED_SYNTHETIC
    payload = MemoryPayload(allocation.data)
    assert payload.read(len(allocation.data)) == Success(allocation.data)
    assert payload.read(1) == Failure(payload.read(1).error)
    assert isinstance(payload.read(True), Failure)
    assert payload.read(0).error.code is ErrorCode.OUTPUT_CHANGED
    assert repr(payload) == "MemoryPayload(<sealed>)"
