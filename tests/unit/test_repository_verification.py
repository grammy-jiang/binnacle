from __future__ import annotations

import configparser
import json
import re
import subprocess
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]


def _dry_run(repo_root: Path, target: str, *variables: str) -> list[str]:
    result = subprocess.run(
        ["make", "--no-print-directory", "--dry-run", target, *variables],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _normalise_commands(script: str) -> list[str]:
    joined = re.sub(r"\\\s*\n\s*", " ", script)
    commands = []
    for line in joined.splitlines():
        command = " ".join(line.split())
        if not command:
            continue
        if command.startswith("uv run "):
            command = command.removeprefix("uv run ")
        command = re.sub(r" --cache-dir=\S+", "", command)
        commands.append(command)
    return commands


def test_verify_target_runs_the_frozen_phase10_profile(repo_root: Path) -> None:
    policy = json.loads(
        (repo_root / "spec/acceptance/phase10-policy.json").read_text(encoding="utf-8")
    )
    profiles = policy["required_local_check_profiles"]
    profile_order = (
        "tox-py311",
        "tox-py312",
        "tox-py313",
        "tox-quality",
        "pre-commit-all-files",
    )
    expected = [" ".join(profiles[profile]["argv"]) for profile in profile_order]

    assert _dry_run(repo_root, "verify") == expected


def test_attested_ci_jobs_match_the_canonical_tox_profile(repo_root: Path) -> None:
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    tox = configparser.ConfigParser(interpolation=None)
    tox.read_string(project["tool"]["tox"]["legacy_tox_ini"])
    workflow = cast(
        dict[str, Any],
        yaml.safe_load((repo_root / ".github/workflows/python.yml").read_text(encoding="utf-8")),
    )
    jobs = workflow["jobs"]
    test_job = jobs["test"]
    quality_job = jobs["quality"]

    assert test_job["strategy"]["matrix"]["python-version"] == ["3.11", "3.12", "3.13"]
    assert tox["tox"]["env_list"].replace(" ", "") == "py311,py312,py313,quality"
    assert tox["testenv"]["commands"].strip() == "pytest"
    assert 'uv run --python "${{ matrix.python-version }}" pytest' in {
        step.get("run") for step in test_job["steps"]
    }

    local_quality = _normalise_commands(tox["testenv:quality"]["commands"])
    local_quality.append("pre-commit run --all-files")
    remote_quality = []
    for step in quality_job["steps"]:
        run = step.get("run")
        if isinstance(run, str) and not run.startswith("uv sync "):
            remote_quality.extend(_normalise_commands(run))

    assert Counter(remote_quality) == Counter(local_quality)


def test_verify_python_rejects_an_unsupported_version(repo_root: Path) -> None:
    result = subprocess.run(
        ["make", "--no-print-directory", "verify-python", "PYTHON=3.10"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "PYTHON must be one of 3.11, 3.12, or 3.13" in result.stderr
