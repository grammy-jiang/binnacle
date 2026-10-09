#!/usr/bin/env python3
"""G7 fail-closed retirement gate: legacy filenames and imports must stay absent.

The historical list is deliberately frozen, independent of the current source tree.
This prevents reintroducing a retired compatibility alias unnoticed.
"""

from __future__ import annotations

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


def failures(root: Path = SRC) -> list[str]:
    files = [f"legacy file remains: {name}" for name in existing_retired_files(root)]
    imports = [f"legacy import remains: {line}" for line in legacy_imports(root)]
    return files + imports


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
