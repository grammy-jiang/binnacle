"""r6 D2 (J7-FOLLOWUP-stop-marker-start-refusal): no start into a pending stop.

While the provisioner's quiet-window stop marker names the serving incarnation,
``start`` is refused with a typed, retryable reply whose text is the existing
manager-unavailable class, and no job record is created. A marker naming
another incarnation, or none at all, leaves ``start`` working.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.features.commands import job_client
from binnacle.platform.composition import create_job_client
from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.darwin import job_manager_entry as entry
from tests.platform.darwin.test_durable_tool_wiring import _manager, _run
from tests.platform.darwin.test_job_manager_entry import MODULE, ping_when_ready
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    req,
)

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin manager entry")


def write_marker(marker: Path, owner_instance_id: str, mode: int = 0o600) -> None:
    marker.write_text(json.dumps({"owner_instance_id": owner_instance_id}))
    marker.chmod(mode)


def start_entry(base: Path) -> subprocess.Popen[str]:
    env = {"BINNACLE_CONFIG_FILE": str(base / "config.toml"), "HOME": str(base)}
    env["PATH"] = f"{base / 'bin'}:/usr/bin:/bin"
    argv = [sys.executable, "-m", MODULE]
    pipe = subprocess.PIPE
    return subprocess.Popen(
        argv, env=env, cwd=base, stdout=pipe, stderr=pipe, text=True
    )


def job_dirs(jobs: Path) -> list[str]:
    return sorted(p.name for p in jobs.iterdir() if p.is_dir()) if jobs.exists() else []


@pytest.fixture
def reaped(tmp_path):
    owner = ReferenceOwner()
    manager, halt = manager_for(owner, tmp_path / "jobs"), threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,))
    reaper.start()
    yield owner, manager
    halt.set()
    reaper.join()
    manager.close()


def test_pending_stop_refuses_start_typed_and_writes_no_record(reaped):
    owner, manager = reaped
    with tempfile.TemporaryDirectory(prefix="r6-r6-d21-a1-", dir="/tmp") as value:
        base = Path(value).resolve()  # private 0700 runtime root
        sock, jobs = base / "jobs.sock", manager.jobs_dir
        manager.stop_pending = lambda: entry.stop_pending_refusal(
            sock, owner.owner_instance_id
        )
        write_marker(sock.with_name("jobs.sock.stop"), owner.owner_instance_id)
        reply = manager.handle(req(base, "echo never"))
        assert reply == {
            "ok": False,
            "error": f"{pc.JOB_MANAGER_UNAVAILABLE} at {sock}: manager_stopping",
            "code": entry.STOP_PENDING_CODE,
            "retryable": True,
        }
        assert job_dirs(jobs) == [] and owner.live == owner.exits == {}
        sock.with_name("jobs.sock.stop").unlink()
        assert manager.handle(req(base, "true", wait=5))["ok"] is True
        assert len(job_dirs(jobs)) == 1


@NATIVE
def test_entry_refuses_start_only_while_its_own_marker_exists(tmp_path):
    with tempfile.TemporaryDirectory(prefix="r6-r6-d21-a1-", dir="/tmp") as value:
        base = Path(value).resolve()
        (base / "rt").mkdir(mode=0o700)
        (base / "bin").mkdir()
        sock, jobs = base / "rt" / "jobs.sock", base / "jobs"
        (base / "config.toml").write_text(
            f'[jobs]\nsocket_path = "{sock}"\ndir = "{jobs}"\n'
        )
        marker = sock.with_name("jobs.sock.stop")
        child = start_entry(base)
        try:
            client, pong = ping_when_ready(sock, child)
            me = pong["owner_instance_id"]
            kw = {"workdir": base, "stdin": None, "call_id": "d2"}
            # Marker absent: start works.
            done = client.start(sock, command="exit 0", wait_seconds=10, **kw)
            assert done["state"] == "exited"
            before = job_dirs(jobs)
            # Another incarnation's or a non-private marker: not ours, ignored.
            for owner_id, mode in (("previous-incarnation", 0o600), (me, 0o644)):
                write_marker(marker, owner_id, mode)
                extra = client.start(sock, command="exit 0", wait_seconds=10, **kw)
                assert extra["state"] == "exited"
                before = job_dirs(jobs)
                marker.unlink()
            # Our own marker: typed retryable refusal, no record, still serving.
            write_marker(marker, me)
            with pytest.raises(job_client.JobManagerError) as refused:
                client.start(sock, command="echo never", wait_seconds=0, **kw)
            assert str(refused.value) == (
                f"{pc.JOB_MANAGER_UNAVAILABLE} at {sock}: {entry.STOP_PENDING_CODE}"
            )
            assert job_dirs(jobs) == before
            assert client.ping(sock)["running_jobs"] == 0
            assert marker.exists()  # the peek never consumes the provisioner's marker
            # MCP side: run_command shows the existing manager-unavailable text.
            settings, root, backend = _manager(tmp_path, client=create_job_client())
            backend._socket_path = sock
            unavailable = rf"{pc.JOB_MANAGER_UNAVAILABLE} at {re.escape(str(sock))}: "
            with pytest.raises(ToolError, match=unavailable + "manager_stopping"):
                _run(settings, root, backend, "echo never", 5)
            assert job_dirs(jobs) == before
            # Marker withdrawn: start works again in the same incarnation.
            marker.unlink()
            again = client.start(sock, command="exit 0", wait_seconds=10, **kw)
            assert again["state"] == "exited" and again["job_id"] not in before
            # The quiet-window stop itself is unchanged: marker + TERM exits 0.
            write_marker(marker, me)
            child.send_signal(signal.SIGTERM)
            _, err = child.communicate(timeout=30)
            assert child.returncode == 0, err
            assert "reason=provisioner_quiet_window" in err
            assert "event=job_start_refused reason=stop_marker" in err
        finally:
            if child.poll() is None:  # our exact child only (RULE-NO-PKILL)
                child.kill()
                child.communicate(timeout=10)


def test_marker_peek_matches_the_consuming_reader():
    with tempfile.TemporaryDirectory(prefix="r6-r6-d21-a1-", dir="/tmp") as value:
        sock = Path(value).resolve() / "jobs.sock"
        marker = sock.with_name("jobs.sock.stop")
        assert not entry.stop_marker_names(sock, "me")
        assert entry.stop_pending_refusal(sock, "me") is None
        write_marker(marker, "other")
        assert not entry.stop_marker_names(sock, "me") and marker.exists()
        write_marker(marker, "me")
        assert entry.stop_marker_names(sock, "me") and marker.exists()
        assert entry.provisioner_stop(sock, "me") and not marker.exists()


# --- R6-D21-a3 (SD-69): SR6-F1 marker freshness and SR6-F2 check under the lock ---


def aged(marker: Path, age_s: float) -> None:
    when = time.time() - age_s
    os.utime(marker, (when, when))


def test_marker_counts_only_while_fresh_and_a_stale_own_marker_is_removed(caplog):
    """SR6-F1: honored only for -5 s <= now - st_mtime < 300 s (format unchanged)."""
    with tempfile.TemporaryDirectory(prefix="r6-d21a3-", dir="/tmp") as value:
        sock = Path(value).resolve() / "jobs.sock"
        marker = sock.with_name("jobs.sock.stop")
        for age in (0.0, 120.0, 299.0, -4.0):  # fresh, near expiry, clock skew
            write_marker(marker, "me")
            aged(marker, age)
            assert entry.stop_pending_refusal(sock, "me")["code"] == "manager_stopping"
            assert marker.exists()  # a fresh marker is only peeked
        caplog.clear()
        for age in (301.0, 300.0, -6.0, -3600.0):  # expired, or future beyond -5 s
            write_marker(marker, "me")
            aged(marker, age)
            with caplog.at_level("WARNING", logger="binnacle.job_manager"):
                assert entry.stop_pending_refusal(sock, "me") is None
            assert not marker.exists()  # removed: the same inode that was read
        stale = [r.message for r in caplog.records if "stop_marker_stale" in r.message]
        assert len(stale) == 4 and all(m.startswith("event=") for m in stale)
        assert not any(value in m or "me" in m.split() for m in stale)  # no path/id
        # Another incarnation's stale marker: never refuses, never removed by a peek.
        write_marker(marker, "previous")
        aged(marker, 3600.0)
        assert entry.stop_pending_refusal(sock, "me") is None and marker.exists()


def test_stale_marker_removal_never_touches_a_replaced_or_unsafe_entry(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="r6-d21a3-", dir="/tmp") as value:
        sock = Path(value).resolve() / "jobs.sock"
        marker = sock.with_name("jobs.sock.stop")
        # Replaced between the read and the removal: the new entry stays.
        write_marker(marker, "me")
        aged(marker, 600.0)
        replacement = sock.with_name("replacement")
        write_marker(replacement, "someone else's")
        swapped = (replacement.stat().st_dev, replacement.stat().st_ino)
        read = entry.bounded_json

        def read_then_swap(data):
            os.replace(replacement, marker)
            return read(data)

        monkeypatch.setattr(entry, "bounded_json", read_then_swap)
        assert entry.stop_pending_refusal(sock, "me") is None
        assert (marker.stat().st_dev, marker.stat().st_ino) == swapped
        monkeypatch.setattr(entry, "bounded_json", read)
        marker.unlink()
        # A symlink (never followed) and a non-private stale marker: untouched.
        target = sock.with_name("target")
        write_marker(target, "me")
        aged(target, 600.0)
        marker.symlink_to(target)
        assert entry.stop_pending_refusal(sock, "me") is None
        assert marker.is_symlink() and target.exists()
        marker.unlink()
        write_marker(marker, "me", mode=0o644)
        aged(marker, 600.0)
        assert entry.stop_pending_refusal(sock, "me") is None and marker.exists()


def test_quiet_window_exit_honors_only_a_fresh_marker():
    """The consuming stop path: fresh -> True (exit 0) and removed, as before;
    stale own -> False (``reason=unrequested``, non-zero, launchd restarts) and
    removed; another incarnation's marker -> False and removed, as before."""
    with tempfile.TemporaryDirectory(prefix="r6-d21a3-", dir="/tmp") as value:
        sock = Path(value).resolve() / "jobs.sock"
        marker = sock.with_name("jobs.sock.stop")
        for owner_id, age, expected in (
            ("me", 1.0, True),
            ("me", 299.0, True),  # fresh near the 300 s bound
            ("me", 301.0, False),
            ("me", -60.0, False),
            ("previous", 1.0, False),
        ):
            write_marker(marker, owner_id)
            aged(marker, age)
            assert entry.provisioner_stop(sock, "me") is expected
            assert not marker.exists()


