"""Exact-SHA required CI eligibility; all operations are read-only.

Use explicit Actions attempt numbers, not check-run completion timestamps.
Every canonical CI run must pass, including both push and PR runs. Optional
workflows cannot substitute for required checks and do not veto them.
"""

from __future__ import annotations

import json
import re
from typing import Any

from scripts.smoke_checks import Env, last_line

WORKFLOW = ".github/workflows/ci.yml"


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value


def _positive(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("expected a positive integer identity/attempt")
    return value


def _required(env: Env) -> dict[str, int]:
    policy = _object(
        json.loads(env.read(env.checkout / ".github/rulesets/master.json"))
    )
    if (
        policy["name"] != "master deployment gate"
        or policy["target"] != "branch"
        or policy["enforcement"] != "active"
        or policy["conditions"]
        != {"ref_name": {"include": ["refs/heads/master"], "exclude": []}}
    ):
        raise ValueError("CI policy is not the active master deployment ruleset")
    rules = [
        r for r in policy["rules"] if _object(r)["type"] == "required_status_checks"
    ]
    if len(rules) != 1:
        raise ValueError("expected one required-check policy")
    checks = rules[0]["parameters"]["required_status_checks"]
    if not isinstance(checks, list) or not checks:
        raise ValueError("required-check policy is empty or malformed")
    required: dict[str, int] = {}
    for entry in checks:
        entry = _object(entry)
        name, issuer = entry["context"], _positive(entry["integration_id"])
        if not isinstance(name, str) or not name.strip() or name in required:
            raise ValueError("empty or duplicate required check")
        if issuer != 15368:
            raise ValueError("required check issuer is not supported github-actions")
        required[name] = issuer
    return required


def _api(env: Env, path: str, *, paginated: bool = False) -> Any:
    argv = ["gh", "api"]
    if paginated:
        argv.append("--paginate")
    rc, out = env.run([*argv, path], 60)
    if rc:
        raise ValueError(f"GitHub CI read failed: {last_line(out)}")
    if not paginated:
        return json.loads(out)
    # gh 2.46 (the production host) emits concatenated JSON pages and has no
    # --slurp. Decode every document; reject malformed trailing data too.
    pages: list[Any] = []
    decoder = json.JSONDecoder()
    remaining = out.lstrip()
    while remaining:
        page, end = decoder.raw_decode(remaining)
        pages.append(page)
        remaining = remaining[end:].lstrip()
    return pages


def _pages(env: Env, path: str, key: str) -> list[dict[str, Any]]:
    pages = _api(env, path, paginated=True)
    if not isinstance(pages, list) or not pages:
        raise ValueError("missing paginated CI response")
    records: list[dict[str, Any]] = []
    total = _object(pages[0])["total_count"]
    if type(total) is not int or total < 0:
        raise ValueError("invalid CI result count")
    if key == "workflow_runs" and total >= 1000:
        raise ValueError("CI workflow query reached GitHub's result limit")
    if len(pages) != max(1, (total + 99) // 100):
        raise ValueError("incomplete CI pagination")
    for index, page in enumerate(pages):
        page = _object(page)
        values = page[key]
        if (
            type(page["total_count"]) is not int
            or page["total_count"] != total
            or not isinstance(values, list)
            or len(values) != min(100, max(0, total - index * 100))
        ):
            raise ValueError("inconsistent or incomplete CI page")
        records.extend(_object(record) for record in values)
    ids = [_positive(record["id"]) for record in records]
    if len(ids) != len(set(ids)) or len(ids) != total:
        raise ValueError("duplicate or missing CI records")
    return records


def _run_signature(env: Env, run: dict[str, Any], sha: str) -> tuple[Any, ...]:
    path = run["path"]
    if not isinstance(path, str) or run["head_sha"] != sha:
        raise ValueError("CI workflow SHA/path mismatch")
    filename, separator, ref = path.partition("@")
    if filename != WORKFLOW:
        raise ValueError("CI workflow file mismatch")
    # GitHub may qualify a workflow path with @ref. Let Git validate its own
    # ref syntax; do not accept arbitrary filename prefixes or option strings.
    if separator and (
        not ref
        or ref.startswith("-")
        or env.run(["git", "check-ref-format", "--allow-onelevel", ref], 5)[0]
    ):
        raise ValueError("invalid CI workflow ref suffix")
    return (
        _positive(run["id"]),
        _positive(run["check_suite_id"]),
        _positive(run["run_attempt"]),
        run["status"],
        run["conclusion"],
        path,
    )


def _inventory(env: Env, root: str, sha: str) -> dict[int, tuple[Any, ...]]:
    runs = _pages(
        env,
        f"{root}/actions/workflows/ci.yml/runs?head_sha={sha}&per_page=100",
        "workflow_runs",
    )
    return {run["id"]: _run_signature(env, run, sha) for run in runs}


def _status(status: Any, conclusion: Any, label: str) -> tuple[str, str]:
    if status in ("queued", "in_progress", "waiting", "pending", "requested"):
        return "pending", f"{label} is {status}"
    if status != "completed" or conclusion != "success":
        return "failed", f"{label}={status}/{conclusion}"
    return "success", ""


def _selected_jobs(
    env: Env,
    root: str,
    sha: str,
    run_id: int,
    attempt: int,
    required: dict[str, int],
) -> dict[str, dict[str, Any]]:
    jobs = _pages(
        env, f"{root}/actions/runs/{run_id}/jobs?filter=all&per_page=100", "jobs"
    )
    selected: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, int]] = set()
    for job in jobs:
        job_attempt = _positive(job["run_attempt"])
        if (
            job["head_sha"] != sha
            or job["run_id"] != run_id
            or type(job["run_id"]) is not int
            or job_attempt > attempt
            or not isinstance(job["name"], str)
        ):
            raise ValueError("CI job SHA/run/attempt mismatch")
        name = job["name"]
        if name not in required:
            continue
        if (name, job_attempt) in seen:
            raise ValueError(f"ambiguous required job {name} in attempt {job_attempt}")
        seen.add((name, job_attempt))
        if name not in selected or job_attempt > selected[name]["run_attempt"]:
            selected[name] = job
    return selected


