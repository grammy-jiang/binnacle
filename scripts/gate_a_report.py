#!/usr/bin/env python3
"""Preliminary Gate A source-state report.

This is a preparation harness, not the final acceptance gate. Default mode reports
current static/PENDING status and exits zero. --strict fails while any item is not PASS.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.gate_a_evidence import build_payload
from scripts.gate_a_manifest import (
    compatibility_facade_coverage,
    manifest_coverage,
    manifest_groups,
)
from scripts.gate_a_source import (
    has_root_health_route,
    imported_names_from,
    imports_for,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "binnacle"


@dataclass(frozen=True)
class Cell:
    id: str
    status: str
    detail: str
    evidence: str = "static"


def any_import(paths: list[Path], prefixes: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        for name in sorted(imports_for(path)):
            if any(
                name == prefix or name.startswith(prefix + ".") for prefix in prefixes
            ):
                hits.append(f"{path.relative_to(ROOT)} -> {name}")
    return hits


def git_environment() -> dict[str, str]:
    names = subprocess.check_output(
        ["git", "rev-parse", "--local-env-vars"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    return {key: value for key, value in os.environ.items() if key not in names}


def current_sha() -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        env=git_environment(),
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


def group_paths(*groups: str) -> list[Path]:
    owners = manifest_groups()
    return sorted({SRC / rel for group in groups for rel in owners[group]})


def product_domain_files() -> list[Path]:
    return group_paths("files", "search", "commands")


def companion_modules() -> tuple[str, ...]:
    return tuple(
        "binnacle." + p.relative_to(SRC).with_suffix("").as_posix().replace("/", ".")
        for p in group_paths("watchdog", "tunnel")
        if p.name != "__init__.py"
    )


def has_custom_route() -> bool:
    return has_root_health_route(SRC / "server.py")


def clean_snapshot() -> str | None:
    sha = current_sha()
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        env=git_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    return sha if proc.returncode == 0 and not proc.stdout else None


def collect_report() -> dict:
    before = clean_snapshot()
    cells = report()
    after = clean_snapshot()
    bound = before is not None and before == after
    cells.insert(
        0,
        Cell(
            "evidence.source_snapshot_bound",
            "PASS" if bound else "FAIL",
            "clean unchanged HEAD"
            if bound
            else "source snapshot is dirty, unavailable, or changed",
        ),
    )
    return build_payload(cells, candidate=before if bound else None)


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
        group_paths("diagnostics"),
        companion_modules(),
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
            "root literal GET /healthz registered with include_in_schema=False; payload/auth require tests"
            if has_custom_route()
            else "required root health route registration missing",
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
        tunnel_names == {"TUNNEL_UNIT"} and not tunnel_module_import
    )
    if not tunnel_names and not tunnel_module_import:
        tunnel_detail = "required TUNNEL_UNIT identity import missing"
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

    companion_paths = set(group_paths("watchdog", "tunnel"))
    core_paths = [p for p in python_files() if p not in companion_paths]
    watchdog_hits = any_import(core_paths, companion_modules())
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
        (
            "companion.healthz_http_behavior",
            "requires exact unauthenticated health payload and unchanged MCP auth/wire tests",
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

    payload = collect_report()
    print(json.dumps(payload, indent=2))
    if args.strict and any(cell["status"] != "PASS" for cell in payload["cells"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
