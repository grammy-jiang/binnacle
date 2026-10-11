"""E2 §2.6 wire handoff: the native FastMCP path serializes the returned result.

The serialized ``tools/call`` result bytes carry a hint only for jobs whose
lab ``emit`` row is EMITTED. A commit failure, a control arm (adapter off) or
a suppressed render returns the original bytes, and the jobs are never
re-hinted after an abort.
"""

import json

import pytest

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import META_KEY
from tests.contracts.job_awareness.e2_composition import (
    NOTE,
    E2Server,
    chat,
    running,
)
from tests.contracts.job_awareness.e2_scoring import ledger_rows
from tests.contracts.job_awareness.synthetic_app import in_loop

_NOTE_TEXT = f'{{"text":"{NOTE}","type":"text"}}'
_TAIL = f'"isError":false,"structuredContent":{{"note":"{NOTE}"}}}}'
PLAIN = f'{{"content":[{_NOTE_TEXT}],{_TAIL}'


def expected(carrier: HintCarrier, keys: list[str]) -> str:
    hint = "[Binnacle job reminder] " + "; ".join(f"{k} unconfirmed" for k in keys)
    if carrier is HintCarrier.META:
        return f'{{"_meta":{{"{META_KEY}":"{hint}"}},"content":[{_NOTE_TEXT}],{_TAIL}'
    block = f'{{"text":"{hint}","type":"text"}}'
    return f'{{"content":[{_NOTE_TEXT},{block}],{_TAIL}'


def emit_states(server: E2Server) -> dict[str, str]:
    rows = ledger_rows(server, "SELECT jobref,state FROM emit")
    return {str(job): str(state) for job, state in rows}


class Fault:
    def __init__(self) -> None:
        self.armed: str | None = None

    def __call__(self, point: str) -> None:
        if point == self.armed:
            raise RuntimeError("injected")


async def start_sealed(server, wire, who, slots):
    handles = []
    for slot in slots:
        call = await wire.call(who, "fixture_start", {"slot": slot})
        handles.append(str(call.data["job"]))
        await server.seal(who, handles[-1])
    return handles


@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@in_loop
async def test_serialized_bytes_carry_exactly_the_emitted_jobs(tmp_path, carrier):
    server = E2Server(tmp_path / "phase", carrier=carrier)
    server.adapter = server.build_adapter(enabled=True)
    who = chat("wire-A")
    async with running(server) as wire:
        await start_sealed(server, wire, who, ["R3-SYN-JOB-01", "R3-SYN-JOB-02"])
        await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-03"})  # unsealed
        call = await wire.call(who, "fixture_unrelated_read")
        emitted = sorted(k for k, v in emit_states(server).items() if v == "EMITTED")
        assert len(emitted) == 2  # nosec B101 - pytest assertion
        assert call.raw.decode() == expected(carrier, emitted)  # nosec B101 - pytest assertion
        assert call.row["emit_state"] == "EMITTED"  # nosec B101 - pytest assertion
        again = await wire.call(who, "fixture_unrelated_read")
        assert again.raw.decode() == PLAIN  # nosec B101 - pytest assertion
    for key, state in emit_states(server).items():
        assert (key.encode() in call.raw) is (state == "EMITTED")  # nosec B101 - pytest assertion


@pytest.mark.parametrize("point", ["lab:commit", "lab:reserve"])
@in_loop
async def test_store_failure_returns_original_bytes_and_never_rehints(tmp_path, point):
    fault = Fault()
    server = E2Server(tmp_path / "phase", faults=fault)
    who = chat("wire-B")
    async with running(server) as wire:
        await start_sealed(server, wire, who, ["R3-SYN-JOB-01"])
        fault.armed = point
        failed = await wire.call(who, "fixture_unrelated_read")
        fault.armed = None
        assert failed.raw.decode() == PLAIN  # nosec B101 - pytest assertion
        after = set(emit_states(server).values())
        assert after == ({"ABORTED"} if point == "lab:commit" else {"PENDING"})  # nosec B101 - pytest assertion
        later = await wire.call(who, "fixture_unrelated_read")
    hinted = point == "lab:reserve"  # a failed reserve wrote nothing: still PENDING
    assert (later.raw.decode() != PLAIN) is hinted  # nosec B101 - pytest assertion


@in_loop
async def test_control_arm_keeps_original_bytes_and_jobs_pending(tmp_path):
    server = E2Server(tmp_path / "phase")
    server.adapter = server.build_adapter(enabled=False)
    who = chat("wire-C")
    async with running(server) as wire:
        await start_sealed(server, wire, who, ["R3-SYN-JOB-01"])
        control = await wire.call(who, "fixture_unrelated_read")
        assert control.raw.decode() == PLAIN  # nosec B101 - pytest assertion
        assert set(emit_states(server).values()) == {"PENDING"}  # nosec B101 - pytest assertion
        server.adapter = server.build_adapter(enabled=True)
        hinted = await wire.call(who, "fixture_unrelated_read")
    assert json.loads(hinted.raw)["_meta"][META_KEY].endswith("unconfirmed")  # nosec B101 - pytest assertion
    assert set(emit_states(server).values()) == {"EMITTED"}  # nosec B101 - pytest assertion
