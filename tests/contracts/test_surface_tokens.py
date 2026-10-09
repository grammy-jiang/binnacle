"""The token budget of what ChatGPT is served.

What is counted: the server instructions as the client receives them and,
for each tool of the ChatGPT profile (tests/contracts/surface_support.py),
the name, the description, the input schema and the output schema, each
schema as compact JSON in served order. The tokenizer is the one binnacle's
tokenizer telemetry loads (``binnacle.token_telemetry``, tiktoken with the
telemetry's default encoding, o200k_base).

The input schema is counted in the form Python 3.11+ serves it; the
production host runs 3.13. Python 3.10 nests an optional parameter's
``anyOf`` with the description inside (about 3 % more tokens), and
``served_form`` rewrites that form, so every Python measures the same number.

The rule: the measured count may exceed TOKEN_BUDGET by at most 5 %. A
larger surface is a documented override: set TOKEN_BUDGET to the new
measured count and add a line to BUDGET_CHANGES with the date and the reason,
in the same commit. The test fails when the two disagree, so the budget
cannot move without a recorded reason.
"""

import json

from binnacle.config import TokenizerTelemetrySettings
from binnacle.observability.token_telemetry import _load_encoding
from tests.contracts.surface_support import PROFILES, served

ENCODING = "o200k_base"
TOLERANCE = 0.05
TOKEN_BUDGET = 2262
#: (date, budget, reason): the last entry must match TOKEN_BUDGET.
BUDGET_CHANGES = (
    ("2026-09-28", 2140, "first measurement, master b857452 (6 tools)"),
    (
        "2026-09-29",
        2262,
        "frozen cursor v1 adds job_status input/output schema and required description",
    ),
)


def served_form(spec: dict) -> dict:
    """One input parameter as Python 3.11+ serves it.

    3.10: ``{"anyOf": [{"anyOf": [T, null], "description": D}, null], "default": x}``
    3.11+: ``{"anyOf": [T, null], "default": x, "description": D}``
    """
    branches = spec.get("anyOf")
    if not (
        isinstance(branches, list)
        and len(branches) == 2
        and "anyOf" in branches[0]
        and branches[1] == {"type": "null"}
    ):
        return spec
    inner = branches[0]
    rewritten = {"anyOf": inner["anyOf"]}
    rewritten.update((key, value) for key, value in spec.items() if key != "anyOf")
    if "description" in inner:
        rewritten["description"] = inner["description"]
    return rewritten


def _compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _texts() -> dict[str, list[str]]:
    """The counted text per part: the instructions and each served tool."""
    tools, instructions = served(PROFILES["chatgpt"])
    parts = {"instructions": [instructions or ""]}
    for tool in tools:
        schema = dict(tool.input_schema)
        schema["properties"] = {
            name: served_form(spec) for name, spec in schema["properties"].items()
        }
        parts[tool.name] = [
            tool.name,
            tool.description or "",
            _compact(schema),
            _compact(tool.output_schema),
        ]
    return parts


def measure() -> dict[str, int]:
    encoder = _load_encoding(ENCODING)
    return {
        part: sum(len(encoder.encode(text)) for text in texts)
        for part, texts in _texts().items()
    }


def test_chatgpt_surface_is_within_its_token_budget():
    counts = measure()
    total = sum(counts.values())
    limit = TOKEN_BUDGET * (1 + TOLERANCE)
    assert total <= limit, (
        f"ChatGPT's surface is {total} tokens, over the budget {TOKEN_BUDGET} "
        f"+ {TOLERANCE:.0%}; per part: {counts}. If the growth is deliberate, "
        "raise TOKEN_BUDGET and record the reason in BUDGET_CHANGES."
    )


def test_every_budget_change_is_documented():
    date, budget, reason = BUDGET_CHANGES[-1]
    assert budget == TOKEN_BUDGET, "record the new budget in BUDGET_CHANGES"
    assert date and reason.strip()


def test_the_budget_uses_the_telemetry_tokenizer():
    assert TokenizerTelemetrySettings().encoding == ENCODING


def test_served_form_rewrites_only_the_python_310_form():
    modern = {
        "anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}],
        "default": None,
        "description": "N lines.",
    }
    legacy = {
        "anyOf": [
            {
                "anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}],
                "description": "N lines.",
            },
            {"type": "null"},
        ],
        "default": None,
    }
    assert served_form(modern) is modern
    assert _compact(served_form(legacy)) == _compact(modern)
    plain = {"type": "string", "description": "Path."}
    assert served_form(plain) is plain
