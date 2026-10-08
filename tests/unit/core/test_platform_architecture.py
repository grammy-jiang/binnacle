"""Enforce the small G3 platform and storage ownership boundaries."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "src" / "binnacle"
MODULE_PATHS = {
    "process_contracts": "platform/contracts/process_contracts.py",
    "resource_contracts": "platform/contracts/resource_contracts.py",
    "job_process": "platform/linux/job_process.py",
    "job_cgroup": "platform/linux/job_cgroup.py",
    "job_platform": "platform/job_platform.py",
    "job_resource_history": "features/commands/job_resource_history.py",
    "job_store": "features/commands/job_store.py",
    "jobs": "features/commands/jobs.py",
    "job_owner": "features/commands/job_owner.py",
    "job_manager": "features/commands/job_manager.py",
}
EDGES = {
    "process_contracts": set(),
    "resource_contracts": set(),
    "job_process": {"process_contracts"},
    "job_cgroup": set(),
    "job_platform": {
        "process_contracts",
        "resource_contracts",
        "job_process",
        "job_cgroup",
    },
    "job_resource_history": {"resource_contracts"},
    "job_store": set(),
    "jobs": {
        "job_resource_history",
        "job_store",
        "callctx",
        "config",
        "job_output",
        "job_platform",
        "process_contracts",
    },
    "job_owner": {"callctx", "job_client", "jobs", "job_store"},
    "job_manager": {
        "job_owner",
        "jobs",
        "callctx",
        "config",
        "job_client",
        "job_platform",
        "provenance",
    },
}

MODULE_OWNERS = {
    "binnacle.mcp.callctx": "callctx",
    "binnacle.platform.contracts.process_contracts": "process_contracts",
    "binnacle.platform.contracts.resource_contracts": "resource_contracts",
    "binnacle.platform.linux.job_process": "job_process",
    "binnacle.platform.linux.job_cgroup": "job_cgroup",
    "binnacle.platform.job_platform": "job_platform",
    "binnacle.features.commands.job_resource_history": "job_resource_history",
    "binnacle.features.commands.job_store": "job_store",
    "binnacle.features.commands.jobs": "jobs",
    "binnacle.features.commands.job_owner": "job_owner",
    "binnacle.features.commands.job_manager": "job_manager",
    "binnacle.features.commands.job_client": "job_client",
    "binnacle.features.commands.job_output": "job_output",
}


def imported_owner(name: str) -> str | None:
    for module, owner in MODULE_OWNERS.items():
        if name == module or name.startswith(module + "."):
            return owner
    if name.startswith("binnacle."):
        return name.split(".")[1]
    return None


ORCHESTRATION = {
    "jobs",
    "job_owner",
    "job_manager",
    "job_resource_history",
    "job_store",
}
FORBIDDEN_CALLS = {
    "os.kill",
    "os.killpg",
    "os.system",
    "os.fork",
    "os.posix_spawn",
    "os.posix_spawnp",
    "subprocess.Popen",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
}


def violations(source, owner):
    tree = ast.parse(source)
    found = []
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports = [
                (alias.name, alias.asname or alias.name.split(".")[0])
                for alias in node.names
            ]
        elif isinstance(node, ast.ImportFrom):
            imports = [
                (f"{node.module}.{alias.name}", alias.asname or alias.name)
                for alias in node.names
            ]
            if node.level or any(alias.name == "*" for alias in node.names):
                found.append("relative or wildcard import")
        else:
            continue
        for name, bound in imports:
            aliases[bound] = name
            root = name.split(".")[0]
            if root in {"fastmcp", "mcp", "importlib"}:
                found.append(name)
            dependency = imported_owner(name)
            if dependency is not None and dependency not in EDGES[owner]:
                found.append(name)
            if owner in {"process_contracts", "resource_contracts"} and root not in {
                "typing",
                "pathlib",
                "collections",
            }:
                found.append(name)

    def dotted(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return dotted(node.value) + "." + node.attr
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) == 2
            and isinstance(node.args[1], ast.Constant)
        ):
            return dotted(node.args[0]) + "." + str(node.args[1].value)
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "__import__":
            found.append("dynamic import")
        if owner in ORCHESTRATION:
            if isinstance(node, ast.Call) and dotted(node.func) in FORBIDDEN_CALLS:
                found.append(dotted(node.func))
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith(("/proc", "/sys/fs/cgroup"))
            ):
                found.append("Linux filesystem path")
        if (
            owner == "job_owner"
            and isinstance(node, ast.Attribute)
            and dotted(node)
            in {
                "binnacle.jobs._STORE_LOCK",
                "binnacle.jobs._read_meta",
                "binnacle.jobs._write_meta",
                "binnacle.features.commands.jobs._STORE_LOCK",
                "binnacle.features.commands.jobs._read_meta",
                "binnacle.features.commands.jobs._write_meta",
            }
        ):
            found.append("private jobs storage")
    return found


@pytest.mark.parametrize("owner", EDGES)
def test_platform_dependencies(owner):
    path = SOURCE / MODULE_PATHS.get(owner, f"{owner}.py")
    assert violations(path.read_text(), owner) == []


@pytest.mark.parametrize("owner", EDGES)
@pytest.mark.parametrize(
    "source",
    [
        "from fastmcp import FastMCP",
        "from mcp import types",
        "from binnacle import server",
        "import importlib as il; il.import_module('binnacle.jobs')",
        "from importlib import import_module as load; load('binnacle.platform.linux.job_cgroup')",
        "loader = __import__; loader('binnacle.platform.linux.job_process')",
    ],
)
def test_import_rule_rejects_forbidden_and_dynamic_edges(owner, source):
    assert violations(source, owner)


@pytest.mark.parametrize("owner", ORCHESTRATION)
@pytest.mark.parametrize(
    "source",
    [
        "import os; os.kill(1, 15)",
        "from os import killpg as send; send(1, 9)",
        "import subprocess as sp; sp.Popen(['sh'])",
        "from subprocess import Popen as launch; launch(['sh'])",
        "import os; getattr(os, 'kill')(1, 15)",
        "from pathlib import Path; Path('/proc/12/stat').read_text()",
        "from pathlib import Path; Path('/sys/fs/cgroup/scope').rmdir()",
    ],
)
def test_orchestration_rejects_linux_mechanics(owner, source):
    assert violations(source, owner)


@pytest.mark.parametrize(
    "source",
    [
        "from binnacle.platform.linux import job_process",
        "from binnacle.platform.linux import job_cgroup",
        "from binnacle.platform import job_platform",
        "from binnacle import jobs",
        "from binnacle.config import get_settings",
    ],
)
@pytest.mark.parametrize(
    "owner",
    ["process_contracts", "resource_contracts", "job_resource_history", "job_store"],
)
def test_contract_history_and_store_reject_concrete_dependencies(owner, source):
    assert violations(source, owner)


@pytest.mark.parametrize("member", ["_STORE_LOCK", "_read_meta", "_write_meta"])
@pytest.mark.parametrize(
    "import_statement",
    [
        "from binnacle import jobs as j",
        "from binnacle.features.commands import jobs as j",
        "import binnacle.features.commands.jobs as j",
    ],
)
def test_owner_rejects_private_storage(member, import_statement):
    assert violations(f"{import_statement}; j.{member}", "job_owner")


def test_platform_contains_only_two_explicit_lazy_constructors():
    tree = ast.parse((SOURCE / MODULE_PATHS["job_platform"]).read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert [node.name for node in functions] == [
        "create_process_backend",
        "create_resource_accounting",
    ]
    assert all(
        isinstance(node, (ast.Expr, ast.ImportFrom, ast.FunctionDef))
        for node in tree.body
    )
    for function, concrete in zip(
        functions, ["LinuxProcessBackend", "CgroupResourceAccounting"], strict=True
    ):
        assert len(function.body) == 2
        assert isinstance(function.body[0], ast.ImportFrom)
        result = function.body[1]
        assert isinstance(result, ast.Return) and isinstance(result.value, ast.Call)
        assert (
            isinstance(result.value.func, ast.Name) and result.value.func.id == concrete
        )
        assert not result.value.args and not result.value.keywords


def test_only_job_engine_and_manager_select_platform():
    for path in SOURCE.rglob("*.py"):
        if path.stem in {"jobs", "job_manager"}:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "binnacle.platform.job_platform", path
                if node.module == "binnacle":
                    assert all(alias.name != "job_platform" for alias in node.names), (
                        path
                    )
            elif isinstance(node, ast.Import):
                assert all(
                    alias.name != "binnacle.platform.job_platform"
                    for alias in node.names
                ), path


def test_g6_callctx_owner_exception_does_not_admit_mcp_glue():
    assert imported_owner("binnacle.mcp.callctx.current_call") == "callctx"
    assert imported_owner("binnacle.mcp.visibility") == "mcp"
    assert violations(
        "from binnacle.mcp.visibility import ClientToolVisibility", "jobs"
    )
