"""E2 S5: §4.4 three-chat isolation sub-phases in process (design §3, §4.4).

Real SessionLab + real ``adapt_routed`` + S3 MCP extraction over native
streamable HTTP. Every sub-phase uses fresh chats, fresh allocations and its
own ledger pair and epoch, with the TC grant TTL (60 min) and real ``Limits``.
"""

from dataclasses import replace

import pytest

from tests.contracts.job_awareness.e2_composition import E2Server, chat, running
from tests.contracts.job_awareness.e2_scoring import (
    INHERITED,
    Item,
    Record,
    emitted_handles,
    exports,
    score,
)
from tests.contracts.job_awareness.e2_subphases import SUBPHASES, Turn, tc1, tc4
from tests.contracts.job_awareness.synthetic_app import in_loop


async def run_subphase(tmp_path, name):
    server = E2Server(tmp_path / name)
    async with running(server) as wire:
        record, n5 = await SUBPHASES[name](server, wire)
    return server, record, n5


@pytest.mark.parametrize("name", sorted(SUBPHASES))
@in_loop
async def test_subphase_passes_with_valid_pending_proofs(tmp_path, name):
    server, record, n5 = await run_subphase(tmp_path, name)
    failed = [check.name for check in record.checks if not check.ok]
    assert failed == []  # nosec B101 - pytest assertion
    negatives = [check for check in record.checks if check.proof is not None]
    assert negatives and all(c.proof.valid for c in negatives)  # nosec B101 - pytest assertion
    result = score(
        record,
        emitted=emitted_handles(server),
        n5=n5 if name == "TC-5" else None,
        exports=exports(server),
    )
    assert result.verdict == "PASS", result  # nosec B101 - pytest assertion
    assert (n5 is True) == (name == "TC-5")  # nosec B101 - pytest assertion
    remaining = [
        int(r["grant_remaining_ms"])
        for _, r in record.rows
        if "grant_remaining_ms" in r
    ]
    assert remaining and min(remaining) > 0  # nosec B101 - pytest assertion


@in_loop
async def test_tc1_three_chats_map_to_three_keys_and_one_hint_each(tmp_path):
    server, record, _ = await run_subphase(tmp_path, "TC-1")
    assert len(set(record.keys.values())) == 3  # nosec B101 - pytest assertion
    hints = [r for _, r in record.rows if r.get("ja_hint") == "1"]
    assert len(hints) == 3 == len(emitted_handles(server))  # nosec B101 - pytest assertion
    namespaces = {key: set() for key in record.keys.values()}
    for kd in namespaces:
        binding = server.lab.table.get(kd)
        assert binding is not None  # nosec B101 - pytest assertion
        namespaces[kd] = {job.run_namespace for job in binding.jobs}
    assert all(len(ns) == 1 for ns in namespaces.values())  # nosec B101 - pytest assertion


@in_loop
async def test_negative_after_emission_is_void_not_pass(tmp_path):
    """A negative that finds the target already EMITTED is VOID, never PASS."""
    server = E2Server(tmp_path / "void")
    async with running(server) as wire:
        record = Record()
        a, b = chat("void-A"), chat("void-B")
        handle = (
            await Turn(server, wire, record, a).user("Start.").start("R3-SYN-JOB-01")
        )
        await server.seal(a, handle)
        own = Turn(server, wire, record, a).user("Call fixture_unrelated_read once.")
        await own.call("fixture_unrelated_read")
        proof = record.proof(server, a, handle)
        late = Turn(server, wire, record, b).user("Call fixture_unrelated_read once.")
        call = await late.call("fixture_unrelated_read")
        record.expect("B no hint", not call.hints, proof)
    assert proof.emit == "EMITTED" and not proof.valid  # nosec B101 - pytest assertion
    result = score(record, emitted=emitted_handles(server), exports=exports(server))
    assert result.d == ["VOID:B no hint"] and result.verdict == "RERUN"  # nosec B101 - pytest assertion


