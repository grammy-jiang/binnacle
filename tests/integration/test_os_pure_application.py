"""OI-03/OI-04: one native FastMCP tree functions with Linux adapters blocked."""

import ast
import subprocess
import sys
from pathlib import Path

from tests.integration.test_packaging_smoke import clean_env


def test_pure_composition_fake_services_without_linux_adapter_import(tmp_path):
    """Use a separate interpreter so all eager imports are visible and blocked."""
    fixture = tmp_path / "file.txt"
    fixture.write_text("search-needle\n")
    script = """
import asyncio, importlib.abc, json, sys
from pathlib import Path
class NoLinux(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("binnacle.platform.linux", "binnacle.observability.linux",
                                "binnacle.companions")):
            raise ImportError("forbidden adapter import: " + fullname)
sys.meta_path.insert(0, NoLinux())
from fastmcp import Client
from binnacle.config import Settings, RootsSettings
from binnacle.application import create_application
from tests.command_support import MemoryCommands
root = Path(sys.argv[1])
settings = Settings(
    roots=RootsSettings(default_root=root, extra_roots=()),
)
assert settings.jobs.socket_path is None
settings.jobs.socket_path = root / "manager.sock"
settings.jobs.owner = "embedded"
backend = MemoryCommands("fake-job")
mcp = create_application(settings=settings, token="mock-token", backend=backend)
async def verify():
    async with Client(mcp) as client:
        names = [x.name for x in await client.list_tools()]
        assert names == ["read_file", "list_files", "search_text", "edit_file",
                         "write_file", "run_command", "job_status", "stop_job"]
        read = await client.call_tool("read_file", {"path":"file.txt"})
        assert "search-needle" in str(read.structured_content)
        found = await client.call_tool("search_text",
                        {"path":".", "pattern":"search-needle"})
        assert not found.is_error, found
        run = await client.call_tool("run_command",
                        {"workdir":".","command":"probe"})
        assert run.structured_content["job_id"] == "fake-job"
        status = await client.call_tool("job_status", {"job_id":"fake-job"})
        assert status.structured_content["state"] == "running"
        stopped = await client.call_tool("stop_job", {"job_id":"fake-job"})
        assert stopped.structured_content["state"] == "exited"
        print(json.dumps({"names": names, "fake_calls": len(backend.calls),
                          "linux_imported": any(
                         name.startswith(("binnacle.platform.linux", "binnacle.observability.linux"))
                          for name in sys.modules),
                         "search_entries": len(found.structured_content["entries"])}))
asyncio.run(verify())
"""
    env = clean_env(tmp_path / "nonexistent-config.toml")
    env.pop("BINNACLE_MANAGED_DEPLOYMENT", None)
    proc = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '"linux_imported": false' in proc.stdout


def test_pure_factory_source_does_not_select_platform():
    from binnacle import application

    path = Path(application.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        name and ("platform.linux" in name or name.startswith("binnacle.server"))
        for name in imports
    )
