"""R4 J4: Darwin command tools wired to the com.binnacle.jobs manager owner.

The manager rows stay UNAVAILABLE in the committed scope until J-CR, so the
manager-composed paths run here with test-only AVAILABLE rows and a fake
client that writes the J2 spool contract (meta.json + out.log).
"""

import asyncio
import inspect
import json
import platform
import subprocess
import time
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings, Settings
from binnacle.features.commands import command_backend as cb
from binnacle.features.commands.tools import job_status as js
from binnacle.features.commands.tools import run_command as rc
from binnacle.features.commands.tools import stop_job as sj
from binnacle.platform.contracts.process_contracts import (
    JOB_MANAGER_UNAVAILABLE,
    OWNER_LOST_STOP_REFUSED,
)

_DARWIN = pytest.mark.skipif(
    platform.system() != "Darwin", reason="native Darwin composition"
)

AVAILABLE = dict.fromkeys(("run_command", "job_status", "stop_job"), "AVAILABLE")


class _SpoolClient:
    """Stand-in for DarwinJobClient that honours the J2 spool contract."""

    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir
        self.stops: list[str] = []

    def _write(self, job_id, meta):
        (self.jobs_dir / job_id / "meta.json").write_text(json.dumps(meta))

    def start(self, socket_path, *, command, workdir, stdin, wait_seconds, call_id):
        job_id = f"{len(list(self.jobs_dir.iterdir())):012x}"
        directory = self.jobs_dir / job_id
        directory.mkdir()
        meta = {
            "schema_version": 2,
            "owner": "manager",
            "owner_instance_id": "test-incarnation",
            "boot_id": "test-boot",
            "command": command,
            "workdir": str(workdir),
            "pid": 4242,
            "pgid": 4242,
            "starttime": 1,
            "started_at": time.time(),
        }
        if command.startswith("RUNNING"):
            (directory / "out.log").write_bytes(b"partial\n")
            self._write(job_id, meta)
            return {"ok": True, "job_id": job_id, "state": "running"}
        with open(directory / "out.log", "wb") as out:
            done = subprocess.run(
                ["/bin/sh", "-c", command],
                cwd=workdir,
                stdout=out,
                stderr=out,
                check=False,
            )
        meta.update(exit_code=done.returncode, signal=None, ended_at=time.time())
        meta["termination_reason"] = "normal_exit"
        self._write(job_id, meta)
        return {"ok": True, "job_id": job_id, "state": "exited"}

    def stop(self, socket_path, job_id, *, call_id="-"):
        self.stops.append(job_id)
        meta = json.loads((self.jobs_dir / job_id / "meta.json").read_text())
        meta.update(exit_code=None, signal=15, ended_at=time.time())
        meta["termination_reason"] = "stop_requested"
        self._write(job_id, meta)
        return {"ok": True, "job_id": job_id, "state": "exited"}

    def lose_owner(self, job_id):
        meta = json.loads((self.jobs_dir / job_id / "meta.json").read_text())
        meta.update(authority="UNKNOWN", exit_code=None, signal=None)
        meta.update(ended_at=time.time(), termination_reason="owner_restart")
        self._write(job_id, meta)


def _settings(tmp_path):
    root = (tmp_path / "root").resolve()
    root.mkdir(exist_ok=True)
    settings = Settings(roots=RootsSettings(default_root=root))
    settings.jobs.dir = tmp_path / "jobs"
    settings.jobs.dir.mkdir(exist_ok=True)
    settings.jobs.socket_path = tmp_path / "jobs.sock"
    return settings, root


def _manager(tmp_path, states=AVAILABLE, client=None):
    settings, root = _settings(tmp_path)
    backend = cb.DarwinManagerCommandBackend(
        jobs_dir=settings.jobs.dir,
        socket_path=settings.jobs.socket_path,
        release_states=states,
        warmup_s=settings.jobs.warmup_s,
        max_output_chars=settings.jobs.max_output_chars,
        client=client or _SpoolClient(settings.jobs.dir),
    )
    return settings, root, backend


