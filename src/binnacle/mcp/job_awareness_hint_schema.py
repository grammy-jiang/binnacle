"""Bounded, closed schema subset for synthetic native tool results."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from binnacle.mcp.job_awareness_hint_walk import Meter, Unsupported, _is, walk

_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "boolean": (bool,),
    "integer": (int,),
    "number": (int, float),
    "null": (type(None),),
}
_SCALARS = (str, int, float, bool, type(None))
_BOUNDS = {
    "minItems": (list,),
    "maxItems": (list,),
    "minLength": (str,),
    "maxLength": (str,),
    "minimum": (int, float),
    "maximum": (int, float),
}


def equal(left: Any, right: Any, meter: Meter) -> bool:
    """Only scalar enum/const values are supported; comparison work is metered."""
    meter.charge()
    if type(left) is not type(right):
        return False
    if type(left) is str:
        meter.charge(len(left) + len(right) + 1)
    return _is(left, *_SCALARS) and left == right


class Schema:
    def __init__(self, schema: Any):
        meter = Meter()
        walk(schema, meter, node_limit=256)
        meter.initial = False
        self.value = walk(schema, meter, copy=True, node_limit=256)
        self._compile(self.value)

    def _compile(self, schema: Any) -> None:
        if type(schema) is not dict:
            raise Unsupported
        for key, value in schema.items():
            children: Iterable[Any] = ()
            if key == "type":
                rule = value if type(value) is list else [value]
                valid = bool(rule) and all(type(n) is str and n in _TYPES for n in rule)
            elif key == "properties":
                valid = type(value) is dict
                children = value.values() if valid else ()
            elif key in ("items", "anyOf", "oneOf"):
                value = [value] if key == "items" else value
                valid = type(value) is list and bool(value)
                children = value if valid else ()
            elif key == "required":
                valid = type(value) is list and all(type(v) is str for v in value)
            elif key == "additionalProperties":
                valid = type(value) is bool
            elif key in ("const", "enum"):
                value = [value] if key == "const" else value
                valid = (
                    type(value) is list
                    and bool(value)
                    and all(_is(v, *_SCALARS) for v in value)
                )
            elif key in _BOUNDS:
                valid = (
                    _is(value, int, float)
                    if key in ("minimum", "maximum")
                    else type(value) is int and value >= 0
                )
            else:
                raise Unsupported
            if not valid:
                raise Unsupported
            for child in children:
                self._compile(child)

    def valid(self, value: Any, meter: Meter, schema: Any = None) -> bool:
        schema = self.value if schema is None else schema
        for key, rule in schema.items():
            meter.charge()
            meter.predicates += 1
            if key == "type":
                names = rule if type(rule) is list else [rule]
                meter.charge(len(names))
                if not any(type(value) is t for n in names for t in _TYPES[n]):
                    return False
            elif key in ("anyOf", "oneOf"):
                count = sum(self.valid(value, meter, child) for child in rule)
                if count == 0 or (key == "oneOf" and count != 1):
                    return False
            elif key in ("const", "enum"):
                if not any(
                    equal(value, v, meter) for v in (rule if key == "enum" else [rule])
                ):
                    return False
            elif key in ("required", "additionalProperties") and type(value) is dict:
                if key == "additionalProperties" and rule is not False:
                    continue
                keys, allowed = rule, value
                if key == "additionalProperties":
                    keys, allowed = value, schema.get("properties", {})
                for name in keys:
                    meter.charge(len(name) + 1)
                    if name not in allowed:
                        return False
            elif key == "properties" and type(value) is dict:
                for name, child in rule.items():
                    meter.charge(len(name) + 1)
                    if name in value and not self.valid(value[name], meter, child):
                        return False
            elif key == "items" and type(value) is list:
                for item in value:
                    meter.charge()
                    if not self.valid(item, meter, rule):
                        return False
            elif key in _BOUNDS and _is(value, *_BOUNDS[key]):
                measured = len(value) if _is(value, str, list) else value
                if (measured < rule) if key.startswith("min") else (measured > rule):
                    return False
        return True
