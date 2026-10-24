"""Bridge authorization, privacy, and ChatGPT tool registration contracts."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client

from binnacle.features import lsp_bridge_server as bridge
from binnacle.mcp.logging_middleware import _scalar
from binnacle.observability.log_safety import safe_arguments, safe_tool_name


def _state(tmp_path: Path, *, names: tuple[str, ...] = ("Projects",)) -> Path:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    token = state / "token"
    token.write_text("synthetic-test-secret-" + "a" * 32)
    token.chmod(0o600)
    grants = state / "grants.json"
    grants.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "grants": {
                    f"wsg_test_{index}": name for index, name in enumerate(names)
                },
            }
        )
    )
    grants.chmod(0o600)
    return state


def test_single_grant_and_token_must_be_private(tmp_path: Path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    state = _state(tmp_path)
    token, handle = bridge._credentials(state, workspace)
    assert token.startswith("synthetic-test-secret-")
    assert handle == "wsg_test_0"
    (state / "token").chmod(0o644)
    with pytest.raises(ValueError, match="permissions"):
        bridge._credentials(state, workspace)
    (state / "token").chmod(0o600)
    (state / "grants.json").unlink()
    (state / "grants.json").symlink_to(state / "token")
    with pytest.raises(OSError):
        bridge._credentials(state, workspace)


def test_multiple_or_wrong_grants_denied(tmp_path: Path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    for names in (("Elsewhere",), ("Projects", "Another")):
        state = _state(tmp_path, names=names)
        with pytest.raises(ValueError, match="grant"):
            bridge._credentials(state, workspace)
        for p in state.iterdir():
            p.unlink()
        state.rmdir()


def test_cannot_target_production_or_testing_port(tmp_path: Path):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    for port in (8000, 18765, 80, 65536):
        with pytest.raises(ValueError, match="port"):
            bridge.create_lsp_bridge_server(
                state_dir=tmp_path, workspace=workspace, port=port
            )


def test_actual_mcp_tool_forwards_only_host_grant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    workspace = tmp_path / "Projects"
    workspace.mkdir()
    state = _state(tmp_path)
    calls: list[dict] = []
    fake_content = {
        "schema_version": "p4.internal.v0",
        "status": "partial",
        "definitions": [{"path": "demo/src/a.py"}],
        "references": [],
        "reason_codes": ["index_incomplete"],
    }

    class StubClient:
        def __init__(self, transport, *, timeout):
            assert timeout <= 150
            calls.append({"transport": transport, "timeout": timeout})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def call_tool(self, name, args, *, raise_on_error):
            calls.append({"tool": name, "args": args, "raise": raise_on_error})
            return SimpleNamespace(is_error=False, structured_content=fake_content)

    monkeypatch.setattr(bridge, "Client", StubClient)
    child = bridge.create_lsp_bridge_server(
        state_dir=state, workspace=workspace, port=18767
    )

    async def check():
        names = [tool.name for tool in await child.list_tools(run_middleware=False)]
        assert names == ["inspect_symbol"]
        async with Client(child) as client:
            returned = await client.call_tool(
                "inspect_symbol",
                {"path": "demo/src/a.py", "line": 7, "symbol_text": "secret_method"},
            )
        assert not returned.is_error
        assert returned.structured_content == fake_content

    asyncio.run(check())
    assert calls[1]["tool"] == "inspect_symbol"
    assert calls[1]["args"]["workspace_id"] == "wsg_test_0"
    assert calls[1]["args"]["path"] == "demo/src/a.py"
    assert calls[1]["args"]["symbol_text"] == "secret_method"
    assert "token" not in calls[1]["args"]


def test_lsp_logs_are_structured_but_source_text_redacted():
    symbol = "private_name_should_never_appear"
    data = safe_arguments(
        {
            "path": "a/b/c.py",
            "line": 17,
            "symbol_text": symbol,
            "column": None,
            "reference_limit": 30,
            "include_hover": False,
        }
    )
    assert safe_tool_name("inspect_symbol") == "inspect_symbol"
    assert data["line"] == 17
    assert data["reference_limit"] == 30
    assert data["symbol_text"].startswith("symbolhash:")
    assert symbol not in json.dumps(data)
    assert "unknown_keys" not in data
    assert _scalar("partial", "status") == "partial"
    assert _scalar("EXTERNAL_PRIVATE_TEXT", "status") == "[redacted]"