def _tools(app):
    async def listing():
        async with Client(app) as client:
            return {tool.name: tool for tool in await client.list_tools()}

    return asyncio.run(listing())


def _app(settings, backend):
    from binnacle.application import create_application

    return create_application(settings=settings, token="t", backend=backend)


@_DARWIN
def test_production_composes_manager_owner_and_fails_closed(tmp_path):
    from binnacle.application import (
        DARWIN_MANAGER_REQUIREMENT,
        _server_instructions,
        compose_native_tools,
    )

    settings, root = _settings(tmp_path)
    assert settings.jobs.owner == "auto"  # CR0 point 4: auto is manager on Darwin
    _, backend = compose_native_tools(settings=settings)
    assert isinstance(backend, cb.DarwinManagerCommandBackend)
    # The committed rows stay UNAVAILABLE until J-CR; no embedded fallback.
    assert set(backend.release_states.values()) == {"UNAVAILABLE"}
    assert "com.binnacle.jobs" in _server_instructions("manager")
    assert DARWIN_MANAGER_REQUIREMENT in _server_instructions("manager")
    assert "fail closed" in DARWIN_MANAGER_REQUIREMENT
    app = _app(settings, backend)
    assert "com.binnacle.jobs" in app.instructions
    with pytest.raises(ToolError, match="no embedded fallback"):
        rc.run_command_impl(
            "echo hi", str(root), 5, False, None, roots=settings.roots, backend=backend
        )
    with pytest.raises(ToolError, match="no embedded fallback"):
        js.job_status_impl(None, 10, backend=backend)
    with pytest.raises(ToolError, match="no embedded fallback"):
        sj.stop_job_impl("000000000000", backend=backend)


@_DARWIN
def test_explicit_embedded_owner_keeps_limited_composition(tmp_path):
    from binnacle.application import _DARWIN_INSTRUCTIONS, compose_native_tools

    settings, _ = _settings(tmp_path)
    settings.jobs.owner = "embedded"
    _, backend = compose_native_tools(settings=settings)
    assert backend.release_states["run_command"] == "LIMITED"
    assert _app(settings, backend).instructions == _DARWIN_INSTRUCTIONS


@_DARWIN
def test_unreachable_manager_is_the_linux_per_call_error(tmp_path):
    from binnacle.platform.darwin.job_manager_service import DarwinJobClient

    settings, root, backend = _manager(tmp_path, client=DarwinJobClient())
    with pytest.raises(ToolError, match=JOB_MANAGER_UNAVAILABLE):
        rc.run_command_impl(
            "echo hi", str(root), 5, False, None, roots=settings.roots, backend=backend
        )
    assert list(settings.jobs.dir.iterdir()) == []  # nothing ran locally


@_DARWIN
def test_manager_descriptions_are_linux_text_plus_disclosures(tmp_path):
    from binnacle.platform.contracts.darwin_release_scope import MANAGER_DISCLOSURES

    settings, _, backend = _manager(tmp_path)
    assert cb.DARWIN_COMMAND_DISCLOSURE == (
        "macOS differences: " + "; ".join(MANAGER_DISCLOSURES) + "."
    )
    darwin = _tools(_app(settings, backend))

    class _LinuxShape:  # the Linux tool path: a non-restricted backend
        owner_mode, warmup_s, max_output_chars = "manager", 1.0, 1000

    linux = _tools(_app(settings, _LinuxShape()))
    for name in ("run_command", "job_status", "stop_job"):
        expected = inspect.cleandoc(linux[name].description)
        assert darwin[name].description == (
            expected + "\n\n" + cb.DARWIN_COMMAND_DISCLOSURE
        )
        assert darwin[name].input_schema == linux[name].input_schema
        assert darwin[name].output_schema == linux[name].output_schema


