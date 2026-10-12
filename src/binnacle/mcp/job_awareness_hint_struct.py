"""E2 lab STRUCT carrier (design g6 §9.2 S-1): one declared field, mirror rule.

Routed mode only and default off. The hint goes into one optional
``structuredContent`` field. The bound tool's closed output schema must
declare that field exactly as ``{"type": "string", "maxLength": 512}``: not
required and without a description. ``maxLength`` counts characters; the
renderer already limits the hint to 512 UTF-8 bytes, so a valid hint always
fits. The bind check reads only the walked plain copy of the schema.

Text blocks are classified against the ORIGINAL structured content before
any change:

- an exact JSON mirror is a text block equal to one of ``MIRROR_FORMATS``
  of the structured content. Exactly one mirror is re-serialized in its own
  format after the insertion; two or more mirrors suppress;
- a text block that is a JSON object equal to the structured content in any
  other format is an ambiguous mirror and suppresses (it could not be kept
  equal to the new structured content);
- every other text block is plain tool text and is never rewritten.

The insertion is followed by a metered re-validation against the bound
schema. Any doubt returns False or raises ``Unsupported``; the adapter then
returns the original result object.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import Enum
from typing import Any

from fastmcp.tools.base import Tool

from binnacle.mcp.job_awareness_hint_identity import Identity, producer_identity
from binnacle.mcp.job_awareness_hint_schema import Schema
from binnacle.mcp.job_awareness_hint_walk import Meter, Unsupported

__all__ = [
    "HINT_FIELD",
    "HINT_FIELD_SCHEMA",
    "MIRROR_FORMATS",
    "bind_struct",
    "declares_hint_field",
    "insert_hint",
    "struct_carrier",
    "struct_member",
]

HINT_FIELD = "job_awareness_hint"
HINT_FIELD_SCHEMA: dict[str, Any] = {"type": "string", "maxLength": 512}


def _stdlib(value: Any) -> str:
    """``json.dumps`` defaults (the E2-RUN CV variant e and c′ fixture)."""
    return json.dumps(value)


def _compact(value: Any) -> str:
    """Compact, non-ASCII kept: the FastMCP default text for plain JSON."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


MIRROR_FORMATS: tuple[Callable[[Any], str], ...] = (_stdlib, _compact)


def declares_hint_field(schema: Any) -> bool:
    """Bind rule: a closed object schema declares the optional hint field.

    ``schema`` is the walked plain copy (``Schema.value``): only dict, list
    and exact scalar types, so no comparison hook of a caller value runs.
    """
    if type(schema) is not dict:
        return False
    properties = schema.get("properties")
    required = schema.get("required", [])
    field = properties.get(HINT_FIELD) if type(properties) is dict else None
    return (
        type(schema.get("type")) is str
        and schema["type"] == "object"
        and schema.get("additionalProperties") is False
        and type(field) is dict
        and field == HINT_FIELD_SCHEMA
        and type(field["type"]) is str
        and type(field["maxLength"]) is int
        and type(required) is list
        and HINT_FIELD not in required
    )


def struct_member(struct: object, meta: Enum, text: Enum) -> bool:
    """``HintBindings.struct``: None, or a third member of the carrier enum."""
    return struct is None or (
        type(struct) is type(meta) and struct is not meta and struct is not text
    )


def struct_carrier(struct: object, carrier: object) -> bool:
    """True when ``carrier`` is the bindings' STRUCT member (never for None)."""
    return struct is not None and carrier is struct


def bind_struct(tool: Tool) -> tuple[Schema, Identity]:
    """g6 §9.2 S-1 bind: the schema and identity of a STRUCT binding.

    The tool's closed output schema must declare the optional hint field
    exactly (``declares_hint_field``). Anything else raises ``ValueError``,
    so the bind fails closed. ``tool`` is already an exact native Tool.
    """
    try:
        schema = Schema(tool.output_schema)
    except (ValueError, TypeError, RecursionError):
        raise ValueError("STRUCT needs a supported output schema") from None
    if not declares_hint_field(schema.value):
        raise ValueError("STRUCT needs a closed schema declaring the hint field")
    identity = producer_identity(tool)
    if identity is None:  # e.g. a version over 128 characters
        raise ValueError("STRUCT needs a known producer")
    return schema, identity


def _mirror(
    text: str, rendered: list[str], structured: dict[str, Any], meter: Meter
) -> Callable[[Any], str] | None:
    """The mirror format of one text block, None for plain tool text.

    Raises ``Unsupported`` for an ambiguous mirror: a JSON object text equal
    to the structured content in a format that cannot be reproduced.
    """
    meter.charge(len(text) + 1)
    for render, out in zip(MIRROR_FORMATS, rendered, strict=True):
        if text == out:
            return render
    if text.lstrip(" \t\n\r")[:1] != "{":
        return None
    meter.charge(len(text) + 1)
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if parsed == structured:
        raise Unsupported
    return None


def insert_hint(body: dict[str, Any], text: str, schema: Schema, meter: Meter) -> bool:
    """Insert ``text`` into the walked copy ``body``; False suppresses.

    ``body`` is the adapter's private copy, so a False return leaves no
    trace: the adapter returns the original result object.
    """
    structured = body["structuredContent"]
    if type(structured) is not dict or HINT_FIELD in structured:
        return False
    rendered = []
    for render in MIRROR_FORMATS:
        out = render(structured)
        meter.charge(len(out) + 1)
        rendered.append(out)
    mirrors = []
    for block in body["content"]:
        found = _mirror(block["text"], rendered, structured, meter)
        if found is not None:
            mirrors.append((block, found))
    if len(mirrors) > 1:
        return False
    structured[HINT_FIELD] = text
    if not schema.valid(structured, meter):
        return False
    for block, render in mirrors:
        block["text"] = render(structured)
        meter.charge(len(block["text"]) + 1)
    return True
