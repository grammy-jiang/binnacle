"""r6 W2 M1 step 2 (SD-74, STEER-01): the ping reports the jobs dir it HOLDS.

``jobs_dir`` is ``os.path.realpath`` of the configured jobs dir, captured once
when the manager takes ``<jobs_dir>/.manager.lock``. A config edit after start
never changes it; a symlinked or relative configured dir reports the real,
absolute directory. A manager that holds no writer lock reports no key, so the
deploy gate can tell an old (pre-M1) manager by the missing key.
"""

from __future__ import annotations

import fcntl
import os
import sys
import tempfile
from pathlib import Path

import pytest

from tests.platform.darwin.test_job_manager_entry import ping_when_ready
from tests.platform.darwin.test_r6_d1_runtime_rebind import finish, reap_exact
from tests.platform.darwin.test_r6_d2_stop_marker_start import reaped, start_entry

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin manager entry")
__all__ = ["reaped"]  # the in-process manager fixture


def lock_is_held(directory: Path) -> bool:
    """Probe with our own descriptor; a free lock is released at once."""
    fd = os.open(directory / ".manager.lock", os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def test_an_unlocked_in_process_manager_reports_no_jobs_dir(reaped):
    _, manager = reaped
    pong = manager.handle({"version": 1, "op": "ping"})
    assert pong["ok"] is True and "jobs_dir" not in pong


@NATIVE
@pytest.mark.parametrize("spelling", ["symlink", "relative"])
def test_ping_jobs_dir_is_the_held_realpath_and_survives_a_config_edit(spelling):
    with tempfile.TemporaryDirectory(prefix="r6w2-m1-", dir="/tmp") as value:
        base = Path(value).resolve()
        (base / "rt").mkdir(mode=0o700)
        (base / "bin").mkdir()
        real = base / "jobs-real"
        real.mkdir()
        if spelling == "symlink":
            (base / "jobs-link").symlink_to(real)
            configured = str(base / "jobs-link")
        else:
            configured = "jobs-real"  # relative to the entry's cwd (base)
        sock, config = base / "rt" / "jobs.sock", base / "config.toml"
        config.write_text(f'[jobs]\nsocket_path = "{sock}"\ndir = "{configured}"\n')
        child = start_entry(base)
        try:
            client, pong = ping_when_ready(sock, child)
            assert pong["jobs_dir"] == str(real) == os.path.realpath(real)
            assert os.path.isabs(pong["jobs_dir"]) and lock_is_held(real)
            other = base / "jobs-other"
            other.mkdir()
            config.write_text(f'[jobs]\nsocket_path = "{sock}"\ndir = "{other}"\n')
            again = client.ping(sock)
            assert again["jobs_dir"] == str(real) and again["pid"] == child.pid
            assert lock_is_held(real) and not (other / ".manager.lock").exists()
            finish(child, sock, pong["owner_instance_id"])
            assert not lock_is_held(real)  # released with the process
        finally:
            reap_exact(child)
