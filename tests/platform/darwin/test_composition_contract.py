"""Native composition must import without Linux engines and refuse unreviewed tools."""

import os
import subprocess
import sys


def test_native_server_import_has_no_linux_engine(tmp_path):
    token = tmp_path / "token"
    token.write_text("test-token")
    config = tmp_path / "config.toml"
    config.write_text(f'[auth]\ntoken_file = "{token}"\n')
    script = """
import platform
platform.system = lambda: "Darwin"
import sys
import binnacle.server
assert not any(m.startswith("binnacle.platform.linux") for m in sys.modules)
assert "binnacle.features.commands.jobs" not in sys.modules
import asyncio
from fastmcp import Client
from tests.contracts.surface_support import digest, surface
from tests.contracts.test_tool_surface import SURFACE_SHA256
async def check():
    calls = {
        "read_file": {"path": "/untrusted"},
        "list_files": {"path": "/untrusted"},
        "write_file": {"path": "/untrusted", "content": "x"},
        "edit_file": {"path": "/untrusted", "old_string": "x", "new_string": "y"},
        "search_text": {"path": "/untrusted", "pattern": "x"},
        "run_command": {"command": "echo forbidden", "workdir": "/untrusted"},
        "job_status": {}, "stop_job": {"job_id": "unknown"},
    }
    async with Client(binnacle.server.mcp) as client:
        listed = await client.list_tools()
        import json
        from pathlib import Path
        original = json.loads(Path("docs/os-independent-stage1-evidence/os0-raw-mcp-surface.json").read_text())
        old_run = next(t for t in original["profile_surfaces"]["default"]["tools"] if t["name"] == "run_command")
        normalized = [t.model_copy(update={"description": old_run["description"]}) if t.name == "run_command" else t for t in listed]
        assert {t.name: digest(surface(t)) for t in normalized} == SURFACE_SHA256["default"]
        for name, arguments in calls.items():
            result = await client.call_tool(name, arguments, raise_on_error=False)
            assert result.is_error, name
            assert "UNAVAILABLE" in str(result.content), (name, result)
asyncio.run(check())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "BINNACLE_CONFIG_FILE": str(config)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_unreviewed_command_refuses_before_workdir_access(tmp_path, monkeypatch):
    import pytest

    from binnacle.features.commands.restricted_backend import RestrictedCommandBackend
    from binnacle.features.commands.tools import run_command

    def forbidden(*args, **kwargs):
        raise AssertionError("disabled command inspected workdir")

    monkeypatch.setattr(run_command, "resolve_path", forbidden)
    with pytest.raises(Exception, match="native_capability_unavailable"):
        run_command.run_command_impl(
            "echo unexpected",
            "/untrusted",
            1,
            False,
            None,
            backend=RestrictedCommandBackend(),
        )


def test_native_factories_keep_scope_and_generation(tmp_path, monkeypatch):
    from binnacle.platform import composition
    from binnacle.platform.contracts.capability_contracts import CapabilityState

    monkeypatch.setattr(composition.platform, "system", lambda: "Darwin")
    files_factory = getattr(composition, "create_file_access", None)
    assert files_factory is not None, "native Files factory is missing"
    files = files_factory()
    try:
        assert composition.create_search_access(files=files, rg_bin="rg") is not None
    finally:
        files.close()
    accounting = composition.create_resource_accounting()
    values = accounting.snapshot_scoped("missing-reaper-record")
    assert values["job.cpu.usage_usec"].value is None
    assert values["job.cpu.usage_usec"].capability.state == CapabilityState.UNAVAILABLE
    assert (
        values["direct_child.cpu.user_usec"].capability.state == CapabilityState.UNKNOWN
    )
    source = composition.create_service_log_source(
        root=tmp_path, generation="generation-123456"
    )
    writer = composition.create_service_log_writer(
        root=tmp_path,
        generation="generation-123456",
        service="probe",
        redact_values=("secret-value",),
    )
    writer.start()
    try:
        writer.write("message secret-value\n")
    finally:
        writer.close()
    batch = source.read_cursor("probe", None, max_bytes=4096, max_lines=10)
    assert b"message [redacted]" in batch.data
    assert b"secret-value" not in batch.data
    assert batch.capability.state == CapabilityState.LIMITED
    persisted = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert persisted
    assert all(b"secret-value" not in p.read_bytes() for p in persisted)


def test_provisioner_maps_frozen_types_and_refuses_incompatible_launch_plan(
    tmp_path, monkeypatch
):
    import tempfile
    from pathlib import Path

    import pytest

    from binnacle.platform import composition
    from binnacle.platform.contracts.capability_contracts import CapabilityUnavailable
    from binnacle.platform.contracts.native_service_contracts import ServicePlan

    monkeypatch.setattr(composition.platform, "system", lambda: "Darwin")
    factory = getattr(composition, "create_native_provisioner", None)
    assert factory is not None, "A6 type mapping is missing"
    with tempfile.TemporaryDirectory(prefix="b0p-", dir="/private/tmp") as directory:
        root = Path(directory)
        lease = composition.create_service_lease(
            root=root, label="com.binnacle.r3test.b0", generation="b0-generation-123456"
        )
        provisioner = factory(root=root, lease=lease)
        plan = provisioner.plan(
            lease, argv=["/usr/bin/true"], environment={}, workdir=root
        )
        assert isinstance(plan, ServicePlan)
        assert plan.lease == lease
        with pytest.raises(
            CapabilityUnavailable, match="darwin_service_handoff_incomplete"
        ):
            provisioner.apply(plan)
        assert not plan.plist_path.exists()


def test_composed_authenticated_channel_preserves_payload_and_generation(monkeypatch):
    import dataclasses
    import tempfile
    import threading
    import time
    from pathlib import Path

    import pytest

    from binnacle.platform import composition
    from binnacle.platform.contracts.capability_contracts import NativeCapabilityError

    if sys.platform != "darwin":
        pytest.skip("Real Darwin getpeereid and LOCAL_PEERPID")
    monkeypatch.setattr(composition.platform, "system", lambda: "Darwin")
    with tempfile.TemporaryDirectory(prefix="b0i-", dir="/private/tmp") as directory:
        root = Path(directory)
        lease = composition.create_service_lease(
            root=root,
            label="com.binnacle.r3test.b0ipc",
            generation="generation-b0-123456",
        )
        stop = threading.Event()
        received, failures = [], []

        def handler(payload):
            received.append(dict(payload))
            if payload.get("protocol") == "binnacle-darwin-witness-v1":
                return {
                    **payload,
                    "enrolled": payload.get("generation")
                    == {
                        "manager_epoch": lease.generation,
                        "witness_epoch": "test-enrollment-epoch",
                        "job_id": "test-observation-only",
                    },
                }
            return {"ok": True, "echo": dict(payload)}

        def serve():
            try:
                composition.serve_native_channel(
                    socket_path=root / "jobs.sock",
                    lease=lease,
                    handler=handler,
                    stop=stop,
                )
            except (OSError, NativeCapabilityError) as exc:
                failures.append(exc)

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    channel = composition.connect_native_channel(
                        socket_path=root / "jobs.sock", lease=lease, timeout_s=0.2
                    )
                    break
                except NativeCapabilityError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.02)
            try:
                payload = {"version": 1, "op": "ping", "unchanged": [1, "value"]}
                reply = channel.request(payload, timeout_s=1)
                assert reply["echo"] == payload
                assert received == [payload]
                from binnacle.platform.contracts.capability_contracts import (
                    CapabilityState,
                )
                from binnacle.platform.contracts.darwin_contracts import OwnerGeneration

                factory = getattr(composition, "create_owned_witness", None)
                assert factory is not None, "A2/A3 witness composition is missing"
                generation = OwnerGeneration(
                    lease.generation, "test-enrollment-epoch", "test-observation-only"
                )
                witness = factory(channel=channel, generation=generation)
                process = composition.create_process_backend(witness=witness)
                observation = process.authority("test-observation-only")
                assert observation.capability.state == CapabilityState.LIMITED
                assert observation.generation == generation
                assert not observation.can_signal and not observation.membership_closed
                witness.close()
                assert (
                    process.authority("test-observation-only").capability.state
                    == CapabilityState.UNKNOWN
                )
            finally:
                channel.close()
            wrong = dataclasses.replace(lease, generation="other-generation-123456")
            with pytest.raises(NativeCapabilityError):
                composition.connect_native_channel(
                    socket_path=root / "jobs.sock", lease=wrong, timeout_s=0.5
                )
        finally:
            stop.set()
            thread.join(5)
        assert not thread.is_alive()
        assert not failures
        assert not (root / "jobs.sock").exists()
        assert not (root / "jobs.sock.auth").exists()


def test_foreground_bridge_runs_off_loop_and_forwards_cancellation(tmp_path):
    import asyncio
    import threading

    from binnacle.features.commands import command_execution
    from binnacle.platform.contracts.darwin_contracts import ForegroundRequest

    started, cancelled = threading.Event(), threading.Event()
    thread_ids = []

    class Execution:
        def run_foreground(self, request, *, cancel):
            thread_ids.append(threading.get_ident())
            started.set()
            if cancel.wait(1):
                cancelled.set()
            raise RuntimeError("test worker finished")

    bridge = getattr(command_execution, "run_foreground_async", None)
    assert bridge is not None, "foreground thread/cancellation bridge missing"
    request = ForegroundRequest("test", tmp_path, None, 1, False, 1, 100)

    async def exercise():
        task = asyncio.create_task(bridge(Execution(), request))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        assert thread_ids == [thread_ids[0]] and thread_ids[0] != threading.get_ident()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        for _ in range(100):
            if cancelled.is_set():
                break
            await asyncio.sleep(0.005)
        assert cancelled.is_set(), "request cancellation did not reach A2 Event"

    asyncio.run(exercise())


def test_darwin_command_description_states_foreground_limits():
    import asyncio

    from binnacle.features.commands.commands_server import create_commands_server
    from binnacle.features.commands.restricted_backend import RestrictedCommandBackend

    root = create_commands_server(backend=RestrictedCommandBackend())
    tool = next(t for t in asyncio.run(root.list_tools()) if t.name == "run_command")
    description = tool.description.lower()
    assert (
        "background processes are terminated when the command finishes" in description
    )
    assert "processes that start a new session (setsid) are not tracked" in description
    assert "unavailable" in description


def test_native_mcp_foreground_uses_worker_and_cancels_owned_event(tmp_path):
    import asyncio
    import threading

    from fastmcp import Client

    from binnacle.config import RootsSettings, RunCommandSettings
    from binnacle.features.commands.commands_server import create_commands_server
    from binnacle.features.commands.restricted_backend import RestrictedCommandBackend
    from binnacle.platform.contracts.darwin_contracts import ForegroundResult

    started, cancelled = threading.Event(), threading.Event()
    worker_threads = []

    class Execution:
        def run_foreground(self, request, *, cancel):
            worker_threads.append(threading.get_ident())
            if request.command == "cancel":
                started.set()
                if cancel.wait(2):
                    cancelled.set()
            return ForegroundResult(
                "execution", "generation", 0, None, b"ok", 2, False, 0.01, True
            )

    class HarnessBackend(RestrictedCommandBackend):
        max_output_chars = 1024

        def require_available(self):
            # Harness-only dependency injection, never product enablement.
            return None

    root = create_commands_server(
        roots=RootsSettings(default_root=tmp_path, extra_roots=()),
        run_settings=RunCommandSettings(),
        backend=HarnessBackend(foreground_execution=Execution()),
    )

    async def exercise():
        async with Client(root) as client:
            result = await client.call_tool(
                "run_command", {"command": "complete", "workdir": str(tmp_path)}
            )
            assert result.structured_content["output"] == "ok"
            assert result.structured_content["state"] == "exited"
            task = asyncio.create_task(
                client.call_tool(
                    "run_command", {"command": "cancel", "workdir": str(tmp_path)}
                )
            )
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.005)
            assert started.is_set()
            assert all(t != threading.get_ident() for t in worker_threads)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            for _ in range(100):
                if cancelled.is_set():
                    break
                await asyncio.sleep(0.005)
            assert cancelled.is_set()

    asyncio.run(exercise())


def test_owned_reaper_metrics_wiring_and_no_competing_async_waiter(tmp_path):
    """R1P-A2-05: real MCP worker + native owner; all child waits are PID-specific."""
    import pytest

    if sys.platform != "darwin":
        pytest.skip("Real Darwin owned-child process and stdlib event-loop contract")
    script = """
