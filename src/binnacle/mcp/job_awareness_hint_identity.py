"""Producer provenance: the bound native Tool object, never caller strings.

FastMCP 4.1.0 does not make (name, version) or even (name, version, schema)
unique: ToolInjectionMiddleware overrides by name, a parent local tool shadows
an unnamespaced mounted child, transforms rename or redeclare tools, and a
Tool subclass can report an effective output schema that differs from its
backing field map (CHATGPT-POST-01/02). Provenance is therefore object
identity with the bound registered tool plus an exact reviewed native type
(no subclasses, no mounted, proxied, OpenAPI or transformed wrappers). The
(name, version, canonical-JSON output schema) identity remains an additional
condition. It is read from the backing field map of an exact-typed object, so
no descriptor, comparison or hashing callback of any field value runs.
"""

from __future__ import annotations

import json
from typing import Any

from fastmcp.tools.base import Tool
from fastmcp.tools.function_tool import FunctionTool

from binnacle.mcp.job_awareness_hint_walk import Meter, walk

__all__ = [
    "NATIVE_TOOL_TYPES",
    "Identity",
    "canonical_schema",
    "native_tool",
    "producer_identity",
]

Identity = tuple[str, str | None, str]
_FIELDS = ("name", "version", "output_schema")
# Reviewed directly registered FastMCP 4.1.0 classes. Wrappers (TransformedTool,
# FastMCPProviderTool, ProxyTool, OpenAPITool) and every subclass are excluded.
NATIVE_TOOL_TYPES: tuple[type[Tool], ...] = (Tool, FunctionTool)


def native_tool(tool: object) -> bool:
    """True only for an exact reviewed native type; ``type()`` runs no hook."""
    cls = type(tool)
    return any(cls is native for native in NATIVE_TOOL_TYPES)


def canonical_schema(schema: Any) -> str:
    """Bounded exact canonical JSON; raises for unsupported or oversized values."""
    meter = Meter()
    walk(schema, meter, node_limit=256)
    meter.initial = False
    value = walk(schema, meter, copy=True, node_limit=256)
    if type(value) is not dict:
        raise ValueError("output schema must be an object")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def producer_identity(tool: object) -> Identity | None:
    """Return (name, version, canonical schema) of a native Tool, else None.

    None means unknown: the caller must suppress. The exact-type check runs
    before any attribute, key lookup or equality, so a subclass (hostile or
    not) is unknown and never gets a callback.
    """
    try:
        if not native_tool(tool):
            return None
        data = object.__getattribute__(tool, "__dict__")
        if (
            type(data) is not dict
            or len(data) > 64
            or not all(type(key) is str for key in data)
            or not all(name in data for name in _FIELDS)
        ):
            return None
        name, version, schema = (data[field] for field in _FIELDS)
        if (
            type(name) is not str
            or not 1 <= len(name) <= 128
            or (version is not None and type(version) is not str)
            or (version is not None and len(version) > 128)
            or type(schema) is not dict
        ):
            return None
        return name, version, canonical_schema(schema)
    except Exception:  # noqa: BLE001 - unknown producer identity suppresses
        return None
