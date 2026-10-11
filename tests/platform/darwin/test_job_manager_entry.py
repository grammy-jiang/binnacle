"""com.binnacle.jobs entry point (J2r STEP 2) and the J1r manager handoff."""

from __future__ import annotations

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

from binnacle import config
from binnacle.features.commands import job_client
from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.darwin import job_manager_entry as entry
from binnacle.platform.darwin import job_manager_service as svc
from binnacle.platform.darwin.job_manager_client import DarwinJobClient
from tests.platform.darwin.test_job_manager_resilience import lock_open_fails, wait_for
from tests.platform.darwin.test_job_manager_service import (
    ReferenceOwner,
    manager_for,
    meta_of,
    req,
    stop_req,
    write_record,
)

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin J1 owner, A3")
MODULE = "binnacle.platform.darwin.job_manager_service"
PING_FIELDS = {"ok", "version", "owner_instance_id", "boot_id", "pid"}
PING_FIELDS |= {"package_version", "revision", "running_jobs", "unknown_jobs"}


@pytest.mark.parametrize(
    "toml",
    [
        None,
        "",
        (
            '[jobs]\nsocket_path = "/tmp/r4-x/rt/m.sock"\ndir = "/tmp/r4-x/j"\n'
            'keep_newest = 7\nowner = "manager"\n[run_command]\nwait_max_s = 20\n'
        ),
    ],
)
def test_config_reader_is_pinned_to_binnacle_settings(tmp_path, monkeypatch, toml):
    # Layering forbids platform -> config; the restated keys must not drift.
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in list(os.environ):
        if name.startswith("BINNACLE_"):
            monkeypatch.delenv(name)
    path = tmp_path / "config.toml"
    if toml is not None:
        path.write_text(toml)
    monkeypatch.setenv(config.CONFIG_FILE_ENV, str(path))
    ours, theirs = entry.read_config(), config.Settings()
    assert ours.jobs.socket_path == theirs.jobs.socket_path
    assert ours.jobs.dir == theirs.jobs.dir
    assert ours.jobs.keep_newest == theirs.jobs.keep_newest
    assert ours.run_command.wait_max_s == theirs.run_command.wait_max_s
    assert entry.CONFIG_FILE_ENV == config.CONFIG_FILE_ENV
    for override in ("BINNACLE_JOBS__DIR", "BINNACLE_RUNTIME_DIR"):  # RJ2D-F4
        monkeypatch.setenv(override, "/elsewhere")
        with pytest.raises(ValueError, match="config file only"):
            entry.read_config()
        monkeypatch.delenv(override)


@pytest.fixture
def live(tmp_path):
    owner = ReferenceOwner()
    manager, halt = manager_for(owner, tmp_path / "jobs"), threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,))
    reaper.start()
    yield owner, manager
    halt.set()
    reaper.join()
    manager.close()


def test_ping_counts_running_and_unknown_jobs(tmp_path, live):
    jobs_dir = tmp_path / "jobs"
    # D3 (frozen J2r ping fields): additive to the Linux ping object.
    owner, manager = live
    v2 = {"schema_version": 2, "owner_instance_id": "old", "boot_id": "boot"}
    write_record(jobs_dir, "a" * 12, **v2)  # foreign unfinished: unknown
    write_record(jobs_dir, "d" * 12, **v2, exit_code=0)  # finished: not counted
    (jobs_dir / ("b" * 12)).mkdir()  # unusable record: not counted
    running = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
    manager.handle(req(tmp_path, "exit 0", wait=5))
    pong = manager.handle({"version": 1, "op": "ping"})
    assert (pong["running_jobs"], pong["unknown_jobs"]) == (1, 1)
    assert (pong["version"], pong["owner_instance_id"]) == (1, owner.owner_instance_id)
    assert manager.handle(stop_req(running))["state"] == "exited"
    pong = manager.handle({"version": 1, "op": "ping"})
    assert (pong["running_jobs"], pong["unknown_jobs"]) == (0, 1)