import asyncio, dataclasses, os, signal, sys, threading
from pathlib import Path
waited = []
for name in ("waitpid", "wait4"):
    original = getattr(os, name)
    def guarded(pid, options, _original=original):
        assert pid > 0, "foreign wildcard waiter"
        waited.append(pid)
        return _original(pid, options)
    setattr(os, name, guarded)
original_signal = signal.signal
def reserve(sig, handler):
    assert sig != signal.SIGCHLD, "foreign SIGCHLD watcher"
    return original_signal(sig, handler)
signal.signal = reserve
from fastmcp import Client
from binnacle.application import compose_native_tools, create_application
from binnacle.config import Settings, RootsSettings
from binnacle.platform import composition as c
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.contracts.darwin_release_scope import DARWIN_RELEASE_SCOPE
from binnacle.platform.darwin.process_backend import DarwinProcessBackend, _ForegroundRunner
# Test-only substitution at the PUBLIC observer seam. Production stays disabled.
DarwinProcessBackend.run_foreground = _ForegroundRunner(5, 5).run_foreground
settings = Settings(roots=RootsSettings(default_root=Path(sys.argv[1]), extra_roots=()))
settings.run_command.wait_max_s = 5
scope = dict(DARWIN_RELEASE_SCOPE)
scope["run_command"] = dataclasses.replace(scope["run_command"], capability=Capability(CapabilityState.LIMITED, "test_only", "foreground"))
access, backend = compose_native_tools(settings=settings, release_scope=scope)
backend.max_output_chars = 1024
app = create_application(settings=settings, token="test", backend=backend, file_access=access)
async def exercise():
    async with Client(app) as client:
        result = await client.call_tool("run_command", {"command": "printf ok", "workdir": sys.argv[1], "wait_seconds": 5})
        data = result.structured_content
        assert data["output"] == "ok" and data["exit_code"] == 0
        metrics = backend.foreground_execution.execution.accounting.snapshot_scoped(data["job_id"])
        assert metrics["direct_child.cpu.user_usec"].final
        assert metrics["direct_child.cpu.user_usec"].capability.state == CapabilityState.LIMITED
        assert metrics["job.cpu.usage_usec"].value is None
        assert signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL
        timeout = await client.call_tool("run_command", {"command": "trap '' TERM; while :; do sleep 0.05; done", "workdir": sys.argv[1], "wait_seconds": 1}, raise_on_error=False)
        assert timeout.is_error and "darwin_background_jobs_unavailable" in str(timeout.content)
asyncio.run(exercise())
assert waited and len(set(waited)) == 2
assert signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_cli_preserves_linux_loop_and_reserves_darwin_sigchld(monkeypatch):
    from binnacle import cli
    from binnacle.platform import composition

    called = []
    monkeypatch.delenv("BINNACLE_SERVICE_ROLE", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: called.append(kwargs))
    for host, loop in (("Darwin", "asyncio"), ("Linux", "uvloop")):
        monkeypatch.setattr(composition.platform, "system", lambda host=host: host)
        cli.serve()
        assert called[-1]["loop"] == loop
        assert called[-1]["http"] == "httptools"
