"""R4 J4: Darwin command tools wired to the com.binnacle.jobs manager owner.

Supervisor ruling (4) b: the committed manager rows are AVAILABLE ahead of
J-CR. The manager-composed paths run here with explicit AVAILABLE rows and a
fake client that writes the J2 spool contract (meta.json + out.log).
"""

import asyncio
import json
import os
import platform
import subprocess
import threading
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
        self.down = False  # SD-41: the manager is unreachable while set
        # LATE jobs: persist the exit record only after this event is set.
        self.persist_late = threading.Event()
        self.late_persisted = threading.Event()

    def _write(self, job_id, meta):
        # Atomic like job_store.write_meta: a reader never sees a partial record.
        target = self.jobs_dir / job_id / "meta.json"
        partial = target.with_suffix(".tmp")
        partial.write_text(json.dumps(meta))
        os.replace(partial, target)

    def _persist_when_released(self, job_id, final):
        self.persist_late.wait()
        self._write(job_id, final)
        self.late_persisted.set()

    def start(self, socket_path, *, command, workdir, stdin, wait_seconds, call_id):
        job_id = f"{len(list(self.jobs_dir.iterdir())):012x}"
        directory = self.jobs_dir / job_id
        directory.mkdir()
        meta = {"schema_version": 2, "owner": "manager", "boot_id": "test-boot"}
        meta.update(owner_instance_id="test-incarnation", command=command, pid=4242)
        meta.update(workdir=str(workdir), pgid=4242, starttime=1)
        meta["started_at"] = time.time()
        if command.startswith("LATE"):  # reaped, record not yet persisted
            (directory / "out.log").write_bytes(b"late\n")
            self._write(job_id, meta)
            final = {**meta, "exit_code": 0, "signal": None, "ended_at": time.time()}
            final["termination_reason"] = "normal_exit"
            threading.Thread(
                target=self._persist_when_released, args=(job_id, final), daemon=True
            ).start()
            return {"ok": True, "job_id": job_id, "state": "unknown"}
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

    def ping(self, socket_path):
        if self.down:
            raise RuntimeError(f"{JOB_MANAGER_UNAVAILABLE} at {socket_path}: refused")
        return {"ok": True}

    def stop(self, socket_path, job_id, *, call_id="-"):
        self.ping(socket_path)
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
    from binnacle.application import manager_bindings

    settings, root = _settings(tmp_path)
    backend = cb.DarwinManagerCommandBackend(
        jobs_dir=settings.jobs.dir,
        socket_path=settings.jobs.socket_path,
        release_states=states,
        warmup_s=settings.jobs.warmup_s,
        max_output_chars=settings.jobs.max_output_chars,
        client=client or _SpoolClient(settings.jobs.dir),
        bindings=manager_bindings(),
    )
    return settings, root, backend


def _run(settings, root, backend, command, wait):
    return rc.run_command_impl(
        command, str(root), wait, False, None, roots=settings.roots, backend=backend
    )


def _tools(app):
    async def listing():
        async with Client(app) as client:
            return {tool.name: tool for tool in await client.list_tools()}

    return asyncio.run(listing())


def _o200k():
    from binnacle.observability.token_telemetry import _load_encoding

    return _load_encoding("o200k_base")  # the test_surface_tokens tokenizer


def _app(settings, backend):
    from binnacle.application import create_application

    return create_application(settings=settings, token="t", backend=backend)


@_DARWIN
def test_production_composes_manager_owner_and_fails_closed(tmp_path):
    from binnacle.application import (
        DARWIN_JOBS_DISCLOSURE,
        DARWIN_MANAGER_REQUIREMENT,
        _server_instructions,
        compose_native_tools,
    )

    settings, root = _settings(tmp_path)
    assert settings.jobs.owner == "auto"  # CR0 point 4: auto is manager on Darwin
    _, backend = compose_native_tools(settings=settings)
    assert isinstance(backend, cb.DarwinManagerCommandBackend)
    assert type(backend.client).__name__ == "DarwinJobClient"
    # Ruling (4) b: the committed manager rows are AVAILABLE ahead of J-CR.
    assert set(backend.release_states.values()) == {"AVAILABLE"}
    instructions = _server_instructions("manager")
    assert "com.binnacle.jobs" in instructions and len(instructions) <= 512
    assert DARWIN_MANAGER_REQUIREMENT in instructions
    assert "fail closed" in DARWIN_MANAGER_REQUIREMENT
    # STEER-04 2(a): one short D-1 sentence of at most 35 tokens (measured: 19).
    assert instructions.endswith(DARWIN_JOBS_DISCLOSURE)
    assert len(_o200k().encode(DARWIN_JOBS_DISCLOSURE)) <= 35
    app = _app(settings, backend)
    assert "com.binnacle.jobs" in app.instructions
    # The socket is never published: each manager call is the per-call error.
    with pytest.raises(ToolError, match=JOB_MANAGER_UNAVAILABLE):
        _run(settings, root, backend, "echo hi", 5)
    assert list(settings.jobs.dir.iterdir()) == []  # nothing ran locally
    js.job_status_impl(None, 10, backend=backend)  # spool read, no process
    running = _SpoolClient(settings.jobs.dir).start(
        None, command="RUNNING", workdir=root, stdin=None, wait_seconds=0, call_id="-"
    )["job_id"]
    with pytest.raises(ToolError, match=JOB_MANAGER_UNAVAILABLE):
        sj.stop_job_impl(running, backend=backend)


