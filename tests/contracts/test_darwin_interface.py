"""Reviewed Darwin descriptions and release scope preserve all eight schemas."""

import asyncio
import json
import platform
from pathlib import Path

import pytest
from fastmcp import Client

from binnacle.application import create_application
from binnacle.config import RootsSettings, Settings
from binnacle.features.commands.restricted_backend import RestrictedCommandBackend
from binnacle.features.files import paths
from binnacle.features.files.paths import FileToolAccess
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState


def test_native_wire_schema_preserves_v101_with_declared_description_exception(
    tmp_path,
):
    baseline = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/os-independent-stage1-evidence/os0-raw-mcp-surface.json"
        ).read_text()
    )["profile_surfaces"]["default"]
    settings = Settings(roots=RootsSettings(default_root=tmp_path, extra_roots=()))
    root = create_application(
        settings=settings,
        token="test",
        backend=RestrictedCommandBackend(),
        file_access=FileToolAccess(
            roots=settings.roots,
            files=None,
            search=None,
            generation="schema",
            capability=Capability(CapabilityState.UNAVAILABLE, "test", "schema"),
        ),
    )

    async def inspect():
        async with Client(root) as client:
            return await client.list_tools(), client.instructions

    tools, instructions = asyncio.run(inspect())
    actual = [tool.model_dump(mode="json", by_alias=True) for tool in tools]
    if platform.system() == "Darwin":
        assert "Raspberry Pi" not in instructions and "vcgencmd" not in instructions
        assert "stop_job is unavailable" in instructions
        assert "jobs for job_status/stop_job" not in instructions
    else:
        assert instructions == baseline["instructions"]
    assert len(actual) == 8
    native = next(tool for tool in actual if tool["name"] == "run_command")
    description = native["description"].lower()
    assert (
        "background processes are terminated when the command finishes" in description
    )
    assert "processes that start a new session (setsid) are not tracked" in description
    assert "new sessions/process groups are not tracked or terminated" in description
    assert "foreground execution is unavailable on macos" in description
    assert "descendants_unverified=true" in description
    original = next(tool for tool in baseline["tools"] if tool["name"] == "run_command")
    native["description"] = original["description"]
    for name, needle in (
        ("stop_job", "unavailable on macos"),
        ("job_status", "lost on restart"),
    ):
        declared = next(tool for tool in actual if tool["name"] == name)
        assert needle in declared["description"].lower()
        assert "sigterm" not in declared["description"].lower()
        declared["description"] = next(
            tool["description"] for tool in baseline["tools"] if tool["name"] == name
        )
    search = next(tool for tool in actual if tool["name"] == "search_text")
    assert "per-file size limit: 16 MiB (16,777,216 bytes)" in search["description"]
    assert "remaining aggregate 16 MiB input budget" in search["description"]
    search["description"] = next(
        tool["description"]
        for tool in baseline["tools"]
        if tool["name"] == "search_text"
    )
    assert actual == baseline["tools"]


def test_release_scope_requires_review_and_production_cannot_override():
    import ast

    from binnacle.platform.contracts.capability_contracts import CapabilityState
    from binnacle.platform.contracts.darwin_release_scope import DARWIN_RELEASE_SCOPE

    assert set(DARWIN_RELEASE_SCOPE) == {
        "read_file",
        "list_files",
        "search_text",
        "edit_file",
        "write_file",
        "run_command",
        "job_status",
        "stop_job",
    }
    approved = {
        "read_file",
        "edit_file",
        "write_file",
        "run_command",
        "job_status",
        "list_files",
        "search_text",
    }
    enabled = {
        tool
        for tool, row in DARWIN_RELEASE_SCOPE.items()
        if row.capability.state == CapabilityState.LIMITED
    }
    assert enabled == approved
    for tool, row in DARWIN_RELEASE_SCOPE.items():
        assert row.capability.state in (
            CapabilityState.UNAVAILABLE,
            CapabilityState.LIMITED,
        )
        assert row.decision_target == (
            "unavailable" if tool == "stop_job" else "limited"
        )
        if tool in enabled:
            verdict = (
                "CR1A-SUPERVISOR-REVIEW.json"
                if tool in ("run_command", "job_status")
                else "CR2-SUPERVISOR-REVIEW-PART2.json"
                if tool in ("list_files", "search_text")
                else "CR2-SUPERVISOR-REVIEW-PART1.json"
            )
            assert verdict in row.decision_reference
            assert (
                "38e330e" if tool in ("list_files", "search_text") else "fd7343b"
            ) in row.decision_reference
            assert (
                "0e23f99"
                if tool in ("run_command", "job_status")
                else "38e330e"
                if tool in ("list_files", "search_text")
                else "ad5f22f"
            ) in row.decision_reference
        else:
            assert (
                row.decision_reference
                == f"CAPABILITY-DECISION.json#/scope_decision/tool_by_tool/{tool}"
            )
        assert row.enabling_gate == (
            "never"
            if tool == "stop_job"
            else "CR1a"
            if tool in ("run_command", "job_status")
            else "CR2"
        )
    source = Path(__file__).resolve().parents[2] / "src/binnacle"
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                supplied = [kw for kw in node.keywords if kw.arg == "release_scope"]
                if supplied:
                    # Only internal propagation of the keyword-only test seam.
                    assert path == source / "application.py"
                    assert isinstance(node.func, ast.Name)
                    assert node.func.id == "native_file_capability"
                    assert isinstance(supplied[0].value, ast.Name)
                    assert supplied[0].value.id == "release_scope"


