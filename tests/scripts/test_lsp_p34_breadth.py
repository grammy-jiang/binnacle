"""Offline fixture evidence, opt-in, discovery and privacy regressions."""

import json
import os
import sys
from pathlib import Path

import pytest

from scripts import lsp_p34_breadth as breadth
from scripts.lsp_p34_evidence import advertised, command_version, shape
from scripts.lsp_p34_fixtures import CASES, fixture, options, settings


def case(key):
    return next(item for item in CASES if item.key == key)


def test_opt_in_required_before_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(breadth, "probe", lambda *a: pytest.fail("provider launched"))
    with pytest.raises(SystemExit, match="2"):
        breadth.main(["--output", str(tmp_path / "out.json")])
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize("timeout", ["nan", "inf", "0", "121"])
def test_invalid_timeout_is_rejected(tmp_path, timeout):
    with pytest.raises(SystemExit, match="2"):
        breadth.main(
            [
                "--run-native",
                "--timeout",
                timeout,
                "--output",
                str(tmp_path / "out.json"),
            ]
        )


def test_absent_make_does_not_search_path_or_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(breadth, "Peer", lambda *a: pytest.fail("launched"))
    monkeypatch.setenv("PATH", str(tmp_path))
    (tmp_path / "make-ls").write_text("unreviewed executable")
    result = breadth.probe(case("make"), tmp_path / "absent", 1)
    assert result["status"] == "not_installed"
    assert result["read_eligible"] is False


def test_present_make_requires_identity_review(tmp_path):
    (tmp_path / "make-language-server").write_text("unreviewed")
    assert (
        breadth.probe(case("make"), tmp_path, 1)["status"] == "identity_review_required"
    )


