"""Schema semantics and exact bounded traversal regression controls."""

import pytest
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolResult, TextContent

from binnacle.mcp.job_awareness_hint import Meter, Schema, Unsupported, equal, walk


def test_metered_schema_semantics_and_unknown_native_shapes():
    cases = [
        ({"type": ["integer", "null"]}, 4, True),
        ({"type": "integer"}, True, False),
        ({"anyOf": [{"const": "a"}, {"enum": ["b", "c"]}]}, "b", True),
        ({"oneOf": [{"type": "number"}, {"type": "integer"}]}, 1, False),
        ({"anyOf": [{"const": 0}]}, 1, False),
        ({"const": True}, True, True),
        ({"type": "object", "required": ["a"]}, {}, False),
        ({"additionalProperties": False}, {"a": 1}, False),
        ({"items": {"type": "integer"}}, [1, "x"], False),
        ({"minItems": 1, "maxItems": 2}, [], False),
        ({"maxItems": 2}, [1, 2, 3], False),
        ({"minLength": 1, "maxLength": 2}, "ab", True),
        ({"minimum": -1, "maximum": 2}, -2, False),
        ({"minimum": -1, "maximum": 2}, 3, False),
        ({"minimum": -1, "maximum": 2}, 0.5, True),
    ]
    for schema, value, expected in cases:
        meter = Meter(initial=False)
        assert Schema(schema).valid(value, meter) is expected  # nosec B101 - pytest assertion
        assert meter.predicates > 0  # nosec B101 - pytest assertion
    assert not equal("a", "aa", Meter())  # nosec B101 - pytest assertion
    assert not equal("a", "b", Meter())  # nosec B101 - pytest assertion
    assert not equal("a", 1, Meter())  # nosec B101 - pytest assertion
    for schema in (
        {"type": "unknown"},
        {"properties": []},
        {"anyOf": {}},
        {"required": [1]},
        {"additionalProperties": {}},
        {"enum": [{}]},
        {"minItems": -1},
        {"maxLength": 0.5},
    ):
        with pytest.raises(Unsupported):
            Schema(schema)
    raw = ToolResult.from_mcp_result(CallToolResult(content=[]))
    extra = TextContent(type="text", text="original")
    extra.__dict__["unknown"] = "unsupported"
    for value in (raw, ToolResult(content=[extra]), {1: "bad"}, [object()]):
        with pytest.raises(Unsupported):
            walk(value, Meter())


def test_actual_exact_payload_node_schema_limits():
    value = ["a" * 65536] * 3 + ["a" * 65523]
    meter = Meter()
    walk(value, meter)
    assert meter.bytes == 262144  # nosec B101 - pytest assertion
    with pytest.raises(Unsupported):
        walk(value[:-1] + [value[-1] + "a"], Meter())
    value = {str(i): None for i in range(2047)}
    value["0"] = [None]
    walk(value, meter)
    assert meter.nodes == 4096 and meter.entries == 2048  # nosec B101 - pytest assertion
    with pytest.raises(Unsupported):
        walk({str(i): None for i in range(2048)}, Meter())
    schema = {"enum": [None] * 253}
    walk(schema, meter)
    assert meter.nodes == 256  # nosec B101 - pytest assertion
    Schema(schema)
    with pytest.raises(Unsupported):
        Schema({"enum": [None] * 254})
