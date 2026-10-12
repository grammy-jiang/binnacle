"""E1: a serving MCP process first-imports no binnacle module after start-up.

OPS-FOLLOWUP-shared-venv-lazy-import / R-M1-X1: a lazily imported module comes
from whatever revision the shared checkout holds at that moment.
"""

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from binnacle.startup_imports import import_runtime_modules, runtime_module_names

REPO = Path(__file__).resolve().parents[3]

_PROBE = """
import asyncio, json, sys
import binnacle.server as server
started = {m for m in sys.modules if m.startswith("binnacle")}
from fastmcp import Client
root = sys.argv[1]
calls = [
    ("write_file", {"path": f"{root}/a.txt", "content": "hello\\n"}),
    ("read_file", {"path": f"{root}/a.txt"}),
    ("edit_file", {"path": f"{root}/a.txt", "old_string": "hello", "new_string": "bye"}),
    ("list_files", {"path": root}),
    ("search_text", {"pattern": "bye", "path": root}),
    ("run_command", {"command": "echo hi", "workdir": root}),
    ("job_status", {}),
    ("stop_job", {"job_id": "0" * 12}),
]
async def exercise():
    async with Client(server.mcp) as client:
        listed = sorted(tool.name for tool in await client.list_tools())
        for name, arguments in calls:
            await client.call_tool(name, arguments, raise_on_error=False)
        return listed
listed = asyncio.run(exercise())
late = sorted({m for m in sys.modules if m.startswith("binnacle")} - started)
print(json.dumps({"listed": listed, "called": [n for n, _ in calls], "late": late}))
"""


@pytest.fixture
def private_home():
    """Token, config and roots live under ~/.local/state/binnacle-test (0700)."""
    base = Path.home() / ".local" / "state" / "binnacle-test"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    home = base / f"r6w3-e1-{uuid.uuid4().hex[:12]}"
    home.mkdir(mode=0o700)
    try:
        yield home
    finally:
        shutil.rmtree(home)


def test_runtime_modules_cover_every_tool_and_backend_module_per_os():
    for system, other in (("Linux", "darwin"), ("Darwin", "linux")):
        names = set(runtime_module_names(system))
        for module in (
            "binnacle.application",
            "binnacle.features.commands.job_client",
            "binnacle.features.commands.tools.stop_job",
            "binnacle.features.files.tools.read_file",
            "binnacle.features.search.tools.search_text",
            "binnacle.mcp.logging_middleware",
            f"binnacle.platform.{system.lower()}",
        ):
            assert module in names, (system, module)
        assert not any(
            name in {"binnacle.server", "binnacle.cli"}
            or name.startswith(("binnacle.companions", f"binnacle.platform.{other}"))
            for name in names
        ), system


def test_host_runtime_modules_import_without_failure():
    assert import_runtime_modules() == ()


def test_server_first_imports_no_binnacle_module_after_startup(private_home):
    root = private_home / "root"
    root.mkdir(mode=0o700)
    token = private_home / "token"
    token.write_text("Bearer e1-startup-imports\n", encoding="utf-8")
    token.chmod(0o600)
    config = private_home / "config.toml"
    config.write_text(
        f'[auth]\ntoken_file = "{token}"\n'
        f'[roots]\ndefault_root = "{root}"\nextra_roots = []\n'
        f'[jobs]\ndir = "{private_home / "jobs"}"\nowner = "embedded"\n',
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
    env["BINNACLE_CONFIG_FILE"] = str(config)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(root)],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    assert "event=startup_import_error" not in proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["listed"] == sorted(result["called"])
    assert result["late"] == []
