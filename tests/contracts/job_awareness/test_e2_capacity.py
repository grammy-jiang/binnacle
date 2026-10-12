"""E2 §4.6 capacity dry run over all 72 frozen A/B arm slots, real ``Limits``.

``fixtures/e2_ab`` is an exact in-repo copy of the frozen R3 E0 inputs: the
72 arms of ``ab-pairs.json`` (sha256 pinned) and the 12 frozen payloads.
When the frozen run directory exists on this host, a test re-derives the copy
from it. One carrier = one phase with its own ledger pair and epoch. STRUCT is
``NOT_RUN`` in E2, so its arms run the lifecycle with the adapter off.

g5 §9.2 S-2: routed TEXT runs only on the v2-U lab tool (no output schema),
so the TEXT block runs TEXT-U. The META and STRUCT blocks also run once more
relabeled to TEXT-U, so all 72 frozen slots pass the TEXT-U lab tool.
"""

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.features.commands.job_awareness.receipt_schema import Limits
from binnacle.features.commands.job_awareness.session_lab import LabConfig
from binnacle.features.commands.job_awareness.session_snapshot import FrozenTemplate
from tests.contracts.job_awareness.e2_composition import (
    E2Server,
    chat,
    hinted_keys,
    running,
)
from tests.contracts.job_awareness.e2_scoring import (
    emitted_handles,
    exports,
    ledger_rows,
    score,
)
from tests.contracts.job_awareness.e2_subphases import SUBPHASES
from tests.contracts.job_awareness.synthetic_app import in_loop

FIXTURES = Path(__file__).parent / "fixtures" / "e2_ab"
SOURCE_SHA256 = "7360a4a3d0b9482325627a59a473a413306a48f32aba2b8d2590e1266f19c265"
FROZEN = (
    Path.home()
    / "Projects/binnacle-job-awareness-r3-results/R3-20261010-201023-74abf737/E0"
)
SLOTS = json.loads((FIXTURES / "slots.json").read_text())
ARM_KEYS = (
    "pair_id",
    "carrier",
    "execution_rank_within_carrier",
    "job_id",
    "fixture_payload_sha256",
    "nonce_sha256",
    "expected_values",
    "expected_pages",
)


def templates() -> dict[str, FrozenTemplate]:
    frozen: dict[str, FrozenTemplate] = {}
    for arm in SLOTS["arms"]:
        payload = (FIXTURES / f"{arm['job_id']}.json").read_bytes()
        frozen[arm["job_id"]] = FrozenTemplate(
            arm["job_id"], payload, arm["fixture_payload_sha256"], arm["nonce_sha256"]
        )
    return frozen


def receipt_rows(server: E2Server, sql: str) -> list[tuple[object, ...]]:
    path = Path(server.phase) / "receipt" / "receipt.sqlite"
    db = sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)
    try:
        return list(db.execute(sql).fetchall())
    finally:
        db.close()


def test_slot_table_is_the_pinned_frozen_input():
    assert SLOTS["source_sha256"] == SOURCE_SHA256  # nosec B101 - pytest assertion
    arms = SLOTS["arms"]
    assert len(arms) == 72 == 2 * SLOTS["total_pair_slots"]  # nosec B101 - pytest assertion
    assert Counter(a["carrier"] for a in arms) == {"META": 24, "TEXT": 24, "STRUCT": 24}  # nosec B101 - pytest assertion
    for arm in arms:
        payload = (FIXTURES / f"{arm['job_id']}.json").read_bytes()
        assert hashlib.sha256(payload).hexdigest() == arm["fixture_payload_sha256"]  # nosec B101 - pytest assertion
        nonce = json.loads(payload)["nonce"].encode()
        assert hashlib.sha256(nonce).hexdigest() == arm["nonce_sha256"]  # nosec B101 - pytest assertion


