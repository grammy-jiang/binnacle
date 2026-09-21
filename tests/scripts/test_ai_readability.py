from scripts import check_ai_readability as ar


def test_parse_findings_reads_lizard_length_warning():
    output = (
        "src/a.py:42: warning: cycle has 268 NLOC, 89 CCN, 1645 token, "
        "6 PARAM, 307 length, 0 nesting\n"
    )
    assert ar.parse_findings(output) == [ar.Finding("src/a.py", 42, "cycle", 307)]


def test_severity_uses_warning_bands():
    assert ar.severity(101, strong=120, severe=150) == "WARNING"
    assert ar.severity(121, strong=120, severe=150) == "STRONG"
    assert ar.severity(151, strong=120, severe=150) == "SEVERE"


def test_main_is_warning_only(monkeypatch, tmp_path, capsys):
    policy = tmp_path / "quality.json"
    policy.write_text(
        '{"ai_readability":{"warning_lines":100,"strong_warning_lines":120,'
        '"severe_warning_lines":150,"roots":["src/binnacle"]}}'
    )
    monkeypatch.setattr(
        ar,
        "run_lizard",
        lambda roots, warning: [ar.Finding("src/a.py", 1, "big", 200)],
    )

    assert ar.main(["--policy", str(policy)]) == 0
    out = capsys.readouterr().out
    assert "SEVERE:" in out
    assert "warning-only (non-blocking)" in out
