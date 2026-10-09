"""GitHub CI security controls and failure diagnostics contracts."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
SECURITY = ROOT / ".github" / "workflows" / "security.yml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
PRECOMMIT = ROOT / ".pre-commit-config.yaml"


def test_all_checkout_steps_disable_token_persistence():
    found = 0
    for path in (CI, SECURITY):
        workflow = yaml.safe_load(path.read_text())
        assert workflow["permissions"] == {"contents": "read"}
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    assert step["with"]["persist-credentials"] is False
                    found += 1
    assert found == 5


def test_dependabot_cooldown_preserves_immediate_security_updates():
    data = yaml.safe_load(DEPENDABOT.read_text())
    assert {entry["package-ecosystem"] for entry in data["updates"]} == {
        "uv",
        "pre-commit",
        "github-actions",
    }
    for entry in data["updates"]:
        assert entry["cooldown"]["default-days"] == 7


def test_security_audit_is_offline_and_moderate_findings_block():
    hooks = yaml.safe_load(PRECOMMIT.read_text())
    audit = [
        hook
        for repo in hooks["repos"]
        if repo["repo"] == "local"
        for hook in repo["hooks"]
        if hook["id"] == "zizmor"
    ]
    assert len(audit) == 1
    hook = audit[0]
    cmd = hook["entry"]
    assert "--offline" in cmd and "--min-severity medium" in cmd
    assert ".github/workflows" in cmd
    assert ".github/dependabot.yml" in cmd
    assert ".pre-commit-config.yaml" in cmd
    assert hook["pass_filenames"] is False


def test_test_and_coverage_jobs_publish_only_failed_diagnostics():
    workflow = yaml.safe_load(CI.read_text())
    matrix = workflow["jobs"]["tests"]
    coverage = workflow["jobs"]["coverage"]
    for job in (matrix, coverage):
        save = [s for s in job["steps"] if s["name"].startswith("Save failing")]
        assert len(save) == 1
        action = save[0]
        assert action["if"] == "failure()"
        assert action["uses"].startswith("actions/upload-artifact@")
        assert action["with"]["retention-days"] == 7
        assert action["with"]["if-no-files-found"] == "warn"
        run = next(s for s in job["steps"] if "run" in s and "tox -e" in s["run"])
        assert "--seed 12345" in run["run"]
        assert "--junit-dir " in run["run"]
        assert "--durations=15" in run["run"]


def test_seven_required_check_ids_and_names_unchanged():
    import json

    cfg = json.loads((ROOT / ".github/rulesets/master.json").read_text())
    names = [
        check["context"]
        for rule in cfg["rules"]
        if rule["type"] == "required_status_checks"
        for check in rule["parameters"]["required_status_checks"]
    ]
    assert names == [
        "Code quality",
        "Tests / Python 3.10",
        "Tests / Python 3.11",
        "Tests / Python 3.12",
        "Tests / Python 3.14",
        "Coverage policy / Python 3.13",
        "Packaging / Python 3.13",
    ]
