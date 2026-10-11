"""Skip-policy tables for native macOS runs (rows, pinned site counts)."""

import re

# Files that may hold a platform-conditioned or opt-in skip ("<lane>: <why>");
# only Darwin-package rows may name unmerged files. A new row needs review.
# LINUX_PIN_FILES hold one alias-based per-test skipif(sys.platform != "linux").
_PINS = """contracts/descriptions contracts/golden_outputs contracts/job_schemas
    contracts/job_spool_compat contracts/job_status_cursor_internal
    contracts/os_stage1_wire_parity contracts/search_text_surface
    contracts/server_composition contracts/tool_surface
    integration/composition_workflows integration/os_pure_application"""
LINUX_PIN_FILES = [
    p.replace("/", "/test_").join(("tests/", ".py")) for p in re.findall(r"\S+", _PINS)
]
_T0A9 = """
tests/integration/test_cli.py
tests/integration/test_commands_settings.py
tests/integration/test_http_workflows.py
tests/integration/test_job_manager.py
tests/integration/test_job_manager_reload.py
tests/integration/test_job_manager_telemetry.py
tests/integration/test_job_telemetry.py
tests/integration/test_jobs.py
tests/integration/test_jobs_lifecycle.py
tests/integration/test_jobs_lifecycle_stops.py
tests/integration/test_jobs_state_machine.py
tests/integration/test_jobs_stop_paths.py
tests/integration/test_jobs_store.py
tests/integration/test_log_privacy.py
tests/integration/test_logging_jobs.py
tests/integration/test_mounted_call_context.py
tests/integration/test_os_job_rpc_cross_version.py
tests/integration/test_packaging_smoke.py
tests/integration/test_root_settings.py
tests/scripts/test_deploy_smoke_env.py
tests/system/test_diagnostic_boundaries.py
tests/system/test_doctor.py
tests/system/test_doctor_coverage.py
tests/unit/core/test_command_backend.py
tests/unit/core/test_job_manager_edges.py
tests/unit/core/test_jobs_cgroup_integration.py
tests/unit/core/test_os_independence_paths.py
tests/unit/core/test_os_job_partial_persistence.py
tests/unit/core/test_platform_activation.py
tests/unit/core/test_process_contract.py
tests/unit/core/test_runtime_paths.py
tests/unit/core/test_units.py
"""
T0A9_PIN_FILES = _T0A9.split()
# Modules where EVERY test exercises the durable job engine/manager/store/RPC,
# which Darwin never runs by contract (CR0-04): a module-level LINUX_ONLY is
# allowed only here, and the node count is pinned in test_collection_contract.
LINUX_ONLY_MODULES = frozenset(
    f"tests/integration/{n}.py"
    for n in [
        "test_jobs",
        "test_jobs_lifecycle",
        "test_jobs_lifecycle_stops",
        "test_job_manager",
        "test_jobs_state_machine",
        "test_job_telemetry",
        "test_os_job_rpc_cross_version",
        "test_logging_jobs",
    ]
)
_ROWS = """
system/test_uplink_network.py | baseline: Linux SO_BINDTODEVICE / iproute2 only
live/test_deployment_smoke.py | baseline: opt-in live host (BINNACLE_LIVE=1)
scripts/test_macos_collection_native.py | T0: Darwin host probe (sw_vers); the rest of the module runs everywhere
platform/darwin/test_foreground_commands.py | A2: per-test Darwin posix_spawn owned-child mechanism
platform/darwin/test_process_native.py | A2: per-test Darwin kqueue/posix_spawn child and witness probes
platform/darwin/test_ipc_generation.py | A3: per-test Darwin getpeereid/LOCAL_PEERPID contract
platform/darwin/test_ipc_launchd.py | A3: per-test opt-in real launchd bootstrap (BINNACLE_A3_LAUNCHD=1)
platform/darwin/test_search_parity.py | A4: in-body skip when APFS rejects a non-UTF-8 filename
platform/darwin/test_package_install.py | A6: per-test Apple-silicon (arm64) native package install
platform/darwin/test_jobs_launchd_plan.py | A6: J3 per-test Darwin kern.maxprocperuid default for the com.binnacle.jobs plist NumberOfProcesses limit
platform/darwin/test_composition_contract.py | B0: in-body skip of the real-socket peer check off Darwin
unit/tools/test_command_characterization.py | T0: Linux durable job-engine characterization; Darwin counterpart tests/platform/darwin/test_foreground_commands.py::test_native_normal_exit_cwd_stdin_binary_combined_output
unit/tools/test_stop_job_edges.py | T0: Linux durable job_owner.stop_job; Darwin counterpart tests/platform/darwin/test_native_smoke_mcp.py::test_stop_job_is_unavailable_never_enabled
integration/test_files_settings.py | T0: Files child over Linux pathname Core (CR0-06); Darwin counterpart tests/platform/darwin/test_files_roots.py::test_escaping_paths_rejected
integration/test_run_command_output_shaping.py | T0: Linux durable job engine; Darwin counterpart tests/platform/darwin/test_native_smoke_mcp.py::test_run_command_sd18, background jobs UNAVAILABLE by release scope
integration/test_run_command_policy_telemetry.py | T0: Linux auto-background durable job; Darwin counterpart tests/platform/darwin/test_native_smoke_mcp.py::test_run_command_sd18
integration/test_run_command_error_telemetry.py | T0: Linux run_command default backend via composed server; Darwin counterpart tests/platform/darwin/test_native_smoke_mcp.py::test_run_command_sd18
integration/test_search_settings.py | T0: Search child over Linux pathname Core (CR0-06); Darwin counterpart tests/platform/darwin/test_search_parity.py::test_native_local_ignore_and_glob_parity
contracts/test_darwin_interface.py | B0: Darwin root-grant lifecycle tests need native descriptors (R2D-T0A6-01 fix ecf6aea)
platform/darwin/test_missing_roots.py | B0: Darwin missing-root lifespan tests need native descriptors (SD-24 fix 8132d8d)
"""
ALLOWED_PLATFORM_SKIPS = {
    **{
        f"tests/{k}": v for k, v in (r.split(" | ") for r in _ROWS.strip().splitlines())
    },
    **dict.fromkeys(LINUX_PIN_FILES, "T0: per-test Linux-only golden/host pin"),
    **dict.fromkeys(
        T0A9_PIN_FILES, "T0: per-test Linux-only job engine/systemd/procfs pin"
    ),
    **dict.fromkeys(
        LINUX_ONLY_MODULES,
        "T0: module is wholly durable-job engine; no Darwin counterpart: UNAVAILABLE on Darwin by release scope (CR0-04)",
    ),
}

