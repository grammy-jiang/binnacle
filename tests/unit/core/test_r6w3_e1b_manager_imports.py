"""E1-a2: a serving job manager first-imports no binnacle module after start-up.

E1 (51d7918) closed OPS-FOLLOWUP-shared-venv-lazy-import / R-M1-X1 for the MCP
server. Both job manager entries (Linux ``job_manager.main``, Darwin
``job_manager_entry.main``) make the same eager import before serving. Each
host runs its own manager entry here: identical assertions on both OSes. The
test home (config, jobs, socket) lives under ~/.local/state/bt/e1b (0700).
"""

import ast
import json
import logging
import os
import platform
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest

from binnacle.platform.darwin import job_manager_entry
from binnacle.startup_imports import runtime_module_names

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src" / "binnacle"
TEST_ROOT = Path.home() / ".local" / "state" / "bt" / "e1b"

# Runs the host's manager entry as launchd/systemd do; a watcher thread
# snapshots sys.modules once the socket exists and again after the exercise.
PROBE = """
import json, platform, sys, threading, time
from pathlib import Path
home, sock = Path(sys.argv[1]), Path(sys.argv[2])
def binnacle_modules():
    return {m for m in list(sys.modules) if m.split(".")[0] == "binnacle"}
def watch():
    while not sock.exists():
        time.sleep(0.01)
    served = binnacle_modules()
    (home / "served.json").write_text(json.dumps(sorted(served)))
    while not (home / "exercised").exists():
        time.sleep(0.01)
    late = sorted(binnacle_modules() - served)
    (home / "late.json").write_text(json.dumps(late))
threading.Thread(target=watch, daemon=True).start()
sys.argv[1:] = []
if platform.system() == "Darwin":
    import runpy
    runpy.run_module("binnacle.platform.darwin.job_manager_service", run_name="__main__")
else:
    from binnacle.features.commands.job_manager import main
    main()
"""


def manager_client():
    """The host's job-manager RPC client (one signature on both OSes)."""
    if platform.system() == "Darwin":
        from binnacle.platform.darwin.job_manager_client import DarwinJobClient

        return DarwinJobClient()
    from binnacle.features.commands import job_client

    return job_client


@pytest.fixture
def private_home():
    """One 0700 home under TEST_ROOT, removed by exact path."""
    import shutil

    TEST_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    TEST_ROOT.chmod(0o700)
    home = TEST_ROOT / f"m-{uuid.uuid4().hex[:12]}"
    home.mkdir(mode=0o700)
    try:
        yield home
    finally:
        shutil.rmtree(home)
        with suppress(OSError):  # only when no other test home remains
            TEST_ROOT.rmdir()


@contextmanager
def running_manager(home: Path, *, source: Path = REPO, env_extra=None):
    """The host manager entry over a TEST config; only its own child is signalled."""
    (home / "rt").mkdir(mode=0o700)
    (home / "work").mkdir(mode=0o700)
    sock, jobs = home / "rt" / "jobs.sock", home / "jobs"
    config = home / "config.toml"
    config.write_text(f'[jobs]\nsocket_path = "{sock}"\ndir = "{jobs}"\n')
    config.chmod(0o600)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
    env.update(BINNACLE_CONFIG_FILE=str(config), HOME=str(home), **(env_extra or {}))
    argv = [sys.executable, "-c", PROBE, str(home), str(sock)]
    started = time.monotonic()
    with open(home / "manager.log", "wb") as log:
        child = subprocess.Popen(argv, env=env, cwd=source, stdout=log, stderr=log)
    try:
        client = manager_client()
        pong = ping_when_ready(client, sock, child)
        yield child, client, sock, pong, time.monotonic() - started
    finally:
        stop_manager(child, client, sock)


