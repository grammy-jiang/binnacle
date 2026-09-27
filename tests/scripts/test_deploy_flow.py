"""scripts/deploy_flow.py: every step of the gated deploy, with git, gh,
systemctl, the journal and the smoke faked."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import scripts.deploy_flow as flow
from scripts.smoke_checks import Env, Report

PREV = "a" * 40
NEW = "b" * 40


class Host:
    """A fake production host: a git checkout, gh, systemd and the journal."""

    def __init__(self, **opts: Any) -> None:
        self.opts: dict[str, Any] = {
            "branch": "master",
            "dirty": "",
            "ff": 0,
            "diff": "src/binnacle/tools/job_status.py\n",
            "ci": [[{"name": "CI", "status": "completed", "conclusion": "success"}]],
            "mode": "dev mode",
            "busy": 0,
            "reloads": True,
            "push": 0,
            "target": NEW,
        }
        self.opts.update(opts)
        self.head = PREV
        self.calls: list[str] = []
        self.t = 1_790_460_000.0
        self.config_at: float | None = None
        self.ci_seen = 0

    def now(self) -> float:
        self.t += 0.01
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def run(self, argv: Sequence[str], timeout: float) -> tuple[int, str]:
        cmd = " ".join(argv)
        self.calls.append(cmd)
        if argv[0] == "git":
            return self._git(argv[3:])
        if argv[:3] == ["gh", "run", "list"]:
            runs = self.opts["ci"][min(self.ci_seen, len(self.opts["ci"]) - 1)]
            self.ci_seen += 1
            return 0, json.dumps(runs)
        if argv[0].endswith("binnacle") and argv[1:] == ["mode", "status"]:
            return 0, f"binnacle-mcp.service: active; {self.opts['mode']}\n"
        if argv[:3] == ["systemctl", "--user", "restart"]:
            self.config_at = self.t
            return 0, ""
        return 1, "unexpected"

    def _git(self, args: Sequence[str]) -> tuple[int, str]:
        op = args[0]
        if op == "fetch":
            return 0, ""
        if op == "remote":
            return 0, "https://github.com/grammy-jiang/binnacle.git\n"
        if op == "rev-parse" and args[1] == "--verify":
            target = self.opts["target"]
            return (0, target + "\n") if target else (128, "fatal: bad revision")
        if op == "rev-parse" and args[1] == "--abbrev-ref":
            return 0, self.opts["branch"] + "\n"
        if op == "rev-parse":
            return 0, self.head + "\n"
        if op == "status":
            return 0, self.opts["dirty"]
        if op == "merge-base":
            return self.opts["ff"], ""
        if op == "diff":
            return 0, self.opts["diff"]
        if op == "merge":
            self.head = args[-1]
            if self.opts["reloads"] and not self.opts["mode"].startswith("prod"):
                self.config_at = self.t
            return 0, ""
        if op == "reset":
            self.head = args[-1]
            if self.opts["reloads"]:
                self.config_at = self.t
            return 0, ""
        if op == "push":
            return self.opts["push"], "" if not self.opts["push"] else "rejected"
        return 1, "unknown git op"

    def journal(self, since: float, until: float | None) -> list[str]:
        lines = []
        if self.opts["busy"] and self.t < 1_790_460_000.0 + self.opts["busy"]:
            lines.append("x INFO: event=tool_call call=1 tool=read_file")
        if self.config_at is not None and self.config_at >= since - 0.5:
            lines.append("2026-09-27T23:00:00.000 INFO: event=config pid=2")
        return lines


def env_for(host: Host, tmp_path: Path) -> Env:
    return Env(
        run=host.run,
        journal=host.journal,
        now=host.now,
        sleep=host.sleep,
        client=lambda: None,
        read=lambda p: p.read_text(encoding="utf-8"),
        checkout=tmp_path,
        state_dir=tmp_path / "state",
        tmp_root=tmp_path,
    )


@pytest.fixture
def smokes(monkeypatch: Any) -> list[str]:
    """Results the fake smoke returns, in order; the default passes."""
    results: list[str] = []

    def fake_smoke(env: Env, full: bool = False, rebaseline: bool = False) -> Report:
        report = Report()
        report.add("tools", results.pop(0) if results else "ok", "fake smoke")
        return report

    monkeypatch.setattr(flow, "smoke", fake_smoke)
    return results


def deploy(host: Host, tmp_path: Path, **kw: Any) -> tuple[str, str]:
    kw.setdefault("ci_timeout", 120.0)
    kw.setdefault("quiet_timeout", 120.0)
    return flow.deploy(env_for(host, tmp_path), "origin/master", **kw)


def pushed(host: Host) -> bool:
    return any(" push " in c for c in host.calls)


def test_a_good_deploy_reloads_smokes_and_pushes(
    tmp_path: Path, smokes: list[str]
) -> None:
    host = Host()
    level, text = deploy(host, tmp_path)
    assert level == "ok" and text.startswith("OK: deployed bbbbbbb (was aaaaaaa)")
    assert host.head == NEW and pushed(host)
    assert any("HEAD:proof-of-concept" in c for c in host.calls)


@pytest.mark.parametrize(
    "diff",
    [
        "docs/testing.md\n",
        "tests/unit/core/test_units.py\nscripts/deploy_flow.py\n",
        "src/binnacle/py.typed\n",
    ],
)
def test_a_change_outside_the_server_code_needs_no_reload(
    tmp_path: Path, smokes: list[str], diff: str
) -> None:
    host = Host(diff=diff, reloads=False)
    level, text = deploy(host, tmp_path)
    assert level == "ok" and "no server code change" in text and pushed(host)
    assert any(" diff --name-only --no-renames " in c for c in host.calls)


@pytest.mark.parametrize(
    ("opts", "reason"),
    [
        ({"ff": 1}, "not a fast-forward"),
        ({"dirty": " M x.py\n"}, "not a clean master"),
        ({"branch": "feature/x"}, "not a clean master"),
        ({"target": ""}, "unknown target"),
    ],
)
def test_preflight_problems_stop_before_any_change(
    tmp_path: Path, smokes: list[str], opts: dict[str, Any], reason: str
) -> None:
    host = Host(**opts)
    level, text = deploy(host, tmp_path)
    assert level == "alert" and reason in text and "nothing deployed" in text
    assert host.head == PREV and not any(" merge " in c for c in host.calls)


def test_already_live_is_a_no_op(tmp_path: Path, smokes: list[str]) -> None:
    host = Host(target=PREV)
    assert deploy(host, tmp_path)[0] == "ok" and not pushed(host)


def test_a_failed_ci_stops_the_deploy(tmp_path: Path, smokes: list[str]) -> None:
    host = Host(ci=[[{"name": "CI", "status": "completed", "conclusion": "failure"}]])
    level, text = deploy(host, tmp_path)
    assert level == "alert" and "CI=failure" in text and host.head == PREV


def test_a_running_ci_is_awaited(tmp_path: Path, smokes: list[str]) -> None:
    running = [{"name": "CI", "status": "in_progress", "conclusion": ""}]
    done = [{"name": "CI", "status": "completed", "conclusion": "success"}]
    host = Host(ci=[running, running, done])
    assert deploy(host, tmp_path)[0] == "ok" and host.ci_seen == 3


def test_ci_that_never_appears_times_out(tmp_path: Path, smokes: list[str]) -> None:
    host = Host(ci=[[]])
    level, text = deploy(host, tmp_path, ci_timeout=60.0)
    assert level == "alert" and "CI not finished" in text and host.head == PREV


def test_no_quiet_moment_stops_the_deploy(tmp_path: Path, smokes: list[str]) -> None:
    host = Host(busy=10_000)
    level, text = deploy(host, tmp_path, quiet_timeout=60.0)
    assert level == "alert" and "no quiet moment" in text and host.head == PREV


def test_a_busy_server_is_awaited(tmp_path: Path, smokes: list[str]) -> None:
    host = Host(busy=50)
    assert deploy(host, tmp_path)[0] == "ok"


def test_a_failed_smoke_rolls_back_and_never_pushes(
    tmp_path: Path, smokes: list[str]
) -> None:
    smokes.extend(["alert", "ok"])  # the new code fails; the old code passes
    host = Host()
    level, text = deploy(host, tmp_path)
    assert level == "alert" and "rolled back to aaaaaaa (smoke OK)" in text
    assert host.head == PREV and not pushed(host)
    assert any(" reset --keep " + PREV in c for c in host.calls)


def test_a_failed_rollback_smoke_is_reported(tmp_path: Path, smokes: list[str]) -> None:
    smokes.extend(["alert", "alert"])
    level, text = deploy(Host(), tmp_path)
    assert level == "alert" and "(smoke ALERT)" in text


def test_code_that_does_not_load_rolls_back(tmp_path: Path, smokes: list[str]) -> None:
    host = Host(reloads=False)
    level, text = deploy(host, tmp_path, reload_timeout=5.0)
    assert level == "alert" and "the new code did not load" in text
    assert host.head == PREV and not pushed(host)


def test_prod_mode_restarts_the_unit(tmp_path: Path, smokes: list[str]) -> None:
    host = Host(mode="prod mode")
    assert deploy(host, tmp_path)[0] == "ok"
    assert any("systemctl --user restart binnacle-mcp.service" in c for c in host.calls)


def test_a_failed_push_is_a_warning(tmp_path: Path, smokes: list[str]) -> None:
    host = Host(push=1)
    level, text = deploy(host, tmp_path)
    assert level == "warn" and "the push failed" in text and host.head == NEW


def test_ci_state_reads_gh_output(tmp_path: Path) -> None:
    host = Host(
        ci=[[{"name": "CI", "status": "completed", "conclusion": "success"}] * 2]
    )
    state, detail = flow.ci_state(env_for(host, tmp_path), NEW)
    assert state == "success" and "2 run(s)" in detail
    assert any("--repo grammy-jiang/binnacle" in c for c in host.calls)
