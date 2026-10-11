"""Negative-first native adapter controls. No production application imports."""

import json
from unittest.mock import patch

import pytest
import uvloop
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.models import HintCarrier
from binnacle.mcp.job_awareness_hint import (
    META_KEY,
    Meter,
    Schema,
    Unsupported,
    walk,
)
from tests.contracts.job_awareness.synthetic_app import (
    Lab,
    app_for,
    assert_adapter_import_topology,
    check_explicit_bindings,
    in_loop,
    original,
    worker_lifetime_negative_control,
)


@in_loop
async def test_invalid_success_suppresses():
    with Lab() as lab:
        adapter = lab.adapter(enabled=True)
        original = ToolResult(
            content=[TextContent(type="text", text="original")],
            structured_content={"ok": "invalid"},
        )
        result = await adapter.adapt_bound(original)
        assert result is original  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion
        assert META_KEY not in (original.meta or {})  # nosec B101 - pytest assertion


@in_loop
async def test_disabled_identity():
    with Lab() as lab:
        for enabled, exclusive, schema in (
            (False, True, None),
            (True, False, None),
            (True, True, {"$ref": "https://invalid"}),
        ):
            adapter = lab.adapter(enabled=enabled, exclusive=exclusive, schema=schema)
            value = original()
            before = value.model_dump_json()
            assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
            assert value.model_dump_json() == before  # nosec B101 - pytest assertion
            assert adapter.last_meter is None  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == lab.payload.reads == 0  # nosec B101 - pytest assertion


def test_carriers_and_protocols():
    async def run():
        for protocol in ("2025-06-18", "2026-07-28"):
            for carrier in (HintCarrier.META, HintCarrier.TEXT):
                with Lab() as lab:
                    value = original()
                    before = value.model_dump_json()
                    app, seen = app_for(
                        lab.adapter(enabled=True, carrier=carrier), value
                    )
                    async with Client(
                        app, mode="legacy" if protocol == "2025-06-18" else protocol
                    ) as client:
                        result = await client.call_tool("synthetic")
                    assert len(seen) == 1  # nosec B101 - pytest assertion
                    assert result.structured_content == {"ok": True}  # nosec B101 - pytest assertion
                    assert result.is_error is False  # nosec B101 - pytest assertion
                    text = (
                        result.meta[META_KEY]
                        if carrier is HintCarrier.META
                        else result.content[-1].text
                    )
                    assert "unconfirmed" in text  # nosec B101 - pytest assertion
                    assert len(text.encode()) <= 512  # nosec B101 - pytest assertion
                    assert (  # nosec B101 - pytest assertion
                        "synthetic-secret-canary" not in text
                        and "/private/path" not in text
                    )
                    assert value.model_dump_json() == before  # nosec B101 - pytest assertion
                    assert result.content[0] == value.content[0]  # nosec B101 - pytest assertion
                    assert result.meta["existing"] == "kept"  # nosec B101 - pytest assertion
                    assert lab.payload.reads == 0  # nosec B101 - pytest assertion

    with patch("mcp.client.session.LATEST_HANDSHAKE_VERSION", "2025-06-18"):
        uvloop.run(run())


@in_loop
async def test_six_failures_preserve_envelope():
    with Lab() as lab:
        for failure in [
            "error",
            "collision",
            "invalid",
            "denied",
            "query",
            "observation",
        ]:
            adapter = lab.adapter(enabled=True)
            value = original()
            if failure == "error":
                value.is_error = True
            if failure == "collision":
                value.meta[META_KEY] = "producer-owned"
            if failure == "invalid":
                value.structured_content = {"ok": "bad"}
            before = value.model_dump_json()
            if failure in ("denied", "query", "observation"):
                obj, method = (
                    (lab.authority, "check")
                    if failure == "denied"
                    else (lab, "query" if failure == "query" else "observe")
                )
                with patch.object(obj, method, side_effect=RuntimeError("secret")):
                    assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
            else:
                assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
            assert value.model_dump_json() == before  # nosec B101 - pytest assertion


@in_loop
async def test_native_raised_error_is_unchanged():
    with Lab() as lab:
        app, seen = app_for(
            lab.adapter(enabled=True), error=ToolError("original error")
        )
        async with Client(app) as client:
            result = await client.call_tool("synthetic", raise_on_error=False)
        assert result.is_error  # nosec B101 - pytest assertion
        assert result.content[0].text == "original error"  # nosec B101 - pytest assertion
        assert not seen  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion


@in_loop
async def test_large_shallow_result_preflight():
    with Lab() as lab:
        for key in ("jobs", "processes"):
            value = original()
            value.structured_content = {key: [object()] * 10000}
            adapter = lab.adapter(enabled=True, schema={"type": "object"})
            assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
            assert adapter.last_meter.nodes < 30  # nosec B101 - pytest assertion
            assert adapter.last_meter.copied_bytes == adapter.last_meter.predicates == 0  # nosec B101 - pytest assertion
            assert lab.queries == lab.catalog_reads == 0  # nosec B101 - pytest assertion


