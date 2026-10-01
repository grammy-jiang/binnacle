"""Repository GitHub governance desired-state tooling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import github_governance as gov


def _desired() -> dict[str, Any]:
    return {
        "name": "master deployment gate",
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": ["refs/heads/master"],
                "exclude": [],
            }
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [
                        {
                            "context": "Tests / Python 3.10",
                            "integration_id": 15368,
                        },
                        {
                            "context": "Code quality",
                            "integration_id": 15368,
                        },
                    ],
                },
            },
        ],
    }


def test_policy_view_ignores_remote_metadata_and_check_order() -> None:
    desired = _desired()
    remote = {
        **desired,
        "id": 42,
        "source_type": "Repository",
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [
                        {
                            "context": "Code quality",
                            "integration_id": 15368,
                            "extra": "ignored",
                        },
                        {
                            "context": "Tests / Python 3.10",
                            "integration_id": 15368,
                        },
                    ],
                },
            },
            {"type": "non_fast_forward"},
            {"type": "deletion"},
        ],
    }
    assert gov.policy_view(remote) == gov.policy_view(desired)


def test_policy_view_detects_meaningful_ruleset_drift() -> None:
    desired = _desired()
    remote = json.loads(json.dumps(desired))
    remote["rules"][2]["parameters"]["required_status_checks"].pop()
    assert gov.policy_view(remote) != gov.policy_view(desired)


def test_find_ruleset_reads_matching_detail(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake(repo: str, path: str, **kwargs: Any) -> gov.Result:
        calls.append(path)
        if path == "rulesets":
            return gov.Result(
                0,
                json.dumps(
                    [
                        {"id": 7, "name": "other"},
                        {"id": 42, "name": "master deployment gate"},
                    ]
                ),
            )
        if path == "rulesets/42":
            return gov.Result(0, json.dumps({**_desired(), "id": 42}))
        raise AssertionError(path)

    monkeypatch.setattr(gov, "gh_api", fake)
    ruleset_id, value, problem = gov.find_ruleset(
        "owner/repo",
        "master deployment gate",
    )
    assert (ruleset_id, problem) == (42, None)
    assert value is not None
    assert value["name"] == "master deployment gate"
    assert calls == ["rulesets", "rulesets/42"]


def test_check_ruleset_reports_missing_and_matching(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        gov,
        "find_ruleset",
        lambda repo, name: (None, None, None),
    )
    ok, detail = gov.check_ruleset("owner/repo", _desired())
    assert not ok and "missing" in detail

    monkeypatch.setattr(
        gov,
        "find_ruleset",
        lambda repo, name: (42, {**_desired(), "id": 42}, None),
    )
    ok, detail = gov.check_ruleset("owner/repo", _desired())
    assert ok and "matches desired state" in detail


def test_apply_ruleset_creates_then_rechecks(monkeypatch: Any) -> None:
    seen: list[tuple[str, str, dict[str, Any] | None]] = []
    desired = _desired()

    monkeypatch.setattr(
        gov,
        "find_ruleset",
        lambda repo, name: (None, None, None),
    )

    def fake_api(
        repo: str,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> gov.Result:
        seen.append((path, method, payload))
        return gov.Result(0, "{}")

    monkeypatch.setattr(gov, "gh_api", fake_api)
    monkeypatch.setattr(
        gov,
        "check_ruleset",
        lambda repo, value: (True, "ruleset matches desired state (id 42)"),
    )

    ok, detail = gov.apply_ruleset("owner/repo", desired)
    assert ok
    assert detail.startswith("created;")
    assert seen == [("rulesets", "POST", desired)]


def test_check_dependabot_requires_both_settings(monkeypatch: Any) -> None:
    def enabled(repo: str, path: str, **kwargs: Any) -> gov.Result:
        if path == "vulnerability-alerts":
            return gov.Result(0, "")
        if path == "automated-security-fixes":
            return gov.Result(0, '{"enabled":true,"paused":false}')
        raise AssertionError(path)

    monkeypatch.setattr(gov, "gh_api", enabled)
    ok, details = gov.check_dependabot("owner/repo")
    assert ok
    assert all(detail.endswith(" enabled") for detail in details)

    def updates_off(repo: str, path: str, **kwargs: Any) -> gov.Result:
        if path == "vulnerability-alerts":
            return gov.Result(0, "")
        return gov.Result(0, '{"enabled":false,"paused":false}')

    monkeypatch.setattr(gov, "gh_api", updates_off)
    ok, details = gov.check_dependabot("owner/repo")
    assert not ok
    assert details[-1].endswith("disabled/unavailable")


def test_enable_dependabot_writes_both_settings_then_checks(
    monkeypatch: Any,
) -> None:
    writes: list[tuple[str, str]] = []

    def fake(
        repo: str,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> gov.Result:
        if method == "PUT":
            writes.append((path, method))
            return gov.Result(0, "")
        raise AssertionError((path, method, payload))

    monkeypatch.setattr(gov, "gh_api", fake)
    monkeypatch.setattr(
        gov,
        "check_dependabot",
        lambda repo: (
            True,
            [
                "Dependabot alerts enabled",
                "Dependabot security updates enabled",
            ],
        ),
    )
    ok, details = gov.enable_dependabot("owner/repo")
    assert ok
    assert len(details) == 2
    assert writes == [
        ("vulnerability-alerts", "PUT"),
        ("automated-security-fixes", "PUT"),
    ]


def test_repository_governance_files_have_expected_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    dependabot = (root / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert dependabot.count("package-ecosystem:") == 3
    for ecosystem in ("uv", "pre-commit", "github-actions"):
        assert f'package-ecosystem: "{ecosystem}"' in dependabot
    assert dependabot.count('timezone: "Australia/Sydney"') == 3

    desired = gov.load_ruleset(root / ".github" / "rulesets" / "master.json")
    checks = next(
        rule for rule in desired["rules"] if rule["type"] == "required_status_checks"
    )["parameters"]["required_status_checks"]
    assert len(checks) == 7
    assert {check["integration_id"] for check in checks} == {15368}
