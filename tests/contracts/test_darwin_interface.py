"""CR1A-02 permits one Darwin description change; all eight schemas stay pinned."""

import asyncio
import json
from pathlib import Path

from fastmcp import Client

from binnacle.application import create_application
from binnacle.config import RootsSettings, Settings
from binnacle.features.commands.restricted_backend import RestrictedCommandBackend


def test_native_wire_schema_preserves_v101_with_declared_description_exception(
    tmp_path,
):
    baseline = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/os-independent-stage1-evidence/os0-raw-mcp-surface.json"
        ).read_text()
    )["profile_surfaces"]["default"]
    root = create_application(
        settings=Settings(roots=RootsSettings(default_root=tmp_path, extra_roots=())),
        token="test",
        backend=RestrictedCommandBackend(),
    )

    async def inspect():
        async with Client(root) as client:
            return await client.list_tools(), client.instructions

    tools, instructions = asyncio.run(inspect())
    actual = [tool.model_dump(mode="json", by_alias=True) for tool in tools]
    assert instructions == baseline["instructions"]
    assert len(actual) == 8
    native = next(tool for tool in actual if tool["name"] == "run_command")
    description = native["description"].lower()
    assert (
        "background processes are terminated when the command finishes" in description
    )
    assert "processes that start a new session (setsid) are not tracked" in description
    assert "new sessions/process groups are not tracked or terminated" in description
    assert "unavailable pending r1 + cr1" in description
    original = next(tool for tool in baseline["tools"] if tool["name"] == "run_command")
    native["description"] = original["description"]
    assert actual == baseline["tools"]


def test_release_scope_is_committed_unavailable_and_production_cannot_override():
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
    for tool, row in DARWIN_RELEASE_SCOPE.items():
        assert row.capability.state == CapabilityState.UNAVAILABLE
        assert row.decision_target == (
            "unavailable" if tool == "stop_job" else "limited"
        )
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
