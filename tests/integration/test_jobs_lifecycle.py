"""Job lifecycle, process, signal, and failure-boundary integration tests."""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle import jobs as jobstore
from binnacle.callctx import current_call, current_call_started
from binnacle.tools import job_status as js
from binnacle.tools import run_command as rc
from tests.integration.job_test_support import run, status, stop


@pytest.fixture(autouse=True, scope="module")
def _isolate_job_store(tmp_path_factory):
    original = jobstore.JOBS_DIR
    jobstore.JOBS_DIR = tmp_path_factory.mktemp("jobs-lifecycle")
    yield
    jobstore.JOBS_DIR = original


@pytest.fixture(autouse=True)
def _short_job_warmup(monkeypatch):
    monkeypatch.setattr(jobstore, "WARMUP_S", 0.05)


@pytest.fixture()
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "store")


# -- 2026-09-03 additions: wait, processes, tail_lines ----------------------
# Motivated by docs/usage-analysis-2026-09-03.md: 596 job_status polls on
# 119 jobs and 333 hand-written `| tail -n` in one week of ChatGPT use.


def test_waited_s_uses_monotonic_counter(monkeypatch):
    ticks = iter((100.0, 101.234))
    monkeypatch.setattr(js, "_PERF_COUNTER", lambda: next(ticks))
    monkeypatch.setattr(
        jobstore, "await_exit", lambda job_id, timeout: {"state": "running"}
    )

    state, waited = js._wait_for_exit("job", 50)
    assert state == {"state": "running"}
    assert waited == 1.234


def test_single_job_timing_logs_stage_breakdown(monkeypatch, caplog):
    state = {
        "job_id": "timing-job",
        "state": "running",
        "exit_code": None,
        "signal": None,
        "command": "sleep 30",
        "workdir": "/tmp",
        "pid": 123,
        "pgid": 123,
        "started_at": 1.0,
        "ended_at": None,
        "runtime_s": 10.0,
        "last_output_age_s": 10.0,
        "log_bytes": 0,
        "log_path": "/tmp/out.log",
    }
    monkeypatch.setattr(jobstore, "job_state", lambda job_id: state)
    monkeypatch.setattr(jobstore, "read_log", lambda job_id: b"")
    monkeypatch.setattr(
        jobstore,
        "job_processes",
        lambda pgid: [
            {"pid": 123, "state": "S", "etime_s": 10.0, "cpu_s": 0.0, "cmd": "sleep 30"}
        ],
    )
    call_token = current_call.set("timing-test-call")
    start_token = current_call_started.set(js._PERF_COUNTER() - 0.020)
    try:
        with caplog.at_level("INFO", logger="binnacle.job_status"):
            p = status("timing-job")
    finally:
        current_call_started.reset(start_token)
        current_call.reset(call_token)

    assert p["state"] == "running"
    lines = [
        r.getMessage()
        for r in caplog.records
        if "event=job_status_timing" in r.getMessage()
    ]
    assert len(lines) == 1
    line = lines[0]
    assert "call=timing-test-call" in line
    assert "job_id=timing-job" in line
    assert "wait_requested_s=0" in line
    assert "wait_bounded_s=0" in line
    assert "wait_effective_s=0" in line
    assert "waited_s=0.0" in line
    assert "blocking_budget_s=na" in line
    assert "blocking_spent_before_s=na" in line
    assert "blocking_remaining_before_s=na" in line
    assert "blocking_active_before=0" in line
    assert "blocking_policy=no_policy" in line
    assert "blocking_budget_exhausted=false" in line
    assert "turn=-" in line and "client=-" in line
    assert "dispatch_ms=" in line and "dispatch_ms=na" not in line
    assert "state_ms=" in line
    assert "read_log_ms=" in line
    assert "process_scan_ms=" in line
    assert "impl_ms=" in line
    assert "state=running" in line
    assert "processes=1" in line


def test_status_wait_returns_when_job_exits():
    p = run("sleep 0.5; echo finished", background=True)
    t0 = time.time()
    s = status(p["job_id"], wait_seconds=10)
    waited = time.time() - t0
    assert s["state"] == "exited" and s["exit_code"] == 0
    assert "finished" in s["log_tail"]
    assert 0.2 < waited < 5  # returned soon after exit, not at the deadline
    assert 0 < s["waited_s"] <= waited + 0.1
    assert s["wait_requested_s"] == 10
    assert s["wait_effective_s"] == 10
    assert s["blocking_budget_s"] is None
    assert s["blocking_remaining_s"] is None
    assert s["blocking_budget_exhausted"] is False
    assert s["blocking_policy"] == "no_policy"