def _check_job(
    env: Env, root: str, sha: str, suite_id: int, issuer: int, job: dict[str, Any]
) -> tuple[str, str]:
    state, detail = _status(job["status"], job["conclusion"], job["name"])
    if state != "success":
        return state, detail
    prefix = f"https://api.github.com/{root}/check-runs/"
    url = job["check_run_url"]
    if not isinstance(url, str) or not url.startswith(prefix):
        raise ValueError("CI job check-run URL repository mismatch")
    suffix = url[len(prefix) :]
    if not re.fullmatch(r"[1-9][0-9]*", suffix):
        raise ValueError("invalid CI job check-run identity")
    check = _object(_api(env, f"{root}/check-runs/{suffix}"))
    if (
        _positive(check["id"]) != int(suffix)
        or check["head_sha"] != sha
        or check["name"] != job["name"]
        or _positive(_object(check["app"])["id"]) != issuer
        or _positive(_object(check["check_suite"])["id"]) != suite_id
    ):
        raise ValueError("required check SHA/name/issuer/suite mismatch")
    return _status(check["status"], check["conclusion"], job["name"])


def _observe(env: Env, sha: str, slug: str) -> tuple[str, str]:
    required = _required(env)
    root = f"repos/{slug}"
    before = _inventory(env, root, sha)
    if not before:
        return "none", "no canonical CI run yet"
    for run_id, signature in before.items():
        _, suite_id, attempt, status, conclusion, _ = signature
        state, detail = _status(status, conclusion, f"CI run {run_id}")
        if state != "success":
            return state, detail
        selected = _selected_jobs(env, root, sha, run_id, attempt, required)
        missing = required.keys() - selected.keys()
        if missing:
            return "pending", f"CI run {run_id} missing: {', '.join(sorted(missing))}"
        for name, issuer in required.items():
            state, detail = _check_job(env, root, sha, suite_id, issuer, selected[name])
            if state != "success":
                return state, detail
        after = _object(_api(env, f"{root}/actions/runs/{run_id}"))
        if _run_signature(env, after, sha) != signature:
            return "pending", f"CI run {run_id} changed during verification"
    if _inventory(env, root, sha) != before:
        return "pending", "CI inventory changed during verification"
    return (
        "success",
        f"{len(required)} required checks in {len(before)} CI run(s) succeeded",
    )


def required_ci_state(env: Env, sha: str, slug: str | None) -> tuple[str, str]:
    """Fail closed when policy or exact-commit evidence cannot be verified."""
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not slug:
        return "failed", "cannot identify exact candidate/repository"
    try:
        return _observe(env, sha, slug)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return "failed", f"invalid CI evidence: {exc}"
