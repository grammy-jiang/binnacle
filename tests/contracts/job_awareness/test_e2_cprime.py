"""E2 g6 §9.3 / §9.5 D0: frozen lab manifests (v1, v2-U, c′) and the c′ fixture.

The in-process composition must reproduce the frozen E2-RUN manifest hashes
for v1 and v2-U, and the pinned (c′) manifest. The (c′) result is
schema-valid against its advertised schema with and without the hint, and
its native wire bytes are pinned. Lab-only; no product tool changes.
"""

import json
from pathlib import Path

import pytest

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import Meter, Schema
from tests.contracts.job_awareness import e2_cprime as cp
from tests.contracts.job_awareness.e2_composition import E2Server, running
from tests.contracts.job_awareness.synthetic_app import in_loop

#: Second witness beside the fixture file. v1 and v2-U equal the frozen
#: E2-RUN ``lab/manifest.json`` and ``lab/v2/manifest.json`` hashes.
PINNED = {
    "v1": "ca4563c3ba00fdeb1b9cee2932a33c7ea110eeb05d20e5781c5b20dccfc77e04",
    "v2-U": "4aab8ee00b24d5c4759b8b55e875e59fae6c9b6d28fc1aa33dde830bdf087721",
    "c-prime": "a995405136191de89fb9657ecccf8de14ae9ee011d98eddce365845481627828",
}
NOTE_TOOL = "fixture_unrelated_read"


def servers(tmp_path) -> dict[str, E2Server]:
    return {
        "v1": E2Server(tmp_path / "v1"),
        "v2-U": E2Server(tmp_path / "v2u", carrier=HintCarrier.TEXT, structured=False),
        "c-prime": cp.cprime_server(tmp_path / "cp"),
    }


def tools(manifest: dict) -> dict[str, dict]:
    return {tool["name"]: tool for tool in manifest["tools"]}


def test_fixture_hashes_follow_the_hash_rule():
    data = cp.frozen()
    assert data["lab_only"] is True  # nosec B101 - pytest assertion
    for name, entry in data["manifests"].items():
        assert cp.manifest_sha256(entry["manifest"]) == entry["sha256"] == PINNED[name]  # nosec B101 - pytest assertion


@in_loop
async def test_composition_reproduces_every_frozen_manifest(tmp_path):
    data = cp.frozen()["manifests"]
    for name, server in servers(tmp_path).items():
        manifest = await cp.capture_manifest(server)
        assert manifest == data[name]["manifest"]  # nosec B101 - pytest assertion
        assert cp.manifest_sha256(manifest) == PINNED[name]  # nosec B101 - pytest assertion


def test_variants_differ_only_in_the_note_output_schema():
    data = cp.frozen()["manifests"]
    v1, v2u, cprime = (tools(data[k]["manifest"]) for k in ("v1", "v2-U", "c-prime"))
    assert v1.keys() == v2u.keys() == cprime.keys()  # nosec B101 - pytest assertion
    for name in v1:
        if name != NOTE_TOOL:
            assert v1[name] == v2u[name] == cprime[name]  # nosec B101 - pytest assertion
    strip = {k: v for k, v in v1[NOTE_TOOL].items() if k != "outputSchema"}
    assert v2u[NOTE_TOOL] == strip  # nosec B101 - pytest assertion
    assert cprime[NOTE_TOOL] == strip | {"outputSchema": cp.CPRIME_SCHEMA}  # nosec B101 - pytest assertion


def test_cprime_schema_declares_an_optional_undescribed_bounded_field():
    schema = cp.frozen()["c_prime"]["output_schema"]
    assert schema == cp.CPRIME_SCHEMA  # nosec B101 - pytest assertion
    assert schema["additionalProperties"] is False  # nosec B101 - pytest assertion
    assert cp.HINT_FIELD not in schema["required"]  # nosec B101 - pytest assertion
    assert schema["properties"][cp.HINT_FIELD] == {"type": "string", "maxLength": 512}  # nosec B101 - pytest assertion
    assert "description" not in json.dumps(schema)  # nosec B101 - pytest assertion


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ({"note": "n"}, True),
        ({"note": "n", cp.HINT_FIELD: "h" * 512}, True),
        ({"note": "n", cp.HINT_FIELD: "h" * 513}, False),
        ({"note": "n", cp.HINT_FIELD: 7}, False),
        ({"note": "n", cp.HINT_FIELD: None}, False),
        ({"note": "n", "reminder": "h"}, False),
        ({cp.HINT_FIELD: "h"}, False),
    ],
)
def test_cprime_schema_with_the_adapter_schema_checker(value, valid):
    assert Schema(cp.CPRIME_SCHEMA).valid(value, Meter()) is valid  # nosec B101 - pytest assertion


def test_cprime_result_never_carries_an_invalid_hint():
    schema = Schema(cp.CPRIME_SCHEMA)
    hint = cp.frozen()["c_prime"]["example_hint"]
    for given, field in ((None, False), ("", False), (hint, True), ("h" * 513, False)):
        result = cp.cprime_result("Synthetic reference note.", given)
        body = result.structured_content
        assert schema.valid(body, Meter())  # nosec B101 - pytest assertion
        assert (cp.HINT_FIELD in body) is field  # nosec B101 - pytest assertion
        assert [c.text for c in result.content] == [json.dumps(body)]  # nosec B101 - pytest assertion


@pytest.mark.parametrize("case", ["unhinted", "hinted"])
@in_loop
async def test_cprime_wire_bytes_are_pinned(tmp_path, case):
    frozen = cp.frozen()["c_prime"]
    hint = frozen["example_hint"] if case == "hinted" else None
    server = cp.cprime_server(tmp_path / case, hint=hint)
    async with running(server) as wire:
        call = await wire.call(None, NOTE_TOOL)
    assert call.raw.decode() == frozen["wire_legacy"][case]  # nosec B101 - pytest assertion
    assert call.error is None  # nosec B101 - pytest assertion


@in_loop
async def test_cprime_tools_list_is_identical_for_both_arms(tmp_path):
    hint = cp.frozen()["c_prime"]["example_hint"]
    control = await cp.capture_manifest(cp.cprime_server(tmp_path / "control"))
    candidate = await cp.capture_manifest(cp.cprime_server(tmp_path / "cand", hint))
    assert (
        cp.manifest_sha256(control)
        == cp.manifest_sha256(candidate)
        == PINNED["c-prime"]
    )  # nosec B101 - pytest assertion


def test_no_production_source_names_the_cprime_fixture():
    """ADV-TUG2-01: the c' fixture stays in the synthetic lab tests."""
    root = Path(cp.__file__).resolve().parents[3] / "src" / "binnacle"
    needles = ("e2_cprime", "cprime", "lab-manifests", "tests.contracts")
    sources = sorted(root.rglob("*.py"))
    assert sources  # nosec B101 - pytest assertion
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert not [n for n in needles if n in text], path  # nosec B101 - pytest assertion