def test_deep_result_preflight():
    for depth in (16, 17, 10000):
        value = None
        for _ in range(depth):
            value = [value]
        meter = Meter()
        if depth == 16:
            walk(value, meter)
            assert meter.depth == 16  # nosec B101 - pytest assertion
        else:
            with pytest.raises(Unsupported):
                walk(value, meter)
            assert meter.depth <= 16  # nosec B101 - pytest assertion
            assert meter.nodes <= 17  # nosec B101 - pytest assertion
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(Unsupported):
        walk(cyclic, Meter())


def test_string_byte_and_escape_preflight():
    for char in ("a", "é", "中", "😀", "\n", "\\", '"', "\x01"):
        text = char * (65536 // len(char.encode()))
        meter = Meter()
        # Escaped controls reach the whole-result cap before raw string cap.
        if len(json.dumps(text).encode()) > 262144:
            with pytest.raises(Unsupported):
                walk(text, meter)
        else:
            walk(text, meter)
            assert meter.bytes == len(json.dumps(text).encode())  # nosec B101 - pytest assertion
        with pytest.raises(Unsupported):
            walk(text + char, Meter())
    for value in ("x" * 1000000, "\ud800", float("nan"), float("inf"), 2**54):
        with pytest.raises(Unsupported):
            walk(value, Meter())
    meter = Meter()
    with pytest.raises(Unsupported):
        walk("😀" * 20000 + "unvisited", meter)
    assert meter.codepoints == 16385  # nosec B101 - pytest assertion


def test_each_validation_limit_and_one_more():
    for name, limit in (("nodes", 4096), ("entries", 2048), ("bytes", 262144)):
        meter = Meter()
        meter.add(name, limit, limit)
        with pytest.raises(Unsupported):
            meter.add(name, 1, limit)
        assert getattr(meter, name) == limit  # nosec B101 - pytest assertion
    for initial, limit in ((True, 1048576), (False, 4194304)):
        meter = Meter(initial=initial)
        meter.charge(limit)
        with pytest.raises(Unsupported):
            meter.charge()
        assert meter.total == limit  # nosec B101 - pytest assertion
    for count in (2048, 2049):
        meter = Meter()
        if count == 2048:
            walk([None] * count, meter)
            assert meter.entries == 2048  # nosec B101 - pytest assertion
        else:
            with pytest.raises(Unsupported):
                walk([None] * count, meter)
            assert meter.nodes == 1  # nosec B101 - pytest assertion
    Schema({"type": "object"})
    with pytest.raises(Unsupported):
        Schema({"enum": list(range(257))})
    for keyword in ("$ref", "pattern", "allOf", "unevaluatedProperties"):
        with pytest.raises(Unsupported):
            Schema({keyword: "unsupported"})


def test_no_work_after_budget_exhaustion():
    meter = Meter(total=1048576, preflight=1048576)
    with pytest.raises(Unsupported):
        walk(object(), meter)
    assert meter.total == meter.preflight == 1048576  # nosec B101 - pytest assertion
    assert meter.nodes == meter.codepoints == meter.copied_bytes == 0  # nosec B101 - pytest assertion


def test_guard_negative_controls():
    """Deliberately remove schema/size guards and require behavioral failure."""

    with (
        patch.object(Schema, "valid", return_value=True),
        pytest.raises(AssertionError),
    ):
        test_invalid_success_suppresses()
    real_add = Meter.add

    def no_entry_limit(self, name, amount, limit):
        return real_add(self, name, amount, 100000 if name == "entries" else limit)

    with (
        patch.object(Meter, "add", no_entry_limit),
        pytest.raises(pytest.fail.Exception),
    ):
        test_each_validation_limit_and_one_more()


@in_loop
async def test_malformed_native_fields_deny_before_reads():
    with Lab() as lab:
        for field, malformed in (
            ("content", {"text": "bad"}),
            ("meta", TextContent(type="text", text="bad")),
            ("meta", {"nested": TextContent(type="text", text="bad")}),
        ):
            value = original()
            value.__dict__[field] = malformed
            assert await lab.adapter(enabled=True).adapt_bound(value) is value  # nosec B101 - pytest assertion
            assert lab.queries == lab.catalog_reads == 0  # nosec B101 - pytest assertion


def test_serialized_string_budget_stops_suffix():
    meter = Meter()
    with pytest.raises(Unsupported):
        walk("\x01" * 50000, meter)
    assert (
        meter.codepoints <= 43691
    )  # 2 quotes + six bytes per control point  # nosec B101 - pytest assertion


@in_loop
async def test_whole_native_projection_and_carrier_limit():
    with Lab() as lab:
        value = original()
        meter = Meter()
        wire = walk(value, meter, copy=True)
        assert meter.bytes == len(  # nosec B101 - pytest assertion
            json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode()
        )
        baseline = meter.bytes
        adapted = await lab.adapter(enabled=True).adapt_bound(value)
        walk(adapted, meter)
        added = meter.bytes - baseline
        for limit in (1024, 1025):
            with patch(
                "binnacle.mcp.job_awareness_hint.META_KEY",
                META_KEY + "x" * (limit - added),
            ):
                result = await lab.adapter(enabled=True).adapt_bound(value)
            if limit == 1024:
                assert result is not value  # nosec B101 - pytest assertion
                walk(result, meter)
                assert meter.bytes - baseline == 1024  # nosec B101 - pytest assertion
            else:
                assert result is value  # nosec B101 - pytest assertion


@in_loop
async def test_plain_dict_cannot_impersonate_native_content():
    with Lab() as lab:
        value = original()
        value.__dict__["content"] = [
            {"type": "text", "text": "forged native", "_meta": None}
        ]
        assert await lab.adapter(enabled=True).adapt_bound(value) is value  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion


def test_pending_siblings_reserve_nodes_before_descent():
    value = {str(i): None for i in range(1024)}
    value["0"] = {str(i): None for i in range(1024)}
    meter = Meter()
    with pytest.raises(Unsupported):
        walk(value, meter)
    assert meter.nodes <= 2  # nosec B101 - pytest assertion


def test_worker_lifetime_guard_negative_control():
    worker_lifetime_negative_control()


def test_adapter_import_topology():
    assert_adapter_import_topology()


def test_explicit_bindings_fail_closed():
    uvloop.run(check_explicit_bindings())


TRAP_SLOTS = "nested meta dict extra private text_extra text_dict text_private key"
RENDER_CASES = "namespace 513 multibyte astral carrier bytes text_type extra 512 unicode wire_overflow"


@pytest.mark.parametrize("slot", TRAP_SLOTS.split())
@in_loop
async def test_preflight_rejects_callback_traps(slot):
    from tests.contracts.job_awareness.synthetic_app import callback_trap

    with Lab() as lab:
        calls, trap = callback_trap()
        value = original()
        if slot == "nested":
            value.structured_content["ok"] = trap
        elif slot == "meta":
            value.__dict__["meta"] = trap
        elif slot == "key":

            class Key(str):
                def __eq__(self, other):
                    calls.append("key equality")
                    return super().__eq__(other)

                __hash__ = str.__hash__

            value.__dict__[Key("meta")] = value.__dict__.pop("meta")
        else:
            target = value.content[0] if slot.startswith("text_") else value
            name = {
                "dict": "__dict__",
                "extra": "__pydantic_extra__",
                "private": "__pydantic_private__",
            }[slot.removeprefix("text_")]
            if name == "__dict__":
                trap.update(target.__dict__)
            object.__setattr__(target, name, trap)
        calls.clear()
        result = await lab.adapter(enabled=True).adapt_bound(value)
        assert calls == [] and result is value  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion


@pytest.mark.parametrize("case", RENDER_CASES.split())
@in_loop
async def test_renderer_utf8_limit_and_shape(case):
    from dataclasses import replace
    from types import SimpleNamespace

    from binnacle.features.commands.job_awareness.models import RenderedHint

    with Lab() as lab:
        adapter, value = lab.adapter(enabled=True), original()
        if case == "wire_overflow":
            value.meta = None
        hint = RenderedHint(HintCarrier.META, "x", 1)
        text = {
            "513": "x" * 513,
            "multibyte": "é" * 257,
            "astral": "😀" * 129,
            "512": "x" * 512,
            "unicode": "é" * 160,
            "wire_overflow": '"' * 491,
        }.get(case, "x")
        object.__setattr__(hint, "text", text)
        object.__setattr__(hint, "utf8_bytes", len(text.encode()))
        if case == "namespace":
            hint = SimpleNamespace(text="x" * 800)
        elif case == "carrier":
            object.__setattr__(hint, "carrier", HintCarrier.TEXT)
        elif case == "bytes":
            object.__setattr__(hint, "utf8_bytes", True)
        elif case == "text_type":
            object.__setattr__(hint, "text", type("Text", (str,), {})("x"))
        elif case == "extra":
            object.__setattr__(hint, "extra", "unsupported")
        adapter.bindings = replace(adapter.bindings, render=lambda *_: hint)
        result = await adapter.adapt_bound(value)
        assert lab.catalog_reads == lab.queries == 1  # nosec B101 - pytest assertion
        if case in ("512", "unicode"):
            assert result is not value and result.meta[META_KEY] == text  # nosec B101 - pytest assertion
        else:
            assert result is value and META_KEY not in (value.meta or {})  # nosec B101 - pytest assertion
