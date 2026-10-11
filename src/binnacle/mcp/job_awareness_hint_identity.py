"""Producer identity from the resolved native Tool object, never caller strings.

FastMCP 4.1.0 does not make (name, version) unique: ToolInjectionMiddleware
overrides by name, providers mounted without a namespace can serve the same
component key, and transforms rename or redeclare tools. Mounted tools are new
wrapper objects on every lookup, so object identity is not usable either. The
identity is therefore the resolved Tool's exact name, exact version and
canonical-JSON output schema, read from its backing field map without running
descriptors, comparison or hashing callbacks of any field value.
"""

from __future__ import annotations

import json
from typing import Any

from fastmcp.tools.base import Tool

from binnacle.mcp.job_awareness_hint_walk import Meter, walk

__all__ = ["Identity", "canonical_schema", "producer_identity"]

Identity = tuple[str, str | None, str]
_FIELDS = ("name", "version", "output_schema")


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

    None means unknown: the caller must suppress. Exact-type checks run before
    any key lookup or equality, so hostile subclasses never get a callback.
    """
    try:
        if not issubclass(type(tool), Tool):
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
