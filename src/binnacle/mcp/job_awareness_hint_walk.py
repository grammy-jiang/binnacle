"""Bounded native-result traversal and work accounting for synthetic hints."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from threading import Event
from typing import Any

from fastmcp.tools.base import ToolResult
from mcp.types import TextContent


class Unsupported(ValueError):
    """Fixed internal suppression; never reflected to a tool consumer."""


@dataclass
class Meter:
    stop: Event = field(default_factory=Event)
    total: int = 0
    preflight: int = 0
    nodes: int = 0
    entries: int = 0
    depth: int = 0
    codepoints: int = 0
    bytes: int = 0
    copied_bytes: int = 0
    predicates: int = 0
    initial: bool = True

    def charge(self, units: int = 1) -> None:
        if (
            self.total + units > 4194304
            or (self.initial and self.preflight + units > 1048576)
            or self.stop.is_set()
        ):
            raise Unsupported
        self.total += units
        if self.initial:
            self.preflight += units

    def add(self, name: str, amount: int, limit: int) -> None:
        self.charge()
        value = getattr(self, name) + amount
        if value > limit:
            raise Unsupported
        setattr(self, name, value)


def _string(value: str, meter: Meter, limit: int, raw_limit: int = 65536) -> int:
    meter.charge()
    if len(value) > raw_limit:
        raise Unsupported
    raw, encoded = 0, 2
    for char in value:
        meter.charge()
        meter.codepoints += 1
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            raise Unsupported
        width = 1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4
        raw += width
        increment = width
        if code < 32 or code > 126:
            increment = 12 if code > 0xFFFF else 6
        if char in '\\"\b\f\n\r\t':
            increment = 2
        meter.charge(increment)
        encoded += increment
        if raw > raw_limit or meter.bytes + encoded > limit:
            raise Unsupported
    return encoded


def _is(value: Any, *types: type) -> bool:
    return any(type(value) is t for t in types)


def _fields(data: Any, fields: tuple[str, ...]) -> bool:
    """Check exact backing maps before key hashing, equality, or field lookup."""
    return (
        type(data) is dict
        and len(data) == len(fields)
        and all(type(k) is str and len(k) <= 32 for k in data)
        and data.keys() == set(fields)
    )


def _native(value: Any) -> Any:
    """Pinned finite maps; unknown fields and serializers are unsupported."""
    if not _is(value, ToolResult, TextContent):
        return value
    tool = type(value) is ToolResult
    fields = ("content", "structured_content", "meta", "is_error")
    if not tool:
        fields = ("type", "text", "annotations", "meta")
    data = object.__getattribute__(value, "__dict__")
    extra = object.__getattribute__(value, "__pydantic_extra__")
    private = object.__getattribute__(value, "__pydantic_private__")
    assigned = object.__getattribute__(value, "__pydantic_fields_set__")
    if (
        not _fields(data, fields)
        or not (extra is None or (type(extra) is dict and len(extra) == 0))
        or type(assigned) is not set
        or len(assigned) > 4
        or not all(type(k) is str and len(k) <= 32 and k in fields for k in assigned)
        or not _is(data["meta"], dict, type(None))
    ):
        raise Unsupported
    if tool:
        if (
            not _fields(private, ("_raw_mcp_result",))
            or private["_raw_mcp_result"] is not None
            or type(data["content"]) is not list
            or not _is(data["structured_content"], dict, type(None))
            or data["is_error"] is not False
        ):
            raise Unsupported
        names = ("content", "structuredContent", "_meta", "isError")
    else:
        if (
            private is not None
            or data["annotations"] is not None
            or type(data["type"]) is not str
            or data["type"] != "text"
            or type(data["text"]) is not str
        ):
            raise Unsupported
        names = ("type", "text", "annotations", "_meta")
    result = {n: data[k] for n, k in zip(names, fields, strict=True)}
    if tool:
        result["resultType"] = "complete"
    return result


def walk(
    value: Any,
    meter: Meter,
    *,
    copy: bool = False,
    node_limit: int = 4096,
    byte_limit: int = 262144,
) -> Any:
    """Bounded depth-first cursor; never flatten a container or encode a string."""
    meter.nodes = meter.entries = meter.depth = meter.bytes = 0
    meter.charge(256)  # bounded native backing-map and slot checks
    native = _native(value)
    root: list[Any] = []
    stack: list[tuple[Iterator[Any], Any, int, int | None]] = [
        (iter(((None, native),)), root, 0, None)
    ]
    ancestors: set[int] = set()
    reserved_nodes = 1
    content_id = id(native["content"]) if type(value) is ToolResult else None
    while stack:
        meter.charge()
        cursor, target, depth, identity = stack[-1]
        try:
            key, item = next(cursor)
        except StopIteration:
            stack.pop()
            if identity is not None:
                ancestors.remove(identity)
            continue
        if depth > 16:
            raise Unsupported
        meter.depth = max(meter.depth, depth)
        meter.add("nodes", 1, node_limit)
        if content_id is not None and identity == content_id:
            meter.charge(256)  # finite native field-map accesses
            if type(item) is not TextContent:
                raise Unsupported
            item = _native(item)
        kind = type(item)
        size = 0
        if kind is dict or kind is list:
            meter.charge()
            count = len(item)
            if depth == 16 and count:
                raise Unsupported
            meter.add("entries", count, 2048)
            reserved_nodes += count * (2 if kind is dict else 1)
            if reserved_nodes > node_limit:
                raise Unsupported
            if id(item) in ancestors:
                raise Unsupported
            ancestors.add(id(item))
            size = 2 + max(0, count - 1) + (count if kind is dict else 0)
            result: Any = {} if kind is dict else []
            children = iter(item.items()) if kind is dict else enumerate(item)
            stack.append((children, result, depth + 1, id(item)))
        elif kind is str:
            size, result = _string(item, meter, byte_limit), item
        elif item is None or kind is bool:
            size, result = (4 if item is None or item else 5), item
        elif kind is int or kind is float:
            if (kind is int and not -9007199254740991 <= item <= 9007199254740991) or (
                kind is float and not math.isfinite(item)
            ):
                raise Unsupported
            meter.charge(32)
            # 32 covers both pinned binary64 encodings, including decimal 1e-5.
            size, result = (32 if kind is float else len(str(item))), item
        else:
            raise Unsupported
        if type(target) is dict:
            if type(key) is not str:
                raise Unsupported
            meter.add("nodes", 1, node_limit)
            size += _string(key, meter, byte_limit - size)
        meter.charge(size)
        meter.add("bytes", size, byte_limit)
        if copy:
            meter.charge(size + 1)
            meter.copied_bytes += size
            if type(target) is dict:
                target[key] = result
            else:
                target.append(result)
    return root[0] if copy else None