def test_moved_names_live_only_in_their_new_homes():
    # RJ2D-F1 option (b): G7 forbids identity/lazy forwarding, so the J2-a1
    # path is gone (BREAKING; J4 imports the new homes, ROWS-FOR-J4 item 3).
    from binnacle.platform.darwin import job_manager_client as client_home

    assert client_home.DarwinJobClient.__module__ == client_home.__name__
    assert issubclass(client_home.DarwinJobManagerError, RuntimeError)
    assert entry.serve_job_manager.__module__ == entry.__name__
    for name in ("DarwinJobClient", "DarwinJobManagerError", "serve_job_manager"):
        assert not hasattr(svc, name), name  # a stale import fails loudly
    assert svc.main.__module__ == svc.__name__  # the launchd -m delegate stays
    fresh = (  # a new interpreter: every home imports without a cycle
        "import binnacle.platform.darwin.job_manager_service, "
        "binnacle.platform.darwin.job_manager_client, "
        "binnacle.platform.darwin.job_manager_entry"
    )
    argv = [sys.executable, "-c", fresh]
    out = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr


def test_owner_is_composed_without_its_own_reaper(monkeypatch):
    # STEER-03: reap_forever is the only reaper of the composed J1 owner.
    calls = []
    monkeypatch.setattr(entry, "DarwinJobProcessOwner", lambda **kw: calls.append(kw))
    entry.compose_owner("boot")
    assert calls == [{"boot_id": "boot", "start_reaper": False}]


def test_main_takes_no_arguments():
    assert entry.main(["--socket", "/tmp/x"]) == entry.EX_USAGE


def test_stop_marker_must_name_this_incarnation():
    with tempfile.TemporaryDirectory(prefix="r4-j2e-", dir="/tmp") as value:
        root = Path(value).resolve() / "rt"
        root.mkdir(mode=0o700)
        sock, marker = root / "jobs.sock", root / "jobs.sock.stop"
        assert not entry.provisioner_stop(sock, "me")  # no marker: unrequested
        for content, mode, expected in (
            ({"owner_instance_id": "previous"}, 0o600, False),
            ({"owner_instance_id": "me"}, 0o644, False),  # not private
            ({"owner_instance_id": "me"}, 0o600, True),
        ):
            marker.write_text(json.dumps(content))
            marker.chmod(mode)
            assert entry.provisioner_stop(sock, "me") is expected
            marker.unlink(missing_ok=True)


def test_release_only_after_the_terminal_record_is_durable(tmp_path, monkeypatch):
    # J1r handoff 1: release() acknowledges a durable record, never before.
    owner = ReferenceOwner()
    released = []
    owner.release = released.append
    manager = manager_for(owner, tmp_path / "jobs")
    job_id = manager.handle(req(tmp_path, "exit 3"))["job_id"]
    exited = pc.OwnedJobExit(job_id, 3, None, "normal_exit")
    with lock_open_fails(monkeypatch, threading.current_thread().name):
        assert manager.record_exit(exited) is False
    assert released == []
    assert manager.record_exit(exited) and released == [job_id]
    assert meta_of(tmp_path / "jobs", job_id)["exit_code"] == 3
    os.waitpid(owner.live.pop(job_id), 0)


def test_reference_owner_release_matches_the_j1_owner(tmp_path):
    # RJ1D2-F3: the test double refuses ids it never spawned, as J1 does.
    owner = ReferenceOwner()
    with pytest.raises(pc.UnverifiedJobProcess, match="darwin_job_not_owned"):
        owner.release("0" * 12)
    manager = manager_for(owner, tmp_path / "jobs")
    job_id = manager.handle(req(tmp_path, "sleep 30"))["job_id"]
    with pytest.raises(ValueError, match="darwin_job_not_terminal"):
        owner.release(job_id)
    manager.close()
    owner.release(job_id)  # terminal and recorded: acknowledged
    assert owner.released == {job_id}


