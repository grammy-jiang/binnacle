#!/usr/bin/env python3
"""Preliminary Gate A source-state report.

This is a preparation harness, not the final acceptance gate. Default mode reports
current static/PENDING status and exits zero. --strict fails while any item is not PASS.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.gate_a_manifest import compatibility_facade_coverage, manifest_coverage

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "binnacle"


@dataclass(frozen=True)
class Cell:
    id: str
    status: str
    detail: str
    evidence: str = "static"


def imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{alias.name}" for alias in node.names)
    return out


def any_import(paths: list[Path], prefixes: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        for name in sorted(imports_for(path)):
            if name.startswith(prefixes):
                hits.append(f"{path.relative_to(ROOT)} -> {name}")
    return hits


def imported_names_from(path: Path, module: str) -> tuple[set[str], bool]:
    """Return names imported from one module and whether the module is imported directly."""
    if not path.exists():
        return set(), False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    direct_module_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import) and any(
            alias.name == module for alias in node.names
        ):
            direct_module_import = True
    return names, direct_module_import


def current_sha() -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and len(value) == 40 else None


def defines_function(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        for node in tree.body
    )


def python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def product_domain_files() -> list[Path]:
    files: list[Path] = []
    for rel in [
        "files_server.py",
        "search_server.py",
        "commands_server.py",
        "command_contracts.py",
        "command_execution.py",
        "command_status.py",
    ]:
        files.append(SRC / rel)
    files.extend(sorted((SRC / "tools").glob("*.py")))
    files.extend(sorted(SRC.glob("search_text_*.py")))
    return files


def has_custom_route() -> bool:
    for path in python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "custom_route":
                return True
    return False


def report() -> list[Cell]:
    cells: list[Cell] = []

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    stable_fastmcp = "fastmcp==4.0.10" in pyproject
    cells.append(
        Cell(
            "composition.stable_fastmcp_4",
            "PASS" if stable_fastmcp else "FAIL",
            "fastmcp==4.0.10 pinned"
            if stable_fastmcp
            else "FastMCP 4.0.10 pin missing",
        )
    )

    root_factory = defines_function(SRC / "server.py", "create_server")
    cells.append(
        Cell(
            "composition.explicit_root_construction",
            "PASS" if root_factory else "FAIL",
            "server.create_server exists"
            if root_factory
            else "server.create_server missing",
        )
    )

    child_factories = {
        "files": (SRC / "files_server.py", "create_files_server"),
        "search": (SRC / "search_server.py", "create_search_server"),
        "commands": (SRC / "commands_server.py", "create_commands_server"),
    }
    for domain, (path, factory) in child_factories.items():
        present = defines_function(path, factory)
        cells.append(
            Cell(
                f"composition.{domain}_focused_child",
                "PASS" if present else "FAIL",
                f"{path.relative_to(ROOT)}::{factory} {'exists' if present else 'missing'}",
            )
        )

    registry_text = (SRC / "tools" / "__init__.py").read_text(encoding="utf-8")
    server_text = (SRC / "server.py").read_text(encoding="utf-8")
    registry_removed = (
        "register_all" not in registry_text and "register_all" not in server_text
    )
    cells.append(
        Cell(
            "composition.hardcoded_registry_removed",
            "PASS" if registry_removed else "FAIL",
            "no tools.register_all composition path"
            if registry_removed
            else "tools.register_all still referenced",
        )
    )

    cells.append(
        Cell(
            "composition.no_duplicate_framework",
            "PENDING",
            "final architecture review must confirm no generic Feature/Builder/DI/provider framework",
            evidence="review",
        )
    )

    fastmcp_importers = []
    for path in python_files():
        if any(
            name == "fastmcp" or name.startswith("fastmcp.")
            for name in imports_for(path)
        ):
            fastmcp_importers.append(str(path.relative_to(ROOT)))
    cells.append(
        Cell(
            "architecture.fastmcp_boundary",
            "PENDING",
            "final G6 package layout must confine FastMCP imports to MCP-facing modules; "
            f"current importers={','.join(fastmcp_importers)}",
            evidence="review",
        )
    )

    cells.append(
        Cell(
            "architecture.package_convergence",
            "PENDING",
            "G6 relocation and compatibility-facade removal have not started",
            evidence="review",
        )
    )

    unclassified, duplicate = manifest_coverage()
    manifest_ok = not unclassified and not duplicate
    detail_parts = [f"{len(python_files())} production modules singly classified"]
    if unclassified:
        detail_parts.append("unclassified=" + ",".join(unclassified))
    if duplicate:
        detail_parts.append(
            "duplicate/stale="
            + ";".join(
                f"{path}:{','.join(groups)}"
                for path, groups in sorted(duplicate.items())
            )
        )
    cells.append(
        Cell(
            "architecture.g6_manifest_coverage",
            "PASS" if manifest_ok else "FAIL",
            "; ".join(detail_parts),
        )
    )

    missing_facades, facade_owners = compatibility_facade_coverage()
    facade_bad = {
        path: groups for path, groups in facade_owners.items() if len(groups) != 1
    }
    facade_ok = not missing_facades and not facade_bad
    facade_detail = [
        f"{len(facade_owners)} compatibility facades tracked before G6 removal review"
    ]
    if missing_facades:
        facade_detail.append("missing=" + ",".join(missing_facades))
    if facade_bad:
        facade_detail.append(
            "ownership="
            + ";".join(
                f"{path}:{','.join(groups) or '<none>'}"
                for path, groups in sorted(facade_bad.items())
            )
        )
    cells.append(
        Cell(
            "architecture.g6_compatibility_facade_inventory",
            "PASS" if facade_ok else "FAIL",
            "; ".join(facade_detail),
        )
    )

    required_contracts = {
        "platform.process_contract": SRC / "process_contracts.py",
        "platform.resource_contract": SRC / "resource_contracts.py",
        "platform.service_log_contract": SRC / "service_log_contracts.py",
        "platform.managed_service_contract": SRC / "service_lifecycle_contracts.py",
        "platform.runtime_path_contract": SRC / "runtime_path_contracts.py",
    }
    for ident, path in required_contracts.items():
        cells.append(
            Cell(
                ident,
                "PASS" if path.exists() else "FAIL",
                f"{path.relative_to(ROOT)} {'exists' if path.exists() else 'missing'}",
            )
        )

    linux_impls = (
        "binnacle.job_process",
        "binnacle.job_cgroup",
        "binnacle.service_systemd",
        "binnacle.service_journal",
        "binnacle.service_provisioning_linux",
        "binnacle.service_unit_linux",
        "binnacle.runtime_paths_linux",
    )
    product_hits = any_import(product_domain_files(), linux_impls)
    cells.append(
        Cell(
            "platform.product_domains_no_linux_imports",
            "FAIL" if product_hits else "PASS",
            "; ".join(product_hits)
            if product_hits
            else "no direct Linux-adapter imports",
        )
    )

    doctor_hits = any_import(
        [SRC / "doctor.py", SRC / "doctor_connectivity.py"],
        ("binnacle.uplink", "binnacle.ops.watchdog", "binnacle.watchdog"),
    )
    cells.append(
        Cell(
            "companion.core_doctor_no_watchdog_uplink",
            "FAIL" if doctor_hits else "PASS",
            "; ".join(doctor_hits) if doctor_hits else "no watchdog/uplink imports",
        )
    )

    cli_hits = any_import(
        [SRC / "cli.py"],
        ("binnacle.webminstats", "binnacle.watchdog", "binnacle.ops.watchdog"),
    )
    cells.append(
        Cell(
            "companion.core_cli_no_watchdog_webmin",
            "FAIL" if cli_hits else "PASS",
            "; ".join(cli_hits) if cli_hits else "no watchdog/Webmin imports",
        )
    )

    cells.append(
        Cell(
            "companion.operational_http_surface",
            "PASS" if has_custom_route() else "FAIL",
            "FastMCP custom_route registered"
            if has_custom_route()
            else "no custom_route registered",
        )
    )

    companion_edge_specs = [
        (
            "companion.watchdog_doctor_no_core_aggregate",
            SRC / "watchdog_doctor.py",
            ("binnacle.doctor",),
            "watchdog doctor no longer imports the core doctor aggregate",
        ),
        (
            "companion.tunnel_doctor_no_core_connectivity_impl",
            SRC / "tunnel_doctor.py",
            ("binnacle.doctor_connectivity",),
            "tunnel doctor no longer imports core connectivity implementation",
        ),
        (
            "companion.watchdog_cli_no_core_cli",
            SRC / "watchdog_cli.py",
            ("binnacle.cli",),
            "watchdog CLI no longer imports the core CLI aggregate",
        ),
        (
            "companion.tunnel_cli_no_core_cli",
            SRC / "tunnel_cli.py",
            ("binnacle.cli",),
            "tunnel CLI no longer imports the core CLI aggregate",
        ),
        (
            "companion.watchdog_services_no_tunnel_doctor_impl",
            SRC / "ops" / "watchdog" / "services.py",
            ("binnacle.tunnel_doctor",),
            "watchdog services no longer import tunnel doctor implementation",
        ),
    ]
    for ident, path, prefixes, clean_detail in companion_edge_specs:
        hits = any_import([path], prefixes)
        cells.append(
            Cell(
                ident,
                "FAIL" if hits else "PASS",
                "; ".join(hits) if hits else clean_detail,
            )
        )

    tunnel_names, tunnel_module_import = imported_names_from(
        SRC / "watchdog_cli.py", "binnacle.tunnel_unit"
    )
    narrow_tunnel_contract = (
        tunnel_names in (set(), {"TUNNEL_UNIT"}) and not tunnel_module_import
    )
    if not tunnel_names and not tunnel_module_import:
        tunnel_detail = "no watchdog CLI dependency on tunnel unit internals"
    elif narrow_tunnel_contract:
        tunnel_detail = (
            "watchdog CLI imports only the approved public service identity "
            "binnacle.tunnel_unit.TUNNEL_UNIT"
        )
    else:
        shown = ",".join(sorted(tunnel_names)) or "<module>"
        tunnel_detail = (
            "watchdog CLI widens the approved tunnel-unit contract: "
            f"names={shown}, direct_module_import={tunnel_module_import}"
        )
    cells.append(
        Cell(
            "companion.watchdog_tunnel_unit_contract",
            "PASS" if narrow_tunnel_contract else "FAIL",
            tunnel_detail,
        )
    )

    core_paths = [
        p
        for p in python_files()
        if "ops/watchdog" not in p.as_posix()
        and p.name
        not in {
            "watchdog.py",
            "watchdog_cli.py",
            "watchdog_doctor.py",
            "watchdog_config.py",
            "watchdog_unit.py",
            "watchlog.py",
            "uplink.py",
            "webminstats.py",
            "tunnel_cli.py",
            "tunnel_doctor.py",
            "tunnel_unit.py",
        }
    ]
    watchdog_hits = any_import(
        core_paths,
        ("binnacle.ops.watchdog", "binnacle.watchdog"),
    )
    cells.append(
        Cell(
            "companion.server_core_platform_no_watchdog_impl",
            "FAIL" if watchdog_hits else "PASS",
            "; ".join(watchdog_hits)
            if watchdog_hits
            else "no watchdog implementation imports",
        )
    )

    # These require execution/evidence binding and must not be inferred from source.
    for ident, detail in [
        (
            "companion.server_works_without_watchdog",
            "requires runtime construction/import test with watchdog unavailable",
        ),
        ("convergence.full_suite", "requires exact-final-SHA managed full suite"),
        (
            "convergence.python_matrix",
            "requires exact-final-SHA supported Python matrix",
        ),
        ("convergence.coverage", "requires exact-final-SHA coverage policy"),
        ("convergence.packaging", "requires exact-final-SHA wheel/package smoke"),
        (
            "convergence.architecture",
            "requires final architecture/import gates after G6 moves",
        ),
        (
            "convergence.live_deploy",
            "requires canonical deployment of reviewed final SHA",
        ),
        ("convergence.linux_healthy", "requires post-deploy live smoke/doctors"),
        (
            "convergence.real_chatgpt_call",
            "requires real external ChatGPT read-only MCP call",
        ),
    ]:
        cells.append(Cell(ident, "PENDING", detail, evidence="external"))

    return cells


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    cells = report()
    payload = {
        "kind": "gate-a-preparation-report",
        "candidate": current_sha(),
        "cells": [asdict(cell) for cell in cells],
        "summary": {
            "pass": sum(cell.status == "PASS" for cell in cells),
            "fail": sum(cell.status == "FAIL" for cell in cells),
            "pending": sum(cell.status == "PENDING" for cell in cells),
        },
    }
    print(json.dumps(payload, indent=2))
    if args.strict and any(cell.status != "PASS" for cell in cells):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
