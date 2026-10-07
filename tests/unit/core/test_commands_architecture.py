"""Narrow executable import rules for the frozen Commands domain seam."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "src" / "binnacle"
ADAPTERS = ("tools/run_command.py", "tools/job_status.py", "tools/stop_job.py")
DOMAIN = ("command_execution.py", "command_status.py", "command_contracts.py")
STANDARD = {"dataclasses", "pathlib", "typing", "logging", "time"}
DOMAIN_IMPORTS = {
    "binnacle.features.commands.command_contracts",
    "binnacle.job_output",
    "binnacle.callctx",
    "binnacle.run_command_evidence",
    "binnacle.run_command_telemetry",
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
    "binnacle.paths",
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
            "binnacle.jobs",
            "binnacle.job_owner",
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
                    and module == "binnacle.job_store"
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
                or node.args[0].value not in {"binnacle.jobs", "binnacle.job_owner"}
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
        "from binnacle import jobs as store",
        "import binnacle.job_owner as owner",
        "from binnacle.job_store import read_meta",
        "from binnacle.command_backend import create_command_backend",
        "from binnacle.config import get_settings as load",
        "from fastmcp.tools.base import ToolResult",
        "from os import kill as signal; signal(1, 15)",
        "from subprocess import Popen; Popen(['probe'])",
        "import importlib as il; il.import_module('binnacle.jobs')",
        "from importlib import import_module as load; load('binnacle.jobs')",
        "loader = __import__; loader('binnacle.jobs')",
        "__import__('binnacle.platform.linux.job_cgroup')",
        "import importlib; getattr(importlib, 'import_module')('binnacle.jobs')",
    ],
)
def test_boundary_rejects_forbidden_and_dynamic_imports(source):
    assert violations(source, "command_status.py")


def test_job_gone_exception_is_the_only_store_import_exception():
    source = "from binnacle.job_store import JobGone"
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
        if fullname in {"binnacle.jobs", "binnacle.job_owner", "binnacle.job_client",
                        "binnacle.platform.linux.job_process", "binnacle.platform.linux.job_cgroup", "binnacle.job_manager"}:
            raise AssertionError("engine imported: " + fullname)
sys.meta_path.insert(0, Block())
from binnacle import command_contracts, command_execution, command_status, config
from binnacle.platform.contracts import process_contracts, resource_contracts
from binnacle.commands_server import create_commands_server
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
assert 'binnacle.jobs' not in sys.modules
"""
    subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, timeout=20
    )


def test_default_child_selects_engine_at_construction_before_requests():
    code = """
import sys
from binnacle import config
from binnacle.commands_server import create_commands_server
assert 'binnacle.jobs' not in sys.modules
settings = config.get_settings().model_copy(deep=True)
settings.jobs.owner = 'embedded'
settings.jobs.warmup_s = 0.125
config.get_settings = lambda: settings
create_commands_server()
from binnacle import jobs
settings.jobs.owner = 'manager'
settings.jobs.warmup_s = 0.5
assert jobs.OWNER_MODE == 'embedded' and jobs.WARMUP_S == 0.125
"""
    subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, timeout=20
    )


def test_legacy_command_contract_symbols_preserve_identity():
    from binnacle import command_contracts as legacy
    from binnacle.features.commands import command_contracts as owned

    assert legacy.CommandBackend is owned.CommandBackend
    assert legacy.CommandFailure is owned.CommandFailure
    assert legacy.CommandReply is owned.CommandReply


def test_legacy_command_backend_symbols_preserve_identity():
    from binnacle import command_backend as legacy
    from binnacle.features.commands import command_backend as owned

    assert legacy.DurableCommandBackend is owned.DurableCommandBackend
    assert legacy.create_command_backend is owned.create_command_backend


def test_legacy_command_domain_symbols_preserve_identity():
    from binnacle import command_execution as legacy_execution
    from binnacle import command_status as legacy_status
    from binnacle.features.commands import command_execution, command_status

    assert legacy_execution.run_command is command_execution.run_command
    assert legacy_execution.stop_job is command_execution.stop_job
    assert legacy_status.job_status is command_status.job_status