def test_reaper_fault_records_no_exit_and_ends_the_reaper(tmp_path):
    # J1r handoff 3: JobOwnerLost means authority UNKNOWN, never an exit.
    owner = ReferenceOwner()
    manager = manager_for(owner, tmp_path / "jobs")

    def lost(*_args):
        raise pc.JobOwnerLost("darwin_job_reaper_failed")

    owner.wait = owner.reap_exits = lost
    reply = manager.handle(req(tmp_path, "true", wait=1))
    assert reply["ok"] is True
    assert not svc._terminal(meta_of(tmp_path / "jobs", reply["job_id"]))
    manager.reap_forever(threading.Event())  # returns: serving then stops
    os.waitpid(owner.live.pop(reply["job_id"]), 0)


def test_persistent_reap_failure_stops_the_manager(tmp_path, monkeypatch):
    # RJ1D-F1 (3): never retry a failing reaper forever; stop, restart, D-1.
    owner, calls = ReferenceOwner(), []

    def broken(timeout):
        calls.append(timeout)
        raise ValueError("kqueue poll failed")

    owner.reap_exits = broken
    monkeypatch.setattr(svc, "REAP_FAILURE_LIMIT", 3)
    manager_for(owner, tmp_path / "jobs").reap_forever(threading.Event())
    assert len(calls) == 3


@NATIVE
def test_real_owner_persists_background_exits_while_serving(tmp_path):
    # RJ1D-F1 (5): the composed owner (start_reaper=False) and reap_forever
    # persist and release every background exit before any close().
    from binnacle.platform.darwin.job_process_owner import DarwinJobProcessOwner

    owner = DarwinJobProcessOwner(boot_id="b", start_reaper=False)
    manager, halt = manager_for(owner, tmp_path / "jobs"), threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,))
    reaper.start()
    try:
        jobs = [
            manager.handle(req(tmp_path, "sleep 0.2; exit 3"))["job_id"]
            for _ in range(30)
        ]

        def done():
            return all(svc._terminal(meta_of(tmp_path / "jobs", j)) for j in jobs)

        assert wait_for(done, timeout=20)
        assert {meta_of(tmp_path / "jobs", j)["exit_code"] for j in jobs} == {3}
        assert {manager.state(j) for j in jobs} == {"exited"}
        assert not owner.reaper_running
    finally:
        halt.set()
        reaper.join()
        closed = manager.close()
    assert closed == ()  # all released after their durable records


@NATIVE
def test_close_persists_every_unreleased_exit_and_many_jobs_in_budget(
    tmp_path, monkeypatch
):
    # J1r handoff 2 / CR0 point 3 / R-J3-F3: reaped exits whose persistence
    # failed are written by close() with their own reason; running jobs get
    # owner_restart; more than 4 groups stop inside launchd ExitTimeOut.
    from binnacle.platform.darwin.job_process_owner import DarwinJobProcessOwner

    owner = DarwinJobProcessOwner(boot_id="b", start_reaper=False)
    manager = manager_for(owner, tmp_path / "jobs")
    manager.grace = (svc.STOP_SIGTERM_GRACE_S, svc.STOP_SIGKILL_GRACE_S)
    halt = threading.Event()
    reaper = threading.Thread(target=manager.reap_forever, args=(halt,), name="rp")
    with lock_open_fails(monkeypatch, "rp"):
        reaper.start()
        short = [manager.handle(req(tmp_path, f"exit {n}"))["job_id"] for n in (3, 4)]
        running = [
            manager.handle(req(tmp_path, "sleep 60"))["job_id"] for _ in range(6)
        ]
        assert wait_for(lambda: all(j in manager._unrecorded for j in short))
        halt.set()
        reaper.join()
    manager._unrecorded.clear()  # only owner.close() still holds these exits
    started = time.monotonic()
    manager.close()
    assert time.monotonic() - started < 17.0  # JOBS_EXIT_TIMEOUT_S floor
    for job_id, code in zip(short, (3, 4), strict=True):
        meta = meta_of(tmp_path / "jobs", job_id)
        assert (meta["exit_code"], meta["termination_reason"]) == (code, "normal_exit")
    for job_id in running:
        meta = meta_of(tmp_path / "jobs", job_id)
        assert (meta["signal"], meta["termination_reason"]) == (15, "owner_restart")
        assert "authority" not in meta


