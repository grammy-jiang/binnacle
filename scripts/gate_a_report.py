#!/usr/bin/env python3
"""Preliminary Gate A source-state report.

This is a preparation harness, not the final acceptance gate. Default mode reports
current static/PENDING status and exits zero. --strict fails while any item is not PASS.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path

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
        "candidate": None,
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
