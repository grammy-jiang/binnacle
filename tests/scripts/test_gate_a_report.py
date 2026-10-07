import scripts.gate_a_report as gate_a


def test_current_report_names_known_pre_g5_gaps():
    cells = {cell.id: cell for cell in gate_a.report()}

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


def test_runtime_and_deploy_cells_remain_pending_in_static_report():
    cells = {cell.id: cell for cell in gate_a.report()}
    assert cells["companion.server_works_without_watchdog"].status == "PENDING"
    assert cells["convergence.live_deploy"].status == "PENDING"
    assert cells["convergence.real_chatgpt_call"].status == "PENDING"
