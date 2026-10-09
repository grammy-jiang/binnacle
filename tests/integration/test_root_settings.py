"""Root construction owns domain policy; durable jobs remain process-owned."""

import asyncio

from fastmcp import Client
from mcp.types import Implementation

from binnacle import server
from binnacle.config import TokenizerTelemetrySettings, get_settings
from binnacle.features.commands import commands_server, jobs
from binnacle.features.commands.tools import job_status, run_command
from binnacle.features.files import files_server, paths
from binnacle.features.files.tools import edit_file, list_files, read_file, write_file
from binnacle.features.search.tools import search_text
from binnacle.mcp import logging_middleware
from binnacle.mcp.identity import ClientIdentity


def fail_global():
    raise AssertionError("root must supply all migrated settings explicitly")


def test_two_roots_capture_one_snapshot_each_without_hidden_reads(
    tmp_path, monkeypatch
):
    sources = []
    for cap in (2, 3):
        settings = get_settings().model_copy(deep=True)
        directory = tmp_path / str(cap)
        directory.mkdir()
        (directory / "file").write_text("needle\n" * 4)
        settings.roots.default_root = directory
        settings.roots.extra_roots = ()
        settings.read_file.max_lines = cap
        settings.list_files.max_results_default = cap
        settings.search_text.max_results_default = cap
        settings.run_command.wait_default_s = cap
        settings.run_command.wait_max_s = cap
        settings.jobs.listing_history_limit = cap
        settings.client_tools = {"limited": ("read_file",) if cap == 2 else ()}
        settings.telemetry.tokenizer.client_prefixes = (f"client-{cap}",)
        sources.append(settings)
    reads = []

    def settings_for_root():
        settings = sources[len(reads)]
        reads.append(settings)
        return settings

    monkeypatch.setattr(server, "get_settings", settings_for_root)
    for module in (
        files_server,
        commands_server,
        logging_middleware,
        paths,
        read_file,
        list_files,
        edit_file,
        write_file,
        search_text,
        run_command,
        job_status,
    ):
        monkeypatch.setattr(module, "get_settings", fail_global)
    # A shared process backend is deliberate. No child owns this store/lifecycle.
    monkeypatch.setattr(jobs, "list_jobs", list)
    roots = [server.create_server(), server.create_server()]
    assert len(reads) == 2
    for source in sources:
        source.roots.default_root = tmp_path / "changed"
        source.read_file.max_lines = 99
        source.list_files.max_results_default = 99
        source.search_text.max_results_default = 99
        source.run_command.wait_max_s = 99
        source.client_tools["limited"] = ("write_file",)
        source.telemetry.tokenizer.client_prefixes = ("changed",)

    async def go():
        for root, cap in zip(roots, (2, 3), strict=True):
            assert root.middleware[2]._token_counter.client_prefixes == (
                f"client-{cap}",
            )
            async with Client(root, cache=False) as client:
                tools = {t.name: t for t in await client.list_tools()}
                for name, parameter in (
                    ("list_files", "max_results"),
                    ("search_text", "max_results"),
                    ("run_command", "wait_seconds"),
                ):
                    assert (
                        tools[name].input_schema["properties"][parameter]["default"]
                        == cap
                    )
                for name in ("run_command", "job_status"):
                    assert (
                        tools[name].input_schema["properties"]["wait_seconds"][
                            "maximum"
                        ]
                        == cap
                    )
                read = await client.call_tool("read_file", {"path": "file"})
                assert read.structured_content["end_line"] == cap
                assert read.structured_content["path"] == str(
                    tmp_path / str(cap) / "file"
                )
                found = await client.call_tool(
                    "search_text", {"path": ".", "pattern": "needle"}
                )
                assert len(found.structured_content["entries"]) == cap
                listing = await client.call_tool("job_status", {})
                assert listing.structured_content == {"jobs": []}
            async with Client(
                root,
                client_info=Implementation(name="limited", version="1"),
                cache=False,
            ) as client:
                assert [t.name for t in await client.list_tools()] == (
                    ["read_file"] if cap == 2 else []
                )

    asyncio.run(go())


def test_root_snapshot_precedes_child_construction(tmp_path, monkeypatch):
    source = get_settings().model_copy(deep=True)
    source.search_text.max_results_default = 7
    monkeypatch.setattr(server, "get_settings", lambda: source)
    factory = server.create_files_server

    def mutate_source(**kwargs):
        source.search_text.max_results_default = 9
        return factory(**kwargs)

    monkeypatch.setattr(server, "create_files_server", mutate_source)
    root = server.create_server()

    async def go():
        async with Client(root) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert (
                tools["search_text"].input_schema["properties"]["max_results"][
                    "default"
                ]
                == 7
            )

    asyncio.run(go())


def test_logging_constructor_copies_explicit_tokenizer_settings(monkeypatch):
    settings = TokenizerTelemetrySettings(
        enabled=True, encoding="test", client_prefixes=("one",)
    )
    calls = []
    monkeypatch.setattr(logging_middleware, "get_settings", fail_global)
    monkeypatch.setattr(
        logging_middleware.TokenCounter, "prepare", lambda self: calls.append(self)
    )
    middleware = logging_middleware.ToolLoggingMiddleware(
        ClientIdentity(), tokenizer=settings
    )
    settings.enabled = False
    settings.encoding = "changed"
    settings.client_prefixes = ("two",)
    counter = middleware._token_counter
    assert calls == [counter]
    assert counter.enabled and counter.encoding == "test"
    assert counter.applies("one-client") and not counter.applies("two-client")


def test_fresh_processes_load_two_configs_without_import_order_dependency(tmp_path):
    import subprocess
    import sys

    from tests.integration.test_packaging_smoke import clean_env

    token = tmp_path / "token"
    token.write_text("test-root-token")
    for cap in (2, 3):
        config = tmp_path / f"{cap}.toml"
        config.write_text(
            f'[auth]\ntoken_file = "{token}"\n'
            f'[roots]\ndefault_root = "{tmp_path}"\nextra_roots = []\n'
            f"[search_text]\nmax_results_default = {cap}\n"
            f"[list_files]\nmax_results_default = {cap}\n"
            f"[run_command]\nwait_default_s = {cap}\nwait_max_s = {cap}\n"
        )
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import asyncio
import sys
# Import adapters before construction. No reload or settings-cache reset.
from binnacle.features.files.tools import read_file
from binnacle.tools import job_status
from binnacle.features.search.tools import search_text
from binnacle import server
from fastmcp import Client
async def go():
    for root in (server.mcp, server.create_server()):
        async with Client(root) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            for name in ("search_text", "list_files"):
                assert tools[name].input_schema["properties"]["max_results"]["default"] == int(sys.argv[1])
            for name in ("run_command", "job_status"):
                assert tools[name].input_schema["properties"]["wait_seconds"]["maximum"] == int(sys.argv[1])
asyncio.run(go())
print("construction-ok")
""",
                str(cap),
            ],
            env=clean_env(config),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "construction-ok"
        assert proc.stderr.count("event=config pid=") == 1
