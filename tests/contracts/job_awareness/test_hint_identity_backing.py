"""The bound object's backing triple is still checked after object identity.

CHATGPT-POST-01/02 made object identity with the bound exact-native Tool the
first provenance gate, so foreign producers no longer reach the backing-map
checks. Those checks remain the additional condition for the bound object
itself: if its backing field map is changed after binding to a malformed,
oversized or unsupported triple, the adapter returns the original result with
no worker admission, observation read or receipt query.
"""

import pytest

from binnacle.mcp.job_awareness_hint import canonical_schema, producer_identity
from tests.contracts.job_awareness.synthetic_app import SCHEMA, Lab, in_loop, original
from tests.contracts.job_awareness.test_hint_identity_producer import (
    assert_suppressed,
    bound_adapter,
)


def _deep(levels):
    schema: dict[str, object] = {"type": "object"}
    for _ in range(levels):
        schema = {"type": "object", "properties": {"x": schema}}
    return schema


def _many_keys(backing):
    backing.update({f"extra_{i}": i for i in range(65)})


def _non_str_key(backing):
    backing[1] = "x"


def _drop(name):
    return lambda backing: backing.pop(name)


def _set(name, value):
    return lambda backing: backing.__setitem__(name, value)


MALFORMED_BACKING = {
    # Backing map shape (field map is not a plain bounded str-keyed dict).
    "too_many_fields": _many_keys,
    "non_str_field_key": _non_str_key,
    "missing_name": _drop("name"),
    "missing_version": _drop("version"),
    "missing_output_schema": _drop("output_schema"),
    # Field values (name, version, schema types and bounds).
    "name_not_str": _set("name", b"synthetic"),
    "name_empty": _set("name", ""),
    "name_too_long": _set("name", "x" * 129),
    "version_not_str": _set("version", 1),
    "version_too_long": _set("version", "1" * 129),
    "schema_not_dict": _set("output_schema", [SCHEMA]),
    "schema_none": _set("output_schema", None),
    # Canonicalization raises: unsupported or oversized schema values.
    "schema_unsupported_value": _set("output_schema", {**SCHEMA, "x": {1, 2}}),
    "schema_nan": _set("output_schema", {**SCHEMA, "x": float("nan")}),
    "schema_non_str_key": _set("output_schema", {**SCHEMA, 1: "x"}),
    "schema_over_node_limit": _set("output_schema", _deep(200)),
}


@pytest.mark.parametrize(
    "mutate", list(MALFORMED_BACKING.values()), ids=list(MALFORMED_BACKING)
)
@pytest.mark.parametrize("version", [None, "1"])
@in_loop
async def test_bound_object_with_malformed_backing_fails_closed(mutate, version):
    with Lab() as lab:
        adapter = bound_adapter(lab, version, workers=False)
        assert adapter.identity is not None  # nosec B101 - valid at binding
        mutate(object.__getattribute__(adapter.tool, "__dict__"))
        assert producer_identity(adapter.tool) is None  # nosec B101 - unknown
        await assert_suppressed(lab, adapter, original(), tool=adapter.tool)


@pytest.mark.parametrize("value", [[SCHEMA], "schema", 1, None, True])
def test_canonical_schema_rejects_non_object_schema(value):
    """The public canonicalizer accepts only a JSON object schema."""
    with pytest.raises(ValueError, match="output schema must be an object"):
        canonical_schema(value)


def test_canonical_schema_is_order_independent_and_exact():
    reordered = {k: SCHEMA[k] for k in reversed(list(SCHEMA))}
    assert canonical_schema(reordered) == canonical_schema(SCHEMA)  # nosec B101 - pytest assertion
    assert canonical_schema({**SCHEMA, "title": "t"}) != canonical_schema(SCHEMA)  # nosec B101 - pytest assertion
