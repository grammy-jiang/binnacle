"""Fresh root construction and the existing deployment bootstrap contract."""

import asyncio
import subprocess
import sys

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.server.middleware.dereference import DereferenceRefsMiddleware

from binnacle import server
from binnacle.logging_middleware import RequestLoggingMiddleware, ToolLoggingMiddleware
from binnacle.visibility import ClientToolVisibility
from tests.integration.http_test_support import HEADERS, INITIALIZE, sse_json
from tests.integration.test_packaging_smoke import clean_env


def test_factory_roots_have_independent_registration_and_identity():
    assert callable(getattr(server, "create_server", None))
    first, second = server.create_server(), server.create_server()
    assert first is not second and first is not server.mcp
    expected = [
        DereferenceRefsMiddleware,
        RequestLoggingMiddleware,
        ToolLoggingMiddleware,
        ClientToolVisibility,
    ]
    for root in (first, second, server.mcp):
        assert [type(middleware) for middleware in root.middleware] == expected
        identities = [middleware._identity for middleware in root.middleware[1:]]
        assert all(identity is identities[0] for identity in identities)
    assert first.middleware[1]._identity is not second.middleware[1]._identity
    assert first.middleware[1]._identity is not server.mcp.middleware[1]._identity

    @first.tool
    def factory_probe() -> str:
        return "isolated"

    async def names(root):
        async with Client(root) as client:
            return [tool.name for tool in await client.list_tools()]

    assert "factory_probe" in asyncio.run(names(first))
    assert "factory_probe" not in asyncio.run(names(second))
    assert "factory_probe" not in asyncio.run(names(server.mcp))


def test_factory_does_not_build_http_app_or_repeat_config_logging(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("factory repeated a module bootstrap side effect")

    monkeypatch.setattr(FastMCP, "http_app", unexpected)
    monkeypatch.setattr(server, "log_effective_config", unexpected)
    assert isinstance(server.create_server(), FastMCP)


def test_fresh_factory_auth_and_asgi_lifespan(monkeypatch):
    monkeypatch.setattr(server, "_load_token", lambda: "factory-test-token")
    root = server.create_server()
    app = root.http_app()

    async def go():
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            rejected = await client.post("/mcp", json=INITIALIZE, headers=HEADERS)
            assert rejected.status_code == 401
            accepted = await client.post(
                "/mcp",
                json=INITIALIZE,
                headers={**HEADERS, "Authorization": "Bearer factory-test-token"},
            )
            assert accepted.status_code == 200
            result = sse_json(accepted.text)["result"]
            assert result["serverInfo"]["name"] == "binnacle"
            assert result["instructions"] == server.mcp.instructions

    asyncio.run(go())


def _bootstrap(tmp_path, script, token_text):
    token = tmp_path / "token"
    if token_text is not None:
        token.write_text(token_text)
    config = tmp_path / "config.toml"
    config.write_text(f'[auth]\ntoken_file = "{token}"\n')
    return subprocess.run(
        [sys.executable, "-c", script],
        env=clean_env(config),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_module_exports_and_config_log_once(tmp_path):
    proc = _bootstrap(
        tmp_path,
        """
from fastmcp import FastMCP
from binnacle import server
assert isinstance(server.mcp, FastMCP)
assert callable(server.app)
assert server.create_server() is not server.create_server()
print("bootstrap-ok")
""",
        "Bearer bootstrap-token\n",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "bootstrap-ok"
    assert proc.stderr.count("event=config pid=") == 1


@pytest.mark.parametrize(
    ("token_text", "error"),
    [(None, "FileNotFoundError"), ("", "RuntimeError"), ("Bearer\n", "RuntimeError")],
)
def test_import_still_rejects_missing_or_empty_token(tmp_path, token_text, error):
    proc = _bootstrap(tmp_path, "import binnacle.server", token_text)
    assert proc.returncode != 0
    assert error in proc.stderr
    assert str(tmp_path / "token") in proc.stderr
    assert "event=config pid=" not in proc.stderr


def test_module_execution_keeps_http_runner_arguments(tmp_path):
    proc = _bootstrap(
        tmp_path,
        """
import runpy
from unittest.mock import patch
from fastmcp import FastMCP
with patch.object(FastMCP, "run") as run:
    runpy.run_module("binnacle.server", run_name="__main__")
run.assert_called_once_with(
    transport="http", host="127.0.0.1", port=8000, show_banner=False,
)
""",
        "bootstrap-token",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.count("event=config pid=") == 1


def test_tool_package_has_no_eager_registry_and_keeps_adapter_paths(tmp_path):
    proc = _bootstrap(
        tmp_path,
        """
import importlib
import sys
import binnacle.tools
assert not hasattr(binnacle.tools, "register_all")
assert not any(name.startswith("binnacle.tools.") for name in sys.modules)
for name in (
    "read_file", "list_files", "search_text", "edit_file", "write_file",
    "run_command", "job_status", "stop_job",
):
    module = importlib.import_module(f"binnacle.tools.{name}")
    assert callable(module.register)
assert "binnacle.server" not in sys.modules
""",
        "bootstrap-token",
    )
    assert proc.returncode == 0, proc.stderr
