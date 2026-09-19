"""Implementation gate for run_command / job_status / stop_job.

Spec: docs/tools/run_command.md §7. These tests spawn real short-lived
processes under /tmp; a session-scoped cleanup removes their job dirs.
"""

import time

import pytest
from fastmcp.exceptions import ToolError

from binnacle import jobs as jobstore
from binnacle.callctx import current_call, current_call_started
from binnacle.tools import job_status as js
from binnacle.tools import run_command as rc
from binnacle.tools import stop_job as sj


def run(
    command: str,
    workdir: str = "/tmp",
    wait_seconds: int = 10,
    background: bool = False,
    stdin: str | None = None,
    tail_lines: int | None = None,
) -> dict:
    payload = rc.run_command_impl(
        command, workdir, wait_seconds, background, stdin, tail_lines
    ).structured_content
    assert payload is not None
    return payload


def status(job_id=None, tail_lines: int = 100, wait_seconds: int = 0) -> dict:
    payload = js.job_status_impl(job_id, tail_lines, wait_seconds).structured_content
    assert payload is not None
    return payload


def stop(job_id: str) -> dict:
    payload = sj.stop_job_impl(job_id).structured_content
    assert payload is not None
    return payload


# -- run_command: fast path ------------------------------------------------


def test_fast_command_exits_zero_with_output():
    p = run("echo hello")
    assert p["state"] == "exited" and p["exit_code"] == 0
    assert p["output"] == "hello\n"


def test_stderr_merges_with_stdout():
    p = run("echo out; echo err 1>&2")
    assert "out" in p["output"] and "err" in p["output"]


def test_nonzero_exit_code():
    p = run("exit 3")
    assert p["state"] == "exited" and p["exit_code"] == 3


def test_stdin_piped():
    p = run("cat", stdin="piped-input\n")
    assert p["output"] == "piped-input\n"


def test_workdir_honored(tmp_path):
    p = run("pwd", workdir=str(tmp_path))
    assert p["output"].strip() == str(tmp_path)


def test_workdir_outside_roots_rejected():
    with pytest.raises(ToolError, match="not a directory|outside allowed roots"):
        rc.run_command_impl("pwd", "/etc/nonexistent-xyz", 5, False, None)


def test_env_hygiene_pager_is_cat():
    p = run("echo $PAGER $CI $BINNACLE")
    assert p["output"].strip() == "cat 1 1"


# -- run_command: yield path -----------------------------------------------


def test_slow_command_yields_job_then_completes():
    p = run("sleep 2; echo done", wait_seconds=1)
    assert p["state"] == "running" and "job_id" in p
    job_id = p["job_id"]
    for _ in range(40):
        time.sleep(0.2)
        s = status(job_id)
        if s["state"] == "exited":
            break
    assert s["state"] == "exited" and s["exit_code"] == 0
    assert "done" in s["log_tail"]


def test_background_returns_fast():
    t0 = time.time()
    p = run("sleep 5", background=True)
    assert p["state"] == "running" and (time.time() - t0) < 3


def test_output_truncated_head_tail_but_full_log_on_disk():
    # 60k chars of output; per-call clip is 24k, disk keeps all.
    p = run("for i in $(seq 1 6000); do printf '0123456789\\n'; done", wait_seconds=10)
    assert p["truncated"] and len(p["output"]) < 30_000
    assert "chars elided" in p["output"]
    assert p["output_bytes"] >= 60_000


# -- job_status ------------------------------------------------------------


def test_status_unknown_job_errors():
    with pytest.raises(ToolError, match="No job with id"):
        status("deadbeefdead")


def test_status_list_newest_first():
    a = run("echo a")["job_id"]
    time.sleep(0.05)
    b = run("echo b")["job_id"]
    listing = status()["jobs"]
    ids = [row["job_id"] for row in listing]
    assert ids.index(b) < ids.index(a)


def _listing_state(
    job_id: str,
    *,
    state: str = "exited",
    command: str = "echo ok",
    workdir: str = "/tmp",
    started_at: float = 1.0,
    runtime_s: float = 1.0,
    exit_code: int | None = 0,
) -> dict:
    return {
        "job_id": job_id,
        "state": state,
        "exit_code": exit_code,
        "runtime_s": runtime_s,
        "started_at": started_at,
        "workdir": workdir,
        "command": command,
    }


