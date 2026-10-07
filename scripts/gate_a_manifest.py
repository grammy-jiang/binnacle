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
        "mcp": {
            "identity.py",
            "logging_middleware.py",
            "visibility.py",
            "callctx.py",
            "tool_order.py",
            "tools/__init__.py",
        },
        "files": {
            "files_server.py",
            "tools/read_file.py",
            "tools/list_files.py",
            "tools/edit_file.py",
            "tools/write_file.py",
            "paths.py",
            "textio.py",
        },
        "search": {
            "search_server.py",
            "tools/search_text.py",
            *(rel(path) for path in SRC.glob("search_text_*.py")),
        },
        "commands": {
            "commands_server.py",
            "tools/run_command.py",
            "tools/job_status.py",
            "tools/stop_job.py",
            "command_contracts.py",
            "command_execution.py",
            "command_status.py",
            "command_backend.py",
            "jobs.py",
            "job_client.py",
            "job_manager.py",
            "job_output.py",
            "job_owner.py",
            "job_resource_history.py",
            "job_store.py",
            "run_command_telemetry.py",
            "run_command_evidence.py",
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
        "platform_composition": {"deployment_platform.py", "job_platform.py"},
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
        },
        "diagnostics": {
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
            *(rel(path) for path in SRC.glob("logstats*.py")),
            "system_resource_contracts.py",
            "system_resource_history.py",
            "token_telemetry.py",
        },
        "observability_linux": {"webminstats.py"},
        "deployment": {
            "units.py",
            "server_unit.py",
            "job_manager_unit.py",
        },
        "tunnel": {
            "tunnel_cli.py",
            "tunnel_doctor.py",
            "tunnel_log.py",
            "tunnel_unit.py",
        },
        "watchdog": {
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
        "jobs.py",
        "watchdog.py",
        "logstats.py",
        "logstats_io.py",
        "service_journal.py",
        "service_unit_linux.py",
        "units.py",
        "tools/search_text.py",
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
