from __future__ import annotations

import ast
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


def test_bandit_is_a_canonical_local_and_ci_gate(repo_root: Path) -> None:
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    quality_dependencies = project["dependency-groups"]["quality"]
    assert any(dependency.startswith("bandit[") for dependency in quality_dependencies)

    pre_commit = cast(
        dict[str, Any],
        yaml.safe_load((repo_root / ".pre-commit-config.yaml").read_text(encoding="utf-8")),
    )
    local_repository = next(
        repository for repository in pre_commit["repos"] if repository["repo"] == "local"
    )
    bandit = next(hook for hook in local_repository["hooks"] if hook["id"] == "bandit")
    assert bandit["entry"] == "bandit --recursive src/binnacle"
    assert bandit["language"] == "system"
    assert bandit["pass_filenames"] is False
    assert bandit["always_run"] is True

    workflow = cast(
        dict[str, Any],
        yaml.safe_load((repo_root / ".github/workflows/python.yml").read_text(encoding="utf-8")),
    )
    quality_commands = {step.get("run") for step in workflow["jobs"]["quality"]["steps"]}
    assert "uv run pre-commit run --all-files" in quality_commands
    assert _dry_run(repo_root, "verify")[-1] == "uv run pre-commit run --all-files"


def test_production_python_has_no_optimization_sensitive_assertions(repo_root: Path) -> None:
    assertions: list[str] = []
    for path in sorted((repo_root / "src/binnacle").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assertions.extend(
            f"{path.relative_to(repo_root)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Assert)
        )
    assert assertions == []


def test_phase8_inventory_names_the_implemented_git_verifier(repo_root: Path) -> None:
    document = (repo_root / "docs/implementation/phase-08-git-development.rst").read_text(
        encoding="utf-8"
    )
    section_start = document.index("34. Repository layout and implementation seams")
    inventory_start = document.index(".. code-block:: text", section_start)
    inventory_end = document.index("\n\nThe exact credential service assets", inventory_start)
    inventory = document[inventory_start:inventory_end]
    verifier = "scripts/verify_git_credential_broker.py"
    assert verifier in inventory
    assert (repo_root / verifier).is_file()
    assert "scripts/verify_git_profile.py" not in inventory


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
