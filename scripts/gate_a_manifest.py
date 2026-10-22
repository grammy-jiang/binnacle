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
        "root": {
            "server.py",
            "application.py",
            "config_maintenance.py",
            "startup_imports.py",
            "manager_bootstrap.py",
            "job_manager_cli.py",
            "entrypoint.py",
            "startup_server_modules.py",
        },
        "feature_namespace": {"features/__init__.py"},
        "mcp": {
            "mcp/__init__.py",
            "mcp/identity.py",
            "mcp/logging_middleware.py",
            "mcp/logging_setup.py",
            "mcp/tool_admission_drain.py",
            "mcp/maintenance_request_admission.py",
            "mcp/visibility.py",
            "mcp/callctx.py",
            "mcp/tool_order.py",
        },
        "files": {
            "features/files/__init__.py",
            "features/files/files_server.py",
            "features/files/tools/__init__.py",
            "features/files/tools/read_file.py",
            "features/files/tools/list_files.py",
            "features/files/list_files_glob.py",
            "features/files/tools/edit_file.py",
            "features/files/tools/write_file.py",
            "features/files/paths.py",
            "features/files/file_tool_access.py",
            "features/files/error_text.py",
            "features/files/textio.py",
            "features/files/fd_walk.py",
            "features/files/fd_write.py",
            "features/files/fd_chain.py",
            "features/files/rg_env.py",
        },
        "search": {
            "features/search/__init__.py",
            "features/search/search_server.py",
            "features/search/tools/__init__.py",
            "features/search/tools/search_text.py",
            *(rel(path) for path in SRC.glob("features/search/search_text_*.py")),
        },
        "commands": {
            "features/commands/commands_server.py",
            "features/commands/tools/__init__.py",
            "features/commands/tools/run_command.py",
            "features/commands/tools/job_status.py",
            "features/commands/tools/stop_job.py",
            "features/commands/__init__.py",
            "features/commands/command_contracts.py",
            "features/commands/command_execution.py",
            "features/commands/command_status.py",
            "features/commands/command_backend.py",
            "features/commands/restricted_backend.py",
            "features/commands/run_command_telemetry.py",
            "features/commands/run_command_evidence.py",
            "features/commands/jobs.py",
            "features/commands/job_stop.py",
            "features/commands/job_client.py",
            "features/commands/job_manager.py",
            "features/commands/job_output.py",
            "features/commands/job_owner.py",
            "features/commands/job_resource_history.py",
            "features/commands/job_store.py",
        },
        # Reviewed P2.0–P3.1 Development Intelligence; one source owner per
        # module, NOT a wildcard that silently admits new adapters into CI.
        "development_intelligence": {
            "features/development_intelligence/__init__.py",
            "features/development_intelligence/lsp_authorized_session.py",
            "features/development_intelligence/lsp_client.py",
            "features/development_intelligence/lsp_document_sync.py",
            "features/development_intelligence/lsp_manager_cooldown.py",
            "features/development_intelligence/lsp_manager_eviction.py",
            "features/development_intelligence/lsp_manager_shutdown.py",
            "features/development_intelligence/lsp_manager_types.py",
            "features/development_intelligence/lsp_policy.py",
            "features/development_intelligence/lsp_preview_mount.py",
            "features/development_intelligence/lsp_preview_server.py",
            "features/development_intelligence/lsp_profile_assessment.py",
            "features/development_intelligence/lsp_process_owner.py",
            "features/development_intelligence/lsp_process_tree.py",
            "features/development_intelligence/lsp_provider_manager.py",
            "features/development_intelligence/lsp_session.py",
            "features/development_intelligence/lsp_wire.py",
            "features/development_intelligence/lsp_workspace_access.py",
            "features/development_intelligence/lsp_workspace_policy.py",
        },
        # Inert, default-off Job Awareness: portable core plus SQLite ledger.
        # Mirrors the job-awareness-core-isolation import-linter contract.
        "job_awareness_core": {
            "features/commands/job_awareness/__init__.py",
            "features/commands/job_awareness/models.py",
            "features/commands/job_awareness/ports.py",
            "features/commands/job_awareness/identifiers.py",
            "features/commands/job_awareness/observation.py",
            "features/commands/job_awareness/snapshots.py",
            "features/commands/job_awareness/projection.py",
            "features/commands/job_awareness/receipts.py",
            "features/commands/job_awareness/grants.py",
            "features/commands/job_awareness/proofs.py",
            "features/commands/job_awareness/hint_policy.py",
            "features/commands/job_awareness/hint_render.py",
            "features/commands/job_awareness/receipt_schema.py",
            "features/commands/job_awareness/receipt_store.py",
        },
        # Native FastMCP adapter modules; mirrors job-awareness-adapter-isolation.
        "job_awareness_adapter": {
            "mcp/job_awareness_hint.py",
            "mcp/job_awareness_hint_schema.py",
            "mcp/job_awareness_hint_walk.py",
            "mcp/job_awareness_hint_identity.py",
        },
        "platform_contracts": {
            "platform/__init__.py",
            "platform/contracts/__init__.py",
            "platform/contracts/process_contracts.py",
            "platform/contracts/resource_contracts.py",
            "platform/contracts/service_log_contracts.py",
            "platform/contracts/service_lifecycle_contracts.py",
            "platform/contracts/runtime_path_contracts.py",
            "platform/contracts/capability_contracts.py",
            "platform/contracts/darwin_contracts.py",
            "platform/contracts/darwin_release_scope.py",
            "platform/contracts/file_access_contracts.py",
            "platform/contracts/metric_log_contracts.py",
            "platform/contracts/native_service_contracts.py",
            "platform/contracts/maintenance_contracts.py",
            "platform/contracts/stop_contracts.py",
            "platform/contracts/special_file_contracts.py",
        },
        "platform_composition": {
            "platform/deployment_platform.py",
            "platform/job_platform.py",
            "platform/composition.py",
        },
        # Neutral, writer-injected runtime helper, not another OS selector.
        "platform_service_output": {"platform/native_output.py"},
        "platform_linux": {
            "platform/linux/__init__.py",
            "platform/linux/job_process.py",
            "platform/linux/job_identity.py",
            "platform/linux/notify_systemd.py",
            "platform/linux/job_cgroup.py",
            "platform/linux/service_journal.py",
            "platform/linux/service_systemd.py",
            "platform/linux/service_provisioning_linux.py",
            "platform/linux/runtime_paths_linux.py",
        },
        "platform_darwin": {
            "platform/darwin/__init__.py",
            "platform/darwin/file_access.py",
            "platform/darwin/file_io.py",
            "platform/darwin/file_traversal.py",
            "platform/darwin/generation_publish.py",
            "platform/darwin/generation_runtime.py",
            "platform/darwin/ipc_transport.py",
            "platform/darwin/job_group_fence.py",
            "platform/darwin/job_manager_client.py",
            "platform/darwin/job_manager_config.py",
            "platform/darwin/job_manager_entry.py",
            "platform/darwin/job_manager_procinfo.py",
            "platform/darwin/job_manager_queue.py",
            "platform/darwin/job_manager_lifecycle.py",
            "platform/darwin/job_manager_records.py",
            "platform/darwin/job_manager_service.py",
            "platform/darwin/job_manager_maintenance_fence.py",
            "platform/darwin/job_manager_telemetry.py",
            "platform/darwin/daemon_logstats.py",
            "platform/darwin/job_manager_start.py",
            "platform/darwin/job_manager_stopping.py",
            "platform/darwin/job_process_owner.py",
            "platform/darwin/log_maintenance_transaction.py",
            "platform/darwin/log_maintenance_observer.py",
            "platform/darwin/log_maintenance_recovery_policy.py",
            "platform/darwin/log_maintenance_recovery_rpc.py",
            "platform/darwin/log_maintenance_installed_identity.py",
            "platform/darwin/log_maintenance_fd_evidence.py",
            "platform/darwin/mcp_maintenance_admission_rpc.py",
            "platform/darwin/mcp_maintenance_admission_runtime.py",
            "platform/darwin/log_cursor.py",
            "platform/darwin/log_source.py",
            "platform/darwin/process_authority.py",
            "platform/darwin/process_backend.py",
            "platform/darwin/resource_accounting.py",
            "platform/darwin/search_access.py",
            "platform/darwin/service_launchd.py",
            "platform/darwin/witness_protocol.py",
        },
        "diagnostics": {
            "diagnostics/__init__.py",
            "diagnostics/doctor_io.py",
            "diagnostics/doctor_render.py",
            "diagnostics/doctor_provenance.py",
            "diagnostics/doctor_config_keys.py",
            "diagnostics/doctor_connectivity.py",
            "diagnostics/darwin_doctor.py",
            "diagnostics/doctor.py",
            "diagnostics/doctor_common.py",
            "diagnostics/doctor_jobs.py",
            "diagnostics/job_manager_doctor.py",
        },
        "diagnostics_linux": {"diagnostics/linux_checks.py"},
        "deployment_linux": {
            "deployment/linux/__init__.py",
            "deployment/linux/unit_inspection.py",
        },
        "deployment_darwin": {
            "deployment/darwin/__init__.py",
            "deployment/darwin/plist.py",
            "deployment/darwin/provisioner.py",
            "deployment/darwin/setup.py",
            "deployment/darwin/installed_cli.py",
            "deployment/darwin/installed_mode.py",
        },
        "observability": {
            "observability/__init__.py",
            *(rel(path) for path in (SRC / "observability").glob("logstats*.py")),
            "observability/system_resource_contracts.py",
            "observability/system_resource_history.py",
            "observability/token_telemetry.py",
            "observability/log_safety.py",
            "observability/full_capture.py",
        },
        "observability_linux": {
            "observability/linux/__init__.py",
            "observability/linux/webminstats.py",
        },
        "deployment": {
            "deployment/__init__.py",
            "deployment/units.py",
            "deployment/server_unit.py",
            "deployment/job_manager_unit.py",
            "deployment/provisioning_contracts.py",
        },
        "tunnel": {
            "companions/__init__.py",
            "companions/tunnel/__init__.py",
            "companions/tunnel/tunnel_cli.py",
            "companions/tunnel/tunnel_doctor.py",
            "companions/tunnel/tunnel_log.py",
            "companions/tunnel/tunnel_unit.py",
        },
        "watchdog": {
            "companions/darwin_log_archive_stage.py",
            "companions/darwin_log_archive_finalize.py",
            "companions/darwin_log_transaction_controller.py",
            "companions/darwin_log_maintenance_admission.py",
            "companions/darwin_log_j7_interlocks.py",
            "companions/darwin_log_writer_hold.py",
            "companions/darwin_log_maintenance_guardian.py",
            "companions/darwin_log_privacy.py",
            "companions/resource_monitor_darwin.py",
            "companions/service_watchdog.py",
            "companions/service_watchdog_maintenance.py",
            "companions/service_watchdog_deploy.py",
            "companions/service_watchdog_safety.py",
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
        },
        "application_shell": {
            "__init__.py",
            "auto_background_shell.py",
            "cli.py",
            "config.py",
            "config_unknown_keys.py",
            "config_telemetry.py",
            "config_development_intelligence.py",
            "errors.py",
            "provenance.py",
            "doctor_contracts.py",
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
