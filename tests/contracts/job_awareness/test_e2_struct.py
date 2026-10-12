"""E2 g6 §9.2 S-1 in process: the v2-S lab tool through the full composition.

The real SessionLab, the real ``adapt_routed`` with the STRUCT carrier on
``fixture_unrelated_read`` v2-S (the c′ schema and result shape) and the S3
extraction over native streamable HTTP. v2-S has the c′ ``tools/list``
(manifest hash pinned, identical for both arms). TC-1..TC-5 and the
capacity dry run run on v2-S. The hint reaches only its owner chat, in the
declared field and the one JSON mirror. No raw platform value reaches a
result, a log row, an argument log or a lab file.
"""

import json
import re
import subprocess
import sys

import pytest

from binnacle.mcp.job_awareness_hint import HINT_FIELD
from binnacle.mcp.job_awareness_hint_schema import Schema
from binnacle.mcp.job_awareness_hint_walk import Meter
from tests.contracts.job_awareness import e2_cprime as cp
from tests.contracts.job_awareness.e2_composition import (
    HINT_PREFIX,
    NOTE,
    chat,
    hinted_keys,
    running,
)
from tests.contracts.job_awareness.e2_scoring import emitted_handles, exports, score
from tests.contracts.job_awareness.e2_subphases import DENIED, SUBPHASES
from tests.contracts.job_awareness.synthetic_app import in_loop
from tests.contracts.job_awareness.test_e2_cprime import PINNED
from tests.contracts.job_awareness.test_e2_no_path import PUBLIC_TOOLS, ROOT
from tests.contracts.job_awareness.test_e2_textu import scan
from tests.integration.test_packaging_smoke import clean_env

_CANONICAL = re.compile(r"ja1_[0-9a-f]{32}:[0-9a-f]{12}:g1_[0-9a-f]{32}")
_RAW = re.compile(rb"v1/[A-Za-z0-9_-]{40,}")
#: v2-S = the frozen c′ manifest (g6 §9.2: one pinned hash for both arms).
V2S_SHA256 = PINNED["c-prime"]


def visible(call) -> tuple[dict, str]:
    """The structured content and the one mirror text of a note result."""
    (block,) = call.result["content"]
    return call.result["structuredContent"], block["text"]


@in_loop
async def test_v2s_manifest_is_the_pinned_cprime_manifest(tmp_path):
    frozen = cp.frozen()["manifests"]["c-prime"]["manifest"]
    control = await cp.capture_manifest(cp.v2s_server(tmp_path / "c", enabled=False))
    candidate = await cp.capture_manifest(cp.v2s_server(tmp_path / "s"))
    assert control == candidate == frozen  # nosec B101 - pytest assertion
    assert cp.manifest_sha256(candidate) == V2S_SHA256  # nosec B101 - pytest assertion
    assert V2S_SHA256.startswith("a9954051")  # nosec B101 - pytest assertion


def test_lab_tool_v2s_binds_struct(tmp_path):
    server = cp.v2s_server(tmp_path / "phase")
    assert server.tool.output_schema == cp.CPRIME_SCHEMA  # nosec B101 - pytest assertion
    assert server.adapter.struct_bound is True  # nosec B101 - pytest assertion
    assert server.build_adapter(enabled=False).struct_bound is True  # nosec B101 - pytest assertion


@pytest.mark.parametrize("name", sorted(SUBPHASES))
@in_loop
async def test_tc_subphase_passes_on_v2s(tmp_path, name):
    server = cp.v2s_server(tmp_path / name)
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
    assert any(c.hints for c in notes)  # nosec B101 - pytest assertion
    schema = Schema(cp.CPRIME_SCHEMA)
    for call in notes:
        structured, mirror = visible(call)
        assert schema.valid(structured, Meter())  # nosec B101 - pytest assertion
        assert mirror == json.dumps(structured)  # nosec B101 - pytest assertion
        assert (HINT_FIELD in structured) is bool(call.hints)  # nosec B101 - pytest assertion
    assert scan(server, raws) == []  # nosec B101 - pytest assertion


@pytest.mark.timeout(600)
@in_loop
async def test_tc_subphases_share_one_v2s_phase(tmp_path):
    server = cp.v2s_server(tmp_path / "tc-phase")
    verdicts = {}
    async with running(server) as wire:
        for name, function in sorted(SUBPHASES.items()):
            record, n5 = await function(server, wire)
            verdicts[name] = score(
                record, emitted=emitted_handles(server), n5=n5, exports=exports(server)
            ).verdict
    assert set(verdicts.values()) == {"PASS"}, verdicts  # nosec B101 - pytest assertion


