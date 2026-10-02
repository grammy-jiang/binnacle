"""Integration tests for run_command, job_status, and stop_job."""

import time

import pytest
from fastmcp.exceptions import ToolError

from binnacle import jobs as jobstore
from binnacle.callctx import current_call
from binnacle.tools import job_status as js
from binnacle.tools import run_command as rc
from tests.integration.job_test_support import run, status, stop

pytestmark = pytest.mark.usefixtures("_short_job_warmup")


@pytest.fixture(autouse=True, scope="module")
def _isolate_job_store(tmp_path_factory):
    original = jobstore.JOBS_DIR
    jobstore.JOBS_DIR = tmp_path_factory.mktemp("jobs")
    yield
    jobstore.JOBS_DIR = original


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


def test_status_single_job_previews_long_command(monkeypatch):
    command = "printf ok; #" + "x" * 100 + "-TAIL"
    job_id = run(command)["job_id"]

    row = status(job_id, preview_chars=40)
    assert row["workdir"]
    assert row["command"].startswith("printf ok; #")
    assert row["command"].endswith("-TAIL")
    assert "chars omitted" in row["command"]


def test_status_listing_keeps_all_running_plus_recent_history(monkeypatch):
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

    rows = status(history_limit=3)["jobs"]
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
    command = "HEAD-" + "x" * 100 + "-TAIL"
    state = _listing_state(
        "job", command=command, workdir="/tmp/project", started_at=42.0
    )
    monkeypatch.setattr(jobstore, "list_jobs", lambda: [state])

    row = status(preview_chars=40)["jobs"][0]
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
    states = [
        _listing_state("unknown", state="unknown", exit_code=None),
        _listing_state("exited"),
        _listing_state("running", state="running", exit_code=None),
    ]
    monkeypatch.setattr(jobstore, "list_jobs", lambda: states)
    assert [r["job_id"] for r in status(history_limit=1)["jobs"]] == [
        "unknown",
        "running",
    ]


def test_status_listing_summary_says_when_history_is_omitted(monkeypatch):
    states = [
        _listing_state("run", state="running", exit_code=None),
        _listing_state("new"),
        _listing_state("old"),
    ]
    monkeypatch.setattr(jobstore, "list_jobs", lambda: states)
    result = js.job_status_impl(None, 100, 0, history_limit=1)
    assert result.structured_content is not None
    assert len(result.structured_content["jobs"]) == 2
    assert "2 of 3 job(s) shown" in result.content[0].text
    assert "all 1 running" in result.content[0].text


def test_status_listing_logs_correlated_counts(monkeypatch, caplog):
    states = [
        _listing_state("run", state="running", exit_code=None),
        _listing_state("new"),
        _listing_state("old"),
    ]
    monkeypatch.setattr(jobstore, "list_jobs", lambda: states)
    token = current_call.set("listing-test-call")
    try:
        with caplog.at_level("INFO", logger="binnacle.job_status"):
            status(history_limit=1)
    finally:
        current_call.reset(token)
    assert "event=job_listing call=listing-test-call" in caplog.text
    assert "recorded_jobs=3" in caplog.text
    assert "returned_jobs=2" in caplog.text
    assert "running_jobs=1" in caplog.text


def test_quiet_flag_on_sleeping_job(monkeypatch):
    p = run("sleep 5", background=True)
    time.sleep(0.3)
    s = status(p["job_id"], quiet_after_s=0)
    assert s["state"] == "running" and s["quiet"] is True
    stop(p["job_id"])


def test_tail_lines_respected():
    p = run("for i in $(seq 1 20); do echo line$i; done")
    s = status(p["job_id"], tail_lines=3)
    assert s["log_tail"].splitlines() == ["line18", "line19", "line20"]


def test_status_giant_single_line_is_hard_bounded_and_disk_log_stays_full(
    caplog,
):
    source_chars = jobstore.RUN_MAX_OUTPUT_CHARS * 4
    p = run(
        f"python -c \"import sys; sys.stdout.write('H' + 'x' * "
        f"{source_chars - 2} + 'T')\""
    )
    raw = jobstore.read_log(p["job_id"])
    assert len(raw) == source_chars
    assert raw.startswith(b"H") and raw.endswith(b"T")

    token = current_call.set("giant-status-call")
    try:
        with caplog.at_level("INFO", logger="binnacle.job_status"):
            s = status(p["job_id"], tail_lines=3)
    finally:
        current_call.reset(token)

    assert len(s["log_tail"]) <= jobstore.RUN_MAX_OUTPUT_CHARS
    assert s["log_tail"].startswith("H") and s["log_tail"].endswith("T")
    assert "chars elided" in s["log_tail"]
    assert s["log_bytes"] == source_chars
    assert "event=job_status_output_shaping call=giant-status-call" in caplog.text
    assert "reason=char_limit" in caplog.text
    assert f"limit_chars={jobstore.RUN_MAX_OUTPUT_CHARS}" in caplog.text
    assert "omitted_chars=" in caplog.text


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