def test_status_listing_keeps_all_running_plus_recent_history(monkeypatch):
    monkeypatch.setattr(js, "LISTING_HISTORY_LIMIT", 3)
    states = [
        _listing_state("newest"),
        _listing_state("run-new", state="running", exit_code=None),
        _listing_state("hist-2"),
        _listing_state("hist-3"),
        _listing_state("old-omit"),
        _listing_state("run-old", state="running", exit_code=None),
        _listing_state("older-omit"),
    ]
    monkeypatch.setattr(jobstore, "list_jobs", lambda: states)

    rows = status()["jobs"]
    assert [r["job_id"] for r in rows] == [
        "newest",
        "run-new",
        "hist-2",
        "hist-3",
        "run-old",
    ]
    assert sum(r["state"] != "running" for r in rows) == 3
    assert {r["job_id"] for r in rows if r["state"] == "running"} == {
        "run-new",
        "run-old",
    }


def test_status_listing_preview_is_head_tail_and_adds_workdir(monkeypatch):
    monkeypatch.setattr(js, "LISTING_COMMAND_PREVIEW_CHARS", 40)
    command = "HEAD-" + "x" * 100 + "-TAIL"
    state = _listing_state(
        "job", command=command, workdir="/tmp/project", started_at=42.0
    )
    monkeypatch.setattr(jobstore, "list_jobs", lambda: [state])

    row = status()["jobs"][0]
    assert row["workdir"] == "/tmp/project"
    assert row["command"].startswith("HEAD-")
    assert row["command"].endswith("-TAIL")
    assert "chars omitted" in row["command"]
    assert row["started_at"] == 42.0


def test_status_listing_short_command_kept_and_newlines_are_one_line(monkeypatch):
    state = _listing_state("job", command="printf one\\nprintf two")
    monkeypatch.setattr(jobstore, "list_jobs", lambda: [state])

    row = status()["jobs"][0]
    assert row["command"] == r"printf one\nprintf two"


def test_status_listing_unknown_counts_as_history(monkeypatch):
    monkeypatch.setattr(js, "LISTING_HISTORY_LIMIT", 1)
    states = [
        _listing_state("unknown", state="unknown", exit_code=None),
        _listing_state("exited"),
        _listing_state("running", state="running", exit_code=None),
    ]
    monkeypatch.setattr(jobstore, "list_jobs", lambda: states)
    assert [r["job_id"] for r in status()["jobs"]] == ["unknown", "running"]


def test_status_listing_summary_says_when_history_is_omitted(monkeypatch):
    monkeypatch.setattr(js, "LISTING_HISTORY_LIMIT", 1)
    states = [
        _listing_state("run", state="running", exit_code=None),
        _listing_state("new"),
        _listing_state("old"),
    ]
    monkeypatch.setattr(jobstore, "list_jobs", lambda: states)
    result = js.job_status_impl(None, 100, 0)
    assert result.structured_content is not None
    assert len(result.structured_content["jobs"]) == 2
    assert "2 of 3 job(s) shown" in result.content[0].text
    assert "all 1 running" in result.content[0].text


def test_status_listing_logs_correlated_counts(monkeypatch, caplog):
    monkeypatch.setattr(js, "LISTING_HISTORY_LIMIT", 1)
    states = [
        _listing_state("run", state="running", exit_code=None),
        _listing_state("new"),
        _listing_state("old"),
    ]
    monkeypatch.setattr(jobstore, "list_jobs", lambda: states)
    token = current_call.set("listing-test-call")
    try:
        with caplog.at_level("INFO", logger="binnacle.job_status"):
            status()
    finally:
        current_call.reset(token)
    assert "event=job_listing call=listing-test-call" in caplog.text
    assert "recorded_jobs=3" in caplog.text
    assert "returned_jobs=2" in caplog.text
    assert "running_jobs=1" in caplog.text


def test_quiet_flag_on_sleeping_job(monkeypatch):
    monkeypatch.setattr(js, "QUIET_AFTER_S", 0)  # any age counts as quiet
    p = run("sleep 5", background=True)
    time.sleep(0.3)
    s = status(p["job_id"])
    assert s["state"] == "running" and s["quiet"] is True
    stop(p["job_id"])