@in_loop
async def test_visible_shape_is_the_field_and_its_mirror(tmp_path):
    server = cp.v2s_server(tmp_path / "phase")
    who = chat("shape-S")
    async with running(server) as wire:
        start = await wire.call(who, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        handle = str(start.data["job"])
        await server.seal(who, handle)
        hinted = await wire.call(who, "fixture_unrelated_read")
        again = await wire.call(who, "fixture_unrelated_read")
    structured, mirror = visible(hinted)
    (key,) = _CANONICAL.findall(structured[HINT_FIELD])
    assert structured == {  # nosec B101 - pytest assertion
        "note": NOTE,
        HINT_FIELD: f"{HINT_PREFIX}{key} unconfirmed",
    }
    assert mirror == json.dumps(structured)  # nosec B101 - pytest assertion
    assert key.split(":")[1] == handle.removeprefix("j_")  # nosec B101 - pytest assertion
    assert hinted_keys(hinted.result) == [
        key
    ]  # field only, mirror not counted  # nosec B101 - pytest assertion
    assert "_meta" not in hinted.result  # nosec B101 - pytest assertion
    hint = structured[HINT_FIELD]
    expected = cp.cprime_result(NOTE, hint)
    assert hinted.result["structuredContent"] == expected.structured_content  # nosec B101 - pytest assertion
    assert again.raw.decode() == cp.frozen()["c_prime"]["wire_legacy"]["unhinted"]  # nosec B101 - pytest assertion


@in_loop
async def test_hint_never_crosses_chats_and_key_is_owner_scoped(tmp_path):
    """Other chats get no hint of the owner's job; the key reads for its owner only."""
    server = cp.v2s_server(tmp_path / "phase")
    owner, other, stranger = (
        chat("s-key-A"),
        chat("s-key-B"),
        chat("s-key-C", "SYNTHM2"),
    )
    async with running(server) as wire:
        start = await wire.call(owner, "fixture_start", {"slot": "R3-SYN-JOB-01"})
        handle = str(start.data["job"])
        await server.seal(owner, handle)
        await wire.call(other, "fixture_start", {"slot": "R3-SYN-JOB-02"})
        foreign = [
            await wire.call(who, "fixture_unrelated_read") for who in (other, stranger)
        ]
        hinted = await wire.call(owner, "fixture_unrelated_read")
        (key,) = _CANONICAL.findall(hinted.result["structuredContent"][HINT_FIELD])
        own = [
            await wire.call(owner, "fixture_read", {"job": key, "page": p})
            for p in (0, 1, 2)
        ]
        denied = []
        for who in (other, stranger):
            denied.append(await wire.call(who, "fixture_read", {"job": key, "page": 0}))
            denied.append(
                await wire.call(who, "fixture_echo", {"job": key, "values": []})
            )
            denied.append(
                await wire.call(who, "fixture_read", {"job": handle, "page": 0})
            )
        await server.close(owner)
        denied.append(await wire.call(owner, "fixture_read", {"job": key, "page": 0}))
        raws = [call.raw for call in wire.calls]
    unhinted = cp.frozen()["c_prime"]["wire_legacy"]["unhinted"]
    for call in foreign:
        assert call.raw.decode() == unhinted and call.hints == []  # nosec B101 - pytest assertion
        assert key.encode() not in call.raw  # nosec B101 - pytest assertion
    assert [p.error for p in own] == [None, None, None]  # nosec B101 - pytest assertion
    assert denied and {call.raw for call in denied} == {DENIED}  # nosec B101 - pytest assertion
    assert scan(server, raws) == []  # nosec B101 - pytest assertion
    for raw in raws:
        assert _RAW.search(raw) is None  # nosec B101 - pytest assertion


PRODUCT_PROBE = """
import asyncio, json
import binnacle.server
from fastmcp import Client

async def tools():
    async with Client(binnacle.server.mcp) as client:
        return [tool.model_dump(mode="json") for tool in await client.list_tools()]

print(json.dumps(asyncio.run(tools())))
"""


def test_no_product_tool_declares_the_hint_field(tmp_path):
    """g6 §9.2: only the lab tool v2-S advertises ``job_awareness_hint``."""
    token = tmp_path / "token"
    token.write_text("Bearer synthetic-no-path\n")
    config = tmp_path / "config.toml"
    config.write_text(f'[auth]\ntoken_file = "{token}"\n')
    proc = subprocess.run(  # nosec B603 - fixed interpreter and script
        [sys.executable, "-c", PRODUCT_PROBE],
        env=clean_env(config),
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]  # nosec B101 - pytest assertion
    listed = proc.stdout.strip().splitlines()[-1]
    assert sorted(t["name"] for t in json.loads(listed)) == PUBLIC_TOOLS  # nosec B101 - pytest assertion
    assert HINT_FIELD not in listed  # nosec B101 - pytest assertion
