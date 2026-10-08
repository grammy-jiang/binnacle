"""Shared diagnostic rendering; no aggregate doctor or host dependencies."""

import json
from collections.abc import Iterable
from dataclasses import asdict

from binnacle.diagnostics.doctor_contracts import Check


def render(checks: Iterable[Check]) -> tuple[str, int]:
    """Human-readable report and the process exit code (1 on any fail)."""
    label = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL"}
    lines = ["binnacle doctor"]
    counts = {"ok": 0, "warn": 0, "fail": 0}
    for c in checks:
        counts[c.status] += 1
        lines.append(f"  [{label[c.status]}] {c.group}: {c.detail}")
        if c.hint and c.status != "ok":
            lines.append(f"         hint: {c.hint}")
    lines.append(f"{counts['ok']} ok, {counts['warn']} warn, {counts['fail']} fail")
    return "\n".join(lines), 1 if counts["fail"] else 0


def render_json(checks: Iterable[Check]) -> tuple[str, int]:
    items = [asdict(c) for c in checks]
    code = 1 if any(c["status"] == "fail" for c in items) else 0
    return json.dumps({"checks": items, "exit_code": code}, indent=2), code
