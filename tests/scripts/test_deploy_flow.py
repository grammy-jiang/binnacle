"""scripts/deploy_flow.py: every step of the gated deploy, with git, gh,
systemctl, the journal and the smoke faked."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import scripts.deploy_flow as flow
from binnacle.platform.contracts.service_lifecycle_contracts import ServiceAction
from binnacle.platform.contracts.service_log_contracts import ServiceLogError
from scripts.smoke_checks import Env, Report
from tests.deploy_ci_fakes import RUNS_PATH, GitHub, workflow
from tests.service_fakes import FakeServiceInspector

PREV = "a" * 40
NEW = "b" * 40


class HostController:
    def __init__(self, host) -> None:
        self.host = host
        self.calls: list[tuple[str, float | None]] = []

    def restart(self, service: str, *, timeout: float | None = None) -> ServiceAction:
        self.calls.append((service, timeout))
        self.host.config_at = self.host.t
        return ServiceAction(0)


class Host:
    """A fake production host: a git checkout, gh, systemd and the journal."""

    def __init__(self, **opts: Any) -> None:
        self.opts: dict[str, Any] = {
            "branch": "master",
            "dirty": "",
            "untracked": "",
            "ff": 0,
            "diff": "src/binnacle/tools/job_status.py\n",
            "ci": [[workflow()]],
            "mode": "dev mode",
            "busy": 0,
            "reloads": True,
            "push": 0,
            "sync": [0],
            "target": NEW,
            "journal_errors": {},
        }
        self.opts.update(opts)
        self.github = GitHub()
        for snapshot in self.opts["ci"]:
            for run in snapshot:
                if run["id"] not in self.github.jobs:
                    self.github.add_jobs(run)
        self.head = PREV
        self.calls: list[str] = []
        self.timed_calls: list[tuple[str, float]] = []
        self.t = 1_790_460_000.0
        self.config_at: float | None = None
        self.ci_seen = 0
        self.sync_seen = 0
        self.journal_seen = 0
        self.controller = HostController(self)

    def now(self) -> float:
        self.t += 0.01
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def run(self, argv: Sequence[str], timeout: float) -> tuple[int, str]:
        cmd = " ".join(argv)
        self.calls.append(cmd)
        self.timed_calls.append((cmd, timeout))
        if argv[0] == "git":
            return self._git(argv[3:])
        if argv[:2] == ["gh", "api"]:
            if argv[-1] == RUNS_PATH:
                self.github.runs = self.opts["ci"][
                    min(self.ci_seen, len(self.opts["ci"]) - 1)
                ]
                self.ci_seen += 1
            return self.github.run(argv, timeout)
        if argv[0].endswith("binnacle") and argv[1:] == ["mode", "status"]:
            return 0, f"binnacle-mcp.service: active; {self.opts['mode']}\n"
        if argv[0].endswith("/uv") and argv[1:2] == ["sync"]:
            results = self.opts["sync"]
            rc = results[min(self.sync_seen, len(results) - 1)]
            self.sync_seen += 1
            return rc, "sync ok\n" if rc == 0 else "sync failed\n"
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
        if op == "ls-files":
            return 0, self.opts["untracked"]
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
        self.journal_seen += 1
        error = self.opts["journal_errors"].get(self.journal_seen)
        if error:
            raise ServiceLogError(error)
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
        read=lambda p: (
            json.dumps(host.github.policy)
            if p.name == "master.json"
            else p.read_text(encoding="utf-8")
        ),
        services=FakeServiceInspector(),
        service_controller=host.controller,
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
    assert any(" push --atomic -q origin " in c for c in host.calls)
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


def test_untracked_docs_do_not_block_deploy(
    tmp_path: Path,
    smokes: list[str],
) -> None:
    host = Host(
        untracked=("docs/design-note.md\0docs/research/evidence.json\0"),
    )
    level, text = deploy(host, tmp_path)
    assert level == "ok" and pushed(host)
    assert "deployed" in text


@pytest.mark.parametrize(
    "untracked",
    [
        "notes.txt\0",
        "src/binnacle/local_probe.py\0",
        "scripts/local_probe.py\0",
        "docs/safe.md\0src/binnacle/unsafe.py\0",
    ],
)
def test_untracked_non_docs_still_block_deploy(
    tmp_path: Path,
    smokes: list[str],
    untracked: str,
) -> None:
    host = Host(untracked=untracked)
    level, text = deploy(host, tmp_path)
    assert level == "alert"
    assert "not a clean master" in text
    assert not pushed(host)


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
    host = Host(ci=[[{**workflow(), "conclusion": "failure"}]])
    level, text = deploy(host, tmp_path)
    assert level == "alert" and "CI run 101=completed/failure" in text
    assert host.head == PREV and not pushed(host) and not host.controller.calls
    assert not any(" merge " in call for call in host.calls)


def test_a_running_ci_is_awaited(tmp_path: Path, smokes: list[str]) -> None:
    running = [{**workflow(), "status": "in_progress", "conclusion": None}]
    done = [workflow()]
    host = Host(ci=[running, running, done])
    assert deploy(host, tmp_path)[0] == "ok" and host.ci_seen == 4
    assert host.t >= 1_790_460_060  # Two bounded CI waits, then a stable final read.


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


def test_dev_dependency_change_syncs_and_restarts(
    tmp_path: Path, smokes: list[str]
) -> None:
    host = Host(diff="pyproject.toml\nuv.lock\n", reloads=False)
    level, text = deploy(host, tmp_path)

    assert level == "ok" and host.head == NEW and pushed(host)
    assert host.sync_seen == 1
    assert any(
        ".venv/bin/uv sync --project" in call and "--locked --group dev" in call
        for call in host.calls
    )
    assert host.controller.calls == [(flow.UNIT, 90.0)]
    assert "sync: sync ok" in text
    assert "restarted after dev environment sync" in text


def test_dev_dependency_restart_uses_restart_timeout(
    tmp_path: Path, smokes: list[str]
) -> None:
    host = Host(diff="uv.lock\n", reloads=False)
    level, _ = deploy(
        host,
        tmp_path,
        reload_timeout=5.0,
        restart_timeout=77.0,
    )

    assert level == "ok"
    assert host.controller.calls == [(flow.UNIT, 77.0)]


def test_dev_dependency_rollback_restart_uses_restart_timeout(
    tmp_path: Path, smokes: list[str]
) -> None:
    smokes.extend(["alert", "ok"])
    host = Host(diff="uv.lock\n", reloads=False)
    level, _ = deploy(
        host,
        tmp_path,
        reload_timeout=5.0,
        restart_timeout=77.0,
    )

    assert level == "alert"
    assert host.controller.calls == [(flow.UNIT, 77.0), (flow.UNIT, 77.0)]


def test_failed_dev_sync_rolls_back_and_restores_old_environment(
    tmp_path: Path, smokes: list[str]
) -> None:
    host = Host(diff="uv.lock\n", reloads=False, sync=[1, 0])
    level, text = deploy(host, tmp_path)

    assert level == "alert" and "sync" in text
    assert host.head == PREV and not pushed(host)
    assert host.sync_seen == 2
    assert "smoke OK" in text


def test_failed_smoke_after_dev_sync_resyncs_rollback_environment(
    tmp_path: Path, smokes: list[str]
) -> None:
    smokes.extend(["alert", "ok"])
    host = Host(diff="pyproject.toml\n", reloads=False, sync=[0, 0])
    level, text = deploy(host, tmp_path)

    assert level == "alert"
    assert host.head == PREV and not pushed(host)
    assert host.sync_seen == 2
    assert "rolled back" in text and "smoke OK" in text


def test_prod_dependency_metadata_does_not_sync_checkout_venv(
    tmp_path: Path, smokes: list[str]
) -> None:
    host = Host(mode="prod mode", diff="uv.lock\n", reloads=False)
    level, text = deploy(host, tmp_path)

    assert level == "ok" and pushed(host)
    assert host.sync_seen == 0
    assert "no server code change" in text


def test_prod_mode_restarts_the_unit(tmp_path: Path, smokes: list[str]) -> None:
    host = Host(mode="prod mode")
    assert deploy(host, tmp_path)[0] == "ok"
    assert host.controller.calls == [(flow.UNIT, 90.0)]


def test_a_failed_atomic_push_rolls_back(tmp_path: Path, smokes: list[str]) -> None:
    host = Host(push=1)
    level, text = deploy(host, tmp_path)
    assert level == "alert"
    assert "deploy of bbbbbbb failed (push)" in text
    assert "rolled back to aaaaaaa (smoke OK)" in text
    assert host.head == PREV
    assert any(" push --atomic -q origin " in c for c in host.calls)
    assert any(" reset --keep " + PREV in c for c in host.calls)


def test_ci_state_reads_gh_output(tmp_path: Path) -> None:
    host = Host(ci=[[workflow(), workflow(102)]])
    state, detail = flow.ci_state(env_for(host, tmp_path), NEW)
    assert state == "success" and "2 CI run(s)" in detail
    assert any(RUNS_PATH in call for call in host.calls)


@pytest.mark.parametrize("detail", ["read failed", "journalctl timed out after 60 s"])
def test_journal_failure_at_quiet_gate_alerts_before_mutation(
    tmp_path: Path, smokes: list[str], detail: str
) -> None:
    host = Host(journal_errors={1: detail})

    level, text = deploy(host, tmp_path)

    assert level == "alert"
    assert "cannot prove a quiet moment; nothing deployed" in text
    assert detail in text
    assert host.head == PREV and not pushed(host)
    assert not any(" merge " in call for call in host.calls)


@pytest.mark.parametrize("detail", ["read failed", "journalctl timed out after 60 s"])
def test_forward_config_journal_failure_rolls_back_without_push(
    tmp_path: Path, smokes: list[str], detail: str
) -> None:
    host = Host(journal_errors={2: detail})

    level, text = deploy(host, tmp_path)

    assert level == "alert"
    assert detail in text
    assert host.head == PREV and not pushed(host)
    assert any(" reset --keep " + PREV in call for call in host.calls)
    assert "smoke OK" in text


@pytest.mark.parametrize("detail", ["read failed", "journalctl timed out after 60 s"])
def test_rollback_config_journal_failure_is_not_confirmed(
    tmp_path: Path, smokes: list[str], detail: str
) -> None:
    host = Host(journal_errors={2: "forward journal failed", 3: detail})

    level, text = deploy(host, tmp_path)

    assert level == "alert"
    assert host.head == PREV and not pushed(host)
    assert detail in text
    assert "smoke NOT CONFIRMED" in text
