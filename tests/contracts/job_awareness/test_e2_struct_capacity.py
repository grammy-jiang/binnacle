"""E2 g6 §9.2 S-1 on v2-S: wire handoff and the capacity dry run.

Serialized ``tools/call`` bytes carry a STRUCT hint only for jobs whose lab
``emit`` row is EMITTED. A store failure or the control arm (adapter off)
returns the frozen c′ unhinted bytes. The capacity dry run covers all 72
frozen A/B arm slots on the v2-S lab tool: the STRUCT block, and the META
and TEXT blocks relabeled to STRUCT.
"""

import json
from typing import cast

import pytest
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.receipt_schema import Limits
from binnacle.features.commands.job_awareness.session_lab import LabConfig
from binnacle.mcp.job_awareness_hint import HINT_FIELD
from tests.contracts.job_awareness import e2_cprime as cp
from tests.contracts.job_awareness.e2_composition import (
    NOTE,
    chat,
    hinted_keys,
    running,
)
from tests.contracts.job_awareness.e2_scoring import emitted_handles, ledger_rows
from tests.contracts.job_awareness.synthetic_app import in_loop
from tests.contracts.job_awareness.test_e2_capacity import (
    SLOTS,
    receipt_rows,
    run_arm,
    templates,
)
from tests.contracts.job_awareness.test_e2_wire_handoff import (
    Fault,
    emit_states,
    start_sealed,
)

UNHINTED = cp.frozen()["c_prime"]["wire_legacy"]["unhinted"]


def expected(keys: list[str]) -> str:
    hint = "[Binnacle job reminder] " + "; ".join(f"{k} unconfirmed" for k in keys)
    hinted = cp.cprime_result(NOTE, hint)
    mirror = json.dumps(
        {"text": cast(TextContent, hinted.content[0]).text, "type": "text"},
        separators=(",", ":"),
    )
    structured = json.dumps(hinted.structured_content, separators=(",", ":"))
    return f'{{"content":[{mirror}],"isError":false,"structuredContent":{structured}}}'


@in_loop
async def test_serialized_bytes_carry_exactly_the_emitted_jobs(tmp_path):
    server = cp.v2s_server(tmp_path / "phase")
    who = chat("wire-S")
    async with running(server) as wire:
        await start_sealed(server, wire, who, ["R3-SYN-JOB-01", "R3-SYN-JOB-02"])
        await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-03"})  # unsealed
        call = await wire.call(who, "fixture_unrelated_read")
        emitted = sorted(k for k, v in emit_states(server).items() if v == "EMITTED")
        assert len(emitted) == 2  # nosec B101 - pytest assertion
        assert call.raw.decode() == expected(emitted)  # nosec B101 - pytest assertion
        assert call.row["emit_state"] == "EMITTED"  # nosec B101 - pytest assertion
        again = await wire.call(who, "fixture_unrelated_read")
        assert again.raw.decode() == UNHINTED  # nosec B101 - pytest assertion
    for key, state in emit_states(server).items():
        assert (key.encode() in call.raw) is (state == "EMITTED")  # nosec B101 - pytest assertion


@pytest.mark.parametrize("point", ["lab:commit", "lab:reserve"])
@in_loop
async def test_store_failure_returns_original_bytes_and_never_rehints(tmp_path, point):
    fault = Fault()
    server = cp.v2s_server(tmp_path / "phase", faults=fault)
    who = chat("wire-S2")
    async with running(server) as wire:
        await start_sealed(server, wire, who, ["R3-SYN-JOB-01"])
        fault.armed = point
        failed = await wire.call(who, "fixture_unrelated_read")
        fault.armed = None
        assert failed.raw.decode() == UNHINTED  # nosec B101 - pytest assertion
        after = set(emit_states(server).values())
        assert after == ({"ABORTED"} if point == "lab:commit" else {"PENDING"})  # nosec B101 - pytest assertion
        later = await wire.call(who, "fixture_unrelated_read")
    assert (later.raw.decode() != UNHINTED) is (point == "lab:reserve")  # nosec B101 - pytest assertion


