"""Exact search result-budget fitting with a machine-readable outcome."""

from dataclasses import dataclass
from typing import Any, Literal

import orjson

from binnacle.errors import CodedToolError

BudgetKind = Literal["none", "entries_trimmed", "context_omitted", "metadata_error"]


@dataclass(frozen=True)
class BudgetOutcome:
    payload: dict[str, Any]
    kind: BudgetKind
    result_bytes: int

    @property
    def hit(self) -> bool:
        return self.kind != "none"


def structured_bytes(payload: dict[str, Any]) -> int:
    """Compact UTF-8 JSON byte size; equivalent to the public result wire shape."""
    return len(orjson.dumps(payload))


def entry_count(payload: dict[str, Any]) -> int:
    entries = payload.get("entries")
    return len(entries) if isinstance(entries, list) else 0


def _budget_note(
    returned: int, total: int, *, names_only: bool, context_omitted: bool = False
) -> str:
    if context_omitted:
        return (
            "The first match is returned without context because its context block "
            "exceeded the response budget. Use read_file around the reported line "
            "to inspect it."
        )
    next_step = (
        "Narrow the path or glob."
        if names_only
        else "Narrow the pattern/path/glob, reduce context_lines, or use names_only."
    )
    return (
        f"Showing first {returned} of {total} matches; response budget reached. "
        f"{next_step}"
    )


def enforce_result_budget(
    payload: dict[str, Any],
    *,
    names_only: bool,
    max_bytes: int,
    initial_bytes: int | None = None,
) -> BudgetOutcome:
    initial_bytes = (
        structured_bytes(payload) if initial_bytes is None else initial_bytes
    )
    if initial_bytes <= max_bytes:
        return BudgetOutcome(payload, "none", initial_bytes)

    entries = list(payload.get("entries", []))
    base = {k: v for k, v in payload.items() if k not in {"entries", "note"}}
    base["truncated"] = True
    total = int(payload.get("count", len(entries)))

    def candidate(n: int) -> dict[str, Any]:
        return {
            **base,
            "entries": entries[:n],
            "note": _budget_note(n, total, names_only=names_only),
        }

    lo, hi = 0, len(entries)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if structured_bytes(candidate(mid)) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1

    if lo:
        fitted = candidate(lo)
        return BudgetOutcome(fitted, "entries_trimmed", structured_bytes(fitted))

    if entries and not names_only:
        compact_first = {
            k: v
            for k, v in entries[0].items()
            if k not in {"context", "context_first_line"}
        }
        out = {
            **base,
            "entries": [compact_first],
            "note": _budget_note(1, total, names_only=False, context_omitted=True),
        }
        out_bytes = structured_bytes(out)
        if out_bytes <= max_bytes:
            return BudgetOutcome(out, "context_omitted", out_bytes)

    empty = candidate(0)
    empty_bytes = structured_bytes(empty)
    if empty_bytes <= max_bytes:
        return BudgetOutcome(empty, "entries_trimmed", empty_bytes)
    raise CodedToolError(
        "response_budget_exceeded",
        "Search result metadata exceeds the configured response budget. "
        "Use a shorter pattern or a more specific path.",
    )