def test_environment_drops_injection_and_only_links_node(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE_OPTIONS", "--require /private/plugin.js")
    monkeypatch.setenv("PYTHONPATH", "/private/python")
    binary_dir = tmp_path / "trusted"
    binary_dir.mkdir()
    (binary_dir / "node").write_text("node")
    env = breadth.environment(tmp_path, binary_dir)
    assert "NODE_OPTIONS" not in env and "PYTHONPATH" not in env
    assert env["PATH"] == str(tmp_path / "bin")
    assert list((tmp_path / "bin").iterdir()) == [tmp_path / "bin/node"]
    assert env["CARGO_NET_OFFLINE"] == "true"


@pytest.mark.parametrize("provider", [item.key for item in CASES])
def test_fixture_is_deterministic_and_has_no_build_hooks(tmp_path, provider):
    current = case(provider)
    files = fixture(current, tmp_path)
    assert files[current.filename] == current.text
    assert "Cargo.toml" not in files and "package.json" not in files
    assert set(files) == {path.name for path in tmp_path.iterdir()}
    if provider == "rust":
        init = options(current, tmp_path)
        assert init["cargo"]["buildScripts"]["enable"] is False
        assert init["procMacro"]["enable"] is False
        assert init["linkedProjects"] == []
    if provider == "yaml":
        assert settings(current)["yaml"]["schemaStore"]["enable"] is False


def test_capability_snapshot_redacts_values_and_keys():
    result = shape(
        {
            "hoverProvider": {},
            "experimental": {"/private/token": "secret"},
            "completionProvider": {"triggerCharacters": ["file:///private/token"]},
        }
    )
    text = json.dumps(result)
    assert "private" not in text and "secret" not in text
    assert result["hoverProvider"] == {}
    assert advertised(result, "hoverProvider")
    assert not advertised({"hoverProvider": False}, "hoverProvider")
    assert not advertised({"hoverProvider": 1}, "hoverProvider")


def test_symbol_and_definition_gold_reject_empty_wrong_results(tmp_path):
    assert not breadth.symbol_ok([], case("json"))
    assert not breadth.symbol_ok(
        [{"name": "answer", "range": {"start": {"line": -1, "character": 0}}}],
        case("json"),
    )
    gold = (1, 22, "lib.ts", 0, 16)
    assert not breadth.definition_ok(None, tmp_path, gold)
    assert not breadth.definition_ok(
        [
            {
                "uri": "file:///private/lib.ts",
                "range": {"start": {"line": 0, "character": 16}},
            }
        ],
        tmp_path,
        gold,
    )
    assert breadth.definition_ok(
        {
            "uri": (tmp_path / "lib.ts").as_uri(),
            "range": {"start": {"line": 0, "character": 16}},
        },
        tmp_path,
        gold,
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX subprocess harness")
def test_end_to_end_report_is_sanitized_and_conservative(tmp_path):
    server = Path(__file__).parents[1] / "fixtures/lsp/p34_server.py"
    binary = tmp_path / "vscode-json-language-server"
    binary.write_text(f"#!{sys.executable}\n" + server.read_text())
    binary.chmod(0o700)
    output = tmp_path / "report.json"
    assert (
        breadth.main(
            [
                "--run-native",
                "--bin-dir",
                str(tmp_path),
                "--provider",
                "json",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    raw = output.read_text()
    report = json.loads(raw)
    result = report["providers"][0]
    assert result["document_symbol"] == "fixture_pass"
    assert result["shutdown"] == "pass"
    assert result["classification"] == "benchmark_only"
    assert result["adapter"]["status"] == "no_upstream_adapter"
    assert str(tmp_path) not in raw and "/private" not in raw
    assert "READ NO-GO" in raw and "not shipped" in raw


def test_provider_fixture_side_effect_must_not_remain_pass(tmp_path, monkeypatch):
    server = Path(__file__).parents[1] / "fixtures/lsp/p34_server.py"
    binary = tmp_path / "vscode-json-language-server"
    binary.write_text(f"#!{sys.executable}\n" + server.read_text())
    binary.chmod(0o700)
    original = breadth.session

    def tampered_session(peer, case, root, row, tsserver=None):
        original(peer, case, root, row, tsserver)
        (root / "provider-side-effect").write_text("not permitted")

    monkeypatch.setattr(breadth, "session", tampered_session)
    row = breadth.probe(case("json"), tmp_path, 5)
    assert row["fixture_files_unchanged"]
    assert row["extra_workspace_entries"] == 1
    assert row["status"] == "failed"
    assert row["failure"] == "fixture_integrity_or_gold_unproven"


@pytest.mark.parametrize("prefix", ["tool ", "v"])
def test_version_command_bounds_and_sanitizes(tmp_path, prefix):
    binary = tmp_path / "version"
    binary.write_text(f"#!{sys.executable}\nprint('{prefix}1.2.3 /private/token')\n")
    binary.chmod(0o700)
    assert command_version(binary, tmp_path, {}) == "1.2.3"


@pytest.mark.parametrize("provider", ["typescript", "javascript", "c", "cpp", "rust"])
def test_upstream_constructor_uses_explicit_binary_without_launch(
    tmp_path, monkeypatch, provider
):
    pytest.importorskip("multilspy")
    import subprocess

    from scripts.lsp_p34_evidence import adapter_probe

    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *a, **kw: pytest.fail("constructor launched subprocess"),
    )
    result = adapter_probe(case(provider), Path(sys.executable), tmp_path)
    assert result["status"] == "constructor_pass_session_unprobed"
    assert len(result["adapter_source_sha256"]) == 64


def test_timeout_report_has_failure_and_cleanup_no_paths(tmp_path):
    binary = tmp_path / "vscode-json-language-server"
    binary.write_text(f"#!{sys.executable}\nimport time; time.sleep(60)\n")
    binary.chmod(0o700)
    # Avoid a separate version-command timeout in this protocol-deadline test.
    (tmp_path / "package.json").write_text('{"version":"1.2.3"}')
    result = breadth.probe(case("json"), tmp_path, 0.1)
    assert result["status"] == "failed"
    assert result["failure"] == "deadline"
    assert result["shutdown"] == "unprobed"
    assert result["cleanup"] == "group_signaled_leader_reaped"
    assert str(tmp_path) not in json.dumps(result)
