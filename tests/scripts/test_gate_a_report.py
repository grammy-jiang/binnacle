import scripts.gate_a_evidence as evidence
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
    assert cells["architecture.g6_compatibility_facade_inventory"].status == "PASS"

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
    assert cells["companion.watchdog_tunnel_unit_contract"].status == "PASS"


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


def test_g6_compatibility_facades_are_present_and_singly_classified():
    missing, owners = manifest.compatibility_facade_coverage()

    assert missing == []
    assert set(owners) == manifest.compatibility_facades()
    assert all(len(groups) == 1 for groups in owners.values())


def test_watchdog_tunnel_contract_allows_only_tunnel_unit_name(tmp_path):
    path = tmp_path / "watchdog_cli.py"
    path.write_text(
        "from binnacle.tunnel_unit import TUNNEL_UNIT\n",
        encoding="utf-8",
    )
    assert gate_a.imported_names_from(path, "binnacle.tunnel_unit") == (
        {"TUNNEL_UNIT"},
        False,
    )

    path.write_text(
        "from binnacle.tunnel_unit import TUNNEL_UNIT, render_tunnel_unit\n",
        encoding="utf-8",
    )
    names, direct = gate_a.imported_names_from(path, "binnacle.tunnel_unit")
    assert names == {"TUNNEL_UNIT", "render_tunnel_unit"}
    assert direct is False

    path.write_text("import binnacle.tunnel_unit\n", encoding="utf-8")
    assert gate_a.imported_names_from(path, "binnacle.tunnel_unit") == (set(), True)


def test_payload_binds_every_cell_to_one_exact_snapshot():
    cells = [
        gate_a.Cell("static", "PASS", "ok"),
        gate_a.Cell("live", "PENDING", "later", evidence="external"),
    ]
    payload = evidence.build_payload(
        cells,
        candidate="a" * 40,
        observed_at="2026-10-07T10:00:00+00:00",
    )

    assert payload["schema_version"] == 1
    assert payload["candidate"] == "a" * 40
    assert payload["observed_at"] == "2026-10-07T10:00:00+00:00"
    assert payload["summary"] == {"pass": 1, "fail": 0, "pending": 1}
    assert {cell["candidate"] for cell in payload["cells"]} == {"a" * 40}
    assert {cell["observed_at"] for cell in payload["cells"]} == {
        "2026-10-07T10:00:00+00:00"
    }
    assert payload["cells"][1]["evidence"] == "external"
