"""Preparation-only G6 ownership manifest coverage checks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "binnacle"


def python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def manifest_groups() -> dict[str, set[str]]:
    """Classify each current production module into one planned ownership group."""

    def rel(path: Path) -> str:
        return path.relative_to(SRC).as_posix()

    return {
        "root": {"server.py"},
        "feature_namespace": {"features/__init__.py"},
        "mcp": {
            "mcp/__init__.py",
            "mcp/identity.py",
            "mcp/logging_middleware.py",
            "mcp/visibility.py",
            "mcp/callctx.py",
            "mcp/tool_order.py",
            "identity.py",
            "logging_middleware.py",
            "visibility.py",
            "callctx.py",
            "tool_order.py",
            "tools/__init__.py",
        },
        "files": {
            "features/files/__init__.py",
            "features/files/files_server.py",
            "features/files/tools/__init__.py",
            "features/files/tools/read_file.py",
            "features/files/tools/list_files.py",
            "features/files/tools/edit_file.py",
            "features/files/tools/write_file.py",
            "features/files/paths.py",
            "features/files/textio.py",
            "paths.py",
        },
        "search": {
            "features/search/__init__.py",
            "features/search/search_server.py",
            "features/search/tools/__init__.py",
            "features/search/tools/search_text.py",
            "tools/search_text.py",
            *(rel(path) for path in SRC.glob("features/search/search_text_*.py")),
        },
        "commands": {
            "commands_server.py",
            "features/commands/commands_server.py",
            "tools/run_command.py",
            "tools/job_status.py",
            "tools/stop_job.py",
            "run_command_telemetry.py",
            "run_command_evidence.py",
            "features/commands/tools/__init__.py",
            "features/commands/tools/run_command.py",
            "features/commands/tools/job_status.py",
            "features/commands/tools/stop_job.py",
            "command_contracts.py",
            "features/commands/__init__.py",
            "features/commands/command_contracts.py",
            "command_execution.py",
            "features/commands/command_execution.py",
            "command_status.py",
            "features/commands/command_status.py",
            "command_backend.py",
            "features/commands/command_backend.py",
            "features/commands/run_command_telemetry.py",
            "features/commands/run_command_evidence.py",
            "features/commands/jobs.py",
            "features/commands/job_client.py",
            "features/commands/job_manager.py",
            "features/commands/job_output.py",
            "features/commands/job_owner.py",
            "features/commands/job_resource_history.py",
            "features/commands/job_store.py",
            "jobs.py",
            "job_client.py",
            "job_manager.py",
            "job_output.py",
            "job_owner.py",
            "job_resource_history.py",
            "job_store.py",
        },
        "platform_contracts": {
            "platform/__init__.py",
            "platform/contracts/__init__.py",
            "platform/contracts/process_contracts.py",
            "platform/contracts/resource_contracts.py",
            "platform/contracts/service_log_contracts.py",
            "platform/contracts/service_lifecycle_contracts.py",
            "platform/contracts/runtime_path_contracts.py",
        },
        "platform_composition": {
            "platform/deployment_platform.py",
            "platform/job_platform.py",
        },
        "platform_linux": {
            "platform/linux/__init__.py",
            "platform/linux/job_process.py",
            "platform/linux/job_cgroup.py",
            "platform/linux/service_journal.py",
            "platform/linux/service_systemd.py",
            "platform/linux/service_provisioning_linux.py",
            "platform/linux/runtime_paths_linux.py",
            "service_journal.py",
            "service_unit_linux.py",
            "platform/linux/service_unit_linux.py",
        },
        "diagnostics": {
            "diagnostics/__init__.py",
            "diagnostics/doctor_contracts.py",
            "diagnostics/doctor_io.py",
            "diagnostics/doctor_render.py",
            "diagnostics/doctor_provenance.py",
            "diagnostics/doctor_connectivity.py",
            "doctor.py",
            "doctor_common.py",
            "doctor_contracts.py",
            "doctor_connectivity.py",
            "doctor_jobs.py",
            "doctor_provenance.py",
            "doctor_io.py",
            "doctor_render.py",
            "job_manager_doctor.py",
        },
        "observability": {
            "observability/__init__.py",
            *(rel(path) for path in SRC.glob("logstats*.py")),
            *(rel(path) for path in (SRC / "observability").glob("logstats*.py")),
            "observability/system_resource_contracts.py",
            "observability/system_resource_history.py",
            "observability/token_telemetry.py",
            "system_resource_contracts.py",
            "system_resource_history.py",
            "token_telemetry.py",
        },
        "observability_linux": {
            "webminstats.py",
            "observability/linux/__init__.py",
            "observability/linux/webminstats.py",
        },
        "deployment": {
            "deployment/__init__.py",
            "deployment/units.py",
            "deployment/server_unit.py",
            "deployment/job_manager_unit.py",
            "units.py",
            "server_unit.py",
            "job_manager_unit.py",
        },
        "tunnel": {
            "companions/__init__.py",
            "companions/tunnel/__init__.py",
            "companions/tunnel/tunnel_cli.py",
            "companions/tunnel/tunnel_doctor.py",
            "companions/tunnel/tunnel_log.py",
            "companions/tunnel/tunnel_unit.py",
            "tunnel_cli.py",
            "tunnel_doctor.py",
            "tunnel_log.py",
            "tunnel_unit.py",
        },
        "watchdog": {
            "companions/watchdog/__init__.py",
            "companions/watchdog/watchdog.py",
            "companions/watchdog/watchdog_cli.py",
            "companions/watchdog/watchdog_doctor.py",
            "companions/watchdog/watchdog_config.py",
            "companions/watchdog/watchdog_connectivity.py",
            "companions/watchdog/watchdog_unit.py",
            "companions/watchdog/watchlog.py",
            "companions/watchdog/uplink.py",
            "companions/watchdog/ops/__init__.py",
            *(
                rel(path)
                for path in (SRC / "companions" / "watchdog" / "ops").glob("*.py")
            ),
            "watchdog.py",
            "watchdog_cli.py",
            "watchdog_doctor.py",
            "watchdog_config.py",
            "watchdog_connectivity.py",
            "watchdog_unit.py",
            "watchlog.py",
            "uplink.py",
            "ops/__init__.py",
            *(rel(path) for path in (SRC / "ops" / "watchdog").rglob("*.py")),
        },
        "application_shell": {
            "__init__.py",
            "cli.py",
            "config.py",
            "errors.py",
            "provenance.py",
        },
    }


def manifest_coverage() -> tuple[list[str], dict[str, list[str]]]:
    """Return unclassified and duplicate/stale manifest entries."""

    actual = {path.relative_to(SRC).as_posix() for path in python_files()}
    owners: dict[str, list[str]] = {}
    for group, paths in manifest_groups().items():
        for path in paths:
            owners.setdefault(path, []).append(group)

    unclassified = sorted(actual - set(owners))
    duplicate = {path: groups for path, groups in owners.items() if len(groups) != 1}
    for path in sorted(set(owners) - actual):
        duplicate[path] = ["stale-manifest-entry", *owners[path]]
    return unclassified, duplicate


def compatibility_facades() -> set[str]:
    """Current compatibility facades that G6 must review before removal."""
    return {
        "doctor_common.py",
        "doctor_contracts.py",
        "doctor_io.py",
        "doctor_render.py",
        "identity.py",
        "logging_middleware.py",
        "visibility.py",
        "callctx.py",
        "tool_order.py",
        "paths.py",
        "jobs.py",
        "job_client.py",
        "job_manager.py",
        "job_output.py",
        "job_owner.py",
        "job_resource_history.py",
        "job_store.py",
        "tunnel_cli.py",
        "tunnel_doctor.py",
        "tunnel_log.py",
        "tunnel_unit.py",
        "watchdog.py",
        "watchdog_cli.py",
        "watchdog_doctor.py",
        "watchdog_config.py",
        "watchdog_connectivity.py",
        "watchdog_unit.py",
        "watchlog.py",
        "uplink.py",
        *(
            path.relative_to(SRC).as_posix()
            for path in (SRC / "ops" / "watchdog").glob("*.py")
        ),
        "webminstats.py",
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
        "system_resource_contracts.py",
        "system_resource_history.py",
        "token_telemetry.py",
        "service_journal.py",
        "service_unit_linux.py",
        "units.py",
        "server_unit.py",
        "job_manager_unit.py",
        "tools/search_text.py",
        "command_contracts.py",
        "command_backend.py",
        "command_execution.py",
        "command_status.py",
        "commands_server.py",
        "tools/run_command.py",
        "tools/job_status.py",
        "tools/stop_job.py",
        "run_command_telemetry.py",
        "run_command_evidence.py",
    }


def compatibility_facade_coverage() -> tuple[list[str], dict[str, list[str]]]:
    """Return missing facades and their current ownership groups."""
    actual = {path.relative_to(SRC).as_posix() for path in python_files()}
    missing = sorted(compatibility_facades() - actual)
    groups = manifest_groups()
    owners: dict[str, list[str]] = {}
    for facade in sorted(compatibility_facades() & actual):
        owners[facade] = sorted(
            group for group, paths in groups.items() if facade in paths
        )
    return missing, owners
