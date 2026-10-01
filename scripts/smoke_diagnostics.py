"""Pure parsing helpers for live-smoke diagnostics."""

from __future__ import annotations

import re

JournalExpectation = tuple[str, tuple[str, ...]]


def missing_from(lines: list[str], logged: list[JournalExpectation]) -> list[str]:
    """Return expectations with no completed matching journal call."""

    missing: list[str] = []
    for tool, tokens in logged:
        call_ids: list[str] = []
        for line in lines:
            if (
                "event=tool_call" in line
                and f"tool={tool} " in line
                and all(token in line for token in tokens)
            ):
                match = re.search(r"\bcall=([0-9a-f]+)", line)
                if match:
                    call_ids.append(match.group(1))
        complete = any(
            "event=tool_result" in line
            and any(f"call={call_id} " in line for call_id in call_ids)
            for line in lines
        )
        if not complete:
            missing.append(tool)
    return missing


def doctor_detail(output: str, failed: bool) -> str:
    """Preserve failing doctor checks instead of only its count summary."""

    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    summary = lines[-1][:160] if lines else "(no output)"
    if not failed:
        return summary
    failures = [line for line in lines if "[FAIL]" in line]
    return "; ".join([*failures, summary])[:200] if failures else summary
