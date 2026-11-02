"""Internal support for an EXPLICIT standalone D1 systemd rehearsal.

This is NOT a pytest test: tests/conftest.py prohibits host modifications.
Imported only by scripts/rehearse_manager_systemd_lifecycle.py after opt-in.
Temporary unit names are checked before ever calling `systemctl stop`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from binnacle.features.commands import job_client, jobs
from tests.integration.test_job_manager_v2 import _pinned_fd, _request, _send
from tests.integration.test_job_manager_v2_lifecycle import _WORKER


def _systemctl(*args: str, timeout: float = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _unit_setting(unit: str, key: str) -> str:
    result = _systemctl("show", "--property", key, "--value", unit)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _process_state(pid: int) -> str | None:
    try:
        data = Path(f"/proc/{pid}/stat").read_text()
        return data.rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def _wait_for(predicate, timeout: float = 8) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _start_disposable_manager_unit(
    *, unit: str, root: Path, run: Path, store: Path, source: Path
) -> None:
    assert unit.startswith("binnacle-d1c-isolated-") and unit.endswith(".service")
    assert _unit_setting(unit, "LoadState") == "not-found"
    assert shutil.which("systemd-run") is not None
    properties = (
        # Match the production Manager's notify readiness and cgroup
        # lifecycle, while disabling automatic *test* service restart.
        "Type=notify",
        "NotifyAccess=main",
        "TimeoutStartSec=30s",
        "Restart=no",
        "KillMode=control-group",
        "Delegate=cpu memory pids",
        "DelegateSubgroup=binnacle-manager",
        "TimeoutStopSec=10s",
        "UMask=0077",
        f"WorkingDirectory={root}",
    )
    command = ["systemd-run", "--user", "--collect", "--unit", unit]
    command.extend(f"--property={p}" for p in properties)
    command.extend(
        [
            f"--setenv=PYTHONPATH={source}",
            "--setenv=PYTHONDONTWRITEBYTECODE=1",
            sys.executable,
            "-c",
            _WORKER,
            str(root),
            str(run),
            str(store),
        ]
    )
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=8, check=False
    )
    assert result.returncode == 0, result.stderr
    assert _wait_for(
        lambda: (
            (run / "start-v2.sock").exists()
            and (run / "legacy.sock").exists()
            and _unit_setting(unit, "ActiveState") == "active"
        ),
        timeout=9,
    ), (
        f"disposable Manager failed to bind, systemd: {_systemctl('status', unit).stdout[-700:]}"
    )
    assert _unit_setting(unit, "KillMode") == "control-group"
    assert _unit_setting(unit, "Type") == "notify"
    assert _unit_setting(unit, "DelegateSubgroup") == "binnacle-manager"
    cgroup = _unit_setting(unit, "ControlGroup")
    assert unit in cgroup and "binnacle-jobs.service" not in cgroup, cgroup
    assert job_client.ping(run / "legacy.sock")["version"] == 1


def _fixture(tmp_path: Path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "marker").write_text("ISOLATED-CGROUP-ONLY\n")
    run = tmp_path / "private-run"
    run.mkdir(mode=0o700)
    run.chmod(0o700)
    store = tmp_path / "job-store"
    source = Path(__file__).resolve().parents[1] / "src"
    assert source.joinpath("binnacle/features/commands/job_manager_v2.py").is_file()
    unit = f"binnacle-d1c-isolated-{uuid.uuid4().hex[:12]}.service"
    return unit, root, run, store, source


def _start_job(root: Path, run: Path, command: str, call_id: str) -> dict:
    fd = _pinned_fd(root)
    try:
        response = _send(
            run / "start-v2.sock",
            _request(root, command=command, wait_seconds=0.0, call_id=call_id),
            (fd,),
        )
    finally:
        os.close(fd)
    assert response["ok"] is True, response
    return response


def _cleanup_own_unit(unit: str) -> None:
    assert unit.startswith("binnacle-d1c-isolated-") and unit.endswith(".service")
    try:
        result = _systemctl("stop", unit, timeout=15)
        assert result.returncode == 0 or "not loaded" in result.stderr.lower(), (
            result.stderr
        )
    finally:
        # Unique test-only unit: never call systemctl on production service.
        assert "binnacle-jobs.service" not in unit


def check_control_group_stop_terminates_active_job(tmp_path: Path) -> dict:
    unit, root, run, store, source = _fixture(tmp_path)
    try:
        _start_disposable_manager_unit(
            unit=unit, root=root, run=run, store=store, source=source
        )
        response = _start_job(
            root,
            run,
            "printf 'ACTIVE-START\\n'; sleep 30; printf 'ACTIVE-END\\n'",
            "d1-isolated-active-job",
        )
        job = response["job_id"]
        assert _wait_for(lambda: (store / job / "meta.json").exists(), timeout=6)
        meta = json.loads((store / job / "meta.json").read_text())
        pid = meta["pid"]
        assert jobs._PROCESS_BACKEND.alive(pid, meta.get("starttime"))
        manager_cgroup = _unit_setting(unit, "ControlGroup")

        # The shell wrapper joins its per-job cgroup *after* Python Popen
        # returns. Inspect after the attach, not before the asynchronous
        # bootstrap has had a chance to write cgroup.procs.
        def in_job_cgroup() -> bool:
            try:
                live = Path(f"/proc/{pid}/cgroup").read_text().split("::", 1)[1].strip()
            except (FileNotFoundError, IndexError):
                return False
            return live.startswith(manager_cgroup + "/job-")

        assert _wait_for(in_job_cgroup, timeout=3), (
            manager_cgroup,
            Path(f"/proc/{pid}/cgroup").read_text(),
        )
        assert _wait_for(
            lambda: "ACTIVE-START" in (store / job / "out.log").read_text(), timeout=5
        )
        _cleanup_own_unit(unit)
        assert _wait_for(
            lambda: not jobs._PROCESS_BACKEND.alive(pid, meta.get("starttime")),
            timeout=5,
        )
        log = (store / job / "out.log").read_text()
        assert "ACTIVE-START" in log and "ACTIVE-END" not in log
        # Some owner reapers can record SIGTERM before systemd finishes stop,
        # while others have no time to persist final metadata. Neither result
        # constitutes successful execution or a safe active-job upgrade.
        current = json.loads((store / job / "meta.json").read_text())
        assert current.get("exit_code") != 0, current
        assert current.get("signal") in (None, 15), current
        return {
            "control_group_matches_isolated_unit": True,
            "child_was_running_when_stop_requested": True,
            "active_job_terminated_before_completion": True,
            "signal_recorded": current.get("signal"),
            "last_marker_missing": True,
            "metadata_exit_code": current.get("exit_code"),
        }
    finally:
        _cleanup_own_unit(unit)


def check_completed_job_is_preserved_on_owner_stop(tmp_path: Path) -> dict:
    """Active job -> pause v1+v2 -> drain -> stop -> restart paused -> resume."""
    unit, root, run, store, source = _fixture(tmp_path)
    nonce = uuid.uuid4().hex
    try:
        _start_disposable_manager_unit(
            unit=unit, root=root, run=run, store=store, source=source
        )
        response = _start_job(
            root,
            run,
            "cat marker; sleep 0.6; printf 'DRAIN-COMPLETE\n'",
            "d1-isolated-completed-job",
        )
        job = response["job_id"]
        assert _wait_for(lambda: (store / job / "meta.json").exists(), timeout=6)
        # A single owner-wide lock ensures the fence is committed *after*
        # any earlier start has written its durable job metadata, and before
        # any later v1/v2 start is admitted.
        pause_req = {"version": 2, "op": "pause_starts", "nonce": nonce}
        initial = _send(run / "start-v2.sock", pause_req, ())
        assert initial["ok"] and initial["starts_paused"]
        assert initial["safe_to_stop"] is False
        assert {j["job_id"] for j in initial["active_jobs"]} == {job}
        try:
            job_client.start(
                run / "legacy.sock",
                command="cat marker",
                workdir=root,
                stdin=None,
                wait_seconds=1.0,
                call_id="must-be-denied-v1",
            )
        except job_client.JobManagerError:
            pass
        else:
            raise AssertionError("v1 admitted a job after global pause")
        denied_fd = _pinned_fd(root)
        try:
            refused_v2 = _send(
                run / "start-v2.sock",
                {
                    "version": 2,
                    "op": "start",
                    "workdir": str(root),
                    "workdir_fd": True,
                    "command": "cat marker",
                    "stdin": None,
                    "wait_seconds": 0.0,
                    "call_id": "must-be-denied-v2",
                },
                (denied_fd,),
            )
        finally:
            os.close(denied_fd)
        assert refused_v2["ok"] is False
        assert len([d for d in store.iterdir() if d.is_dir()]) == 1
        assert _wait_for(
            lambda: "exit_code" in json.loads((store / job / "meta.json").read_text()),
            timeout=8,
        ), "owner has not durably recorded job completion"
        before = json.loads((store / job / "meta.json").read_text())
        assert before["exit_code"] == 0
        ready = _send(run / "start-v2.sock", pause_req, ())
        assert ready["ok"] and ready["safe_to_stop"] and not ready["active_jobs"]
        _cleanup_own_unit(unit)
        after = json.loads((store / job / "meta.json").read_text())
        assert after["exit_code"] == 0
        assert (store / job / "out.log").read_text().endswith("DRAIN-COMPLETE\n")
        # A new Manager process using the SAME state root must still be
        # paused. A release only resumes on an explicit authorized nonce.
        after_unit = f"binnacle-d1c-isolated-{uuid.uuid4().hex[:12]}.service"
        try:
            _start_disposable_manager_unit(
                unit=after_unit, root=root, run=run, store=store, source=source
            )
            state_after_restart = _send(run / "start-v2.sock", pause_req, ())
            assert state_after_restart["ok"]
            assert state_after_restart["safe_to_stop"]
            assert state_after_restart["starts_paused"]
            try:
                job_client.start(
                    run / "legacy.sock",
                    command="cat marker",
                    workdir=root,
                    stdin=None,
                    wait_seconds=1.0,
                    call_id="must-remain-paused",
                )
            except job_client.JobManagerError:
                pass
            else:
                raise AssertionError("v1 reopened after Manager restart without resume")
            resumed = _send(
                run / "start-v2.sock",
                {"version": 2, "op": "resume_starts", "nonce": nonce},
                (),
            )
            assert resumed["ok"] and not resumed["starts_paused"]
            accepted = job_client.start(
                run / "legacy.sock",
                command="cat marker",
                workdir=root,
                stdin=None,
                wait_seconds=2.0,
                call_id="authorized-after-resume",
            )
            assert accepted["ok"] is True
            new_job = accepted["job_id"]
            assert (store / new_job / "out.log").read_text() == "ISOLATED-CGROUP-ONLY\n"
        finally:
            _cleanup_own_unit(after_unit)
        return {
            "owner_paused_with_active_job": True,
            "v1_and_v2_starts_rejected_during_drain": True,
            "completed_job_exit_code_preserved": 0,
            "completed_job_final_log_retained": True,
            "paused_state_survived_manager_stop_and_new_manager_process": True,
            "legacy_v1_reopened_only_after_explicit_v2_resume": True,
        }
    finally:
        _cleanup_own_unit(unit)
