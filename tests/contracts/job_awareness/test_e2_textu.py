"""E2 g5 §9.2 S-2 in process: the v2-U lab tool through the full composition.

The real SessionLab, the real ``adapt_routed`` with the TEXT carrier on
``fixture_unrelated_read`` v2-U (no output schema, one text block) and the S3
extraction over native streamable HTTP. TC-1..TC-5 are re-run on v2-U. The
canonical key that the reminder prints is a lab selector for its owner only;
every other chat gets the uniform ``DENIED`` bytes. No raw platform value
reaches a result, a log row, an argument log or a lab file.
"""

import json
import re

import pytest

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_session import format_fields, raw_value_hits
from tests.contracts.job_awareness.e2_composition import (
    HINT_PREFIX,
    NOTE,
    E2Server,
    chat,
    running,
)
from tests.contracts.job_awareness.e2_scoring import emitted_handles, exports, score
from tests.contracts.job_awareness.e2_subphases import DENIED, SUBPHASES
from tests.contracts.job_awareness.synthetic_app import in_loop
from tests.unit.core.job_awareness.session_support import REGISTERED

_CANONICAL = re.compile(r"ja1_[0-9a-f]{32}:[0-9a-f]{12}:g1_[0-9a-f]{32}")
_RAW = re.compile(rb"v1/[A-Za-z0-9_-]{40,}")


def text_u(path) -> E2Server:
    return E2Server(path, carrier=HintCarrier.TEXT, structured=False)


def scan(server: E2Server, raws: list[bytes]) -> list[str]:
    """Raw platform values in any wire result, log row or lab export."""
    blobs = list(raws) + [format_fields(row).encode() for row in server.rows]
    blobs += exports(server)
    return [
        hit for b in blobs for hit in raw_value_hits(b.decode("latin-1"), REGISTERED)
    ]


def test_lab_tool_v2u_is_registered_without_output_schema(tmp_path):
    server = text_u(tmp_path / "phase")
    assert server.tool.output_schema is None  # nosec B101 - pytest assertion
    assert server.adapter.schema is not None  # nosec B101 - pytest assertion
    with pytest.raises(ValueError, match="TEXT"):
        E2Server(tmp_path / "structured", carrier=HintCarrier.TEXT)


@pytest.mark.parametrize("name", sorted(SUBPHASES))
@in_loop
async def test_tc_subphase_passes_on_text_u(tmp_path, name):
    server = text_u(tmp_path / name)
    async with running(server) as wire:
        record, n5 = await SUBPHASES[name](server, wire)
        raws = [call.raw for call in wire.calls]
        notes = [c for c in wire.calls if c.tool == "fixture_unrelated_read"]
    assert [c.name for c in record.checks if not c.ok] == []  # nosec B101 - pytest assertion
    result = score(
        record,
        emitted=emitted_handles(server),
        n5=n5 if name == "TC-5" else None,
        exports=exports(server),
    )
    assert result.verdict == "PASS", result  # nosec B101 - pytest assertion
    assert notes and all("structuredContent" not in c.result for c in notes)  # nosec B101 - pytest assertion
    assert any(c.hints for c in notes)  # nosec B101 - pytest assertion
    assert scan(server, raws) == []  # nosec B101 - pytest assertion


@pytest.mark.timeout(600)
@in_loop
async def test_tc_subphases_share_one_text_u_phase(tmp_path):
    server = text_u(tmp_path / "tc-phase")
    verdicts = {}
    async with running(server) as wire:
        for name, function in sorted(SUBPHASES.items()):
            record, n5 = await function(server, wire)
            verdicts[name] = score(
                record, emitted=emitted_handles(server), n5=n5, exports=exports(server)
            ).verdict
    assert set(verdicts.values()) == {"PASS"}, verdicts  # nosec B101 - pytest assertion


@in_loop
async def test_visible_shape_is_the_note_then_one_reminder_block(tmp_path):
    server = text_u(tmp_path / "phase")
    who = chat("shape-A")
    async with running(server) as wire:
        handle = str(
            (await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-01"})).data[
                "job"
            ]
        )
        await server.seal(who, handle)
        hinted = await wire.call(who, "fixture_unrelated_read")
        again = await wire.call(who, "fixture_unrelated_read")
    body = json.loads(hinted.raw)
    assert set(body) == {"content", "isError"}  # nosec B101 - pytest assertion
    first, reminder = body["content"]
    assert first == {"type": "text", "text": NOTE}  # nosec B101 - pytest assertion
    assert reminder["type"] == "text" and reminder["text"].startswith(HINT_PREFIX)  # nosec B101 - pytest assertion
    (key,) = _CANONICAL.findall(reminder["text"])
    assert reminder["text"] == f"{HINT_PREFIX}{key} unconfirmed"  # nosec B101 - pytest assertion
    assert key.split(":")[1] == handle.removeprefix("j_")  # nosec B101 - pytest assertion
    assert json.loads(again.raw) == {  # nosec B101 - pytest assertion
        "content": [{"type": "text", "text": NOTE}],
        "isError": False,
    }


@in_loop
async def test_canonical_key_selector_is_owner_scoped_on_the_wire(tmp_path):
    """The model copies the printed key: its owner reads, nobody else does."""
    server = text_u(tmp_path / "phase")
    owner, other, stranger = chat("key-A"), chat("key-B"), chat("key-C", "SYNTHM2")
    async with running(server) as wire:
        start = await wire.call(owner, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        handle = str(start.data["job"])
        await server.seal(owner, handle)
        await wire.call(other, "fixture_start", {"slot": "R3-SYN-JOB-02"})
        hinted = await wire.call(owner, "fixture_unrelated_read")
        (key,) = _CANONICAL.findall(hinted.result["content"][-1]["text"])
        own = [
            await wire.call(owner, "fixture_read", {"job": key, "page": p})
            for p in (0, 1, 2)
        ]
        by_handle = await wire.call(owner, "fixture_read", {"job": handle, "page": 0})
        echo = await wire.call(
            owner,
            "fixture_echo",
            {"job": key, "values": [p.data["value"] for p in own]},
        )
        ns, job_id, incarnation = key.split(":")
        guessed = [
            key,
            f"{ns}:{job_id}:g1_" + "0" * 32,
            f"{ns}:000000000000:{incarnation}",
            key.upper(),
            key + " ",
            key[:-1],
        ]
        denied = []
        for who in (other, stranger):
            for selector in guessed:
                denied.append(
                    await wire.call(who, "fixture_read", {"job": selector, "page": 0})
                )
                denied.append(
                    await wire.call(
                        who, "fixture_echo", {"job": selector, "values": []}
                    )
                )
        for selector in guessed[1:]:
            denied.append(
                await wire.call(owner, "fixture_read", {"job": selector, "page": 0})
            )
        await server.close(owner)
        denied.append(await wire.call(owner, "fixture_read", {"job": key, "page": 0}))
        raws = [call.raw for call in wire.calls]
    assert [p.error for p in own] == [None, None, None]  # nosec B101 - pytest assertion
    assert own[0].data == by_handle.data  # nosec B101 - pytest assertion
    assert echo.data == {"ok": True}  # nosec B101 - pytest assertion
    assert denied and {call.raw for call in denied} == {DENIED}  # nosec B101 - pytest assertion
    assert scan(server, raws) == []  # nosec B101 - pytest assertion
    for raw in raws:
        assert _RAW.search(raw) is None  # nosec B101 - pytest assertion
