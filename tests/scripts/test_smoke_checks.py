"""scripts/smoke_checks.py and the smoke command, with every boundary faked."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import deploy_smoke
from scripts.smoke_checks import CURSOR_FIXTURE_LINES, Env, measure, smoke

CGROUP = "/user.slice/app.slice/binnacle-mcp.service"
ALL_TOOLS = [
    "read_file",
    "list_files",
    "search_text",
    "edit_file",
    "write_file",
    "run_command",
    "job_status",
    "stop_job",
]


class Clock:
    def __init__(self) -> None:
        self.t = 1_790_459_600.0

    def now(self) -> float:
        self.t += 0.01
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class FakeClient:
    """An MCP client that answers like the live server and records calls."""

    def __init__(
        self, tools: list[str] | None = None, fail: dict[str, str] | None = None
    ):
        self.tools = ALL_TOOLS if tools is None else tools
        self.fail = fail or {}  # tool -> "error" | "raise"
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.jobs: dict[str, str] = {}
        self.cursor_reads: dict[str, int] = {}

    async def __aenter__(self) -> FakeClient:  # noqa: PYI034
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def list_tools(self) -> list[Any]:
        return [SimpleNamespace(name=n) for n in self.tools]

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        self.calls.append((name, args))
        mode = self.fail.get(name)
        if mode == "raise":
            raise RuntimeError(f"{name} broke")
        content = self._answer(name, args)
        return SimpleNamespace(is_error=mode == "error", structured_content=content)

    def _answer(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "read_file":
            return {"content": Path(args["path"]).read_text(encoding="utf-8")}
        if name == "list_files":
            return {"entries": [{"path": f"{args['path']}/a.txt"}], "count": 1}
        if name == "search_text":
            return {"count": 1}
        if name == "write_file":
            return {"action": "created"}
        if name == "edit_file":
            return {"replacements": 1}
        if name == "run_command":
            cmd = args["command"]
            if cmd.startswith("echo "):
                return {"state": "exited", "exit_code": 0, "output": cmd[5:] + "\n"}
            job = f"j{len(self.jobs) + 1}"
            self.jobs[job] = cmd
            return {"state": "running", "job_id": job}
        if name == "job_status":
            job = args["job_id"]
            command = self.jobs[job]
            if "cursor" in args:
                nonce_match = re.search(r"--nonce ([^ ]+)", command)
                nonce = nonce_match.group(1) if nonce_match else "missing-nonce"
                read = self.cursor_reads.get(job, 0)
                self.cursor_reads[job] = read + 1
                split = CURSOR_FIXTURE_LINES // 2
                start, end = (0, split) if read == 0 else (split, CURSOR_FIXTURE_LINES)
                delta = "".join(
                    f"fixture={nonce} seq={seq} mode=normal\n"
                    for seq in range(start, end)
                )
                return {
                    "state": "running" if read == 0 else "exited",
                    "exit_code": None if read == 0 else 0,
                    "log_delta": delta,
                    "next_cursor": f"v1:{job}:{end}",
                    "has_more": read == 0,
                }
            tail = command.split("echo ")[-1]
            return {"state": "exited", "exit_code": 0, "log_tail": tail}
        return {"state": "exited", "signal": 15}


def journal_for(client: FakeClient, drop: str = "", extra: tuple[str, ...] = ()):
    def journal(since: float, until: float | None) -> list[str]:
        if until is not None:  # the start-up window
            return ["2026-09-27T07:53:03.215 INFO: event=config pid=1"]
        lines = list(extra)
        for i, (name, args) in enumerate(client.calls):
            lines.append(
                f"x INFO: event=tool_call call=c{i:04x} tool={name} args={json.dumps(args)}"
            )
            if name != drop:
                lines.append(
                    f"x INFO: event=tool_result call=c{i:04x} tool={name} is_error=False"
                )
        return lines

    return journal


def make_env(
    tmp_path: Path,
    client: FakeClient,
    rc: dict[str, int] | None = None,
    rss: int = 50_000,
    **kw: Any,
) -> Env:
    codes = rc or {}
    clock = Clock()

    def run(argv: Sequence[str], timeout: float) -> tuple[int, str]:
        cmd = " ".join(argv)
        if "ControlGroup" in cmd:
            return 0, CGROUP + "\n"
        if "ExecMainStartTimestamp" in cmd:
            return 0, "Sun 2026-09-27 07:53:02.715341 AEST\n"
        if argv[0] == "date":  # the journal's naive stamps are local time, like `date`
            start = datetime.fromisoformat("2026-09-27T07:53:02.715341").timestamp()
            return 0, f"{start:.6f}\n"
        for key in ("binnacle-tunnel", "binnacle-watchdog", "binnacle"):
            if argv[0].endswith(key):
                return codes.get(key, 0), f"{key}: 30 ok, 0 warn, 0 fail\n"
        return 1, "unexpected"

    def read(path: Path) -> str:
        text = str(path)
        if text.endswith("cgroup.procs"):
            return "101\n102\n"
        if re.fullmatch(r"/proc/\d+/status", text):
            return f"Name: x\nVmRSS:\t {rss // 2} kB\n"
        return path.read_text(encoding="utf-8")

    return Env(
        run=run,
        journal=kw.get("journal") or journal_for(client),
        now=clock.now,
        sleep=clock.sleep,
        client=kw.get("factory") or (lambda: client),
        read=read,
        checkout=tmp_path / "checkout",
        state_dir=tmp_path / "state",
        tmp_root=tmp_path,
    )


def levels(report: Any) -> dict[str, str]:
    return {c.name: c.level for c in report.checks}


def test_a_healthy_server_passes_and_records_the_baseline(tmp_path: Path) -> None:
    client = FakeClient()
    report = smoke(make_env(tmp_path, client))
    assert report.level == "ok", report.lines()
    called = [name for name, _ in client.calls]
    assert (
        called.count("run_command") == 4
        and "stop_job" in called
        and "edit_file" in called
    )
    assert all(
        a.get("path", "").find("e2e-smoke-") >= 0
        for n, a in client.calls
        if n == "read_file"
    )
    base = json.loads((tmp_path / "state" / "baseline.json").read_text())
    assert base["rss_kb"] == 50_000 and base["startup_s"] == 0.5
    assert not list(tmp_path.glob("binnacle-smoke-*")), "the fixture must be removed"


def test_cursor_smoke_drains_fixture_with_opaque_next_cursor(tmp_path: Path) -> None:
    client = FakeClient()
    report = smoke(make_env(tmp_path, client))

    cursor_calls = [
        args for name, args in client.calls if name == "job_status" and "cursor" in args
    ]
    assert len(cursor_calls) == 2
    assert cursor_calls[0]["cursor"] == "start"
    assert cursor_calls[1]["cursor"].startswith("v1:")
    cursor_check = next(c for c in report.checks if c.name == "job_status cursor")
    assert cursor_check.level == "ok"


def test_cursor_smoke_rejects_duplicate_sequence_numbers(tmp_path: Path) -> None:
    class DuplicateCursor(FakeClient):
        def _answer(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
            content = super()._answer(name, args)
            if (
                name == "job_status"
                and "cursor" in args
                and content.get("state") == "exited"
            ):
                content["log_delta"] = str(content["log_delta"]).replace(
                    f"seq={CURSOR_FIXTURE_LINES // 2}",
                    f"seq={CURSOR_FIXTURE_LINES // 2 - 1}",
                    1,
                )
            return content

    report = smoke(make_env(tmp_path, DuplicateCursor()))
    cursor_check = next(c for c in report.checks if c.name == "job_status cursor")
    assert cursor_check.level == "alert"
    assert "sequence mismatch" in cursor_check.detail


def test_memory_growth_over_the_ratio_warns(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "baseline.json").write_text(
        json.dumps({"rss_kb": 40_000, "startup_s": 0.5})
    )
    report = smoke(make_env(tmp_path, FakeClient(), rss=60_000))
    assert levels(report)["rss_kb"] == "warn" and report.level == "warn"


def test_small_growth_inside_the_slack_is_ok(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "baseline.json").write_text(
        json.dumps({"rss_kb": 1_000, "startup_s": 0.2})
    )
    report = smoke(make_env(tmp_path, FakeClient(), rss=2_000))
    assert levels(report)["rss_kb"] == "ok" and levels(report)["startup_s"] == "ok"


def test_rebaseline_overwrites_the_baseline(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "baseline.json").write_text(json.dumps({"rss_kb": 1}))
    smoke(make_env(tmp_path, FakeClient()), rebaseline=True)
    assert (
        json.loads((tmp_path / "state" / "baseline.json").read_text())["rss_kb"]
        == 50_000
    )


def test_a_tool_error_is_an_alert(tmp_path: Path) -> None:
    report = smoke(make_env(tmp_path, FakeClient(fail={"search_text": "error"})))
    assert levels(report)["search_text"] == "alert" and report.level == "alert"
    assert "search_text" in report.summary()


def test_a_failed_stop_is_retried_so_no_sleep_job_is_left(tmp_path: Path) -> None:
    client = FakeClient(fail={"stop_job": "raise"})
    report = smoke(make_env(tmp_path, client))
    assert levels(report)["stop_job"] == "alert"
    assert [n for n, _ in client.calls].count("stop_job") == 2


def test_a_wrong_result_is_an_alert(tmp_path: Path) -> None:
    class Wrong(FakeClient):
        def _answer(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
            if name == "job_status":
                return {"state": "running"}
            return super()._answer(name, args)

    report = smoke(make_env(tmp_path, Wrong()))
    assert levels(report)["job_status"] == "alert"


def test_a_call_missing_from_the_journal_is_an_alert(tmp_path: Path) -> None:
    client = FakeClient()
    env = make_env(tmp_path, client, journal=journal_for(client, drop="read_file"))
    report = smoke(env)
    journal = next(c for c in report.checks if c.name == "journal")
    assert journal.level == "alert" and "read_file" in journal.detail


def test_a_traceback_in_the_journal_is_an_alert(tmp_path: Path) -> None:
    client = FakeClient()
    env = make_env(
        tmp_path,
        client,
        journal=journal_for(client, extra=("Traceback (most recent call last):",)),
    )
    assert levels(smoke(env))["tracebacks"] == "alert"


def test_a_failing_doctor_is_an_alert(tmp_path: Path) -> None:
    report = smoke(make_env(tmp_path, FakeClient(), rc={"binnacle": 1}))
    assert levels(report)["doctor"] == "alert"


def test_full_adds_the_tunnel_and_watchdog_doctors(tmp_path: Path) -> None:
    report = smoke(
        make_env(tmp_path, FakeClient(), rc={"binnacle-watchdog": 1}), full=True
    )
    assert (
        levels(report)["tunnel doctor"] == "ok"
        and levels(report)["watchdog doctor"] == "alert"
    )


def test_a_connection_failure_is_an_alert(tmp_path: Path) -> None:
    def broken() -> Any:
        raise ConnectionError("refused")

    report = smoke(make_env(tmp_path, FakeClient(), factory=broken))
    assert levels(report)["mcp"] == "alert"
    assert not list(tmp_path.glob("binnacle-smoke-*"))


def test_a_missing_tool_is_an_alert(tmp_path: Path) -> None:
    tools = [t for t in ALL_TOOLS if t != "stop_job"]
    report = smoke(make_env(tmp_path, FakeClient(tools=tools)))
    assert levels(report)["tools/list"] == "alert"


def test_edit_tools_are_skipped_when_the_client_is_not_served_them(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        tools=[t for t in ALL_TOOLS if t not in ("edit_file", "write_file")]
    )
    report = smoke(make_env(tmp_path, client))
    assert report.level == "ok" and "write_file" not in [n for n, _ in client.calls]


def test_measure_survives_missing_data(tmp_path: Path) -> None:
    env = make_env(tmp_path, FakeClient())
    env.run = lambda argv, timeout: (1, "")
    assert measure(env) == {}


@pytest.mark.parametrize(
    ("flags", "fail", "code", "printed"),
    [
        (["--quiet-ok"], {}, 0, False),
        ([], {}, 0, True),
        ([], {"read_file": "error"}, 1, True),
    ],
)
def test_main_output_and_exit_code(
    tmp_path: Path,
    capsys: Any,
    flags: list[str],
    fail: dict[str, str],
    code: int,
    printed: bool,
) -> None:
    env = make_env(tmp_path, FakeClient(fail=fail))
    assert deploy_smoke.main(flags, env=env) == code
    out = capsys.readouterr().out
    assert bool(out) == printed
    if printed:
        assert out.split(":")[0] in ("OK", "ALERT")


def test_main_deploy_delegates(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    import scripts.deploy_flow as flow

    monkeypatch.setattr(
        flow, "deploy", lambda env, target, **kw: ("warn", f"WARN: {target}")
    )
    assert (
        deploy_smoke.main(["deploy", "abc123"], env=make_env(tmp_path, FakeClient()))
        == 0
    )
    assert capsys.readouterr().out.startswith("WARN: abc123")
