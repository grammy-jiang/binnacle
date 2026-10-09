"""Narrow executable import rules for the frozen Commands domain seam."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "src" / "binnacle"
ADAPTERS = (
    "features/commands/tools/run_command.py",
    "features/commands/tools/job_status.py",
    "features/commands/tools/stop_job.py",
)
DOMAIN = ("command_execution.py", "command_status.py", "command_contracts.py")
STANDARD = {"dataclasses", "pathlib", "typing", "logging", "time"}
DOMAIN_IMPORTS = {
    "binnacle.features.commands.command_contracts",
    "binnacle.features.commands.job_output",
    "binnacle.mcp.callctx",
    "binnacle.features.commands.run_command_evidence",
    "binnacle.features.commands.run_command_telemetry",
}
ADAPTER_IMPORTS = {
    "fastmcp",
    "fastmcp.exceptions",
    "fastmcp.tools.base",
    "pydantic",
    "binnacle.features.commands.command_execution",
    "binnacle.features.commands.command_status",
    "binnacle.features.commands.command_contracts",
    "binnacle.features.commands.command_backend",
    "binnacle.config",
    "binnacle.errors",
    "binnacle.features.files.paths",
}


def violations(source, owner):
    """Exact import edges, plus dynamic import entry points in this small seam."""
    allowed = set(STANDARD)
    if owner in ADAPTERS:
        allowed |= ADAPTER_IMPORTS
    elif owner == "command_backend.py":
        allowed |= {
            "importlib",
            "binnacle.features.commands.command_contracts",
            "binnacle.features.commands.jobs",
            "binnacle.features.commands.job_owner",
        }
    elif owner != "command_contracts.py":
        allowed |= DOMAIN_IMPORTS
    found = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name for alias in node.names if alias.name not in allowed
            )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                module = (
                    f"binnacle.{alias.name}"
                    if node.module == "binnacle"
                    else f"{node.module}.{alias.name}"
                    if node.module == "binnacle.features.commands"
                    else node.module
                )
                if (
                    owner == "command_status.py"
                    and module == "binnacle.features.commands.job_store"
                    and alias.name == "JobGone"
                ):
                    continue
                if (
                    owner == "command_execution.py"
                    and module == "binnacle.config"
                    and alias.name == "RunCommandSettings"
                ):
                    continue
                if module not in allowed or alias.name == "*" or node.level:
                    found.append(f"{module}:{alias.name}")
        elif isinstance(node, ast.Name) and node.id == "__import__":
            found.append("dynamic __import__")
        elif (
            isinstance(node, ast.Call)
            and owner == "command_backend.py"
            and isinstance(node.func, ast.Name)
            and node.func.id == "import_module"
            and (
                len(node.args) != 1
                or not isinstance(node.args[0], ast.Constant)
                or node.args[0].value
                not in {
                    "binnacle.features.commands.jobs",
                    "binnacle.features.commands.job_owner",
                }
            )
        ):
            found.append("unexpected backend selection")
    return found


@pytest.mark.parametrize("owner", (*ADAPTERS, *DOMAIN, "command_backend.py"))
def test_commands_imports_respect_frozen_boundary(owner):
    path = (
        f"features/commands/{owner}"
        if owner
        in {
            "command_contracts.py",
            "command_backend.py",
            "command_execution.py",
            "command_status.py",
        }
        else owner
    )
    assert violations((SOURCE / path).read_text(), owner) == []


@pytest.mark.parametrize(
    "source",
    [
        "from binnacle.mcp.visibility import ClientToolVisibility",
        "from binnacle.features.commands import jobs as store",
        "import binnacle.features.commands.job_owner as owner",
        "from binnacle.features.commands.job_store import read_meta",
        "from binnacle.features.commands.command_backend import create_command_backend",
        "from binnacle.config import get_settings as load",
        "from fastmcp.tools.base import ToolResult",
        "from os import kill as signal; signal(1, 15)",
        "from subprocess import Popen; Popen(['probe'])",
        "import importlib as il; il.import_module('binnacle.features.commands.jobs')",
        "from importlib import import_module as load; load('binnacle.features.commands.jobs')",
        "loader = __import__; loader('binnacle.features.commands.jobs')",
        "__import__('binnacle.platform.linux.job_cgroup')",
        "import importlib; getattr(importlib, 'import_module')('binnacle.features.commands.jobs')",
    ],
)
def test_boundary_rejects_forbidden_and_dynamic_imports(source):
    assert violations(source, "command_status.py")


def test_job_gone_exception_is_the_only_store_import_exception():
    source = "from binnacle.features.commands.job_store import JobGone"
    assert violations(source, "command_status.py") == []
    for owner in (*ADAPTERS, "command_execution.py", "command_contracts.py"):
        assert violations(source, owner)
    assert violations("from binnacle import job_store", "command_status.py")


def test_contract_and_bridge_negative_edges():
    assert violations(
        "from binnacle.config import RunCommandSettings", "command_contracts.py"
    )
    assert violations(
        "from binnacle.platform.linux import job_cgroup", "command_backend.py"
    )
    assert violations(
        "import_module('binnacle.platform.linux.job_process')", "command_backend.py"
    )


def test_pure_domain_and_fake_native_child_with_engine_imports_blocked():
    code = """
