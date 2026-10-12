"""TEXTU-01 extended to STRUCT (g6 §9.2 S-1): the carrier holds on every call.

A STRUCT binding stays STRUCT, and a schema-backed binding of the same
declared-field schema bound as META stays META. A carrier, snapshot or
bindings change after bind returns the original object with no rendered
job, consumes no receipt, reads no observation state, and on the real lab
ledger resets the reservation so the job stays ``PENDING``.
"""

from dataclasses import replace
from threading import Event

import pytest

from binnacle.features.commands.job_awareness.models import HintCarrier
from tests.contracts.job_awareness import e2_cprime as cp
from tests.contracts.job_awareness.e2_composition import NOTE, chat, running
from tests.contracts.job_awareness.e2_scoring import ledger_rows
from tests.contracts.job_awareness.routed_support import RoutedLab
from tests.contracts.job_awareness.synthetic_app import in_loop
from tests.contracts.job_awareness.test_hint_routed_textu_negatives import issued
from tests.contracts.job_awareness.test_hint_schema_support import executed

META, TEXT, STRUCT = HintCarrier.META, HintCarrier.TEXT, HintCarrier.STRUCT
DRIFT = [(STRUCT, META), (STRUCT, TEXT), (META, STRUCT)]
IDS = ["STRUCT-to-META", "STRUCT-to-TEXT", "META-to-STRUCT"]
UNHINTED = cp.frozen()["c_prime"]["wire_legacy"]["unhinted"]


def bound(lab: RoutedLab, carrier: HintCarrier):
    adapter = lab.routed(schema=cp.CPRIME_SCHEMA, enabled=True, carrier=carrier)
    assert adapter.routed_carrier is carrier  # nosec B101 - pytest assertion
    assert adapter.struct_bound is (carrier is STRUCT)  # nosec B101 - pytest assertion
    return adapter


@pytest.mark.parametrize(("carrier", "drift"), DRIFT, ids=IDS)
@in_loop
async def test_drift_is_refused_at_admission(carrier, drift):
    with RoutedLab(2) as lab:
        adapter = bound(lab, carrier)
        adapter.carrier = drift
        value = cp.cprime_result(NOTE)
        receipt = executed(value, adapter.bound_tool)
        outcome = await adapter.adapt_routed(
            value, execution=receipt, route=lab.route(*lab.jobs)
        )
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion
        assert issued(receipt)  # nosec B101 - pytest assertion
        adapter.carrier = carrier  # restored: the same binding hints again
        _, again = await lab.call(adapter, lab.route(*lab.jobs), cp.cprime_result(NOTE))
        assert again.rendered  # nosec B101 - pytest assertion


@pytest.mark.parametrize(("carrier", "drift"), DRIFT, ids=IDS)
def test_render_core_rechecks_the_carrier(carrier, drift):
    with RoutedLab(1) as lab:
        adapter = bound(lab, carrier)
        value = cp.cprime_result(NOTE)
        args = (Event(), lab.handle, (lab.job,))
        hinted, rendered = adapter._render(value, *args, routed=True)
        assert hinted is not value and rendered == (lab.job,)  # nosec B101 - pytest assertion
        adapter.carrier = drift
        assert adapter._render(value, *args, routed=True) == (value, ())  # nosec B101 - pytest assertion
        adapter.carrier = carrier
        object.__setattr__(adapter, "routed_carrier", drift)
        assert adapter._render(value, *args, routed=True) == (value, ())  # nosec B101 - pytest assertion


@in_loop
async def test_snapshot_or_bindings_changed_after_bind_suppress():
    with RoutedLab(1) as lab:
        cleared = bound(lab, STRUCT)
        cleared.struct_bound = False  # now expected META, carrier STRUCT
        forged = bound(lab, META)
        forged.struct_bound = True  # now expected STRUCT, recorded META
        unbound = bound(lab, STRUCT)
        unbound.bindings = replace(unbound.bindings, struct=None)
        for adapter in (cleared, forged, unbound):
            value, outcome = await lab.call(
                adapter, lab.route(lab.job), cp.cprime_result(NOTE)
            )
            assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("drift", [META, TEXT])
@in_loop
async def test_drift_on_the_wire_returns_original_bytes_and_resets(tmp_path, drift):
    server = cp.v2s_server(tmp_path / "phase")
    who = chat("drift-S")
    async with running(server) as wire:
        start = await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        await server.seal(who, str(start.data["job"]))
        server.adapter.carrier = drift
        drifted = await wire.call(who, "fixture_unrelated_read")
        states = {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}
        server.adapter.carrier = STRUCT
        restored = await wire.call(who, "fixture_unrelated_read")
    assert drifted.raw.decode() == UNHINTED and drifted.row["ja_hint"] == "0"  # nosec B101 - pytest assertion
    assert states == {"PENDING"}  # nosec B101 - pytest assertion
    assert restored.hints and restored.raw.decode() != UNHINTED  # nosec B101 - pytest assertion
    final = {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}
    assert final == {"EMITTED"}  # nosec B101 - pytest assertion
