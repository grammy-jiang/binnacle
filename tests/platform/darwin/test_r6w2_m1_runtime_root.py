"""r6 W2 M1 step 1 (SD-68, D21-a2 grant): the Darwin runtime root moves.

The default runtime + socket root is ``~/Library/Application Support/Binnacle/
r3`` (not the purgeable ``~/Library/Caches``), private 0700 and walked with
O_NOFOLLOW. The rebind (D1), the stop marker (D2) and the marker path follow
it. There is no fallback to the legacy Caches root on either side, and a live
legacy manager on the same jobs dir is never joined by a second writer.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from binnacle.features.commands import job_client
from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.darwin import generation_runtime as runtime
from binnacle.platform.darwin import job_manager_entry as entry
from binnacle.platform.darwin.job_manager_client import DarwinJobClient
from tests.platform.darwin.test_job_manager_entry import ping_when_ready
from tests.platform.darwin.test_r6_d1_runtime_rebind import finish, reap_exact
from tests.platform.darwin.test_r6_d2_stop_marker_start import (
    start_entry,
    write_marker,
)

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin runtime root")
NEW = Path("Library/Application Support/Binnacle/r3")
LEGACY = Path("Library/Caches/Binnacle/r3")


@contextmanager
def home(config_socket: Path | None = None) -> Iterator[tuple[Path, Path, Path]]:
    """A private HOME (``/tmp/r6w2-m1-*``) with config and jobs; no runtime root."""
    with tempfile.TemporaryDirectory(prefix="r6w2-m1-", dir="/tmp") as value:
        base = Path(value).resolve()
        (base / "bin").mkdir()
        jobs = base / "jobs"
        toml = f'[jobs]\ndir = "{jobs}"\n'
        if config_socket is not None:
            toml = f'[jobs]\nsocket_path = "{config_socket}"\ndir = "{jobs}"\n'
        (base / "config.toml").write_text(toml)
        yield base, base / NEW / "jobs.sock", jobs


def private_dirs(base: Path, relative: Path) -> Path:
    root = base
    for part in relative.parts:
        root = root / part
        root.mkdir(mode=0o700, exist_ok=True)
    return root


def test_default_root_is_application_support_and_never_caches(monkeypatch):
    assert runtime.RUNTIME_ROOT == str(NEW)
    assert "Caches" not in runtime.RUNTIME_ROOT and " " in runtime.RUNTIME_ROOT
    with home() as (base, sock, _):
        monkeypatch.delenv("BINNACLE_RUNTIME_DIR", raising=False)
        monkeypatch.setenv("HOME", str(base))
        paths = runtime.resolve_runtime_paths()
        assert (paths.binnacle_runtime_dir, paths.jobs_socket) == (base / NEW, sock)
        for directory in (base / "Library", base / NEW):  # created 0700, own uid
            info = directory.lstat()
            assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            assert stat.S_IMODE(info.st_mode) == 0o700
        assert not (base / "Library/Caches").exists()  # no legacy root, no fallback


def test_a_symlinked_component_of_the_new_root_is_refused(monkeypatch):
    with home() as (base, _, _):
        private_dirs(base, Path("Library"))
        elsewhere = private_dirs(base, Path("elsewhere"))
        (base / "Library/Application Support").symlink_to(elsewhere)
        monkeypatch.delenv("BINNACLE_RUNTIME_DIR", raising=False)
        monkeypatch.setenv("HOME", str(base))
        with pytest.raises(NativeCapabilityError):
            runtime.resolve_runtime_paths()
        assert list(elsewhere.iterdir()) == []  # nothing followed or created


def test_overlong_default_socket_path_fails_closed_with_a_clear_error(monkeypatch):
    with home() as (base, _, _):
        long_home = base / ("h" * 60)
        sock = long_home / NEW / "jobs.sock"
        assert len(os.fsencode(sock)) >= entry.SUN_PATH_MAX
        monkeypatch.delenv("BINNACLE_RUNTIME_DIR", raising=False)
        monkeypatch.setenv("HOME", str(long_home))
        with pytest.raises(NativeCapabilityError) as refused:
            runtime.resolve_runtime_paths()
        size = len(os.fsencode(sock))
        assert f"darwin_socket_path_too_long: {size} bytes > 103" in str(
            refused.value.__cause__
        )
        assert not long_home.exists()  # fail closed before any directory


def test_client_has_no_fallback_to_the_legacy_root(monkeypatch):
    with home() as (base, sock, _):
        legacy = private_dirs(base, LEGACY) / "jobs.sock"
        monkeypatch.delenv("BINNACLE_RUNTIME_DIR", raising=False)
        monkeypatch.setenv("HOME", str(base))
        target = runtime.resolve_runtime_paths().jobs_socket
        assert target == sock and target != legacy
        client = DarwinJobClient(error_type=job_client.JobManagerError)
        with pytest.raises(job_client.JobManagerError) as refused:
            client.ping(target)
        assert str(refused.value).startswith(f"{pc.JOB_MANAGER_UNAVAILABLE} at {sock}:")
        assert str(legacy) not in str(refused.value)


@NATIVE
def test_entry_serves_the_default_root_and_the_marker_follows_it():
    """No socket_path in the config: the entry derives the new root from HOME."""
    with home() as (base, sock, _):
        legacy = private_dirs(base, LEGACY)
        child = start_entry(base)
        try:
            client, pong = ping_when_ready(sock, child)
            me = pong["owner_instance_id"]
            assert stat.S_IMODE(sock.parent.stat().st_mode) == 0o700
            assert stat.S_ISSOCK(sock.stat().st_mode) and " " in str(sock)
            kw = {"workdir": base, "stdin": None, "call_id": "m1"}
            done = client.start(sock, command="exit 0", wait_seconds=10, **kw)
            assert done["state"] == "exited"
            # A marker at the legacy path is not this manager's: start still works.
            write_marker(legacy / "jobs.sock.stop", me)
            again = client.start(sock, command="exit 0", wait_seconds=10, **kw)
            assert again["state"] == "exited"
            # The D2 marker is <new socket>.stop: start refused, typed.
            write_marker(sock.with_name("jobs.sock.stop"), me)
            with pytest.raises(job_client.JobManagerError) as refused:
                client.start(sock, command="echo never", wait_seconds=0, **kw)
            assert str(refused.value) == (
                f"{pc.JOB_MANAGER_UNAVAILABLE} at {sock}: {entry.STOP_PENDING_CODE}"
            )
            err = finish(child, sock, me)  # quiet-window stop at the new marker
            assert "reason=provisioner_quiet_window" in err
            assert sorted(p.name for p in legacy.iterdir()) == ["jobs.sock.stop"]
        finally:
            reap_exact(child)


@NATIVE
def test_legacy_marker_never_stops_the_new_manager_quietly():
    with home() as (base, sock, _):
        legacy = private_dirs(base, LEGACY)
        child = start_entry(base)
        try:
            _, pong = ping_when_ready(sock, child)
            write_marker(legacy / "jobs.sock.stop", pong["owner_instance_id"])
            child.terminate()
            _, err = child.communicate(timeout=30)
            assert child.returncode == entry.EX_FAILED, err
            assert "reason=unrequested" in err
            assert (legacy / "jobs.sock.stop").exists()  # never consumed
        finally:
            reap_exact(child)


@NATIVE
def test_a_live_legacy_manager_keeps_the_only_writer_lock():
    """Negative: the new-root manager never becomes a second jobs-dir writer."""
    with home() as (base, sock, jobs):
        legacy_sock = private_dirs(base, LEGACY) / "jobs.sock"
        legacy_home = base / "legacy-home"
        (legacy_home / "bin").mkdir(parents=True)
        (legacy_home / "config.toml").write_text(
            f'[jobs]\nsocket_path = "{legacy_sock}"\ndir = "{jobs}"\n'
        )
        old = new = None
        try:
            old = start_entry(legacy_home)
            client, pong = ping_when_ready(legacy_sock, old)
            new = start_entry(base)
            _, err = new.communicate(timeout=30)
            assert new.returncode == entry.EX_TEMPFAIL, err
            assert "busy=True" in err
            assert not sock.exists() and not sock.with_name("jobs.sock.auth").exists()
            again = client.ping(legacy_sock)
            assert (again["pid"], again["owner_instance_id"]) == (
                old.pid,
                pong["owner_instance_id"],
            )
            finish(old, legacy_sock, pong["owner_instance_id"])
        finally:
            reap_exact(old, new)