def start_entry(base, path_env, extra_fd):
    env = {"BINNACLE_CONFIG_FILE": str(base / "config.toml"), "HOME": str(base)}
    env["PATH"] = path_env
    argv = [sys.executable, "-m", MODULE]
    pipes = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
    return subprocess.Popen(argv, env=env, cwd=base, pass_fds=(extra_fd,), **pipes)


def ping_when_ready(sock, child):
    client = DarwinJobClient(error_type=job_client.JobManagerError)
    deadline = time.monotonic() + 20
    while True:
        try:
            return client, client.ping(sock)
        except job_client.JobManagerError:
            if child.poll() is not None or time.monotonic() > deadline:
                raise
            time.sleep(0.05)


@NATIVE
def test_entry_point_serves_pings_and_exits_per_launchd_contract():
    with tempfile.TemporaryDirectory(prefix="r4-j2e-", dir="/tmp") as value:
        base = Path(value).resolve()
        (base / "rt").mkdir(mode=0o700)
        (base / "bin").mkdir()
        sock, jobs = base / "rt" / "jobs.sock", base / "jobs"
        toml = f'[jobs]\nsocket_path = "{sock}"\ndir = "{jobs}"\n'
        (base / "config.toml").write_text(toml)
        path_env = f"{base / 'bin'}:/usr/bin:/bin"
        read, write = os.pipe()
        inherited = os.dup2(write, 77, inheritable=True)  # RJ1-F6 probe
        children = []
        try:
            child = start_entry(base, path_env, inherited)
            children.append(child)
            client, pong = ping_when_ready(sock, child)
            assert PING_FIELDS <= set(pong) and pong["pid"] == child.pid
            assert (pong["version"], pong["running_jobs"], pong["unknown_jobs"]) == (
                1,
                0,
                0,
            )
            assert re.fullmatch(r"\d+\.\d{6}-[0-9A-Fa-f-]+", pong["boot_id"])
            probe = "printenv PATH; test -e /dev/fd/77 && echo leaked || echo clean"
            kw = {"workdir": base, "stdin": None, "call_id": "c"}
            done = client.start(sock, command=probe, wait_seconds=10, **kw)
            assert done["state"] == "exited"
            out = (jobs / done["job_id"] / "out.log").read_text()
            assert out == f"{path_env}\nclean\n"  # PATH unchanged, no fd leak
            running = client.start(sock, command="sleep 60", wait_seconds=0, **kw)
            assert client.ping(sock)["running_jobs"] == 1
            child.send_signal(signal.SIGTERM)  # a stray stop: not the provisioner
            _, err = child.communicate(timeout=30)
            assert child.returncode == entry.EX_FAILED
            assert "owner_reaper_thread=False" in err
            assert "reason=unrequested" in err
            meta = meta_of(jobs, running["job_id"])
            assert (meta["signal"], meta["termination_reason"]) == (15, "owner_restart")

            child = start_entry(base, path_env, inherited)
            children.append(child)
            client, pong = ping_when_ready(sock, child)
            assert (pong["running_jobs"], pong["unknown_jobs"]) == (0, 0)
            marker = sock.with_name("jobs.sock.stop")  # provisioner quiet window
            marker.write_text(
                json.dumps({"owner_instance_id": pong["owner_instance_id"]})
            )
            marker.chmod(0o600)
            child.send_signal(signal.SIGTERM)
            _, err = child.communicate(timeout=30)
            assert child.returncode == 0, err
            assert "reason=provisioner_quiet_window" in err
            assert not marker.exists()  # consumed: a later stray stop is non-zero
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=10)
            for fd in (read, write, inherited):
                os.close(fd)
