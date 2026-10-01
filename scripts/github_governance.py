#!/usr/bin/env python3
"""Check and apply Binnacle's GitHub repository governance.

This is deliberately separate from scripts/dev.py: it requires authenticated
network access and can mutate repository settings when an explicit apply/enable
subcommand is used.

    uv run --no-project scripts/github_governance.py check
    uv run --no-project scripts/github_governance.py apply-ruleset
    uv run --no-project scripts/github_governance.py enable-dependabot

The desired master ruleset is version-controlled in
.github/rulesets/master.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "grammy-jiang/binnacle"
DEFAULT_RULESET = ROOT / ".github" / "rulesets" / "master.json"


@dataclass(frozen=True)
class Result:
    returncode: int
    output: str


def run(argv: Sequence[str], *, stdin: str | None = None) -> Result:
    try:
        proc = subprocess.run(
            list(argv),
            cwd=ROOT,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return Result(127, str(exc))
    return Result(proc.returncode, (proc.stdout or "") + (proc.stderr or ""))


def gh_api(
    repo: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Result:
    gh = shutil.which("gh")
    if gh is None:
        return Result(127, "gh is not on PATH")
    argv = [gh, "api"]
    if method != "GET":
        argv += ["-X", method]
    argv.append(f"repos/{repo}/{path}")
    stdin = None
    if payload is not None:
        argv += ["--input", "-"]
        stdin = json.dumps(payload)
    return run(argv, stdin=stdin)


def load_ruleset(path: Path = DEFAULT_RULESET) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("ruleset JSON must contain an object")
    return value


def _normalize_rule(rule: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {"type": rule["type"]}
    parameters = rule.get("parameters")
    if isinstance(parameters, dict):
        parameters = dict(parameters)
        checks = parameters.get("required_status_checks")
        if isinstance(checks, list):
            parameters["required_status_checks"] = sorted(
                (
                    {
                        key: check[key]
                        for key in ("context", "integration_id")
                        if key in check
                    }
                    for check in checks
                ),
                key=lambda check: str(check["context"]),
            )
        normalized["parameters"] = parameters
    return normalized


def policy_view(value: dict[str, Any]) -> dict[str, Any]:
    """Return only the remote fields controlled by the desired-state file."""

    rules = value.get("rules", [])
    return {
        "name": value.get("name"),
        "target": value.get("target"),
        "enforcement": value.get("enforcement"),
        "conditions": value.get("conditions"),
        "rules": sorted(
            (_normalize_rule(rule) for rule in rules),
            key=lambda rule: str(rule["type"]),
        ),
    }


def find_ruleset(
    repo: str,
    name: str,
) -> tuple[int | None, dict[str, Any] | None, str | None]:
    listed = gh_api(repo, "rulesets")
    if listed.returncode:
        return None, None, listed.output.strip()
    try:
        rulesets = json.loads(listed.output)
    except ValueError:
        return None, None, "GitHub returned unreadable ruleset JSON"

    match = next(
        (
            item
            for item in rulesets
            if isinstance(item, dict) and item.get("name") == name
        ),
        None,
    )
    if match is None:
        return None, None, None

    ruleset_id = int(match["id"])
    detail = gh_api(repo, f"rulesets/{ruleset_id}")
    if detail.returncode:
        return ruleset_id, None, detail.output.strip()
    try:
        value = json.loads(detail.output)
    except ValueError:
        return ruleset_id, None, "GitHub returned unreadable ruleset detail"
    return ruleset_id, value, None


def check_ruleset(repo: str, desired: dict[str, Any]) -> tuple[bool, str]:
    ruleset_id, remote, problem = find_ruleset(repo, str(desired["name"]))
    if problem:
        return False, f"ruleset check failed: {problem}"
    if ruleset_id is None or remote is None:
        return False, f"ruleset missing: {desired['name']}"
    if policy_view(remote) != policy_view(desired):
        return False, f"ruleset drift: {desired['name']} (id {ruleset_id})"
    return True, f"ruleset matches desired state (id {ruleset_id})"


def apply_ruleset(repo: str, desired: dict[str, Any]) -> tuple[bool, str]:
    ruleset_id, _remote, problem = find_ruleset(repo, str(desired["name"]))
    if problem:
        return False, f"cannot inspect existing ruleset: {problem}"

    if ruleset_id is None:
        result = gh_api(repo, "rulesets", method="POST", payload=desired)
        action = "created"
    else:
        result = gh_api(
            repo,
            f"rulesets/{ruleset_id}",
            method="PUT",
            payload=desired,
        )
        action = "updated"
    if result.returncode:
        return False, result.output.strip() or f"ruleset {action} failed"

    ok, detail = check_ruleset(repo, desired)
    return ok, f"{action}; {detail}"


def check_dependabot(repo: str) -> tuple[bool, list[str]]:
    details: list[str] = []

    alerts = gh_api(repo, "vulnerability-alerts")
    alerts_ok = alerts.returncode == 0
    details.append(
        "Dependabot alerts enabled"
        if alerts_ok
        else "Dependabot alerts disabled/unavailable"
    )

    updates = gh_api(repo, "automated-security-fixes")
    updates_ok = False
    if updates.returncode == 0:
        try:
            body = json.loads(updates.output or "{}")
            updates_ok = body.get("enabled") is True
        except ValueError:
            updates_ok = False
    details.append(
        "Dependabot security updates enabled"
        if updates_ok
        else "Dependabot security updates disabled/unavailable"
    )

    return alerts_ok and updates_ok, details


def enable_dependabot(repo: str) -> tuple[bool, list[str]]:
    results = [
        gh_api(repo, "vulnerability-alerts", method="PUT"),
        gh_api(repo, "automated-security-fixes", method="PUT"),
    ]
    failures = [
        result.output.strip() or f"GitHub API exit {result.returncode}"
        for result in results
        if result.returncode
    ]
    if failures:
        return False, failures
    return check_dependabot(repo)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check/apply Binnacle GitHub repository governance."
    )
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument(
        "--ruleset",
        type=Path,
        default=DEFAULT_RULESET,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="read-only ruleset and Dependabot state")
    sub.add_parser("apply-ruleset", help="create/update the desired master ruleset")
    sub.add_parser(
        "enable-dependabot",
        help="enable Dependabot alerts and security updates",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    desired = load_ruleset(args.ruleset)

    if args.command == "check":
        rules_ok, rules_detail = check_ruleset(args.repo, desired)
        deps_ok, deps_details = check_dependabot(args.repo)
        print(f"[{'OK' if rules_ok else 'FAIL'}] {rules_detail}")
        for detail in deps_details:
            enabled = detail.endswith(" enabled")
            print(f"[{'OK' if enabled else 'FAIL'}] {detail}")
        return 0 if rules_ok and deps_ok else 1

    if args.command == "apply-ruleset":
        ok, detail = apply_ruleset(args.repo, desired)
        print(f"[{'OK' if ok else 'FAIL'}] {detail}")
        return 0 if ok else 1

    if args.command == "enable-dependabot":
        ok, details = enable_dependabot(args.repo)
        for detail in details:
            enabled = detail.endswith(" enabled")
            print(f"[{'OK' if enabled else 'FAIL'}] {detail}")
        return 0 if ok else 1

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