@_DARWIN
def test_explicit_embedded_owner_keeps_limited_composition(tmp_path):
    from binnacle.application import _DARWIN_INSTRUCTIONS, compose_native_tools

    settings, _ = _settings(tmp_path)
    settings.jobs.owner = "embedded"
    _, backend = compose_native_tools(settings=settings)
    assert backend.release_states["run_command"] == "LIMITED"
    with pytest.raises(ValueError, match="explicit owner"):  # RJ4-F4: no implicit owner
        compose_native_tools(settings=settings, release_scope={})
    assert _app(settings, backend).instructions == _DARWIN_INSTRUCTIONS


@_DARWIN
def test_unreachable_manager_is_the_linux_per_call_error(tmp_path):
    from binnacle.platform.composition import create_job_client

    settings, root, backend = _manager(tmp_path, client=create_job_client())
    with pytest.raises(ToolError, match=JOB_MANAGER_UNAVAILABLE):
        _run(settings, root, backend, "echo hi", 5)
    assert list(settings.jobs.dir.iterdir()) == []  # nothing ran locally


@_DARWIN
def test_manager_descriptions_are_byte_identical_to_linux(tmp_path):
    """STEER-04 (amended JCR-4): no description-level disclosure on Darwin."""
    settings, _, backend = _manager(tmp_path)
    darwin = _tools(_app(settings, backend))

    class _LinuxShape:  # the Linux tool path: a non-restricted backend
        owner_mode, warmup_s, max_output_chars = "manager", 1.0, 1000

    linux = _tools(_app(settings, _LinuxShape()))
    for name in ("run_command", "job_status", "stop_job"):
        assert darwin[name].description.encode() == linux[name].description.encode()
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
    result = _run(settings, root, backend, "seq 1 20000", 30)
    payload = result.structured_content
    assert payload["state"] == "exited" and payload["exit_code"] == 0
    assert payload["background_job"] is False
    assert payload["output"].rstrip().endswith("\n20000")
    assert payload["truncated"] is True
    assert "elided" in payload["output"]
    # STEER-04 2(b): the result text keeps the descendants disclosure.
    assert str(result.content).count("descendants_unverified=true") == 1
    assert "descendants_unverified" not in payload


@_DARWIN
def test_start_reply_state_is_not_final(tmp_path, monkeypatch):
    """R-J2-F4: a start reply of 'unknown' waits for the persisted record.

    Events order the steps: the exit record is persisted only after the
    backend has read the not-yet-final record, so no wall-clock race decides
    the result. The grace is only an upper bound for a broken backend.
    """
    monkeypatch.setattr(cb, "EXIT_RECORD_GRACE_S", 60.0)
    settings, root, backend = _manager(tmp_path)
    client, read_state = backend.client, backend.job_state
    reads_before_record: list[str] = []

    def job_state(job_id):
        state = read_state(job_id)
        if not client.late_persisted.is_set():
            reads_before_record.append(state["state"])
            client.persist_late.set()  # handshake: release the manager's write
        return state

    monkeypatch.setattr(backend, "job_state", job_state)
    payload = _run(settings, root, backend, "LATE exit", 5).structured_content
    assert reads_before_record[0] == "running"  # the reply state was not final
    assert client.late_persisted.is_set()
    assert payload["state"] == "exited" and payload["exit_code"] == 0
    assert payload["output"] == "late\n"


@_DARWIN
def test_mcp_side_never_constructs_a_job_manager(tmp_path, monkeypatch):
    """R-J2-F5: the one-writer guarantee lives only in serve_job_manager."""
    import ast

    from binnacle.application import compose_native_tools
    from binnacle.features.commands.commands_server import create_commands_server
    from binnacle.platform.darwin import job_manager_entry as entry
    from binnacle.platform.darwin import job_manager_service as jm

    def forbidden(*args, **kwargs):
        raise AssertionError("MCP composition touched the job manager")

    for name in ("__init__", "recover", "handle", "record_exit"):
        monkeypatch.setattr(jm.DarwinJobManager, name, forbidden)
    monkeypatch.setattr(entry, "serve_job_manager", forbidden)  # J2r home
    settings, _ = _settings(tmp_path)
    _, backend = compose_native_tools(settings=settings)
    app = _app(settings, backend)
    assert len(_tools(app)) == 8 and len(_tools(create_commands_server())) == 3
    src = Path(__file__).parents[3] / "src/binnacle"
    for path in (
        src / "application.py",
        src / "server.py",
        *src.glob("features/**/*.py"),
    ):
        names = {
            getattr(node, "id", None) or getattr(node, "attr", None)
            for node in ast.walk(ast.parse(path.read_text()))
        }
        assert not names & {"DarwinJobManager", "serve_job_manager"}, path


