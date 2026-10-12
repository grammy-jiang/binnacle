"""com.binnacle.jobs entry point (J2r STEP 2): config, identity, pings, launchd exit."""

from __future__ import annotations

import json
import os
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
from binnacle.platform.darwin import job_manager_config
from binnacle.platform.darwin import job_manager_entry as entry
from binnacle.platform.darwin import job_manager_procinfo as procinfo
from binnacle.platform.darwin import job_manager_service as svc
from binnacle.platform.darwin.job_manager_client import DarwinJobClient
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
    ours, theirs = job_manager_config.read_config(), config.Settings()
    assert ours.jobs.socket_path == theirs.jobs.socket_path
    assert ours.jobs.dir == theirs.jobs.dir
    assert ours.jobs.keep_newest == theirs.jobs.keep_newest
    assert ours.run_command.wait_max_s == theirs.run_command.wait_max_s
    assert job_manager_config.CONFIG_FILE_ENV == config.CONFIG_FILE_ENV
    for override in ("BINNACLE_JOBS__DIR", "BINNACLE_RUNTIME_DIR"):  # RJ2D-F4
        monkeypatch.setenv(override, "/elsewhere")
        with pytest.raises(ValueError, match="config file only"):
            job_manager_config.read_config()
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


def test_unreadable_boot_session_is_never_fabricated(monkeypatch):
    # STEER-10: no boot identity means no manager (EX_FAILED), never a guess.
    class NoSysctl:
        def sysctlbyname(self, *_):
            return -1

    monkeypatch.setattr(procinfo.ctypes, "CDLL", lambda *_, **__: NoSysctl())
    with pytest.raises(OSError, match="sysctl kern.bootsessionuuid failed"):
        procinfo.boot_id()


@NATIVE
def test_boot_identity_is_the_public_boot_session_sysctl():
    argv = ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"]
    session = subprocess.run(argv, capture_output=True, text=True, check=True)
    assert procinfo.boot_id() == session.stdout.strip().upper()
    assert procinfo.BOOT_SESSION.fullmatch(procinfo.boot_id())


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
            assert pong["boot_id"] == procinfo.boot_id()  # kern.bootsessionuuid
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
            assert (meta["signal"], meta["termination_reason"]) == (
                None,
                "owner_restart",
            )

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
