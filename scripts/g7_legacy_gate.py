#!/usr/bin/env python3
"""G7 fail-closed retirement gate: legacy filenames and imports must stay absent.

The historical list is deliberately frozen, independent of the current source tree.
This prevents reintroducing a retired compatibility alias unnoticed.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_architecture import imports_of, module_name

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "binnacle"

RETIRED_FILES = frozenset(
    (
        "callctx.py",
        "command_backend.py",
        "command_contracts.py",
        "command_execution.py",
        "command_status.py",
        "commands_server.py",
        "diagnostics/doctor_contracts.py",
        "doctor.py",
        "doctor_common.py",
        "doctor_connectivity.py",
        "doctor_io.py",
        "doctor_jobs.py",
        "doctor_provenance.py",
        "doctor_render.py",
        "identity.py",
        "job_client.py",
        "job_manager.py",
        "job_manager_doctor.py",
        "job_manager_unit.py",
        "job_output.py",
        "job_owner.py",
        "job_resource_history.py",
        "job_store.py",
        "jobs.py",
        "logging_middleware.py",
        "logstats.py",
        "logstats_adaptive.py",
        "logstats_io.py",
        "logstats_jobs.py",
        "logstats_models.py",
        "logstats_parse.py",
        "logstats_render.py",
        "logstats_run_command.py",
        "logstats_run_command_groups.py",
        "logstats_run_command_render.py",
        "logstats_search_exact.py",
        "logstats_tools.py",
        "ops/__init__.py",
        "ops/watchdog/__init__.py",
        "ops/watchdog/actions.py",
        "ops/watchdog/command.py",
        "ops/watchdog/config.py",
        "ops/watchdog/context.py",
        "ops/watchdog/cycle.py",
        "ops/watchdog/device_identity.py",
        "ops/watchdog/diagnostics.py",
        "ops/watchdog/fast.py",
        "ops/watchdog/hardware.py",
        "ops/watchdog/inventory.py",
        "ops/watchdog/lifecycle.py",
        "ops/watchdog/lock.py",
        "ops/watchdog/maintenance.py",
        "ops/watchdog/model.py",
        "ops/watchdog/network.py",
        "ops/watchdog/policy.py",
        "ops/watchdog/policy_recovery.py",
        "ops/watchdog/policy_routes.py",
        "ops/watchdog/policy_usb.py",
        "ops/watchdog/reporting.py",
        "ops/watchdog/schedule.py",
        "ops/watchdog/services.py",
        "ops/watchdog/tunnel.py",
        "paths.py",
        "run_command_evidence.py",
        "run_command_telemetry.py",
        "server_unit.py",
        "service_journal.py",
        "service_unit_linux.py",
        "system_resource_contracts.py",
        "system_resource_history.py",
        "token_telemetry.py",
        "tool_order.py",
        "tools/__init__.py",
        "tools/job_status.py",
        "tools/run_command.py",
        "tools/search_text.py",
        "tools/stop_job.py",
        "tunnel_cli.py",
        "tunnel_doctor.py",
        "tunnel_log.py",
        "tunnel_log.pyi",
        "tunnel_unit.py",
        "tunnel_unit.pyi",
        "units.py",
        "uplink.py",
        "visibility.py",
        "watchdog.py",
        "watchdog_cli.py",
        "watchdog_config.py",
        "watchdog_connectivity.py",
        "watchdog_doctor.py",
        "watchdog_unit.py",
        "watchlog.py",
        "webminstats.py",
    )
)


def retired_module_name(relative_path: str) -> str:
    stem = relative_path.removesuffix(".pyi").removesuffix(".py")
    stem = stem.removesuffix("/__init__")
    return "binnacle." + stem.replace("/", ".")


RETIRED_MODULES = frozenset(retired_module_name(p) for p in RETIRED_FILES)


def is_retired_import(target: str) -> bool:
    return any(
        target == retired or target.startswith(retired + ".")
        for retired in RETIRED_MODULES
    )


def existing_retired_files(root: Path = SRC) -> list[str]:
    return sorted(path for path in RETIRED_FILES if (root / path).exists())


def legacy_imports(root: Path = SRC) -> list[str]:
    results: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.relative_to(root).as_posix() in RETIRED_FILES:
            continue
        source = module_name(path, root.parent)
        for imported in sorted(imports_of(path, source)):
            if is_retired_import(imported):
                results.append(f"{path.relative_to(root)} -> {imported}")
    return results


def _module_registry(node: ast.expr, sys_names: set[str], aliases: set[str]) -> bool:
    return (isinstance(node, ast.Name) and node.id in aliases) or (
        isinstance(node, ast.Attribute)
        and node.attr == "modules"
        and isinstance(node.value, ast.Name)
        and node.value.id in sys_names
    )


def _module_identity_writes(tree: ast.AST) -> list[int]:
    """Find prohibited sys.modules mutations, including explicit import aliases.

    Reading sys.modules is allowed. Assigning into the module registry is
    forbidden: it could turn any new canonical-looking file into a facade.
    """
    sys_names = {"sys"}
    registry_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sys":
                    sys_names.add(alias.asname or "sys")
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module == "sys"
        ):
            registry_names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "modules"
            )
    # Also catch simple rebinding: registry = sys.modules; registry[__name__] = impl.
    # This is deliberately static; do not execute any import or expression.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _module_registry(
            node.value, sys_names, registry_names
        ):
            registry_names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
    writes: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
            targets = (
                node.targets
                if isinstance(node, (ast.Assign, ast.Delete))
                else [node.target]
            )
            for target in targets:
                # Ordinary "registry = sys.modules" only reads the registry.
                # But augmented assignment updates the dict in place, and
                # deleting or assigning an entry mutates module identity.
                registry = (
                    target.value
                    if isinstance(target, ast.Subscript)
                    else target
                    if isinstance(target, ast.Attribute)
                    else target
                    if isinstance(node, ast.AugAssign)
                    else None
                )
                if registry is not None and _module_registry(
                    registry, sys_names, registry_names
                ):
                    writes.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr
            in {
                "setdefault",
                "update",
                "__setitem__",
                "pop",
                "popitem",
                "clear",
                "__delitem__",
            }
            and _module_registry(node.func.value, sys_names, registry_names)
        ):
            writes.append(node.lineno)
    return sorted(set(writes))


def facade_forwarders(root: Path = SRC) -> list[str]:
    """Guard against reintroducing identity/lazy/star forwarding under any name."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in RETIRED_FILES:
            # The missing-file gate already rejects these paths, even if a
            # newly reintroduced module contains syntactically invalid code.
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno in _module_identity_writes(tree):
            violations.append(f"{rel}:{lineno}: sys.modules mutation")
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "*" for alias in node.names
            ):
                violations.append(f"{rel}:{node.lineno}: star re-export")
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "__getattr__"
            ):
                violations.append(f"{rel}:{node.lineno}: module-level __getattr__")
    return violations


def failures(root: Path = SRC) -> list[str]:
    files = [f"legacy file remains: {name}" for name in existing_retired_files(root)]
    imports = [f"legacy import remains: {line}" for line in legacy_imports(root)]
    facades = [f"identity facade remains: {line}" for line in facade_forwarders(root)]
    return files + imports + facades


def main() -> int:
    errors = failures()
    for message in errors:
        print(f"ERROR: {message}", file=sys.stderr)
    print(
        f"G7 legacy gate: {len(RETIRED_FILES)} retired paths, "
        f"{len(RETIRED_MODULES)} module names, {len(errors)} failures"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