import asyncio, importlib.abc, sys
from pathlib import Path
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"binnacle.features.commands.jobs", "binnacle.features.commands.job_owner", "binnacle.features.commands.job_client",
                        "binnacle.platform.linux.job_process", "binnacle.platform.linux.job_cgroup", "binnacle.features.commands.job_manager"}:
            raise AssertionError("engine imported: " + fullname)
sys.meta_path.insert(0, Block())
from binnacle.features.commands import command_contracts, command_execution, command_status
from binnacle import config
from binnacle.platform.contracts import process_contracts, resource_contracts
from binnacle.features.commands.commands_server import create_commands_server
from tests.command_support import MemoryCommands
from fastmcp import Client
def forbidden(): raise AssertionError("global settings read")
config.get_settings = forbidden
backend = MemoryCommands()
child = create_commands_server(
    backend=backend, roots=config.RootsSettings(default_root=Path('/tmp')),
    run_settings=config.RunCommandSettings(), quiet_after_s=2,
    listing_history_limit=1, listing_command_preview_chars=20,
)
async def main():
    async with Client(child, cache=False) as client:
        await client.call_tool('run_command', {'command':'probe','workdir':'/tmp'})
        await client.call_tool('job_status', {'job_id':'fixed','cursor':'start'})
        await client.call_tool('stop_job', {'job_id':'fixed'})
asyncio.run(main())
assert 'binnacle.features.commands.jobs' not in sys.modules
"""
    subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, timeout=20
    )


def test_default_child_selects_engine_at_construction_before_requests():
    code = """
import sys
from binnacle import config
from binnacle.features.commands.commands_server import create_commands_server
assert 'binnacle.features.commands.jobs' not in sys.modules
settings = config.get_settings().model_copy(deep=True)
settings.jobs.owner = 'embedded'
settings.jobs.warmup_s = 0.125
config.get_settings = lambda: settings
create_commands_server()
from binnacle.features.commands import jobs
settings.jobs.owner = 'manager'
settings.jobs.warmup_s = 0.5
assert jobs.OWNER_MODE == 'embedded' and jobs.WARMUP_S == 0.125
"""
    subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, timeout=20
    )


def test_canonical_commands_public_modules_are_owned():
    import importlib

    expected = (
        "command_contracts",
        "command_backend",
        "command_execution",
        "command_status",
        "commands_server",
        "jobs",
        "job_client",
        "job_manager",
        "job_output",
        "job_owner",
        "job_resource_history",
        "job_store",
        "run_command_evidence",
        "run_command_telemetry",
    )
    for name in expected:
        canonical = f"binnacle.features.commands.{name}"
        module = importlib.import_module(canonical)
        assert module.__name__ == canonical


@pytest.mark.parametrize("name", ["run_command", "job_status", "stop_job"])
def test_canonical_commands_mcp_adapters_are_owned(name):
    import importlib

    module = importlib.import_module(f"binnacle.features.commands.tools.{name}")
    assert callable(module.register)
