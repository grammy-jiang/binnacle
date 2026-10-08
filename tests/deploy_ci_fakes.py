"""GitHub API fixtures for deployment eligibility, without host mutations."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.smoke_checks import Env
from tests.service_fakes import FakeServiceController, FakeServiceInspector

SHA = "b" * 40
SLUG = "grammy-jiang/binnacle"
CONTEXTS = (
    "Code quality",
    "Tests / Python 3.10",
    "Tests / Python 3.11",
    "Tests / Python 3.12",
    "Tests / Python 3.14",
    "Coverage policy / Python 3.13",
    "Packaging / Python 3.13",
)
API_ROOT = f"repos/{SLUG}"
RUNS_PATH = f"{API_ROOT}/actions/workflows/ci.yml/runs?head_sha={SHA}&per_page=100"


def workflow(run_id: int = 101, *, attempt: int = 1) -> dict[str, Any]:
    return {
        "id": run_id,
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "head_sha": SHA,
        "check_suite_id": run_id + 400,
        "run_attempt": attempt,
        "status": "completed",
        "conclusion": "success",
    }


def pages(key: str, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"total_count": len(values), key: values[start : start + 100]}
        for start in range(0, max(1, len(values)), 100)
    ]


def _payload(value: Any, paginated: bool) -> str:
    if isinstance(value, str):
        return value
    if paginated and isinstance(value, list):
        return "\n".join(json.dumps(page, indent=2) for page in value)
    return json.dumps(value)


class GitHub:
    """Only transport is fake; policy and deployment decisions remain real."""

    def __init__(self) -> None:
        self.runs = [workflow()]
        self.jobs: dict[int, list[dict[str, Any]]] = {}
        self.checks: dict[int, dict[str, Any]] = {}
        self.overrides: dict[str, tuple[int, Any]] = {}
        self.calls: list[str] = []
        self.legacy_runs = deepcopy(self.runs)
        self.add_jobs(self.runs[0])
        self.policy: Any = json.loads(
            (Path(__file__).parents[1] / ".github/rulesets/master.json").read_text()
        )

    def add_jobs(self, run: dict[str, Any], names: tuple[str, ...] = CONTEXTS) -> None:
        jobs = self.jobs.setdefault(run["id"], [])
        for name in names:
            job_id = run["id"] * 1000 + len(jobs)
            job = {
                "id": job_id,
                "name": name,
                "run_id": run["id"],
                "head_sha": SHA,
                "run_attempt": run["run_attempt"],
                "status": "completed",
                "conclusion": "success",
                "check_run_url": f"https://api.github.com/{API_ROOT}/check-runs/{job_id}",
            }
            jobs.append(job)
            self.checks[job_id] = {
                "id": job_id,
                "name": name,
                "head_sha": SHA,
                "status": "completed",
                "conclusion": "success",
                "app": {"id": 15368},
                "check_suite": {"id": run["check_suite_id"]},
            }

    def run(self, argv: Any, timeout: float) -> tuple[int, str]:
        self.calls.append(" ".join(argv))
        if argv[:3] == ["git", "check-ref-format", "--allow-onelevel"]:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, check=False
            )
            return result.returncode, result.stdout + result.stderr
        if argv[0] == "git" and argv[-3:] == ["remote", "get-url", "origin"]:
            return 0, f"https://github.com/{SLUG}.git\n"
        if argv[:3] == ["gh", "run", "list"]:
            return 0, json.dumps(self.legacy_runs)
        assert argv[:2] == ["gh", "api"], argv
        if "--slurp" in argv:
            return 1, "unknown flag: --slurp (host gh 2.46.0)"
        path = argv[-1]
        if path in self.overrides:
            code, value = self.overrides[path]
            return code, _payload(value, "--paginate" in argv)
        if path == RUNS_PATH:
            value = pages("workflow_runs", self.runs)
        elif "/check-runs/" in path:
            value = self.checks[int(path.rsplit("/", 1)[1])]
        elif path.endswith("/jobs?filter=all&per_page=100"):
            run_id = int(path.split("/")[-2])
            value = pages("jobs", self.jobs[run_id])
        else:
            run_id = int(path.rsplit("/", 1)[1])
            value = next(run for run in self.runs if run["id"] == run_id)
        return 0, _payload(value, "--paginate" in argv)

    def env(self, checkout: Path) -> Env:
        return Env(
            run=self.run,
            journal=lambda since, until: [],
            now=lambda: 0.0,
            sleep=lambda seconds: None,
            client=lambda: None,
            read=lambda path: json.dumps(self.policy),
            checkout=checkout,
            state_dir=checkout / "state",
            tmp_root=checkout,
            services=FakeServiceInspector(),
            service_controller=FakeServiceController(),
        )
