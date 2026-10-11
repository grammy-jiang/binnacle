"""E2 S5 no-path check: production composition cannot reach the lab.

Three independent witnesses (design §2.9 "unchanged", §5 NOT_GO):
1. the import-linter contract forbids every lab module from the production
   entry points (checked statically by the ``import-linter`` hook);
2. a fresh interpreter that imports every production entry point and builds
   the production server loads no Job Awareness module at all;
3. the production server lists exactly the eight public tools and none of the
   lab middleware or ``fixture_*`` tools.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.test_packaging_smoke import clean_env

ROOT = Path(__file__).resolve().parents[3]
PUBLIC_TOOLS = [
    "edit_file",
    "job_status",
    "list_files",
    "read_file",
    "run_command",
    "search_text",
    "stop_job",
    "write_file",
]
LAB_MODULES = [
    "binnacle.mcp.job_awareness_session",
    "binnacle.mcp.job_awareness_hint",
    *(
        f"binnacle.features.commands.job_awareness.session_{name}"
        for name in (
            "binding",
            "emission",
            "fence",
            "lab",
            "route",
            "serving",
            "snapshot",
        )
    ),
]
PROBE = """
import asyncio, json, sys
{inject}
import binnacle.application, binnacle.cli, binnacle.server
from fastmcp import Client

async def names():
    async with Client(binnacle.server.mcp) as client:
        return sorted(tool.name for tool in await client.list_tools())

print(json.dumps({{
    "modules": sorted(m for m in sys.modules if "job_awareness" in m),
    "tools": asyncio.run(names()),
    "middleware": [type(m).__module__ for m in binnacle.server.mcp.middleware],
}}))
"""


def probe(tmp_path: Path, inject: str = "") -> dict[str, list[str]]:
    token = tmp_path / "token"
    token.write_text("Bearer synthetic-no-path\n")
    config = tmp_path / "config.toml"
    config.write_text(f'[auth]\ntoken_file = "{token}"\n')
    proc = subprocess.run(  # nosec B603 - fixed interpreter and script
        [sys.executable, "-c", PROBE.format(inject=inject)],
        env=clean_env(config),
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]  # nosec B101 - pytest assertion
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_production_entry_points_load_no_lab_module(tmp_path):
    seen = probe(tmp_path)
    assert seen["modules"] == []  # nosec B101 - pytest assertion
    assert seen["tools"] == PUBLIC_TOOLS  # nosec B101 - pytest assertion
    assert not any("job_awareness" in m for m in seen["middleware"])  # nosec B101 - pytest assertion


def test_probe_negative_control_sees_an_injected_lab_import(tmp_path):
    seen = probe(tmp_path, "import binnacle.mcp.job_awareness_session")
    assert "binnacle.mcp.job_awareness_session" in seen["modules"]  # nosec B101 - pytest assertion


def test_import_contract_forbids_every_lab_module_from_production():
    tomllib = pytest.importorskip("tomllib")  # Python 3.10 has no stdlib tomllib
    contracts = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"][
        "importlinter"
    ]["contracts"]
    by_id = {contract["id"]: contract for contract in contracts}
    contract = by_id["job-awareness-lab-not-in-production"]
    assert contract["type"] == "forbidden"  # nosec B101 - pytest assertion
    assert set(contract["source_modules"]) >= {  # nosec B101 - pytest assertion
        "binnacle.server",
        "binnacle.application",
        "binnacle.cli",
    }
    assert sorted(contract["forbidden_modules"]) == sorted(LAB_MODULES)  # nosec B101 - pytest assertion