@in_loop
async def test_unsealed_target_is_void_and_never_hinted(tmp_path):
    server = E2Server(tmp_path / "unsealed")
    async with running(server) as wire:
        record = Record()
        a = chat("unsealed-A")
        handle = (
            await Turn(server, wire, record, a).user("Start.").start("R3-SYN-JOB-01")
        )
        proof = record.proof(server, a, handle)
        call = (
            await Turn(server, wire, record, a)
            .user("Note.")
            .call("fixture_unrelated_read")
        )
    assert not proof.sealed and not proof.valid  # nosec B101 - pytest assertion
    assert call.hints == [] and emitted_handles(server) == set()  # nosec B101 - pytest assertion


async def _tc(tmp_path, function):
    server = E2Server(tmp_path / function.__name__)
    async with running(server) as wire:
        record, _ = await function(server, wire)
    return server, record


def _rescore(server, record, **changes):
    return score(
        replace(record, **changes),
        emitted=emitted_handles(server),
        exports=exports(server),
    )


@in_loop
async def test_scoring_negative_controls(tmp_path):
    """Each injected violation is caught by its own criterion."""
    server, record = await _tc(tmp_path, tc1)
    a_items = sorted(record.private["tc1-A"])
    canary = next(v for v in a_items if len(v) == 32 and not v.startswith(b"g1_"))
    leak = Item("tc1-B", "R", 99, b"x" + canary)
    assert _rescore(server, record, items=record.items + [leak]).c  # nosec B101 - pytest assertion
    in_m = Item("tc1-C", "M", 99, canary)
    assert _rescore(server, record, items=record.items + [in_m]).verdict == "FAIL"  # nosec B101 - pytest assertion
    first = next(i for i, (who, _) in enumerate(record.rows) if who == "tc1-B")
    rows = list(record.rows)
    other = rows[first][1] | {"ja_key": "0" * 16}
    rows[first] = ("tc1-B", other)
    assert _rescore(server, record, rows=rows).b  # nosec B101 - pytest assertion
    hint = next(i for i, (_, r) in enumerate(record.rows) if r.get("ja_hint") == "1")
    rows = list(record.rows)
    rows[hint] = (rows[hint][0], rows[hint][1] | {"ja_key": "f" * 16})
    assert _rescore(server, record, rows=rows).a  # nosec B101 - pytest assertion
    raw = Item("tc1-A", "M", 99, b"v1/" + b"Q" * 76)
    assert _rescore(server, record, items=record.items + [raw]).f  # nosec B101 - pytest assertion


@in_loop
async def test_seed_rules_are_exact_and_provenance_bound(tmp_path):
    server, record = await _tc_named(tmp_path, "TC-2")
    seed = next(s for s in record.seeds if s.data.startswith(b"j_"))
    ok = _rescore(
        server, record, items=record.items + [Item("tc2-B2", "M", seed.send, seed.data)]
    )
    assert ok.verdict == "PASS"  # nosec B101 - pytest assertion
    early = Item("tc2-B2", "A", seed.send - 1, seed.data)
    assert _rescore(server, record, items=record.items + [early]).c  # nosec B101 - pytest assertion
    in_r = Item("tc2-B2", "R", seed.send, seed.data)
    assert _rescore(server, record, items=record.items + [in_r]).c  # nosec B101 - pytest assertion


async def _tc_named(tmp_path, name):
    server, record, _ = await run_subphase(tmp_path, name)
    return server, record


@in_loop
async def test_tc4_inherited_history_rule(tmp_path):
    """Quoting an inherited item passes; a new F_A4 item in the branch fails."""
    server, record = await _tc(tmp_path, tc4)
    inherited = [i for i in record.items if i.provenance == INHERITED]
    assert inherited and all(i.chat == "tc4-branch" for i in inherited)  # nosec B101 - pytest assertion
    handle = next(h for h, who in record.owner_of.items() if who == "tc4-A4")
    send = record.boundaries["tc4-branch"][1]
    quoted = Item("tc4-branch", "M", send, f"Job {handle} is denied.".encode())
    assert _rescore(server, record, items=record.items + [quoted]).verdict == "PASS"  # nosec B101 - pytest assertion
    in_result = Item("tc4-branch", "R", send, handle.encode())
    assert _rescore(server, record, items=record.items + [in_result]).c  # nosec B101 - pytest assertion
    fresh = [v for v in record.private["tc4-A4"] if v.startswith(b"ja1_")]
    new = Item("tc4-branch", "M", send, fresh[0])
    assert _rescore(server, record, items=record.items + [new]).c  # nosec B101 - pytest assertion
