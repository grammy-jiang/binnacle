"""Publishing credentials and source provenance must remain non-bypassable."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/publish-pypi.yml"


def _content():
    text = WORKFLOW.read_text()
    return yaml.safe_load(text), text


def test_only_explicit_normal_github_release_can_publish():
    config, text = _content()
    # PyYAML 1.1 maps the YAML key "on" to True.
    assert config.get("on", config.get(True)) == {"release": {"types": ["published"]}}
    assert config["permissions"] == {"contents": "read"}
    assert config["concurrency"]["cancel-in-progress"] is False
    assert sorted(config["jobs"]) == ["build", "publish"]
    gate = config["jobs"]["build"]["if"]
    assert "github.repository == 'grammy-jiang/binnacle'" in gate
    assert "!github.event.release.draft" in gate
    assert "!github.event.release.prerelease" in gate
    assert "workflow_dispatch" not in text and "pull_request_target" not in text


def test_build_has_no_oidc_and_checks_source_and_ci():
    config, text = _content()
    build = config["jobs"]["build"]
    assert build["permissions"] == {"contents": "read", "actions": "read"}
    assert build["runs-on"] == "ubuntu-24.04"
    assert "id-token" not in build["permissions"]
    runs = "\n".join(step.get("run", "") for step in build["steps"])
    assert 'git cat-file -t "refs/tags/$RELEASE_TAG"' in runs
    assert "$GITHUB_SHA" in runs
    assert "git/ref/heads/master" in runs
    assert "git/ref/heads/proof-of-concept" in runs
    assert "version" in runs and "RELEASE_TAG" in runs
    assert "ci_state(default_env(checkout=Path.cwd())" in runs
    assert 'if state != "success"' in runs
    assert "--locked" in runs
    assert "test_wheel_artifact.py" in runs
    assert "uv build --no-sources --sdist" in runs
    assert "uv build --no-sources --wheel" in runs
    assert "twine check --strict" in runs
    assert "actions/upload-artifact@" in text


def test_only_isolated_publisher_can_mint_oidc():
    config, text = _content()
    publisher = config["jobs"]["publish"]
    assert publisher["needs"] == "build"
    assert publisher["environment"]["name"] == "pypi"
    assert publisher["permissions"] == {"id-token": "write", "contents": "read"}
    assert "pypa/gh-action-pypi-publish@" in text
    assert "attestations" in text
    assert "password:" not in text
    assert "username:" not in text
    assert "skip-existing" not in text
    assert "secrets.PYPI" not in text
    for job in config["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                used = step["uses"]
                assert re.search(r"@[0-9a-f]{40}$", used), used
            assert "enable-cache" not in step.get("with", {})


def test_distribution_license_and_readme_remain_explicit():
    import pytest

    # Python 3.10 ships without stdlib tomllib. The packaging gate runs 3.13.
    tomllib = pytest.importorskip("tomllib")
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = cfg["project"]
    assert project["name"] == "binnacle-mcp"
    assert project["version"] == "1.0.1"
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert project["readme"] == "README.md"
    assert project["urls"]["Repository"] == "https://github.com/grammy-jiang/binnacle"
    assert "MIT License" in (ROOT / "LICENSE").read_text()
