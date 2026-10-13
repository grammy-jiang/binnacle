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
platform/darwin/test_job_process_owner.py | A2: per-test Darwin posix_spawn/kqueue manager-owned job leaders (R4 J1, A2 successor)
platform/darwin/test_ipc_generation.py | A3: per-test Darwin getpeereid/LOCAL_PEERPID contract
platform/darwin/test_job_manager_service.py | A3: per-test Darwin getpeereid/LOCAL_PEERPID job-manager IPC (R4 J2, A3 successor) with a waitpid reference owner; no waitid needed
platform/darwin/test_job_manager_service_stop_e2e.py | A3: native stop persistence split from manager service test; waitpid reference owner, not real waitid owner
platform/darwin/test_job_manager_entry.py | A3: per-test Darwin com.binnacle.jobs entry point, J1 owner and job-manager IPC (R4 J2r, A3 successor); SD-97 manager requires os.waitid (Darwin CPython >=3.13)
platform/darwin/test_job_manager_entry_owner.py | A3: per-test Darwin J1 owner behind the com.binnacle.jobs manager: J1r handoff and J1g repairs (r6 T1, split from test_job_manager_entry.py); SD-97 manager requires os.waitid (Darwin CPython >=3.13)
platform/darwin/test_durable_jobs_e2e.py | A3: per-test Darwin kqueue/getpeereid job-manager E2E over the real J1 owner and J2 manager (R4 J5); SD-97 manager requires os.waitid (Darwin CPython >=3.13)
platform/darwin/test_durable_jobs_launchd_restart.py | A3: per-test Darwin native launchd restart, split from J5 to retain 500-line module limit; SD-97 manager requires os.waitid
platform/darwin/test_log_guardian_recovery.py | B0: per-test isolated Mac system launchd guardian bootstrap and SIGKILL recovery; all guardian policy tests run on Linux
platform/darwin/test_log_writer_hold.py | B0: per-test native Mac launchd system-domain writer quiescence fixture for Issue #30; policy and descriptor parsing tests run on Linux
platform/darwin/test_j1g_leader_fence.py | A2: per-test Darwin waitid(WNOWAIT)/KERN_PROC_PGRP leader-exit fence, stopping event and killpg guard (R4 J1g, SD-43); SD-97 manager requires os.waitid (Darwin CPython >=3.13)
platform/darwin/test_j1g_e2e_survival.py | B0: per-test Darwin real com.binnacle.jobs background-member survival E2E (R4 J1g, SD-43 JCRP-F1); SD-97 manager requires os.waitid (Darwin CPython >=3.13)
platform/darwin/test_job_manager_resilience.py | A3: per-test Darwin libproc verified-teardown negative test (R4 J2t, RULE-NO-PKILL); the rest of the module runs everywhere
platform/darwin/test_durable_tool_wiring.py | B0: per-test Darwin manager-owner tool composition (R4 J4); the owner call-site test runs everywhere
platform/darwin/test_durable_manager_e2e.py | B0: per-test Darwin real com.binnacle.jobs end-to-end for the manager-composed command tools (R4 J4, split from test_durable_tool_wiring.py); SD-97 manager requires os.waitid (Darwin CPython >=3.13)
platform/darwin/test_r5_l2_parity.py | B0: per-test Darwin manager composition and caller_form workdir on the real macOS filesystem (r5 L2, SD-50; STEER-01); the Linux-host cases run everywhere
platform/darwin/test_r5_l2b_strict_client.py | B0: per-test Darwin KERN_PROC_PGRP group_listing through the strict in-memory client (r5 L2b, SD-61 STEER-02b)
platform/darwin/test_r5_l2c_output_snapshot.py | B0: per-test Darwin real com.binnacle.jobs burst-writer output/output_bytes one-snapshot repro (r5 L2c); the pairing unit test runs everywhere
platform/darwin/test_r6_d2_stop_marker_start.py | B0: per-test Darwin real com.binnacle.jobs entry start refusal under its own quiet-window stop marker (r6 D2); the in-process and marker-reader tests run everywhere
platform/darwin/test_r6_d1_runtime_rebind.py | B0: per-test Darwin real com.binnacle.jobs endpoint rebind after socket/runtime-root removal, foreign debris and sun_path overflow (r6 D1); the sun_path and rebind-policy unit tests run everywhere
platform/darwin/test_r6w2_m1_runtime_root.py | B0: per-test Darwin real com.binnacle.jobs entry on the moved Application Support runtime root, legacy marker and live legacy writer (r6 W2 M1, SD-68); the root-resolution and no-fallback unit tests run everywhere
platform/darwin/test_r6w2_m1_ping_jobs_dir.py | B0: per-test Darwin real com.binnacle.jobs entry ping jobs_dir = the held realpath across a config edit (r6 W2 M1, SD-74 STEER-01); the unlocked in-process ping test runs everywhere
platform/darwin/test_r6w2_m1_d3_minors.py | B0: per-test Darwin real KERN_PROC_PGRP listing after a transient size race (r6 W2 M1 D3, PRE-J1g-F5); both tests import the Darwin process_authority decoder
platform/darwin/test_r6w2_m1_a2_followups.py | B0: per-test Darwin real com.binnacle.jobs entry rebind after the test HOME's default Application Support root is removed, and the held jobs-dir refusal after a symlink retarget (r6 W2 M1-a2, R-M1-N1/N5); the lock-inode and socket-path reason unit tests run everywhere
platform/darwin/test_r6w2_m1_a3_proof_order.py | B0: Darwin entry proof before recover
platform/darwin/test_r6w2_m1_a3_held_dir_io.py | B0: Darwin entry held-dir I/O (F1)
platform/darwin/test_r6_x2_absolute_in_root_links.py | B0: per-test Darwin /tmp -> /private/tmp configured-root alias (r6 X2, SD-67 STEER-01 item 3); the Darwin/Linux probe parity cases run everywhere
platform/darwin/test_r6w2_lp_tmp_alias.py | B0: per-test Darwin /tmp -> /private/tmp configured-root alias listing (r6 W2 LP, SD-74); the alias-prefix parity cases in tests/unit/tools/test_r6w2_lp_alias_prefixes.py run everywhere
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
integration/test_setup_units.py | B0: systemd unit inspector; Darwin launchd inspector is follow-up DARWIN-FOLLOWUP-service-inspector (per-test LINUX_ONLY on the 6 binnacle mode tests that build it; R4 J4, Supervisor ruling A, PO-J4-3)
contracts/test_darwin_interface.py | B0: Darwin root-grant lifecycle tests need native descriptors (R2D-T0A6-01 fix ecf6aea)
platform/darwin/test_missing_roots.py | B0: Darwin missing-root lifespan tests need native descriptors (SD-24 fix 8132d8d)
unit/tools/test_linux_fd_write_security.py | T0: SEC-FU-14: per-test Linux FD-relative parent and atomic write race fixtures; the Darwin provider uses opened grants instead
unit/tools/test_r6w2_x3a2_permissions.py | T0: R6W2-T3 per-test Linux fd_walk mechanism, open_verified (Linux-only, RX3a2-N4) and the O_PATH traverse flags (r6 W2 X3a-a2); the list permission and link-walk tests run everywhere
unit/tools/test_r6w2_x3a2_guards.py | T0: R6W2-T3 per-test Linux fd_walk.open_verified component checks (RX3a2-N3, Linux-only RX3a2-N4); the list link-walk swap test runs everywhere
unit/tools/test_r6w2_x3b_read_verify.py | T0: R6W2-T3 per-test Linux read path, read_file_impl without file_access over fd_walk.open_walked (r6 W2 X3b); Darwin reads through DarwinFileAccess; the unraced, nested-root and Darwin-dispatch tests run everywhere
unit/tools/test_r6w2_x3b2_read_bounds.py | T0: R6W2-T3 per-test Linux read path over fd_walk.open_walked identity and bounded read (r6 W2 X3b-a2); the leak, at-limit and within-limit reads run everywhere
unit/tools/test_r6w2_x3b3_special_files.py | T0: R6W2-T3 per-test Linux read path beside the Darwin path on one host (r6 W2 X3b-a3); native Darwin counterpart tests/platform/darwin/test_r6w2_t3_special_files.py
unit/core/test_r6w3_e1h_preentry_guard.py | T0: R6W3-01 real process-entry fault injection selects Linux job-manager -m only on Linux and Darwin launchd -m only on macOS; the other three early entry variants run everywhere
platform/darwin/test_r6w2_t3_special_files.py | B0: R6W2-T3 per-test Darwin read_file special files and mode 000 through DarwinFileAccess (r6 W2 T3 item 3)
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
    "tests/platform/darwin/test_job_process_owner.py": 1,
    "tests/platform/darwin/test_ipc_generation.py": 1,
    "tests/platform/darwin/test_job_manager_service.py": 1,
    "tests/platform/darwin/test_job_manager_service_stop_e2e.py": 1,
    "tests/platform/darwin/test_job_manager_entry.py": 1,
    "tests/platform/darwin/test_job_manager_entry_owner.py": 1,
    # Two local pytest.skip branches exercise host-specific manager -m paths.
    "tests/unit/core/test_r6w3_e1h_preentry_guard.py": 2,
    "tests/platform/darwin/test_durable_jobs_e2e.py": 1,
    "tests/platform/darwin/test_durable_jobs_launchd_restart.py": 1,
    "tests/platform/darwin/test_log_guardian_recovery.py": 1,
    "tests/platform/darwin/test_log_writer_hold.py": 1,
    "tests/platform/darwin/test_j1g_leader_fence.py": 1,
    "tests/platform/darwin/test_j1g_e2e_survival.py": 1,
    "tests/platform/darwin/test_job_manager_resilience.py": 1,
    "tests/platform/darwin/test_durable_tool_wiring.py": 1,
    "tests/platform/darwin/test_durable_manager_e2e.py": 1,
    "tests/platform/darwin/test_r5_l2_parity.py": 1,
    "tests/platform/darwin/test_r5_l2b_strict_client.py": 1,
    "tests/platform/darwin/test_r5_l2c_output_snapshot.py": 1,
    "tests/platform/darwin/test_r6_d2_stop_marker_start.py": 1,
    "tests/platform/darwin/test_r6_d1_runtime_rebind.py": 1,
    "tests/platform/darwin/test_r6w2_m1_runtime_root.py": 1,
    "tests/platform/darwin/test_r6w2_m1_ping_jobs_dir.py": 1,
    "tests/platform/darwin/test_r6w2_m1_d3_minors.py": 1,
    "tests/platform/darwin/test_r6w2_m1_a2_followups.py": 1,
    "tests/platform/darwin/test_r6w2_m1_a3_proof_order.py": 1,
    "tests/platform/darwin/test_r6w2_m1_a3_held_dir_io.py": 1,
    "tests/platform/darwin/test_r6_x2_absolute_in_root_links.py": 1,
    "tests/platform/darwin/test_r6w2_lp_tmp_alias.py": 1,
    "tests/platform/darwin/test_ipc_launchd.py": 3,
    "tests/platform/darwin/test_search_parity.py": 1,
    "tests/platform/darwin/test_package_install.py": 1,
    "tests/platform/darwin/test_jobs_launchd_plan.py": 1,
    "tests/platform/darwin/test_composition_contract.py": 3,
    "tests/contracts/test_darwin_interface.py": 1,
    "tests/platform/darwin/test_missing_roots.py": 1,
    "tests/unit/tools/test_linux_fd_write_security.py": 1,
    "tests/unit/tools/test_r6w2_x3a2_permissions.py": 1,
    "tests/unit/tools/test_r6w2_x3a2_guards.py": 1,
    "tests/unit/tools/test_r6w2_x3b_read_verify.py": 2,
    "tests/unit/tools/test_r6w2_x3b2_read_bounds.py": 1,
    "tests/unit/tools/test_r6w2_x3b3_special_files.py": 1,
    "tests/platform/darwin/test_r6w2_t3_special_files.py": 1,
    "tests/unit/tools/test_command_characterization.py": 1,
    "tests/unit/tools/test_stop_job_edges.py": 1,
    "tests/integration/test_files_settings.py": 1,
    "tests/integration/test_run_command_output_shaping.py": 1,
    "tests/integration/test_run_command_policy_telemetry.py": 1,
    "tests/integration/test_run_command_error_telemetry.py": 1,
    "tests/integration/test_search_settings.py": 1,
    "tests/integration/test_setup_units.py": 1,
    **dict.fromkeys(LINUX_PIN_FILES, 1),
    **dict.fromkeys(T0A9_PIN_FILES, 1),
}