def test_tail_lines_respected():
    p = run("for i in $(seq 1 20); do echo line$i; done")
    s = status(p["job_id"], tail_lines=3)
    assert s["log_tail"].splitlines() == ["line18", "line19", "line20"]


# -- stop_job --------------------------------------------------------------


def test_stop_terminates_running_job_and_children():
    # a child sleep inside the group must also die
    p = run("sleep 30 & sleep 30", background=True)
    job_id = p["job_id"]
    result = stop(job_id)
    assert result["state"] == "exited"
    time.sleep(0.3)
    assert status(job_id)["state"] == "exited"


def test_stop_already_exited_is_idempotent():
    p = run("echo done")
    result = stop(p["job_id"])
    assert result["state"] == "exited" and result["exit_code"] == 0


def test_stop_unknown_id_errors():
    with pytest.raises(ToolError, match="No job with id"):
        stop("deadbeefdead")


# -- pruning races (both seen in production, 2026-09-01/02) ----------------


@pytest.fixture()
def fresh_store(tmp_path, monkeypatch):
    """A per-test store: prune tests count directories exactly."""
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "store")


def _fake_finished_dir(name: str) -> None:
    d = jobstore.JOBS_DIR / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        '{"command": "x", "workdir": "/tmp", "pid": 1,'
        ' "started_at": 1.0, "ended_at": 2.0, "exit_code": 0}'
    )


def test_keep_newest_config_requires_at_least_one_slot():
    from pydantic import ValidationError

    from binnacle.config import JobsSettings

    with pytest.raises(ValidationError):
        JobsSettings(keep_newest=0)
    assert JobsSettings(keep_newest=1).keep_newest == 1


def test_start_job_lock_releases_after_popen_failure(fresh_store, monkeypatch):
    real_popen = jobstore.subprocess.Popen
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("synthetic popen failure")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(jobstore.subprocess, "Popen", fail_once)
    with pytest.raises(OSError, match="synthetic popen failure"):
        jobstore.start_job("true", Path("/tmp"), None)

    job_id, proc = jobstore.start_job("true", Path("/tmp"), None)
    proc.wait(timeout=5)
    jobstore.record_exit(job_id, proc)
    assert jobstore.job_state(job_id)["state"] == "exited"


def test_start_job_reserves_one_slot_at_cap(fresh_store, monkeypatch, caplog):
    monkeypatch.setattr(jobstore, "KEEP_NEWEST", 3)
    for i in range(3):
        _fake_finished_dir(f"fake{i:08x}0000")

    with caplog.at_level("INFO", logger="binnacle.jobs"):
        p = run("printf new")
    dirs = [d for d in jobstore.JOBS_DIR.iterdir() if d.is_dir()]
    assert p["state"] == "exited"
    assert len(dirs) == 3
    assert (jobstore.JOBS_DIR / p["job_id"]).exists()
    assert sum(d.name.startswith("fake") for d in dirs) == 2
    prune = next(
        r.getMessage() for r in caplog.records if "event=jobs_pruned" in r.getMessage()
    )
    assert "keep_newest=3" in prune
    assert "reserve=1" in prune
    assert "effective_keep=2" in prune


def test_concurrent_starts_do_not_share_reserved_slot(fresh_store, monkeypatch):
    import threading

    monkeypatch.setattr(jobstore, "KEEP_NEWEST", 3)
    for i in range(3):
        _fake_finished_dir(f"fake{i:08x}0000")

    barrier = threading.Barrier(3)
    results: list[dict] = []
    errors: list[BaseException] = []

    def go() -> None:
        try:
            barrier.wait()
            results.append(run("sleep 0.1"))
        except (AssertionError, ToolError, OSError, RuntimeError) as e:
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    barrier.wait()
    for t in threads:
        t.join()

    assert errors == []
    assert len(results) == 2
    dirs = [d for d in jobstore.JOBS_DIR.iterdir() if d.is_dir()]
    assert len(dirs) == 3
    assert all((jobstore.JOBS_DIR / p["job_id"]).exists() for p in results)