def test_status_wait_expires_leaves_job_running():
    p = run("sleep 30", background=True)
    t0 = time.time()
    result = js.job_status_impl(p["job_id"], 100, 1)
    elapsed = time.time() - t0
    s = result.structured_content
    assert s is not None and 0.9 < elapsed < 3
    assert s["state"] == "running" and s["waited_s"] >= 0.9
    assert "Still running after waiting" in result.content[0].text
    stop(p["job_id"])


def test_status_wait_is_capped(monkeypatch):
    monkeypatch.setattr(js, "WAIT_MAX", 0.25)
    p = run("sleep 30", background=True)
    t0 = time.time()
    s = status(p["job_id"], wait_seconds=40)
    elapsed = time.time() - t0
    assert 0.15 < elapsed < 2 and s["state"] == "running"
    assert (s["wait_requested_s"], s["wait_effective_s"]) == (40, 0.25)
    stop(p["job_id"])


def test_status_lists_processes_of_running_job():
    p = run("sleep 30 & sleep 30; wait", background=True)
    s = status(p["job_id"])
    cmds = [proc["cmd"] for proc in s["processes"]]
    assert any(c.startswith("bash") for c in cmds)
    assert sum("sleep 30" in c for c in cmds) >= 2  # the children, not just bash
    for proc in s["processes"]:
        assert proc["pid"] > 0 and proc["etime_s"] >= 0 and proc["cpu_s"] >= 0
    stop(p["job_id"])
    assert status(p["job_id"])["processes"] == []


def test_job_processes_empty_for_dead_group():
    assert jobstore.job_processes(2**22 - 7) == []


def test_run_tail_lines_keeps_last_lines_only():
    p = run("for i in $(seq 1 50); do echo line$i; done", tail_lines=5)
    body = p["output"].splitlines()
    assert body[0].startswith("[… 45 earlier lines omitted")
    assert body[1:] == ["line46", "line47", "line48", "line49", "line50"]
    assert p["truncated"] is True
    assert p["output_bytes"] > len(p["output"])  # full log still on disk


def test_run_tail_lines_larger_than_output_is_noop():
    p = run("echo a; echo b", tail_lines=10)
    assert p["output"] == "a\nb\n" and p["truncated"] is False


# -- background_job flag (2026-09-06; docs/usage-analysis-2026-09-06.md §6) --
# Synchronous completion must report that no background job was created.


def test_synchronous_run_reports_no_background_job():
    p = run("echo hi")
    assert p["state"] == "exited" and p["background_job"] is False
    content = rc.run_command_impl("echo hi", "/tmp", 10, False, None).content[0].text
    assert "no background job was created" in content.lower()


def test_killed_command_also_reports_no_background_job():
    p = run("exit 4")
    assert p["state"] == "exited" and p["background_job"] is False


def test_background_run_marks_background_job_true():
    p = run("sleep 30", background=True)
    assert p["state"] == "running" and p["background_job"] is True
    content = rc.run_command_impl("sleep 30", "/tmp", 10, True, None).content[0].text
    assert "no background job" not in content.lower()
    assert "Use job_status when the result is needed, or stop_job to cancel." in content
    assert "continue independent work" not in content.lower()
    assert "call job_status once" not in content.lower()
    stop(p["job_id"])
    stop(p["job_id"])  # idempotent; also cleans the second job


def test_fast_command_never_races_to_running():
    # The reaper writes the exit slightly after the process ends; run_command
    # must wait for it, so a quick command is always "exited", not "running"
    # (regression: background_job=true leaked on fast commands, 2026-09-06).
    for _ in range(20):
        p = run("echo quick")
        assert p["state"] == "exited", f"raced to {p['state']}"
        assert p["background_job"] is False


def test_stop_reports_recorded_signal_not_unknown():
    # stop_job must return the recorded exit (signal 15), never a transient
    # "unknown" from reading disk before the reaper wrote it (2026-09-06,
    # coherent with run_command's inline recording).
    for _ in range(10):
        p = run("sleep 30", background=True)
        r = stop(p["job_id"])
        assert r["state"] == "exited", f"got {r['state']}"
        assert r["signal"] == 15 and r["exit_code"] is None


def test_status_wait_bridges_to_exited_for_background_job():
    p = run("sleep 0.4", background=True)
    s = status(p["job_id"], wait_seconds=10)
    assert s["state"] == "exited" and s["exit_code"] == 0  # never "unknown"