def test_in_repo_copy_equals_the_frozen_run():
    """Host-local re-derivation; elsewhere the pinned hashes above stand alone."""
    if not FROZEN.is_dir():
        return
    raw = (FROZEN / "ab-pairs.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256  # nosec B101 - pytest assertion
    pairs = json.loads(raw)["pairs"]
    derived = [
        {key: pair[key] for key in ARM_KEYS} | {"arm": arm}
        for pair in pairs
        for arm in pair["arm_order"]
    ]
    assert derived == SLOTS["arms"]  # nosec B101 - pytest assertion
    for pair in pairs:
        frozen = Path(pair["fixture_payload_ref"]).read_bytes()
        assert frozen == (FIXTURES / f"{pair['job_id']}.json").read_bytes()  # nosec B101 - pytest assertion


async def run_arm(server, wire, arm, *, adapter_on):
    """open -> allocate -> seal at the terminal point -> work -> close."""
    who = chat(f"{arm['pair_id']}-{arm['arm']}")
    server.adapter = server.build_adapter(enabled=adapter_on)
    wire.send()
    start = await wire.call(who, "fixture_start", {"slot": arm["job_id"]})
    handle = str(start.data["job"])
    await server.seal(who, handle)
    note = await wire.call(who, "fixture_unrelated_read")
    values = []
    for page in arm["expected_pages"]:
        read = await wire.call(who, "fixture_read", {"job": handle, "page": page})
        values.append(read.data["value"])
    echo = await wire.call(who, "fixture_echo", {"job": handle, "values": values})
    binding = server.lab.table.get(server.key(who).kd)
    live = 0 if binding is None else len(binding.jobs)
    retired = await server.close(who)
    return {
        "errors": [c.error for c in wire.calls[-6:] if c.error],
        "route": note.row["ja_route"],
        "hint": note.row.get("ja_job"),
        "handle": handle,
        "values": values,
        "echo": echo.data,
        "live": live,
        "retired": retired,
        "grant_after_close": None if binding is None else binding.grant,
        "remaining": note.row.get("grant_remaining_ms"),
    }


#: (frozen block, lab mode). OFF = adapter off for every arm (STRUCT NOT_RUN).
BLOCKS = [
    ("META", "META"),
    ("TEXT", "TEXT-U"),
    ("STRUCT", "OFF"),
    ("META", "TEXT-U"),
    ("STRUCT", "TEXT-U"),
]


@pytest.mark.timeout(600)
@pytest.mark.parametrize(("carrier", "mode"), BLOCKS)
@in_loop
async def test_capacity_dry_run_all_arms_of_one_carrier_phase(tmp_path, carrier, mode):
    arms = sorted(
        (a for a in SLOTS["arms"] if a["carrier"] == carrier),
        key=lambda a: (a["execution_rank_within_carrier"], a["arm"] != "CONTROL"),
    )
    text_u = mode == "TEXT-U"
    server = E2Server(
        tmp_path / carrier,
        templates=templates(),
        config=LabConfig(ttl_ms=1800000, deferred_seal=True),
        carrier=HintCarrier.TEXT if text_u else HintCarrier.META,
        structured=not text_u,
    )
    results = []
    async with running(server) as wire:
        for arm in arms:
            on = mode != "OFF" and arm["arm"] == "CANDIDATE"
            results.append((arm, await run_arm(server, wire, arm, adapter_on=on)))
        notes = [c for c in wire.calls if c.tool == "fixture_unrelated_read"]
    for arm, result in results:
        assert result["errors"] == [] and result["route"] == "BOUND"  # nosec B101 - pytest assertion
        assert result["values"] == arm["expected_values"]  # nosec B101 - pytest assertion
        assert result["echo"] == {"ok": True}  # nosec B101 - pytest assertion
        hinted = mode != "OFF" and arm["arm"] == "CANDIDATE"
        assert (result["hint"] == result["handle"]) is hinted  # nosec B101 - pytest assertion
    assert len(notes) == 24  # nosec B101 - pytest assertion
    for call in notes:
        assert ("structuredContent" in call.result) is not text_u  # nosec B101 - pytest assertion
        blocks = len(call.result["content"])
        assert blocks == (1 + len(call.hints) if text_u else 1)  # nosec B101 - pytest assertion
        assert result["live"] == 1 and result["retired"] == 1  # nosec B101 - pytest assertion
        assert result["grant_after_close"] is None and int(result["remaining"]) > 0  # nosec B101 - pytest assertion
    keys = ledger_rows(server, "SELECT kd,ns FROM keys")
    alloc = ledger_rows(server, "SELECT jobref,kd,state FROM alloc")
    ns_of = dict(keys)
    assert len(keys) == len(arms) == len(alloc) == 24  # nosec B101 - pytest assertion
    assert all(str(j).startswith(str(ns_of[k]) + ":") for j, k, _ in alloc)  # nosec B101 - pytest assertion
    assert {state for _, _, state in alloc} == {"RETIRED"}  # nosec B101 - pytest assertion
    limits = Limits()
    grants = receipt_rows(server, "SELECT count(*), sum(revoked) FROM grants")[0]
    snapshots = receipt_rows(server, "SELECT count(*) FROM snapshots")[0][0]
    epochs = receipt_rows(server, "SELECT count(*) FROM epochs")[0][0]
    assert grants[0] == grants[1] == 24 <= limits.grants  # nosec B101 - pytest assertion
    assert snapshots == 24 <= limits.snapshots and epochs <= limits.epochs  # nosec B101 - pytest assertion
    assert not any("QUOTA_EXCEEDED" in repr(e) for e in server.events)  # nosec B101 - pytest assertion
    assert len(emitted_handles(server)) == (0 if mode == "OFF" else 12)  # nosec B101 - pytest assertion
    hints = [key for call in notes for key in hinted_keys(call.result)]
    assert len(hints) == len(set(hints)) == (0 if mode == "OFF" else 12)  # nosec B101 - pytest assertion


@pytest.mark.timeout(600)
@in_loop
async def test_capacity_all_tc_subphases_in_one_phase(tmp_path):
    """TC-1..TC-5 share one phase ledger pair: each passes, then all retire."""
    server = E2Server(tmp_path / "tc-phase")
    verdicts, chats = {}, set()
    async with running(server) as wire:
        for name, function in sorted(SUBPHASES.items()):
            before = len(ledger_rows(server, "SELECT jobref FROM alloc"))
            record, n5 = await function(server, wire)
            allocated = len(ledger_rows(server, "SELECT jobref FROM alloc")) - before
            assert allocated <= 6  # nosec B101 - pytest assertion
            result = score(
                record, emitted=emitted_handles(server), n5=n5, exports=exports(server)
            )
            verdicts[name] = result.verdict
            chats |= set(record.owner_of.values())
        for name in sorted(chats):
            await server.close(chat(name))
    assert set(verdicts.values()) == {"PASS"}, verdicts  # nosec B101 - pytest assertion
    states = {row[0] for row in ledger_rows(server, "SELECT state FROM alloc")}
    assert states == {"RETIRED"}  # nosec B101 - pytest assertion
    grants = receipt_rows(server, "SELECT count(*), sum(revoked) FROM grants")[0]
    assert grants[0] == grants[1] <= Limits().grants  # nosec B101 - pytest assertion
    keys = ledger_rows(server, "SELECT kd FROM keys")
    assert len(keys) == len({k for (k,) in keys})  # nosec B101 - pytest assertion