def test_composed_source_has_no_foreign_wildcard_reaper_or_sigchld_watcher():
    import ast

    source = Path(__file__).resolve().parents[2] / "src/binnacle"
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = ast.unparse(node.func)
            assert not name.endswith((".wait", ".wait3")) or name not in (
                "os.wait",
                "os.wait3",
            )
            if name in ("os.waitpid", "os.wait4", "os.waitid"):
                assert path == source / "platform/darwin/process_authority.py"
                assert name == "os.wait4" and ast.unparse(node.args[0]) == "self._pid"
            if name.endswith((".signal", ".add_signal_handler")):
                assert not any("SIGCHLD" in ast.unparse(arg) for arg in node.args)
            assert not name.endswith(
                ("MultiLoopChildWatcher", "FastChildWatcher", "SafeChildWatcher")
            )


def test_linux_file_lookup_skips_only_darwin_runtime_requirement(monkeypatch):
    from dataclasses import replace

    from binnacle.platform import composition
    from binnacle.platform.contracts.darwin_release_scope import DARWIN_RELEASE_SCOPE
    from binnacle.platform.darwin.process_backend import DarwinProcessBackend

    monkeypatch.setattr(composition.platform, "system", lambda: "Linux")

    def forbidden(*args, **kwargs):
        raise AssertionError("Linux lookup entered Darwin runtime validation")

    monkeypatch.setattr(DarwinProcessBackend, "validate_release_states", forbidden)
    scope = dict(DARWIN_RELEASE_SCOPE)
    scope["run_command"] = replace(
        scope["run_command"],
        capability=Capability(CapabilityState.LIMITED, "test", "run_command"),
    )
    assert composition.native_file_capability() is None
    assert (
        composition.native_file_capability(release_scope=scope, execution=None) is None
    )


def test_production_scope_controls_real_server_without_test_override(tmp_path):
    import os
    import subprocess
    import sys

    token = tmp_path / "token"
    token.write_text("test-token")
    config = tmp_path / "config.toml"
    config.write_text(
        f'[auth]\ntoken_file = "{token}"\n'
        f'[roots]\ndefault_root = "{tmp_path}"\nextra_roots = []\n'
    )
    script = """
import asyncio, sys
from pathlib import Path
from fastmcp import Client
from binnacle.server import mcp
from binnacle.platform.contracts.darwin_release_scope import DARWIN_RELEASE_SCOPE
if sys.platform != "darwin":
    assert not any(m.startswith("binnacle.platform.darwin") for m in sys.modules)
    sys.exit(0)
assert not any(m.startswith("binnacle.platform.linux") for m in sys.modules)
root = Path(sys.argv[1])
async def check():
    async with Client(mcp) as client:
        for name, args in (
            ("write_file", {"path": str(root / "sample"), "content": "before"}),
            ("edit_file", {"path": str(root / "sample"), "old_string": "before", "new_string": "after"}),
            ("read_file", {"path": str(root / "sample")}),
            ("run_command", {"command": "printf production", "workdir": str(root)}),
            ("job_status", {}),
            ("list_files", {"path": str(root)}),
            ("search_text", {"path": str(root), "pattern": "after"}),
            ("stop_job", {"job_id": "foreign"}),
        ):
            result = await client.call_tool(name, args, raise_on_error=False)
            enabled = DARWIN_RELEASE_SCOPE[name].capability.state.value == "LIMITED"
            assert result.is_error != enabled, (name, result)
            if not enabled:
                assert "unavailable" in str(result.content).lower(), (name, result)
            elif name == "read_file":
                assert result.structured_content["content"] == "after"
            elif name == "run_command":
                assert result.structured_content["output"] == "production"
                assert "descendants_unverified=true" in str(result.content)
                assert "descendants_unverified" not in result.structured_content
asyncio.run(check())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "BINNACLE_CONFIG_FILE": str(config)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_linux_startup_with_flipped_scope_preserves_surface_hashes(tmp_path):
    import os
    import subprocess
    import sys

    token = tmp_path / "token"
    token.write_text("test-token")
    config = tmp_path / "config.toml"
    config.write_text(
        f'[auth]\ntoken_file = "{token}"\n'
        f'[jobs]\nowner = "embedded"\ndir = "{tmp_path / "jobs"}"\n'
        f'socket_path = "{tmp_path / "jobs.sock"}"\n'
    )
    script = """