@in_loop
async def test_control_arm_keeps_original_bytes_and_jobs_pending(tmp_path):
    server = cp.v2s_server(tmp_path / "phase", enabled=False)
    who = chat("wire-S3")
    async with running(server) as wire:
        await start_sealed(server, wire, who, ["R3-SYN-JOB-01"])
        control = await wire.call(who, "fixture_unrelated_read")
        assert control.raw.decode() == UNHINTED  # nosec B101 - pytest assertion
        assert set(emit_states(server).values()) == {"PENDING"}  # nosec B101 - pytest assertion
        server.adapter = server.build_adapter(enabled=True)
        hinted = await wire.call(who, "fixture_unrelated_read")
    body = json.loads(hinted.raw)
    assert body["structuredContent"][HINT_FIELD].endswith("unconfirmed")  # nosec B101 - pytest assertion
    assert set(emit_states(server).values()) == {"EMITTED"}  # nosec B101 - pytest assertion


@pytest.mark.timeout(600)
@pytest.mark.parametrize("carrier", ["STRUCT", "META", "TEXT"])
@in_loop
async def test_capacity_dry_run_all_arms_on_v2s(tmp_path, carrier):
    arms = sorted(
        (a for a in SLOTS["arms"] if a["carrier"] == carrier),
        key=lambda a: (a["execution_rank_within_carrier"], a["arm"] != "CONTROL"),
    )
    server = cp.v2s_server(
        tmp_path / carrier,
        templates=templates(),
        config=LabConfig(ttl_ms=1800000, deferred_seal=True),
    )
    results = []
    async with running(server) as wire:
        for arm in arms:
            on = arm["arm"] == "CANDIDATE"
            results.append((arm, await run_arm(server, wire, arm, adapter_on=on)))
        notes = [c for c in wire.calls if c.tool == "fixture_unrelated_read"]
    for arm, result in results:
        assert result["errors"] == [] and result["route"] == "BOUND"  # nosec B101 - pytest assertion
        assert result["values"] == arm["expected_values"]  # nosec B101 - pytest assertion
        assert result["echo"] == {"ok": True}  # nosec B101 - pytest assertion
        hinted = arm["arm"] == "CANDIDATE"
        assert (result["hint"] == result["handle"]) is hinted  # nosec B101 - pytest assertion
        assert result["live"] == 1 and result["retired"] == 1  # nosec B101 - pytest assertion
        assert result["grant_after_close"] is None and int(result["remaining"]) > 0  # nosec B101 - pytest assertion
    assert len(notes) == 24  # nosec B101 - pytest assertion
    for call in notes:
        (block,) = call.result["content"]
        assert block["text"] == json.dumps(call.result["structuredContent"])  # nosec B101 - pytest assertion
        assert (HINT_FIELD in call.result["structuredContent"]) is bool(call.hints)  # nosec B101 - pytest assertion
    alloc = ledger_rows(server, "SELECT jobref,kd,state FROM alloc")
    assert len(alloc) == 24 and {state for *_, state in alloc} == {"RETIRED"}  # nosec B101 - pytest assertion
    limits = Limits()
    grants = receipt_rows(server, "SELECT count(*), sum(revoked) FROM grants")[0]
    snapshots = receipt_rows(server, "SELECT count(*) FROM snapshots")[0][0]
    assert grants[0] == grants[1] == 24 <= limits.grants  # nosec B101 - pytest assertion
    assert snapshots == 24 <= limits.snapshots  # nosec B101 - pytest assertion
    assert not any("QUOTA_EXCEEDED" in repr(e) for e in server.events)  # nosec B101 - pytest assertion
    assert len(emitted_handles(server)) == 12  # nosec B101 - pytest assertion
    hints = [key for call in notes for key in hinted_keys(call.result)]
    assert len(hints) == len(set(hints)) == 12  # nosec B101 - pytest assertion