@_DARWIN
def test_owner_lost_job_renders_unknown_and_refuses_stop(tmp_path):
    settings, root, backend = _manager(tmp_path)
    started = _run(settings, root, backend, "RUNNING sleep", 1)
    job_id = started.structured_content["job_id"]
    assert started.structured_content["state"] == "running"
    backend.client.lose_owner(job_id)
    result = js.job_status_impl(job_id, 10, backend=backend)
    status = result.structured_content
    assert status["state"] == "unknown"  # D-1: never exited
    assert status["exit_code"] is None
    # RJ4-F1: the D-1 text replaces Linux's "process is gone"; never gone/exited.
    text = result.content[0].text
    assert text == f"Job {job_id} state unknown: owner lost; process not tracked."
    assert "gone" not in text and "exited" not in text
    assert status["note"] == cb.DARWIN_OWNER_LOST_NOTE
    state = backend.job_state(job_id)
    assert state["note"] == cb.DARWIN_OWNER_LOST_NOTE
    with pytest.raises(ToolError, match=OWNER_LOST_STOP_REFUSED):
        sj.stop_job_impl(job_id, backend=backend)
    assert backend.client.stops == []


@_DARWIN
def test_unreachable_manager_job_status_never_claims_running_or_exited(tmp_path):
    """SD-41: terminal records as they are; non-terminal ones unknown/unverified."""
    settings, root, backend = _manager(tmp_path)
    done = _run(settings, root, backend, "true", 5).structured_content["job_id"]
    job_id = _run(settings, root, backend, "RUNNING sleep", 1).structured_content[
        "job_id"
    ]
    backend.client.down = True
    final = js.job_status_impl(done, 10, backend=backend).structured_content
    assert (final["state"], final["exit_code"]) == ("exited", 0)  # served as is
    for wait in (0, 5):  # a wait never blocks on an unverifiable record
        result = js.job_status_impl(job_id, 10, wait, backend=backend)
        text, status = result.content[0].text, result.structured_content
        assert (
            text == f"Job {job_id} state unknown: {cb.DARWIN_MANAGER_UNAVAILABLE_NOTE}."
        )
        assert not {"gone", "running", "exited"} & set(text.replace(".", " ").split())
        assert status["state"] == "unknown" and status["exit_code"] is None
        assert status["note"] == "job manager unavailable; state unverified"
    rows = js.job_status_impl(None, 10, backend=backend).structured_content["jobs"]
    assert {r["job_id"]: r["state"] for r in rows} == {
        done: "exited",
        job_id: "unknown",
    }
    with pytest.raises(ToolError, match=JOB_MANAGER_UNAVAILABLE):
        sj.stop_job_impl(job_id, backend=backend)  # the Linux per-call error
    backend.client.down = False  # reachable again: a reply rendered unknown stays so
    linux_unknown = cb.CommandReply("its process is gone", {"state": "unknown"})
    assert "gone" not in backend.disclose_status(job_id, linux_unknown).summary
    assert (
        js.job_status_impl(job_id, 10, backend=backend).structured_content["state"]
        == "running"
    )


@_DARWIN
def test_d2_sampled_resources_are_marked_in_job_status(tmp_path):
    """STEER-04 2(b): D-2 appears where resource values occur, as sampled."""
    settings, root, backend = _manager(tmp_path)
    job_id = _run(settings, root, backend, "true", 5).structured_content["job_id"]
    plain = js.job_status_impl(job_id, 10, backend=backend)
    assert "resource_usage" not in plain.structured_content
    assert "sampled" not in str(plain.content)
    meta_path = settings.jobs.dir / job_id / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["resource_usage"] = {"cpu_s": 0.01, "max_rss_bytes": 1024}
    backend.client._write(job_id, meta)
    result = js.job_status_impl(job_id, 10, backend=backend)
    usage = result.structured_content["resource_usage"]
    assert usage == {"cpu_s": 0.01, "max_rss_bytes": 1024, "accounting": "sampled"}
    assert "Resource usage is sampled." in str(result.content)


def test_every_production_owner_call_site_passes_owner():
    """CR0-1.2.0 point 2: no production call relies on an owner default."""
    import ast
    import inspect

    from binnacle.platform import composition

    names = {"validate_native_command_states", "native_file_capability"}
    names.add("create_foreground_execution")
    for name in names:  # RJ4-F2: owner is keyword-only and has no default
        owner = inspect.signature(getattr(composition, name)).parameters["owner"]
        assert (owner.kind, owner.default) == (owner.KEYWORD_ONLY, owner.empty), name
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