def test_marker_check_runs_inside_the_launch_transaction(reaped):
    """SR6-F2: after _prune, under the manager lock and the jobs-dir flock,
    before any record dir; a refusal leaves no record."""
    owner, manager = reaped
    jobs, seen = manager.jobs_dir, []
    prune = manager._prune

    def recording_prune(reserve=0):
        seen.append("prune")
        prune(reserve)

    def probe():
        fd = os.open(jobs / ".lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):  # held by _transaction right now
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        seen.append(("check", manager._lock._is_owned(), job_dirs(jobs)))
        return refusal

    manager._prune, manager.stop_pending = recording_prune, probe
    refusal = {"ok": False, "error": "refused", "code": "manager_stopping"}
    with tempfile.TemporaryDirectory(prefix="r6-d21a3-", dir="/tmp") as value:
        workdir = Path(value).resolve()
        assert manager.handle(req(workdir, "echo never")) == refusal
        assert seen == ["prune", ("check", True, [])]
        assert job_dirs(jobs) == [] and owner.live == owner.exits == {}
        refusal = None  # no marker: the same check passes and the start proceeds
        done = manager.handle(req(workdir, "true", wait=5))
        assert done["ok"] is True and seen[-1] == ("check", True, [])
        assert job_dirs(jobs) == [done["job_id"]]


@NATIVE
def test_entry_ignores_a_stale_own_marker_and_its_stop_is_unrequested(tmp_path):
    with tempfile.TemporaryDirectory(prefix="r6-d21a3-", dir="/tmp") as value:
        base = Path(value).resolve()
        (base / "rt").mkdir(mode=0o700)
        (base / "bin").mkdir()
        sock, jobs = base / "rt" / "jobs.sock", base / "jobs"
        (base / "config.toml").write_text(
            f'[jobs]\nsocket_path = "{sock}"\ndir = "{jobs}"\n'
        )
        marker = sock.with_name("jobs.sock.stop")
        child = start_entry(base)
        try:
            client, pong = ping_when_ready(sock, child)
            me = pong["owner_instance_id"]
            kw = {"workdir": base, "stdin": None, "call_id": "d21a3"}
            # Fresh own marker: typed retryable refusal, no record.
            write_marker(marker, me)
            with pytest.raises(job_client.JobManagerError, match="manager_stopping"):
                client.start(sock, command="echo never", wait_seconds=0, **kw)
            assert job_dirs(jobs) == [] and marker.exists()
            # Stale own marker (the gate died before bootout): start works.
            aged(marker, 301.0)
            done = client.start(sock, command="exit 0", wait_seconds=10, **kw)
            assert done["state"] == "exited" and job_dirs(jobs) == [done["job_id"]]
            assert not marker.exists()
            # Future-dated beyond the skew tolerance: stale too.
            write_marker(marker, me)
            aged(marker, -60.0)
            again = client.start(sock, command="exit 0", wait_seconds=10, **kw)
            assert again["state"] == "exited" and not marker.exists()
            # A stale marker never turns a TERM into the quiet-window exit 0.
            write_marker(marker, me)
            aged(marker, 301.0)
            child.send_signal(signal.SIGTERM)
            _, err = child.communicate(timeout=30)
            assert child.returncode == entry.EX_FAILED, err
            assert "reason=unrequested" in err and "event=stop_marker_stale" in err
            assert "reason=provisioner_quiet_window" not in err
            assert not marker.exists()
        finally:
            if child.poll() is None:  # our exact child only (RULE-NO-PKILL)
                child.kill()
                child.communicate(timeout=10)
