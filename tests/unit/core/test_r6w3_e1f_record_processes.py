"""E1-a5: the start-up import record across REAL processes (identical on both OSes).

A real job manager and a real uvicorn-served MCP server each start over a TEST
config whose ``jobs.dir`` fixes the state root. A planted record must survive a
mere import, survive a start that fails after the import phase but before the
bind, and be cleared only once the process has really started. Every process
is this test's own child; only that exact pid is signalled. Test homes live
under ~/.local/state/bt/e1a6 (0700, exact-path teardown).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from pathlib import Path

import pytest

from binnacle.startup_imports import (
    StartupImportFailed,
    record_path,
    record_start_failure,
)
from tests.unit.core.test_r6w3_e1b_manager_imports import PROBE, running_manager

REPO = Path(__file__).resolve().parents[3]
TEST_ROOT = Path.home() / ".local" / "state" / "bt" / "e1a6"
FAILURE = StartupImportFailed("binnacle.x", "ImportError", "binnacle/x.py:3")
IMPORT_ONLY = """
import json, sys
import binnacle.server  # an importer, not the serving process
print(json.dumps(sorted(m for m in sys.modules if m == "binnacle.server")))
"""


@pytest.fixture
def home():
    TEST_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(TEST_ROOT, 0o700)
    path = TEST_ROOT / f"pr-{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o700)
    yield path
    shutil.rmtree(path)  # exact path this fixture created
    with suppress(OSError):
        TEST_ROOT.rmdir()


def plant(home: Path, process: str) -> bytes:
    assert record_start_failure(process, FAILURE, home)  # state root == home
    return record_path(home, process).read_bytes()


def server_env(home: Path, *, socket_path: Path | None = None) -> dict[str, str]:
    root = home / "root"
    root.mkdir(mode=0o700, exist_ok=True)
    token = home / "token"
    token.write_text("Bearer e1f\n", encoding="utf-8")
    token.chmod(0o600)
    config = home / "config.toml"
    jobs = f'[jobs]\ndir = "{home / "jobs"}"\nowner = "embedded"\n'
    config.write_text(
        f'[auth]\ntoken_file = "{token}"\n'
        f'[roots]\ndefault_root = "{root}"\nextra_roots = []\n' + jobs,
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
    env["BINNACLE_CONFIG_FILE"] = str(config)
    return env


def wait_for(predicate, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def stop(child: subprocess.Popen) -> None:
    """Signal only this test's own child, by its exact pid."""
    if child.poll() is None:
        child.send_signal(signal.SIGTERM)
        with suppress(subprocess.TimeoutExpired):
            child.wait(timeout=30)
    if child.poll() is None:
        child.kill()
    child.wait(timeout=30)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def uvicorn(home: Path, port: int, env: dict[str, str]) -> subprocess.Popen:
    argv = [sys.executable, "-m", "uvicorn", "binnacle.server:app"]
    argv += ["--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"]
    log = open(home / "server.log", "wb")  # noqa: SIM115 - closed by the caller
    child = subprocess.Popen(argv, cwd=REPO, env=env, stdout=log, stderr=log)
    log.close()
    return child


def binnacle_serve(home: Path, port: int, env: dict[str, str]) -> subprocess.Popen:
    """The REAL entry the Mac com.binnacle.mcp and the Linux prod unit run:
    ``binnacle serve`` (argv0 ``<home>/bin/binnacle``), through ``cli.main``."""
    code = (
        "import sys\n"
        f"sys.argv = [{str(home / 'bin' / 'binnacle')!r}, 'serve', "
        f"'--host', '127.0.0.1', '--port', '{port}']\n"
        "from binnacle import cli\ncli.main()\n"
    )
    log = open(home / "serve.log", "wb")  # noqa: SIM115 - closed right away
    child = subprocess.Popen(
        [sys.executable, "-c", code], cwd=REPO, env=env, stdout=log, stderr=log
    )
    log.close()
    return child


def test_importing_the_server_leaves_the_record_alone(home):
    before = plant(home, "mcp-server")
    done = subprocess.run(
        [sys.executable, "-c", IMPORT_ONLY],
        cwd=REPO,
        env=server_env(home),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    assert record_path(home, "mcp-server").read_bytes() == before


def test_the_server_clears_the_record_only_after_it_is_serving(home):
    before = plant(home, "mcp-server")
    port = free_port()
    child = uvicorn(home, port, server_env(home))
    try:
        assert wait_for(lambda: _listening(port) or child.poll() is not None, 120)
        assert child.poll() is None, (home / "server.log").read_text(errors="replace")
        assert wait_for(lambda: not record_path(home, "mcp-server").exists(), 15)
    finally:
        stop(child)
    assert before  # the planted record is what was cleared


def test_a_server_that_cannot_bind_keeps_the_record(home):
    before = plant(home, "mcp-server")
    with socket.socket() as holder:  # this test's own listener holds the port
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        child = uvicorn(home, port, server_env(home))
        try:
            assert wait_for(lambda: child.poll() is not None, 120)
        finally:
            stop(child)
    assert child.returncode != 0
    assert record_path(home, "mcp-server").read_bytes() == before


def test_binnacle_serve_clears_the_record_once_the_server_started(home):
    before = plant(home, "mcp-server")
    port = free_port()
    child = binnacle_serve(home, port, server_env(home))
    try:
        assert wait_for(lambda: _listening(port) or child.poll() is not None, 120)
        log = (home / "serve.log").read_text(errors="replace")
        assert child.poll() is None, log
        assert wait_for(lambda: not record_path(home, "mcp-server").exists(), 15), log
    finally:
        stop(child)
    assert before  # the planted record is what was cleared


def test_binnacle_serve_that_cannot_bind_keeps_the_record(home):
    before = plant(home, "mcp-server")
    with socket.socket() as holder:  # this test's own listener holds the port
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        child = binnacle_serve(home, port, server_env(home))
        try:
            assert wait_for(lambda: child.poll() is not None, 120)
        finally:
            stop(child)
    assert child.returncode != 0
    assert record_path(home, "mcp-server").read_bytes() == before


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


def test_a_manager_clears_the_record_only_after_it_is_serving(home):
    plant(home, "job-manager")
    with running_manager(home) as (child, _client, _sock, pong, _):
        assert pong["pid"] == child.pid
        assert wait_for(lambda: not record_path(home, "job-manager").exists(), 15)


def test_a_manager_that_fails_before_the_bind_keeps_the_record(home):
    before = plant(home, "job-manager")
    long_dir = home / ("d" * 130)  # longer than any sun_path: no bind is possible
    long_dir.mkdir(mode=0o700)
    sock = long_dir / "jobs.sock"
    config = home / "config.toml"
    config.write_text(
        f'[jobs]\nsocket_path = "{sock}"\ndir = "{home / "jobs"}"\n', encoding="utf-8"
    )
    config.chmod(0o600)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
    env.update(BINNACLE_CONFIG_FILE=str(config), HOME=str(home))
    with open(home / "manager.log", "wb") as log:
        child = subprocess.Popen(
            [sys.executable, "-c", PROBE, str(home), str(sock)],
            cwd=REPO,
            env=env,
            stdout=log,
            stderr=log,
        )
    try:
        assert wait_for(lambda: child.poll() is not None, 120)
    finally:
        stop(child)
    assert child.returncode != 0
    assert not sock.exists()
    assert record_path(home, "job-manager").read_bytes() == before
    assert json.loads(before)["module"] == "binnacle.x"