def test_start_job_spares_old_running_job_outside_base_window(fresh_store, monkeypatch):
    monkeypatch.setattr(jobstore, "KEEP_NEWEST", 3)
    old = run("sleep 30", background=True)
    assert old["state"] == "running"
    for i in range(3):
        _fake_finished_dir(f"fake{i:08x}0000")

    new = run("printf new")
    dirs = [d for d in jobstore.JOBS_DIR.iterdir() if d.is_dir()]
    assert new["state"] == "exited"
    assert (jobstore.JOBS_DIR / old["job_id"]).exists()
    assert status(old["job_id"])["state"] == "running"
    # Three base slots plus the deliberately protected stale running job.
    assert len(dirs) == 4
    assert sum(d.name.startswith("fake") for d in dirs) == 2
    stop(old["job_id"])


def test_prune_spares_running_job(fresh_store):
    p = run("sleep 5", background=True)
    job_id = p["job_id"]
    for i in range(jobstore.KEEP_NEWEST + 5):
        _fake_finished_dir(f"fake{i:08x}0000")
    jobstore._prune()
    assert (jobstore.JOBS_DIR / job_id).exists()
    s = status(job_id)
    assert s["state"] == "running"
    fakes_left = sum(
        1 for d in jobstore.JOBS_DIR.iterdir() if d.name.startswith("fake")
    )
    assert fakes_left == jobstore.KEEP_NEWEST
    stop(job_id)


def test_prune_deletes_malformed_meta_dir(fresh_store):
    # A meta.json that parses but lacks fields (e.g. server killed
    # mid-write) must count as garbage, not crash the prune.
    for i in range(jobstore.KEEP_NEWEST):
        _fake_finished_dir(f"fake{i:08x}0000")
    bad = jobstore.JOBS_DIR / "badmeta000000"
    bad.mkdir()
    (bad / "meta.json").write_text("{}")
    import os

    os.utime(bad, (1_000_000_000, 1_000_000_000))  # oldest -> prune candidate
    jobstore._prune()
    assert not bad.exists()


def test_write_meta_replaces_complete_record_atomically(fresh_store, monkeypatch):
    job_id = "atomicmeta001"
    d = jobstore.JOBS_DIR / job_id
    d.mkdir(parents=True)
    old = {
        "command": "old",
        "workdir": "/tmp",
        "pid": 1,
        "started_at": 1.0,
    }
    new = dict(old, command="new", ended_at=2.0, exit_code=0)
    (d / "meta.json").write_text(json.dumps(old))

    real_replace = os.replace
    observed_before_replace: list[dict] = []

    def inspect_replace(src, dst):
        observed_before_replace.append(json.loads(Path(dst).read_text()))
        real_replace(src, dst)

    monkeypatch.setattr(jobstore.os, "replace", inspect_replace)
    jobstore._write_meta(job_id, new)

    assert observed_before_replace == [old]
    assert json.loads((d / "meta.json").read_text()) == new
    assert list(d.glob(".meta.*.tmp")) == []


def test_atomic_meta_write_survives_concurrent_readers(fresh_store):
    import threading

    job_id = "atomicmeta002"
    d = jobstore.JOBS_DIR / job_id
    d.mkdir(parents=True)
    base = {"command": "x", "workdir": "/tmp", "pid": 1, "started_at": 1.0}
    jobstore._write_meta(job_id, base)
    stop_readers = threading.Event()
    failures: list[str] = []

    def reader() -> None:
        while not stop_readers.is_set():
            state = jobstore._read_meta(job_id)
            if state is None:
                failures.append("invalid-or-missing-meta")
                return

    readers = [threading.Thread(target=reader) for _ in range(2)]
    for t in readers:
        t.start()
    try:
        for i in range(40):
            jobstore._write_meta(
                job_id,
                dict(
                    base,
                    command=("x" * 20_000) + str(i),
                    ended_at=float(i),
                    exit_code=0,
                ),
            )
    finally:
        stop_readers.set()
        for t in readers:
            t.join()

    assert failures == []
    assert jobstore._read_meta(job_id) is not None


def test_remove_job_dir_tolerates_vanished_dir(fresh_store):
    gone = jobstore.JOBS_DIR / "never-existed"
    assert jobstore._remove_job_dir(gone) is False  # no raise: the
    # deterministic form of the concurrent-prune race (jobs.py rmdir
    # traceback of 2026-09-02 10:25).


