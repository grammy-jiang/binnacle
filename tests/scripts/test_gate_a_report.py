from functools import lru_cache

import scripts.gate_a_evidence as evidence
import scripts.gate_a_manifest as manifest
import scripts.gate_a_report as gate_a


def test_current_report_confirms_g5_boundary_closure():
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
    assert cells["architecture.g7_legacy_retirement"].status == "PASS"

    assert cells["platform.process_contract"].status == "PASS"
    assert cells["platform.resource_contract"].status == "PASS"
    assert cells["platform.service_log_contract"].status == "PASS"
    assert cells["platform.managed_service_contract"].status == "PASS"
    assert cells["platform.runtime_path_contract"].status == "PASS"
    assert cells["platform.product_domains_no_linux_imports"].status == "PASS"

    # G5 is deployed: these ownership boundaries are now the G6 baseline.
    assert cells["companion.core_doctor_no_watchdog_uplink"].status == "PASS"
    assert cells["companion.core_cli_no_watchdog_webmin"].status == "PASS"
    assert cells["companion.operational_http_surface"].status == "PASS"

    assert cells["companion.watchdog_doctor_no_core_aggregate"].status == "PASS"
    assert cells["companion.tunnel_doctor_no_core_connectivity_impl"].status == "PASS"
    assert cells["companion.watchdog_cli_no_core_cli"].status == "PASS"
    assert cells["companion.tunnel_cli_no_core_cli"].status == "PASS"
    assert cells["companion.watchdog_services_no_tunnel_doctor_impl"].status == "PASS"
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


def test_platform_default_composition_is_not_a_command_feature():
    groups = manifest.manifest_groups()
    assert groups["platform_composition"] == {
        "platform/deployment_platform.py",
        "platform/job_platform.py",
    }
    assert "platform/job_platform.py" not in groups["commands"]
    assert "platform/deployment_platform.py" not in groups["deployment"]


def test_g5_additions_have_expected_g6_owners():
    groups = manifest.manifest_groups()
    expected = {
        "diagnostics/doctor_io.py": "diagnostics",
        "diagnostics/doctor_render.py": "diagnostics",
        "observability/system_resource_contracts.py": "observability",
        "observability/system_resource_history.py": "observability",
        "companions/tunnel/tunnel_log.py": "tunnel",
        "companions/watchdog/watchdog_connectivity.py": "watchdog",
    }
    for path, owner in expected.items():
        assert path in groups[owner]
        assert [group for group, paths in groups.items() if path in paths] == [owner]


def test_g7_retirement_cell_reports_actual_source_violations(tmp_path, monkeypatch):
    from scripts import g7_legacy_gate as g7

    # A reintroduced retired module must cause the report to fail,
    # not silently pass on an empty compatibility inventory.
    source_root = tmp_path / "binnacle"
    source_root.mkdir()
    (source_root / "jobs.py").write_text("x = 1\n")
    monkeypatch.setattr(gate_a, "g7_failures", lambda: g7.failures(source_root))
    cells = {cell.id: cell for cell in gate_a.report()}
    cell = cells["architecture.g7_legacy_retirement"]
    assert cell.status == "FAIL"
    assert "legacy file remains: jobs.py" in cell.detail


def test_watchdog_tunnel_contract_allows_only_tunnel_unit_name(tmp_path):
    path = tmp_path / "watchdog_cli.py"
    path.write_text(
        "from binnacle.companions.tunnel.tunnel_unit import TUNNEL_UNIT\n",
        encoding="utf-8",
    )
    assert gate_a.imported_names_from(
        path, "binnacle.companions.tunnel.tunnel_unit"
    ) == (
        {"TUNNEL_UNIT"},
        False,
    )

    path.write_text(
        "from binnacle.companions.tunnel.tunnel_unit import TUNNEL_UNIT, render_tunnel_unit\n",
        encoding="utf-8",
    )
    names, direct = gate_a.imported_names_from(
        path, "binnacle.companions.tunnel.tunnel_unit"
    )
    assert names == {"TUNNEL_UNIT", "render_tunnel_unit"}
    assert direct is False

    path.write_text("import binnacle.companions.tunnel.tunnel_unit\n", encoding="utf-8")
    assert gate_a.imported_names_from(
        path, "binnacle.companions.tunnel.tunnel_unit"
    ) == (set(), True)


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


def test_package_convergence_remains_pending_until_final_evidence():
    cells = {cell.id: cell for cell in gate_a.report()}
    pending = cells["architecture.package_convergence"]
    assert pending.status == "PENDING"
    assert "relocation checkpoints integrated" in pending.detail
    assert "final package review" in pending.detail


def test_gate_a_detects_canonical_boundary_bypasses(monkeypatch):
    cases = [
        (
            "companions/watchdog/watchdog_doctor.py",
            "binnacle.diagnostics.doctor",
            "companion.watchdog_doctor_no_core_aggregate",
        ),
        (
            "companions/tunnel/tunnel_doctor.py",
            "binnacle.diagnostics.doctor_connectivity",
            "companion.tunnel_doctor_no_core_connectivity_impl",
        ),
        (
            "cli.py",
            "binnacle.observability.linux.webminstats",
            "companion.core_cli_no_watchdog_webmin",
        ),
        (
            "features/files/paths.py",
            "binnacle.platform.linux.service_provisioning_linux",
            "platform.product_domains_no_linux_imports",
        ),
        (
            "features/files/paths.py",
            "binnacle.platform.linux",
            "platform.product_domains_no_linux_imports",
        ),
        (
            "server.py",
            "binnacle.companions.watchdog",
            "companion.server_core_platform_no_watchdog_impl",
        ),
        (
            "server.py",
            "binnacle.companions.tunnel",
            "companion.server_core_platform_no_watchdog_impl",
        ),
    ]
    # The G7 retirement scanner is tested independently; this test only
    # varies companion/import boundaries across seven negative cases.
    monkeypatch.setattr(gate_a, "g7_failures", list)
    original = lru_cache(maxsize=None)(gate_a.imports_for)
    for relative_path, illegal_import, gate_cell in cases:
        path = gate_a.SRC / relative_path

        def imports_with_bypass(actual_path, forbidden=illegal_import, target=path):
            current = original(actual_path)
            return current | {forbidden} if actual_path == target else current

        with monkeypatch.context() as patched:
            patched.setattr(gate_a, "imports_for", imports_with_bypass)
            cell = {item.id: item for item in gate_a.report()}[gate_cell]
        assert cell.status == "FAIL", (relative_path, illegal_import)
        assert illegal_import in cell.detail