import hashlib, platform
# Composition/schema check on any host; on the Pi this also uses real Linux imports.
platform.system = lambda: "Linux"
from binnacle.platform.contracts.darwin_release_scope import DARWIN_RELEASE_SCOPE
assert DARWIN_RELEASE_SCOPE["run_command"].capability.state.value == "LIMITED"
from binnacle.server import mcp
from tests.contracts.surface_support import PROFILES, digest, served, surface
from tests.contracts.test_tool_surface import SURFACE_SHA256, INSTRUCTIONS_SHA256
for profile, name in PROFILES.items():
    tools, instructions = served(name, mcp_server=mcp)
    hashes = {tool.name: digest(surface(tool)) for tool in tools}
    assert list(hashes) == list(SURFACE_SHA256[profile])
    assert hashes == SURFACE_SHA256[profile], (profile, hashes)
    assert hashlib.sha256(instructions.encode()).hexdigest() == INSTRUCTIONS_SHA256
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "BINNACLE_CONFIG_FILE": str(config)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


_DARWIN_ONLY = pytest.mark.skipif(
    platform.system() != "Darwin", reason="native Files lifecycle"
)


def _generation_app(tmp_path, monkeypatch):
    from dataclasses import replace

    from binnacle.application import compose_native_tools
    from binnacle.platform import composition
    from binnacle.platform.contracts.darwin_release_scope import DARWIN_RELEASE_SCOPE

    monkeypatch.setattr(composition.platform, "system", lambda: "Darwin")
    root = (tmp_path / "root").resolve()
    root.mkdir()
    (root / "file").write_text("hello")
    settings = Settings(roots=RootsSettings(default_root=root, extra_roots=()))
    scope = {
        tool: replace(
            row, capability=Capability(CapabilityState.UNAVAILABLE, "test", tool)
        )
        for tool, row in DARWIN_RELEASE_SCOPE.items()
    }
    for tool in ("read_file", "list_files"):
        scope[tool] = replace(
            scope[tool], capability=Capability(CapabilityState.LIMITED, "test", tool)
        )
    access, backend = compose_native_tools(settings=settings, release_scope=scope)
    app = create_application(
        settings=settings, token="test", backend=backend, file_access=access
    )
    return app, access, root


async def _both_tools_succeed(client, root):
    read = await client.call_tool("read_file", {"path": str(root / "file")})
    assert read.structured_content["content"] == "hello"
    listing = await client.call_tool("list_files", {"path": str(root)})
    assert not listing.is_error


@_DARWIN_ONLY
def test_sequential_clients_on_one_server_reopen_grants(tmp_path, monkeypatch):
    app, access, root = _generation_app(tmp_path, monkeypatch)

    async def exercise():
        for _ in range(2):
            async with Client(app) as client:
                await _both_tools_succeed(client, root)
            assert access.closed and not access.grants

    asyncio.run(exercise())


@_DARWIN_ONLY
def test_overlapping_clients_share_one_generation_until_last_exit(
    tmp_path, monkeypatch
):
    app, access, root = _generation_app(tmp_path, monkeypatch)

    async def exercise():
        async with Client(app) as first:
            grants = dict(access.grants)
            async with Client(app) as second:
                await _both_tools_succeed(second, root)
            assert not access.closed and access.grants == grants
            await _both_tools_succeed(first, root)
        assert access.closed

    asyncio.run(exercise())


@_DARWIN_ONLY
def test_call_after_last_exit_is_typed_unavailable_not_stale(tmp_path, monkeypatch):
    app, access, root = _generation_app(tmp_path, monkeypatch)

    async def exercise():
        async with Client(app) as client:
            await _both_tools_succeed(client, root)
        assert access.files is None and access.search is None
        with pytest.raises(paths.CodedToolError) as caught:
            access.select(str(root / "file"))
        assert caught.value.telemetry_code == "native_access_closed"
        with pytest.raises(paths.CodedToolError) as caught:
            access.read(str(root / "file"), 100)
        assert caught.value.telemetry_code == "native_access_closed"

    asyncio.run(exercise())


@_DARWIN_ONLY
def test_no_descriptor_leak_across_twenty_lifespans(tmp_path, monkeypatch):
    import os

    app, _access, root = _generation_app(tmp_path, monkeypatch)

    def open_fds():
        return len(os.listdir("/dev/fd"))

    async def cycle():
        async with Client(app) as client:
            await _both_tools_succeed(client, root)

    async def exercise():
        await cycle()  # warm lazy imports and loop descriptors
        before = open_fds()
        for _ in range(20):
            await cycle()
        assert open_fds() <= before

    asyncio.run(exercise())