def _wait_until(cond, timeout: float = 5.0, step: float = 0.05) -> bool:
    """Poll because loaded hosts can delay child-process readiness."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(step)
    return cond()


# -- corner cases: signals, group kill, external kill (2026-09-06) ----------
# Keep run_command / job_status / stop_job consistent when a command dies by
# a signal (its own, stop_job's, or another command's), not a clean exit.


def test_command_that_sigterms_itself_reports_signal():
    p = run("kill -TERM $$")
    assert p["state"] == "exited" and p["background_job"] is False
    assert p["signal"] == 15 and p["exit_code"] is None


def test_command_that_sigkills_itself_reports_signal():
    p = run("kill -KILL $$")
    assert p["state"] == "exited" and p["signal"] == 9 and p["exit_code"] is None


def test_background_flag_with_fast_command_still_reports_exited():
    # background=true must not force a false "running" for a command that
    # finishes inside the warm-up window.
    p = run("echo quick", background=True)
    assert p["state"] == "exited" and p["exit_code"] == 0
    assert p["background_job"] is False


def test_stop_escalates_to_sigkill_when_sigterm_ignored(monkeypatch):
    # A process that ignores SIGTERM must still be stopped, by SIGKILL, and
    # the recorded signal must be 9. Shrink the grace so the test is quick.
    monkeypatch.setattr(jobstore, "STOP_SIGTERM_GRACE_S", 0.25)
    p = run(
        "exec python3 -c 'import signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'",
        background=True,
    )
    r = stop(p["job_id"])
    assert r["state"] == "exited" and r["signal"] == 9


def test_stop_kills_the_whole_process_group():
    p = run("sleep 60 & sleep 60 & wait", background=True)
    pgid = jobstore.job_state(p["job_id"])["pgid"]

    def children() -> list[int]:
        return [
            pr["pid"] for pr in jobstore.job_processes(pgid) if "sleep 60" in pr["cmd"]
        ]

    assert _wait_until(lambda: len(children()) >= 2), (
        f"saw {jobstore.job_processes(pgid)}"
    )
    child_pids = children()
    stop(p["job_id"])
    assert _wait_until(lambda: all(not jobstore._pid_alive(pid) for pid in child_pids))


def test_external_kill_via_run_command_is_recorded_and_visible():
    # The user's example: kill another job from inside run_command. The victim
    # must end up recorded exactly as if stop_job had done it (exited, signal
    # 15), and job_status must show it — all three tools stay consistent.
    victim = run("sleep 30", background=True)
    pid = jobstore.job_state(victim["job_id"])["pid"]
    killer = run(f"kill -TERM {pid}")
    assert killer["state"] == "exited" and killer["background_job"] is False
    s = status(victim["job_id"], wait_seconds=5)
    assert s["state"] == "exited" and s["signal"] == 15


def test_double_stop_reports_the_same_final_state():
    p = run("sleep 30", background=True)
    r1 = stop(p["job_id"])
    r2 = stop(p["job_id"])
    assert r1["state"] == "exited" and r1["signal"] == 15
    assert r2["state"] == "exited" and r2["signal"] == 15  # idempotent, consistent


def test_stop_a_job_that_just_finished_on_its_own():
    # Observe the real child exit instead of sleeping a fixed cushion.
    p = run("sleep 0.3", background=True)
    assert _wait_until(lambda: status(p["job_id"])["state"] == "exited", timeout=3)
    r = stop(p["job_id"])
    assert r["state"] == "exited" and r["exit_code"] == 0 and r["signal"] is None


# -- corner cases beyond signals (2026-09-06) -------------------------------
# Families: reload orphans + pid reuse, malformed/missing store files, stdin
# pipe behavior, exit-code vs signal encoding, processes escaping the group,
# listing robustness, parameter clamps, concurrency, output encoding.


def _fake_job(name: str, meta: dict, log: str = "") -> None:
    d = jobstore.JOBS_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "out.log").write_text(log)


def test_malformed_meta_does_not_crash_status_or_listing(fresh_store):
    _fake_job("badmeta00001", {"command": "x"})  # parses, but incomplete
    with pytest.raises(ToolError, match="No job with id"):
        status("badmeta00001")
    assert status()["jobs"] == []  # listing skips it instead of raising


def test_exit_code_128_plus_n_is_not_mistaken_for_a_signal():
    p = run("exit 143")
    assert p["exit_code"] == 143 and p.get("signal") is None


def test_invalid_utf8_output_is_replaced_not_fatal():
    p = run("printf '\\xff\\xfeok'")
    assert p["state"] == "exited" and "ok" in p["output"]


def test_missing_log_file_does_not_break_status(fresh_store):
    p = run("sleep 5", background=True)
    (jobstore.JOBS_DIR / p["job_id"] / "out.log").unlink()
    s = status(p["job_id"])
    assert s["state"] == "running" and s["log_bytes"] == 0 and s["log_tail"] == ""
    stop(p["job_id"])


def test_large_unread_stdin_does_not_stall_past_wait_seconds():
    # Keep >64 KiB of real pipe pressure while using the minimum public wait.
    t0 = time.time()
    p = run("sleep 20", wait_seconds=1, stdin="x" * 200_000)
    elapsed = time.time() - t0
    assert 0.9 < elapsed < 3 and p["state"] == "running"
    stop(p["job_id"])


def test_stdin_is_delivered_and_survives_on_disk():
    p = run("cat", stdin="from-stdin\n")
    assert p["output"] == "from-stdin\n"
    assert (jobstore.JOBS_DIR / p["job_id"] / "stdin").read_text() == "from-stdin\n"


def test_setsid_child_is_stopped_with_the_job():
    # A child that calls setsid() leaves the process group; stop_job must
    # still reach it through the descendant walk.
    marker = f"sleep 40.{os.getpid() % 1000}"
    p = run(f"setsid {marker} & {marker}", background=True)

    def alive() -> list[str]:
        out = subprocess.run(
            ["pgrep", "-f", f"^{marker}$"], capture_output=True, text=True, check=False
        )
        return out.stdout.split()

    assert _wait_until(lambda: len(alive()) == 2), f"saw {alive()}"
    stop(p["job_id"])
    assert _wait_until(lambda: alive() == []), f"leaked: {alive()}"


def test_pid_reuse_is_not_reported_as_running(fresh_store):
    # A record whose pid now belongs to an unrelated live process (ours) with
    # a different start time must not read as running, so stop_job never
    # signals a stranger after a reload.
    _fake_job(
        "pidreuse0001",
        {
            "command": "x",
            "workdir": "/tmp",
            "pid": os.getpid(),
            "pgid": os.getpid(),
            "starttime": 1,  # not ours
            "started_at": time.time() - 100,
        },
    )
    assert jobstore.job_state("pidreuse0001")["state"] == "unknown"
    assert stop("pidreuse0001")["state"] == "unknown"  # returned without signaling


def test_pid_identity_match_reads_as_running(fresh_store):
    mine = jobstore._proc_starttime(os.getpid())
    _fake_job(
        "pidmatch00001",
        {
            "command": "x",
            "workdir": "/tmp",
            "pid": os.getpid(),
            "pgid": os.getpid(),
            "starttime": mine,
            "started_at": time.time(),
        },
    )
    assert jobstore.job_state("pidmatch00001")["state"] == "running"


def test_legacy_record_without_starttime_falls_back_to_existence(fresh_store):
    _fake_job(
        "legacy000001",
        {"command": "x", "workdir": "/tmp", "pid": os.getpid(), "started_at": 1.0},
    )
    assert jobstore.job_state("legacy000001")["state"] == "running"


def test_reload_orphan_running_then_unknown_and_stop_is_honest(fresh_store):
    # Simulate "the server that started it died": start the process with no
    # watcher (start_job spawns none). While alive it is running; after it
    # ends nobody records the exit, so it is unknown, and stop_job says so
    # rather than inventing a signal.
    job_id, proc = jobstore.start_job("sleep 0.4", Path("/tmp"), None)
    assert status(job_id)["state"] == "running"
    proc.wait()  # reap it ourselves, but record nothing (as a dead server would)
    assert status(job_id)["state"] == "unknown"
    r = stop(job_id)
    assert r["state"] == "unknown" and r["signal"] is None


def test_unwritable_spool_is_a_clean_tool_error(tmp_path, monkeypatch):
    store = tmp_path / "ro"
    store.mkdir()
    store.chmod(0o500)
    if os.access(store, os.W_OK):
        pytest.skip("running as root; chmod does not restrict")
    monkeypatch.setattr(jobstore, "JOBS_DIR", store)
    try:
        with pytest.raises(ToolError, match="Could not start the job"):
            run("echo hi")
    finally:
        store.chmod(0o700)


def test_run_command_wait_seconds_is_clamped_to_max(monkeypatch):
    monkeypatch.setattr(rc, "RUN_WAIT_MAX", 1)
    t0 = time.time()
    p = run("sleep 10", wait_seconds=500)
    assert time.time() - t0 < 4 and p["state"] == "running"
    stop(p["job_id"])


def test_concurrent_stops_agree():
    p = run("sleep 30", background=True)
    results: list[dict] = []

    def go() -> None:
        results.append(stop(p["job_id"]))

    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert [r["state"] for r in results] == ["exited", "exited"]
    assert {r["signal"] for r in results} == {15}
