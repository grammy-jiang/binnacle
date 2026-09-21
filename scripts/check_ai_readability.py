#!/usr/bin/env python3
"""Report long Python functions for AI readability; warning-only by design."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "quality-policy.json"
WARNING_RE = re.compile(
    r"^(?P<path>.*?):(?P<line>\d+): warning: (?P<name>.*?) has "
    r".*?, (?P<length>\d+) length, "
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    name: str
    length: int


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))["ai_readability"]


def parse_findings(output: str) -> list[Finding]:
    findings: list[Finding] = []
    for line in output.splitlines():
        match = WARNING_RE.match(line)
        if match:
            findings.append(
                Finding(
                    path=match.group("path"),
                    line=int(match.group("line")),
                    name=match.group("name"),
                    length=int(match.group("length")),
                )
            )
    return findings


def severity(length: int, *, strong: int, severe: int) -> str:
    if length > severe:
        return "SEVERE"
    if length > strong:
        return "STRONG"
    return "WARNING"


def run_lizard(roots: list[str], warning_lines: int) -> list[Finding]:
    proc = subprocess.run(
        [
            "lizard",
            "-w",
            "-L",
            str(warning_lines),
            "-C",
            "999999",
            "-a",
            "999999",
            "-i",
            "-1",
            *roots,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_findings(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args(argv)

    cfg = load_policy(args.policy)
    warning = int(cfg["warning_lines"])
    strong = int(cfg["strong_warning_lines"])
    severe = int(cfg["severe_warning_lines"])
    roots = [str(x) for x in cfg["roots"]]

    findings = run_lizard(roots, warning)
    counts = {"WARNING": 0, "STRONG": 0, "SEVERE": 0}
    for item in sorted(findings, key=lambda x: (-x.length, x.path, x.line)):
        level = severity(item.length, strong=strong, severe=severe)
        counts[level] += 1
        print(
            f"{level}: {item.path}:{item.line}: {item.name} is "
            f"{item.length} lines (AI-readability target <= {warning})"
        )

    print(
        "ai-readability: "
        f"{len(findings)} long function(s); "
        f"{counts['WARNING']} warning, {counts['STRONG']} strong, "
        f"{counts['SEVERE']} severe; warning-only (non-blocking)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
