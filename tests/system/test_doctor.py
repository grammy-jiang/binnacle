"""Implementation gate for binnacle/doctor.py (`binnacle doctor`).

Every outside dependency (systemctl, /proc, the journal) is a fake passed
in; the endpoint checks talk to a throwaway http.server so the real
urllib path is exercised.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from binnacle import doctor
from binnacle import jobs as jobstore

BEARER = "Bearer secret-token\n"


def statuses(checks: list[doctor.Check]) -> list[str]:
    return [c.status for c in checks]


def fake_systemctl(states: dict[str, str], props: dict[str, str] | None = None):
    """A systemctl stand-in: is-active from `states`, show -p from `props`."""
    props = props or {}

    def run(*args: str) -> subprocess.CompletedProcess:
        if args[0] == "is-active":
            out = states.get(args[1], "inactive")
        elif args[0] == "show":
            out = props.get(f"{args[1]}.{args[3]}", "")
        else:
            out = ""
        return subprocess.CompletedProcess(list(args), 0, stdout=out + "\n", stderr="")

    return run


# -- token -------------------------------------------------------------------


def test_token_missing_fails(tmp_path):
    (c,) = doctor.check_token(tmp_path / "token")
    assert c.status == "fail" and "setup" in c.hint


def test_token_good(tmp_path):
    f = tmp_path / "token"
    f.write_text(BEARER)
    f.chmod(0o600)
    assert statuses(doctor.check_token(f)) == ["ok", "ok", "ok"]


def test_token_wrong_mode_fails(tmp_path):
    f = tmp_path / "token"
    f.write_text(BEARER)
    f.chmod(0o644)
    checks = doctor.check_token(f)
    assert checks[1].status == "fail" and "0644" in checks[1].detail


def test_token_without_prefix_warns(tmp_path):
    # The tunnel forwards the file verbatim as the Authorization header.
    f = tmp_path / "token"
    f.write_text("bare-token\n")
    f.chmod(0o600)
    assert doctor.check_token(f)[2].status == "warn"


def test_token_empty_fails(tmp_path):
    f = tmp_path / "token"
    f.write_text("Bearer \n")
    f.chmod(0o600)
    assert doctor.check_token(f)[2].status == "fail"


# -- units -------------------------------------------------------------------


def test_units_inactive_fails():
    checks, active = doctor.check_units(
        "prod", run=fake_systemctl({}), linger=lambda: True
    )
    assert active is None
    assert statuses(checks) == ["fail"]
    assert "systemctl --user start prod" in checks[0].hint


READY = {"NRestarts": "0", "ExecStartPost": "{ path=/bin/bash ; argv[]=... }"}


def _props(unit: str, **over: str) -> dict[str, str]:
    return {f"{unit}.{k}": v for k, v in {**READY, **over}.items()}


def test_units_active_ok():
    run = fake_systemctl({"prod": "active"}, _props("prod"))
    checks, active = doctor.check_units("prod", run=run, linger=lambda: True)
    assert active == "prod"
    assert statuses(checks) == ["ok", "ok", "ok", "ok"]


def test_units_without_readiness_gate_warns():
    # The restart noise of 2026-09-03: tunnel probed a port uvicorn had not
    # opened yet, because Type=simple counts the fork as "started".
    run = fake_systemctl({"prod": "active"}, _props("prod", ExecStartPost=""))
    checks, _ = doctor.check_units("prod", run=run, linger=lambda: True)
    assert checks[2].status == "warn" and "ExecStartPost" in checks[2].hint


def test_units_restarts_and_no_linger_warn():
    run = fake_systemctl({"dev": "active"}, _props("dev", NRestarts="3"))
    checks, active = doctor.check_units("dev", run=run, linger=lambda: False)
    assert active == "dev"
    assert statuses(checks) == ["ok", "warn", "ok", "warn"]
    assert "3 time(s)" in checks[1].detail


def test_units_linger_unknown_is_silent():
    run = fake_systemctl({"prod": "active"}, _props("prod"))
    checks, _ = doctor.check_units("prod", run=run, linger=lambda: None)
    assert len(checks) == 3


def test_server_busy_reasons_report_jobs_and_calls(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    (jobs_dir / "a1").mkdir(parents=True)
    (jobs_dir / "b2").mkdir()
    (jobs_dir / "note.txt").write_text("not a job")
    monkeypatch.setattr(
        doctor,
        "_job_state_safe",
        lambda job_id: {"state": "running" if job_id == "a1" else "exited"},
    )
    reasons = doctor.server_busy_reasons(
        "prod",
        jobs_dir,
        fetch=lambda unit, since: "event=tool_call x\nevent=tool_call y\n",
    )
    assert reasons == [
        "1 background job(s) running (a1); a unit restart kills them",
        "2 tool call(s) in the last 30s; a restart fails the calls in flight",
    ]


def test_server_busy_reasons_quiet_and_unreadable_journal(tmp_path):
    quiet = doctor.server_busy_reasons(
        "prod", tmp_path / "missing", fetch=lambda unit, since: "event=cycle\n"
    )
    assert quiet == []

    def boom(unit: str, since: str) -> str:
        raise OSError("no journal")

    reasons = doctor.server_busy_reasons("prod", tmp_path / "missing", fetch=boom)
    assert len(reasons) == 1 and "journal unreadable" in reasons[0]


# -- service environment -----------------------------------------------------


def _env_with(path: str):
    return lambda pid: {"PATH": path}


def test_service_env_good(tmp_path):
    user_bin = tmp_path / "bin"
    user_bin.mkdir()
    for name in ("bash", "rg"):
        p = user_bin / name
        p.write_text("#!/bin/sh\n")
        p.chmod(0o755)
    run = fake_systemctl({}, {"u.MainPID": "42"})
    checks = doctor.check_service_env(
        "u", "rg", user_bin, run=run, environ=_env_with(str(user_bin))
    )
    assert statuses(checks) == ["ok", "ok", "ok"]


def test_service_env_missing_user_bin_fails(tmp_path):
    # The 2026-09-02 incident: boot-time PATH without ~/.local/bin.
    run = fake_systemctl({}, {"u.MainPID": "42"})
    checks = doctor.check_service_env(
        "u", "rg", tmp_path / "bin", run=run, environ=_env_with("/usr/bin:/bin")
    )
    assert checks[0].status == "fail" and "environment.d" in checks[0].hint
    assert checks[1].status == "ok"  # bash is on /usr/bin or /bin


def test_service_env_missing_rg_fails(tmp_path):
    run = fake_systemctl({}, {"u.MainPID": "42"})
    checks = doctor.check_service_env(
        "u", "definitely-not-rg", tmp_path, run=run, environ=_env_with(str(tmp_path))
    )
    assert checks[2].status == "fail" and "search_text" in checks[2].detail


def test_service_env_no_pid_warns(tmp_path):
    run = fake_systemctl({}, {"u.MainPID": "0"})
    (c,) = doctor.check_service_env("u", "rg", tmp_path, run=run)
    assert c.status == "warn"


def test_service_env_unreadable_proc_warns(tmp_path):
    run = fake_systemctl({}, {"u.MainPID": "42"})
    (c,) = doctor.check_service_env(
        "u", "rg", tmp_path, run=run, environ=lambda pid: None
    )
    assert c.status == "warn"


@pytest.mark.no_xdist
def test_process_environ_reads_own_process():
    env = doctor.process_environ(os.getpid())
    assert env is not None and "PATH" in env


# -- endpoint ----------------------------------------------------------------


# -- tunnel ------------------------------------------------------------------


# -- jobs --------------------------------------------------------------------


def _job_dir(root: Path, name: str, meta: dict) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "out.log").write_text("")


def test_jobs_spool_absent_is_ok(tmp_path):
    (c,) = doctor.check_jobs(tmp_path / "jobs")
    assert c.status == "ok"


def test_jobs_counts_running_and_orphaned(tmp_path, monkeypatch):
    store = tmp_path / "jobs"
    monkeypatch.setattr(jobstore, "JOBS_DIR", store)
    _job_dir(
        store,
        "a" * 12,
        {"command": "x", "workdir": "/tmp", "pid": os.getpid(), "started_at": 1.0},
    )
    _job_dir(
        store,
        "b" * 12,
        {"command": "x", "workdir": "/tmp", "pid": 2**22 - 1, "started_at": 1.0},
    )
    _job_dir(
        store,
        "c" * 12,
        {
            "command": "x",
            "workdir": "/tmp",
            "pid": 1,
            "started_at": 1.0,
            "exit_code": 0,
            "ended_at": 2.0,
        },
    )
    (store / ("d" * 12)).mkdir()  # no meta at all: ignored, not a crash
    checks = doctor.check_jobs(store)
    assert (
        checks[0].status == "ok"
        and "3 job(s), 1 running, 1 orphaned" in checks[0].detail
    )
    assert checks[1].status == "warn"


def test_jobs_unwritable_fails(tmp_path):
    store = tmp_path / "jobs"
    store.mkdir()
    store.chmod(0o500)
    try:
        if os.access(store, os.W_OK):
            pytest.skip("running as root; chmod does not restrict")
        (c,) = doctor.check_jobs(store)
        assert c.status == "fail"
    finally:
        store.chmod(0o700)


# -- journal -----------------------------------------------------------------


def test_journal_clean_ok():
    (c,) = doctor.check_journal(
        "u", "-1 hour", fetch=lambda u, s: "INFO fine\nINFO ok\n"
    )
    assert c.status == "ok"


def test_journal_errors_warn():
    text = "ERROR: server failure\nTraceback (most recent call last):\n  x\n"
    (c,) = doctor.check_journal("u", "-1 hour", fetch=lambda u, s: text)
    assert c.status == "warn" and "1 error line(s) and 1 traceback(s)" in c.detail


def test_journal_fastmcp_rich_error_warns():
    text = (
        "[09/22/26 05:29:59] INFO     event=request_start\n"
        "                    ERROR    event=request_error                  logging.py:122\n"
    )
    (c,) = doctor.check_journal("u", "-1 hour", fetch=lambda u, s: text)
    assert c.status == "warn" and "1 error line(s)" in c.detail


def test_journal_error_words_inside_payload_do_not_warn():
    text = (
        'payload={"command":"grep -E ERROR|Traceback file.log"}\n'
        '2026-09-22T09:35:00.234 INFO: event=tool_call args={"pattern":"ERROR"}\n'
        "                             ERROR|WARNING|Traceback\n"
    )
    (c,) = doctor.check_journal("u", "-1 hour", fetch=lambda u, s: text)
    assert c.status == "ok"


def test_journal_structured_root_error_warns():
    text = "2026-09-22T09:35:00.234 ERROR: event=server_failure reason=boom\n"
    (c,) = doctor.check_journal("u", "-1 hour", fetch=lambda u, s: text)
    assert c.status == "warn" and "1 error line(s)" in c.detail


def test_journal_unavailable_warns():
    def boom(u, s):
        raise SystemExit("journalctl failed")

    (c,) = doctor.check_journal("u", "-1 hour", fetch=boom)
    assert c.status == "warn"


# -- render ------------------------------------------------------------------


def test_render_exit_code_and_hints():
    checks = [
        doctor.ok("a", "fine"),
        doctor.warn("b", "meh", "do y"),
        doctor.fail("c", "broken", "do x"),
    ]
    text, code = doctor.render(checks)
    assert code == 1
    assert "[FAIL] c: broken" in text and "hint: do x" in text
    assert "hint: do y" in text
    assert text.endswith("1 ok, 1 warn, 1 fail")


def test_render_warn_only_exits_zero():
    _, code = doctor.render([doctor.warn("a", "meh")])
    assert code == 0


def test_render_json():
    text, code = doctor.render_json([doctor.fail("a", "x")])
    data = json.loads(text)
    assert code == 1 and data["exit_code"] == 1
    assert data["checks"][0] == {
        "group": "a",
        "status": "fail",
        "detail": "x",
        "hint": "",
    }


# -- uplink, poller, watchdog ------------------------------------------------
#
# These three are the checks the 2026-09-12 outage proved were missing:
# everything above them is local, and all of it was green for 48 minutes
# while ChatGPT could not reach the connector at all.


# -- driver stability (external daily job) -----------------------------------


# -- the failure-case review (2026-09-13) ------------------------------------


def test_boot_check_wants_lingering():
    def on(*args, **kw):
        return subprocess.CompletedProcess(
            list(args), 0, stdout="Linger=yes\n", stderr=""
        )

    def off(*args, **kw):
        return subprocess.CompletedProcess(
            list(args), 0, stdout="Linger=no\n", stderr=""
        )

    (c,) = doctor.check_boot(on, user="pi")
    assert c.status == "ok" and "start at boot" in c.detail
    (c,) = doctor.check_boot(off, user="pi")
    assert c.status == "fail" and c.hint == "loginctl enable-linger pi"
