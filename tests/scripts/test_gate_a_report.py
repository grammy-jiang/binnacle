import scripts.gate_a_manifest as manifest
import scripts.gate_a_report as gate_a


def test_current_report_names_known_pre_g5_gaps():
    cells = {cell.id: cell for cell in gate_a.report()}

    assert cells["composition.stable_fastmcp_4"].status == "PASS"
    assert cells["composition.explicit_root_construction"].status == "PASS"
    assert cells["composition.files_focused_child"].status == "PASS"
    assert cells["composition.search_focused_child"].status == "PASS"
    assert cells["composition.commands_focused_child"].status == "PASS"
    assert cells["composition.hardcoded_registry_removed"].status == "PASS"
    assert cells["composition.no_duplicate_framework"].status == "PENDING"
    assert cells["architecture.fastmcp_boundary"].status == "PENDING"
    assert cells["architecture.package_convergence"].status == "PENDING"
    assert cells["architecture.g6_manifest_coverage"].status == "PASS"

    assert cells["platform.process_contract"].status == "PASS"
    assert cells["platform.resource_contract"].status == "PASS"
    assert cells["platform.service_log_contract"].status == "PASS"
    assert cells["platform.managed_service_contract"].status == "PASS"
    assert cells["platform.runtime_path_contract"].status == "PASS"

    # Preparation baseline only: these are exactly the G5 gaps this branch is
    # meant to make visible. Update this test when G5 closes them.
    assert cells["companion.core_doctor_no_watchdog_uplink"].status == "FAIL"
    assert cells["companion.core_cli_no_watchdog_webmin"].status == "FAIL"
    assert cells["companion.operational_http_surface"].status == "FAIL"

    assert cells["companion.watchdog_doctor_no_core_aggregate"].status == "FAIL"
    assert cells["companion.tunnel_doctor_no_core_connectivity_impl"].status == "FAIL"
    assert cells["companion.watchdog_cli_no_core_cli"].status == "FAIL"
    assert cells["companion.tunnel_cli_no_core_cli"].status == "FAIL"
    assert cells["companion.watchdog_services_no_tunnel_doctor_impl"].status == "FAIL"
    assert cells["companion.watchdog_tunnel_unit_contract"].status == "PENDING"


def test_runtime_and_deploy_cells_remain_pending_in_static_report():
    cells = {cell.id: cell for cell in gate_a.report()}
    assert cells["companion.server_works_without_watchdog"].status == "PENDING"
    assert cells["convergence.live_deploy"].status == "PENDING"
    assert cells["convergence.real_chatgpt_call"].status == "PENDING"


def test_report_binds_to_current_exact_sha():
    sha = gate_a.current_sha()
    assert sha is not None and len(sha) == 40


def test_g6_manifest_classifies_every_current_module_once():
    unclassified, duplicate = gate_a.manifest_coverage()
    assert unclassified == []
    assert duplicate == {}
    assert sum(len(paths) for paths in manifest.manifest_groups().values()) == len(
        manifest.python_files()
    )