@_DARWIN
def test_embedded_limited_text_does_not_advertise_refused_jobs(tmp_path):
    from binnacle.application import compose_native_tools

    settings, _ = _settings(tmp_path)
    settings.jobs.owner = "embedded"
    _, backend = compose_native_tools(settings=settings)
    tools = _tools(_app(settings, backend))
    run = tools["run_command"]
    assert run.description.startswith("Foreground only on macOS")
    props = run.input_schema["properties"]
    assert "refused" in props["background"]["description"]
    assert "job_id" not in props["background"]["description"]
    assert "job_id" not in props["wait_seconds"]["description"]
    assert "Unavailable on macOS" in tools["stop_job"].description


@_DARWIN
def test_large_output_returns_the_true_tail(tmp_path):
    """PARITY-INVENTORY high gap: seq 1 20000 must end at 20000 like Linux."""
    settings, root, backend = _manager(tmp_path)
    result = rc.run_command_impl(
        "seq 1 20000", str(root), 30, False, None, roots=settings.roots, backend=backend
    )
    payload = result.structured_content
    assert payload["state"] == "exited" and payload["exit_code"] == 0
    assert payload["output"].rstrip().endswith("\n20000")
    assert payload["truncated"] is True
    assert "elided" in payload["output"]


@_DARWIN
def test_owner_lost_job_renders_unknown_and_refuses_stop(tmp_path):
    settings, root, backend = _manager(tmp_path)
    started = rc.run_command_impl(
        "RUNNING sleep",
        str(root),
        1,
        False,
        None,
        roots=settings.roots,
        backend=backend,
    )
    job_id = started.structured_content["job_id"]
    assert started.structured_content["state"] == "running"
    backend.client.lose_owner(job_id)
    status = js.job_status_impl(job_id, 10, backend=backend).structured_content
    assert status["state"] == "unknown"  # D-1: never exited
    assert status["exit_code"] is None
    state = backend.job_state(job_id)
    assert state["note"] == cb.DARWIN_OWNER_LOST_NOTE
    with pytest.raises(ToolError, match=OWNER_LOST_STOP_REFUSED):
        sj.stop_job_impl(job_id, backend=backend)
    assert backend.client.stops == []


@_DARWIN
def test_stop_goes_to_the_manager_and_returns_the_spooled_state(tmp_path):
    settings, root, backend = _manager(tmp_path)
    job_id = rc.run_command_impl(
        "RUNNING sleep",
        str(root),
        1,
        False,
        None,
        roots=settings.roots,
        backend=backend,
    ).structured_content["job_id"]
    stopped = sj.stop_job_impl(job_id, backend=backend).structured_content
    assert backend.client.stops == [job_id]
    assert stopped["state"] == "exited" and stopped["signal"] == 15


@_DARWIN
def test_mcp_restart_keeps_the_job_with_the_manager(tmp_path):
    """No MCP-held job state: a fresh server generation reads the same job.

    The end-to-end restart against a launchd com.binnacle.jobs is J5's E2E.
    """
    settings, root, backend = _manager(tmp_path)
    first = _app(settings, backend)
    job_id = rc.run_command_impl(
        "RUNNING sleep",
        str(root),
        1,
        False,
        None,
        roots=settings.roots,
        backend=backend,
    ).structured_content["job_id"]
    del first
    _, _, again = _manager(tmp_path, client=backend.client)
    _app(settings, again)
    assert again.job_state(job_id)["state"] == "running"
    backend.client.stop(None, job_id)
    final = js.job_status_impl(job_id, 10, backend=again).structured_content
    assert final["state"] == "exited" and final["job_id"] == job_id
    assert again.job_processes(job_id) == []  # no pid adoption in the server


def test_every_production_owner_call_site_passes_owner():
    """CR0-1.2.0 point 2: no production call relies on an owner default."""
    import ast

    names = {
        "validate_native_command_states",
        "native_file_capability",
        "create_foreground_execution",
    }
    src = Path(__file__).parents[3] / "src/binnacle"
    calls = []
    for path in sorted(src.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in names:
                keywords = {k.arg for k in node.keywords}
                calls.append((path.name, node.lineno, name, "owner" in keywords))
    assert {c[0] for c in calls} >= {"application.py", "composition.py"}
    missing = [c[:3] for c in calls if not c[3]]
    assert missing == [], f"production call sites omit owner=: {missing}"