def ping_when_ready(client, sock: Path, child) -> dict:
    deadline = time.monotonic() + 60
    while True:
        try:
            return client.ping(sock)
        except RuntimeError:
            if child.poll() is not None or time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def stop_manager(child, client, sock: Path) -> int:
    """Darwin: the provisioner's stop marker first; then SIGTERM to this child."""
    if child.poll() is None:
        if platform.system() == "Darwin":
            with suppress(RuntimeError, OSError):
                owner = client.ping(sock)["owner_instance_id"]
                marker = sock.with_name(sock.name + ".stop")
                marker.write_text(json.dumps({"owner_instance_id": owner}))
                marker.chmod(0o600)
        child.send_signal(signal.SIGTERM)  # the fixture's own unreaped child
        with suppress(subprocess.TimeoutExpired):
            child.wait(timeout=30)
    if child.poll() is None:
        child.kill()  # the exact child pid, after SIGTERM had its chance
    return child.wait(timeout=30)


def exercise(client, sock: Path, work: Path) -> dict:
    """start (foreground and background), status (ping), stop: once each."""
    done = client.start(
        sock,
        command="echo e1b",
        workdir=work,
        stdin=None,
        wait_seconds=10.0,
        call_id="e1b-fg",
    )
    job = client.start(
        sock,
        command="sleep 30",
        workdir=work,
        stdin=None,
        wait_seconds=0.2,
        call_id="e1b-bg",
    )
    status = client.ping(sock)
    stopped = client.stop(sock, job["job_id"], call_id="e1b-stop")
    return {"done": done, "job": job, "status": status, "stopped": stopped}


def late_imports(home: Path) -> tuple[list[str], list[str]]:
    (home / "exercised").write_text("")
    deadline = time.monotonic() + 10
    while not (home / "late.json").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    served = json.loads((home / "served.json").read_text())
    return served, json.loads((home / "late.json").read_text())


def test_manager_first_imports_no_binnacle_module_after_serving(private_home):
    with running_manager(private_home) as (child, client, sock, pong, _):
        assert pong["pid"] == child.pid
        calls = exercise(client, sock, private_home / "work")
        served, late = late_imports(private_home)
    assert calls["done"]["state"] == "exited"
    assert calls["job"]["state"] == "running" and calls["stopped"]["ok"] is True
    assert calls["status"]["owner_instance_id"] == pong["owner_instance_id"]
    log = (private_home / "manager.log").read_text(errors="replace")
    assert "event=startup_import_error" not in log, log[-4000:]
    assert set(runtime_module_names()) <= set(served)  # eager, before serving
    assert late == [], log[-4000:]


def _main_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    main = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    calls = [node for node in ast.walk(main) if isinstance(node, ast.Call)]
    calls.sort(key=lambda node: (node.lineno, node.col_offset))  # source order
    return [ast.unparse(node.func) for node in calls]


@pytest.mark.parametrize(
    ("entry", "first", "serving"),
    [
        (
            "features/commands/job_manager.py",
            "get_settings",
            "JobManager(settings.jobs.socket_path).serve_forever",
        ),
        (
            "platform/darwin/job_manager_entry.py",
            "logging.basicConfig",
            "serve_job_manager",
        ),
    ],
)
def test_both_manager_entries_import_the_runtime_tree_before_serving(
    entry, first, serving
):
    calls = _main_calls(SRC / entry)
    assert calls.count("import_runtime_modules") == 1, calls
    where = calls.index("import_runtime_modules")
    assert where < calls.index(serving), calls
    if first == "logging.basicConfig":  # right after logging is configured
        assert calls[where - 1] == first, calls
    else:  # the first step of main(), before the settings and the socket
        assert where == 0 and calls[1] == first, calls


def test_darwin_entry_imports_right_after_logging_on_every_host(monkeypatch):
    order = []
    monkeypatch.setattr(logging, "basicConfig", lambda **_: order.append("logging"))
    monkeypatch.setattr(
        job_manager_entry, "import_runtime_modules", lambda: order.append("import")
    )
    monkeypatch.setattr(
        job_manager_entry, "inherited_fds_cloexec", lambda: order.append("cloexec")
    )

    def refuse_config():
        order.append("config")
        raise RuntimeError("e1b: stop before any lease")

    monkeypatch.setattr(job_manager_entry, "read_config", refuse_config)
    assert job_manager_entry.main([]) == job_manager_entry.EX_CONFIG
    assert order == ["logging", "import", "cloexec", "config"]
