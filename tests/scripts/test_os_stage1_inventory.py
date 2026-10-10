"""OS6 source ownership sweep cannot silently miss a Python module."""

from scripts import os_stage1_inventory as scanner


def test_inventory_covers_every_source_and_script_with_judged_keep_reasons():
    manifest = scanner.generate()
    rows = manifest["rows"]
    assert len(rows) == len(scanner.code_paths())
    assert len({row["path"] for row in rows}) == len(rows)
    assert manifest["production_module_count"] >= 143
    assert manifest["script_count"] >= 47
    assert all(
        row["owner"] in {"KEEP", "BOUNDARY", "LINUX"}
        and row["rationale"]
        and row["stage"].startswith("OS")
        and row["imports"] is not None
        for row in rows
    )
    assert manifest["architecture_failures"] == []


def test_source_classifier_never_treats_real_native_or_companion_code_as_keep():
    examples = [
        "src/binnacle/platform/linux/job_process.py",
        "src/binnacle/platform/linux/job_identity.py",
        "src/binnacle/deployment/linux/unit_inspection.py",
        "src/binnacle/observability/linux/webminstats.py",
        "src/binnacle/companions/watchdog/watchdog.py",
        "src/binnacle/diagnostics/linux_checks.py",
        "scripts/resource_monitor.py",
        "scripts/weekly_scope.py",
    ]
    for example in examples:
        owner, stage, rationale = scanner.classify(example, {})
        assert owner == "LINUX", (example, owner)
        assert stage and rationale


def test_portable_ripgrep_and_external_dev_scripts_are_not_linux_by_default():
    for path in [
        "src/binnacle/features/search/search_text_rg.py",
        "src/binnacle/features/files/textio.py",
        "scripts/check_architecture.py",
    ]:
        owner, _, rationale = scanner.classify(path, {})
        assert owner == "KEEP"
        assert rationale


def test_inventory_capture_keeps_source_baseline_evidence_unmodified():
    base = scanner.ROOT / "docs/os-independent-stage1-evidence"
    assert (base / "os0-raw-mcp-surface.json").is_file()
    assert (base / "os0-manifest.sha256").is_file()
    assert (base / "os0-source-inventory.json").is_file()
