"""Review TEXTU-01: the routed carrier rule holds on every call, not only at bind.

A schema-backed routed binding stays META, and a ``NO_STRUCTURE`` binding
stays TEXT. Routed adapters are immutable (plain assignment raises, see
``test_hint_routed_immutable``); these tests use the trusted-code bypass
``object.__setattr__`` (out of model) to prove the per-call checks as
defence in depth. A carrier changed after bind returns the original object with
no rendered job, consumes no receipt, reads no observation state, and on the
real lab ledger resets the reservation so the job stays ``PENDING``.
"""

from threading import Event

import pytest

from binnacle.features.commands.job_awareness.models import HintCarrier
from tests.contracts.job_awareness.e2_composition import E2Server, chat, running
from tests.contracts.job_awareness.e2_scoring import ledger_rows
from tests.contracts.job_awareness.routed_support import RoutedLab, text_only
from tests.contracts.job_awareness.synthetic_app import in_loop, original
from tests.contracts.job_awareness.test_e2_wire_handoff import PLAIN, PLAIN_U
from tests.contracts.job_awareness.test_hint_routed_textu_negatives import issued
from tests.contracts.job_awareness.test_hint_schema_support import executed

META, TEXT = HintCarrier.META, HintCarrier.TEXT
#: (bound carrier, carrier after bind, schema-backed tool)
DRIFT = [(META, TEXT, True), (TEXT, META, False)]
IDS = ["schema-META-to-TEXT", "TEXT-U-to-META"]


def force(adapter, name: str, value: object) -> None:
    """Trusted in-process bypass of the routed immutability (out of model)."""
    object.__setattr__(adapter, name, value)


def bound(lab: RoutedLab, carrier: HintCarrier, structured: bool):
    adapter = lab.routed(structured=structured, enabled=True, carrier=carrier)
    assert adapter.routed_carrier is carrier  # nosec B101 - pytest assertion
    return adapter


def value_for(structured: bool):
    return original() if structured else text_only()


@pytest.mark.parametrize(("carrier", "drift", "structured"), DRIFT, ids=IDS)
@in_loop
async def test_carrier_reassigned_after_bind_is_refused_at_admission(
    carrier, drift, structured
):
    with RoutedLab(2) as lab:
        adapter = bound(lab, carrier, structured)
        force(adapter, "carrier", drift)
        value = value_for(structured)
        receipt = executed(value, adapter.bound_tool)
        outcome = await adapter.adapt_routed(
            value, execution=receipt, route=lab.route(*lab.jobs)
        )
        assert outcome.result is value and outcome.rendered == ()  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion
        assert issued(receipt)  # nosec B101 - pytest assertion
        force(adapter, "carrier", carrier)  # restored: the same binding hints again
        _, again = await lab.call(adapter, lab.route(*lab.jobs), value_for(structured))
        assert again.rendered  # nosec B101 - pytest assertion


@pytest.mark.parametrize(("carrier", "drift", "structured"), DRIFT, ids=IDS)
def test_render_core_rechecks_the_carrier(carrier, drift, structured):
    """Defense in depth: ``_render`` refuses a drifted carrier by itself."""
    with RoutedLab(1) as lab:
        adapter = bound(lab, carrier, structured)
        value = value_for(structured)
        hinted, rendered = adapter._render(
            value, Event(), lab.handle, (lab.job,), routed=True
        )
        assert hinted is not value and rendered == (lab.job,)  # nosec B101 - pytest assertion
        force(adapter, "carrier", drift)
        assert adapter._render(value, Event(), lab.handle, (lab.job,), routed=True) == (  # nosec B101 - pytest assertion
            value,
            (),
        )
        force(adapter, "carrier", carrier)
        force(adapter, "routed_carrier", drift)
        assert adapter._render(value, Event(), lab.handle, (lab.job,), routed=True) == (  # nosec B101 - pytest assertion
            value,
            (),
        )


def test_non_routed_adapt_keeps_text_on_schema_tools():
    """``adapt`` is unchanged: no routed carrier is recorded or required."""
    with RoutedLab(1) as lab:
        adapter = lab.adapter(enabled=True, carrier=TEXT)
        assert adapter.routed_carrier is None  # nosec B101 - pytest assertion


@pytest.mark.parametrize(("carrier", "drift", "structured"), DRIFT, ids=IDS)
@in_loop
async def test_drift_on_the_wire_returns_original_bytes_and_resets(
    tmp_path, carrier, drift, structured
):
    server = E2Server(tmp_path / "phase", carrier=carrier, structured=structured)
    who = chat("drift")
    plain = PLAIN if structured else PLAIN_U
    async with running(server) as wire:
        start = await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        await server.seal(who, str(start.data["job"]))
        force(server.adapter, "carrier", drift)
        drifted = await wire.call(who, "fixture_unrelated_read")
        states = {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}
        force(server.adapter, "carrier", carrier)
        restored = await wire.call(who, "fixture_unrelated_read")
    assert drifted.raw.decode() == plain and drifted.row["ja_hint"] == "0"  # nosec B101 - pytest assertion
    assert states == {"PENDING"}  # nosec B101 - pytest assertion
    assert restored.hints and restored.raw.decode() != plain  # nosec B101 - pytest assertion
    final = {str(s) for (s,) in ledger_rows(server, "SELECT state FROM emit")}
    assert final == {"EMITTED"}  # nosec B101 - pytest assertion