def test_reaper_tolerates_pruned_dir(caplog, fresh_store):
    with caplog.at_level("WARNING", logger="binnacle.jobs"):
        # Long enough that the job is still running after the 1 s
        # background warm-up, so the dir vanishes before the reaper fires.
        p = run("sleep 2", background=True)
        job_id = p["job_id"]
        assert status(job_id)["state"] == "running"
        assert jobstore._remove_job_dir(jobstore.JOBS_DIR / job_id)
        for _ in range(50):
            if any(
                f"event=job_exit_unrecorded job_id={job_id}" in r.getMessage()
                for r in caplog.records
            ):
                break
            time.sleep(0.1)
    assert any(
        f"event=job_exit_unrecorded job_id={job_id}" in r.getMessage()
        for r in caplog.records
    )


# -- cleanup ---------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _isolate_job_store(tmp_path_factory):
    original = jobstore.JOBS_DIR
    jobstore.JOBS_DIR = tmp_path_factory.mktemp("jobs")
    yield
    jobstore.JOBS_DIR = original


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
    assert "dispatch_ms=" in line and "dispatch_ms=na" not in line
    assert "state_ms=" in line
    assert "read_log_ms=" in line
    assert "process_scan_ms=" in line
    assert "impl_ms=" in line
    assert "state=running" in line
    assert "processes=1" in line


def test_status_wait_returns_when_job_exits():
    p = run("sleep 2; echo finished", background=True)  # 1 s warm-up already elapsed
    t0 = time.time()
    s = status(p["job_id"], wait_seconds=10)
    waited = time.time() - t0
    assert s["state"] == "exited" and s["exit_code"] == 0
    assert "finished" in s["log_tail"]
    assert 0.3 < waited < 5  # returned soon after exit, not at the deadline
    assert 0 < s["waited_s"] <= waited + 0.1


def test_status_wait_expires_leaves_job_running():
    p = run("sleep 30", background=True)
    t0 = time.time()
    s = status(p["job_id"], wait_seconds=1)
    assert 0.9 < time.time() - t0 < 3
    assert s["state"] == "running" and s["waited_s"] >= 0.9
    assert (
        "Still running after waiting"
        in js.job_status_impl(p["job_id"], 100, 1).content[0].text
    )
    stop(p["job_id"])


def test_status_wait_is_capped(monkeypatch):
    monkeypatch.setattr(js, "WAIT_MAX", 1)
    p = run("sleep 30", background=True)
    t0 = time.time()
    status(p["job_id"], wait_seconds=40)
    assert time.time() - t0 < 3
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
# A synchronous finish must say plainly that no job was created, so the model
# stops polling job_status to check (50 blind no-arg calls in one week).


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
    assert "job_status" in content
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
    p = run("sleep 1", background=True)  # dies ~1 s after the 1 s warm-up
    s = status(p["job_id"], wait_seconds=10)
    assert s["state"] == "exited" and s["exit_code"] == 0  # never "unknown"


def _wait_until(cond, timeout: float = 5.0, step: float = 0.05) -> bool:
    """Poll a condition instead of sleeping a fixed time: under load (Chrome,
    Xvfb, a parallel suite) child processes can take >0.5 s to appear."""
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
    monkeypatch.setattr(jobstore, "STOP_SIGTERM_GRACE_S", 0.5)
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
    # Race the finish against the stop: the job exits 0 right as stop is called;
    # stop must report the true final state, never a signal it never sent.
    p = run("sleep 1", background=True)
    time.sleep(1.5)  # let it finish (1 s warm-up already elapsed)
    r = stop(p["job_id"])
    assert r["state"] == "exited" and r["exit_code"] == 0 and r["signal"] is None


# -- corner cases beyond signals (2026-09-06) -------------------------------
# Families: reload orphans + pid reuse, malformed/missing store files, stdin
# pipe behavior, exit-code vs signal encoding, processes escaping the group,
# listing robustness, parameter clamps, concurrency, output encoding.

import json
import os
import subprocess
import threading
from pathlib import Path


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
    # 200 KiB > the 64 KiB pipe buffer; the command never reads stdin. With a
    # pipe, start_job would block until the command ended (defeating the
    # wait); with the spool file it returns at wait_seconds.
    t0 = time.time()
    p = run("sleep 20", wait_seconds=2, stdin="x" * 200_000)
    assert time.time() - t0 < 6
    assert p["state"] == "running"
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
    job_id, proc = jobstore.start_job("sleep 1", Path("/tmp"), None)
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
