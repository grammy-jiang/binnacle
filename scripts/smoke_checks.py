"""The live smoke's checks (``scripts/deploy_smoke.py`` is the command).

Everything the checks touch goes through ``Env``, so tests inject fakes: the
command runner, the journal reader, the clock, the MCP client and the file
reader. Quality guard plan: docs/quality-guard-plan-2026-09-27.md, step 2.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

UNIT = "binnacle-mcp.service"
NONCE_PREFIX = "e2e-smoke-"  # usage statistics treat "e2e-" as test traffic
EXPECTED_TOOLS = (
    "read_file",
    "list_files",
    "search_text",
    "run_command",
    "job_status",
    "stop_job",
)
WARN_RATIO = 1.25
# Absolute slack under the ratio, so that a small baseline does not turn
# measurement noise into a WARN.
RSS_SLACK_KB = 8 * 1024
STARTUP_SLACK_S = 1.0
CURSOR_FIXTURE_MINUTES = 0.05
CURSOR_FIXTURE_INTERVAL_S = 0.25
CURSOR_FIXTURE_LINES = 12
LEVELS = {"ok": 0, "warn": 1, "alert": 2}


@dataclass
class Check:
    name: str
    level: str  # ok | warn | alert
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, level: str, detail: str) -> None:
        self.checks.append(Check(name, level, detail))

    @property
    def level(self) -> str:
        levels = [c.level for c in self.checks] or ["ok"]
        return max(levels, key=LEVELS.__getitem__)

    def failing(self) -> list[Check]:
        return [c for c in self.checks if c.level != "ok"]

    def lines(self) -> list[str]:
        return [f"  [{c.level:5}] {c.name}: {c.detail}" for c in self.checks]

    def summary(self) -> str:
        bad = self.failing()
        if not bad:
            return f"live smoke passed ({len(self.checks)} checks)"
        return "; ".join(f"{c.name}: {c.detail}" for c in bad)[:300]


@dataclass
class Env:
    """Everything the smoke touches, injectable for tests."""

    run: Callable[[Sequence[str], float], tuple[int, str]]
    journal: Callable[[float, float | None], list[str]]
    now: Callable[[], float]
    sleep: Callable[[float], None]
    client: Callable[[], Any]
    read: Callable[[Path], str]
    checkout: Path
    state_dir: Path
    tmp_root: Path


def last_line(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1][:160] if lines else "(no output)"


def _expect(condition: bool, message: str) -> str:
    return "" if condition else message


class _Caller:
    """Calls one tool and records the check, and remembers what the journal
    must hold: (tool, a token that appears in that call's logged arguments)."""

    def __init__(self, client: Any, report: Report) -> None:
        self.client = client
        self.report = report
        self.logged: list[tuple[str, str]] = []

    async def __call__(
        self,
        name: str,
        args: dict[str, Any],
        token: str,
        check: Callable[[dict[str, Any]], str],
    ) -> dict[str, Any] | None:
        try:
            result = await self.client.call_tool(name, args)
        except Exception as exc:  # noqa: BLE001 - any failure is the finding
            self.report.add(name, "alert", f"call failed: {exc}"[:200])
            return None
        self.logged.append((name, token))
        content = getattr(result, "structured_content", None)
        content = content if isinstance(content, dict) else {}
        if getattr(result, "is_error", False):
            self.report.add(name, "alert", f"tool error: {str(content)[:160]}")
            return None
        problem = check(content)
        self.report.add(name, "alert" if problem else "ok", problem or "ok")
        return None if problem else content


async def _file_tools(
    call: _Caller, names: set[str], nonce: str, fixture: Path
) -> None:
    await call(
        "read_file",
        {"path": str(fixture / "a.txt")},
        nonce,
        lambda c: _expect(nonce in str(c.get("content", "")), "nonce not in content"),
    )
    await call(
        "list_files",
        {"path": str(fixture)},
        nonce,
        lambda c: _expect(
            any(str(e.get("path", "")).endswith("a.txt") for e in c.get("entries", [])),
            "a.txt not listed",
        ),
    )
    await call(
        "search_text",
        {"pattern": nonce, "path": str(fixture), "fixed_strings": True},
        nonce,
        lambda c: _expect(int(c.get("count", 0)) >= 1, "nonce not found"),
    )
    if {"write_file", "edit_file"} <= names:  # served to this client
        path = str(fixture / "b.txt")
        await call(
            "write_file",
            {"path": path, "content": f"x {nonce}\n"},
            nonce,
            lambda c: _expect(
                c.get("action") in ("created", "overwritten"), "not written"
            ),
        )
        await call(
            "edit_file",
            {"path": path, "old_string": "x ", "new_string": "y "},
            nonce,
            lambda c: _expect(c.get("replacements") == 1, "not replaced once"),
        )


def _job_started(c: dict[str, Any]) -> str:
    return _expect(c.get("state") == "running" and bool(c.get("job_id")), "no job")


def _cursor_sequence_problem(text: str, nonce: str) -> str:
    sequences: list[int] = []
    pattern = re.compile(rf"^fixture={re.escape(nonce)} seq=(\d+) mode=normal$")
    for line in text.splitlines():
        match = pattern.fullmatch(line)
        if not match:
            return f"unexpected cursor output line {line[:100]!r}"
        sequences.append(int(match.group(1)))
    expected = list(range(CURSOR_FIXTURE_LINES))
    return _expect(
        sequences == expected,
        f"sequence mismatch: got {sequences[:20]}, expected {expected}",
    )


async def _cursor_job(call: _Caller, nonce: str, fixture: Path, checkout: Path) -> None:
    """Start and fully drain a short numbered fixture through cursor mode."""
    cursor_nonce = f"{nonce}-cursor"
    command = shlex.join(
        [
            str(checkout / ".venv/bin/python"),
            str(checkout / "scripts/longrun_fixture.py"),
            "normal",
            "--nonce",
            cursor_nonce,
            "--n",
            str(CURSOR_FIXTURE_MINUTES),
            "--s",
            str(CURSOR_FIXTURE_INTERVAL_S),
        ]
    )
    started = await call(
        "run_command",
        {"command": command, "workdir": str(fixture), "wait_seconds": 1},
        cursor_nonce,
        _job_started,
    )
    if not started:
        call.report.add("job_status cursor", "alert", "fixture did not start")
        return

    job = str(started["job_id"])
    cursor = "start"
    chunks: list[str] = []
    for _ in range(100):
        args = {"job_id": job, "cursor": cursor, "wait_seconds": 10}
        try:
            result = await call.client.call_tool("job_status", args)
        except Exception as exc:  # noqa: BLE001 - any failure is the finding
            call.report.add("job_status cursor", "alert", f"call failed: {exc}"[:200])
            return
        call.logged.append(("job_status", cursor))
        content = getattr(result, "structured_content", None)
        content = content if isinstance(content, dict) else {}
        if getattr(result, "is_error", False):
            call.report.add(
                "job_status cursor", "alert", f"tool error: {str(content)[:160]}"
            )
            return
        chunks.append(str(content.get("log_delta", "")))
        if content.get("state") != "running" and content.get("has_more") is False:
            problem = _cursor_sequence_problem("".join(chunks), cursor_nonce)
            call.report.add(
                "job_status cursor", "alert" if problem else "ok", problem or "ok"
            )
            return
        next_cursor = content.get("next_cursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            call.report.add("job_status cursor", "alert", "missing next_cursor")
            return
        cursor = next_cursor

    call.report.add("job_status cursor", "alert", "cursor drain exceeded 100 calls")


async def _job_tools(
    call: _Caller, nonce: str, fixture: Path, checkout: Path
) -> str | None:
    """run_command, job_status and stop_job; return a job id still to stop."""
    wd = str(fixture)
    await call(
        "run_command",
        {"command": f"echo {nonce}-fast", "workdir": wd, "wait_seconds": 10},
        f"{nonce}-fast",
        lambda c: _expect(
            c.get("state") == "exited"
            and c.get("exit_code") == 0
            and f"{nonce}-fast" in str(c.get("output", "")),
            f"unexpected result {str(c)[:120]}",
        ),
    )
    started = await call(
        "run_command",
        {"command": f"sleep 3; echo {nonce}-job", "workdir": wd, "wait_seconds": 1},
        f"{nonce}-job",
        _job_started,
    )
    if started:
        job = str(started["job_id"])
        await call(
            "job_status",
            {"job_id": job, "wait_seconds": 10},
            job,
            lambda c: _expect(
                c.get("state") == "exited"
                and c.get("exit_code") == 0
                and f"{nonce}-job" in str(c.get("log_tail", "")),
                f"unexpected status {str(c)[:120]}",
            ),
        )
    await _cursor_job(call, nonce, fixture, checkout)
    long_job = await call(
        "run_command",
        {"command": f"sleep 60; echo {nonce}-stop", "workdir": wd, "wait_seconds": 1},
        f"{nonce}-stop",
        _job_started,
    )
    if not long_job:
        return None
    job = str(long_job["job_id"])
    stopped = await call(
        "stop_job",
        {"job_id": job},
        job,
        lambda c: _expect(
            c.get("state") in ("exited", "stopped", "killed"),
            f"not stopped {str(c)[:120]}",
        ),
    )
    return None if stopped else job


async def exercise(
    env: Env, report: Report, nonce: str, fixture: Path
) -> list[tuple[str, str]]:
    """Call every tool once through a real MCP client."""
    async with env.client() as client:
        call = _Caller(client, report)
        try:
            names = {t.name for t in await client.list_tools()}
        except Exception as exc:  # noqa: BLE001
            report.add("tools/list", "alert", f"failed: {exc}"[:200])
            return call.logged
        missing = [t for t in EXPECTED_TOOLS if t not in names]
        detail = f"{len(names)} tools" + (f"; missing {missing}" if missing else "")
        report.add("tools/list", "alert" if missing else "ok", detail)
        leftover = None
        try:
            await _file_tools(call, names, nonce, fixture)
            leftover = await _job_tools(call, nonce, fixture, env.checkout)
        finally:
            if leftover:  # never leave a sleep job behind
                try:
                    await client.call_tool("stop_job", {"job_id": leftover})
                except Exception as exc:  # noqa: BLE001 - reported, not raised
                    detail = f"job {leftover} not stopped: {exc}"
                    report.add("cleanup", "warn", detail[:200])
        return call.logged


def _missing_from(lines: list[str], logged: list[tuple[str, str]]) -> list[str]:
    missing = []
    for tool, token in logged:
        call_id = None
        for ln in lines:
            if "event=tool_call" in ln and f"tool={tool} " in ln and token in ln:
                m = re.search(r"\bcall=([0-9a-f]+)", ln)
                call_id = m.group(1) if m else None
                break
        if not call_id or not any(
            "event=tool_result" in ln and f"call={call_id} " in ln for ln in lines
        ):
            missing.append(tool)
    return missing


def check_journal(
    env: Env, report: Report, since: float, logged: list[tuple[str, str]]
) -> None:
    deadline = env.now() + 10  # the journal can lag the call by a moment
    while True:
        lines = env.journal(since, None)
        missing = _missing_from(lines, logged)
        if not missing or env.now() >= deadline:
            break
        env.sleep(1)
    detail = f"{len(logged) - len(missing)}/{len(logged)} calls logged"
    report.add(
        "journal",
        "alert" if missing else "ok",
        detail + (f"; missing {missing}" if missing else ""),
    )
    tracebacks = sum("Traceback" in ln for ln in lines)
    report.add(
        "tracebacks",
        "alert" if tracebacks else "ok",
        f"{tracebacks} since the smoke began",
    )


def _epoch(env: Env, stamp: str) -> float | None:
    rc, out = env.run(["date", "-d", stamp, "+%s.%N"], 10)
    try:
        return float(out.strip()) if rc == 0 else None
    except ValueError:
        return None


def _rss_kb(env: Env) -> float | None:
    show = ["systemctl", "--user", "show", UNIT, "-p", "ControlGroup", "--value"]
    rc, cgroup = env.run(show, 10)
    if rc or not cgroup.strip():
        return None
    total = 0
    try:
        procs = Path("/sys/fs/cgroup") / cgroup.strip().lstrip("/") / "cgroup.procs"
        for pid in env.read(procs).split():
            status = env.read(Path("/proc") / pid / "status")
            m = re.search(r"^VmRSS:\s+(\d+)\s+kB", status, re.MULTILINE)
            total += int(m.group(1)) if m else 0
    except OSError:
        return None
    return float(total) or None


def _startup_s(env: Env) -> float | None:
    # From the main process's start to the server's configured line. Not from
    # ActiveEnterTimestamp: the unit's ExecStartPost port wait makes the unit
    # active only after the server is already up.
    show = ["systemctl", "--user", "show", UNIT, "-p", "ExecMainStartTimestamp"]
    rc, active = env.run([*show, "--value", "--timestamp=us"], 10)
    started = _epoch(env, active.strip()) if rc == 0 and active.strip() else None
    if started is None:
        return None
    for ln in env.journal(started - 1, started + 120):
        m = re.match(r"^(\d{4}-\d\d-\d\dT[\d:.]+) INFO: event=config\b", ln)
        if m:
            ready = datetime.fromisoformat(m.group(1)).timestamp()
            if ready >= started - 1:
                return round(max(0.0, ready - started), 3)
    return None


def measure(env: Env) -> dict[str, float]:
    """RSS of the unit's processes (kB) and the unit's start-up time (s)."""
    out: dict[str, float] = {}
    rss = _rss_kb(env)
    if rss:
        out["rss_kb"] = rss
    startup = _startup_s(env)
    if startup is not None:
        out["startup_s"] = startup
    return out


def check_budgets(env: Env, report: Report, rebaseline: bool) -> None:
    now = measure(env)
    path = env.state_dir / "baseline.json"
    try:
        base = json.loads(env.read(path))
    except (OSError, ValueError):
        base = None
    if base is None or rebaseline:
        env.state_dir.mkdir(parents=True, exist_ok=True)
        record = {**now, "recorded_at": env.now()}
        path.write_text(json.dumps(record, indent=1), encoding="utf-8")
        report.add("baseline", "ok", f"recorded {now}")
        return
    budgets = (("rss_kb", RSS_SLACK_KB, "kB"), ("startup_s", STARTUP_SLACK_S, "s"))
    for key, slack, unit in budgets:
        if key not in now or not base.get(key):
            report.add(key, "ok", "not measured")
            continue
        value, ref = now[key], float(base[key])
        over = value > ref * WARN_RATIO and value - ref > slack
        report.add(
            key, "warn" if over else "ok", f"{value:g} {unit} (baseline {ref:g})"
        )


def smoke(env: Env, full: bool = False, rebaseline: bool = False) -> Report:
    """Run every check once against the live server."""
    report = Report()
    since = env.now()
    rc, out = env.run([str(env.checkout / ".venv/bin/binnacle"), "doctor"], 180)
    report.add("doctor", "ok" if rc == 0 else "alert", last_line(out))
    nonce = f"{NONCE_PREFIX}{time.strftime('%Y%m%d%H%M%S')}-{os.getpid()}"
    fixture = env.tmp_root / f"binnacle-smoke-{nonce}"
    logged: list[tuple[str, str]] = []
    try:
        fixture.mkdir(parents=True)
        (fixture / "a.txt").write_text(f"hello {nonce}\n", encoding="utf-8")
        logged = asyncio.run(exercise(env, report, nonce, fixture))
    except Exception as exc:  # noqa: BLE001 - a broken connection is a finding
        report.add("mcp", "alert", f"{type(exc).__name__}: {exc}"[:200])
    finally:
        shutil.rmtree(fixture, ignore_errors=True)
    check_journal(env, report, since, logged)
    check_budgets(env, report, rebaseline)
    if full:
        venv = env.checkout / ".venv/bin"
        for name, argv in (
            ("tunnel doctor", [str(venv / "binnacle-tunnel"), "doctor"]),
            (
                "watchdog doctor",
                [str(venv / "binnacle-watchdog"), "doctor", "--no-probe"],
            ),
        ):
            rc, out = env.run(argv, 180)
            report.add(name, "ok" if rc == 0 else "alert", last_line(out))
    return report