# Per row: the platform-conditioned skip sites a file may hold (reviewable edit).
PLATFORM_SITE_COUNTS = {
    "tests/system/test_uplink_network.py": 1,
    "tests/live/test_deployment_smoke.py": 0,
    "tests/scripts/test_macos_collection_native.py": 1,
    "tests/platform/darwin/test_foreground_commands.py": 1,
    "tests/platform/darwin/test_process_native.py": 1,
    "tests/platform/darwin/test_ipc_generation.py": 1,
    "tests/platform/darwin/test_ipc_launchd.py": 3,
    "tests/platform/darwin/test_search_parity.py": 1,
    "tests/platform/darwin/test_package_install.py": 1,
    "tests/platform/darwin/test_jobs_launchd_plan.py": 1,
    "tests/platform/darwin/test_composition_contract.py": 3,
    "tests/contracts/test_darwin_interface.py": 1,
    "tests/platform/darwin/test_missing_roots.py": 1,
    "tests/unit/tools/test_command_characterization.py": 1,
    "tests/unit/tools/test_stop_job_edges.py": 1,
    "tests/integration/test_files_settings.py": 1,
    "tests/integration/test_run_command_output_shaping.py": 1,
    "tests/integration/test_run_command_policy_telemetry.py": 1,
    "tests/integration/test_run_command_error_telemetry.py": 1,
    "tests/integration/test_search_settings.py": 1,
    **dict.fromkeys(LINUX_PIN_FILES, 1),
    **dict.fromkeys(T0A9_PIN_FILES, 1),
}
