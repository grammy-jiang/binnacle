from pathlib import Path

from binnacle.indexed_retrieval import (
    config_like,
    parse_config,
    parse_file,
    parse_markdown,
    parse_python,
    query_terms,
)


def test_query_terms_normalizes_regex_noise_stops_and_duplicates():
    assert query_terms(r"(?i) Foo|foo \bBAR\b current 中文测试 1 x") == [
        "foo",
        "bar",
        "中文测试",
    ]


def test_parse_python_extracts_symbols_calls_and_module_body():
    parsed = parse_python(
        "pkg/sample.py",
        "VALUE = 1\n\n"
        "def helper():\n"
        "    return VALUE\n\n"
        "def target():\n"
        "    return helper()\n",
    )

    kinds = {(node.kind, node.symbol) for node in parsed.nodes}
    assert ("python_module", "sample") in kinds
    assert ("function", "helper") in kinds
    assert ("function", "target") in kinds
    assert any(ref.name == "helper" and ref.relation == "call" for ref in parsed.refs)

    module = next(node for node in parsed.nodes if node.kind == "python_module")
    assert "VALUE = 1" in module.body
    assert "def helper" not in module.body


def test_parse_python_syntax_error_is_non_fatal():
    assert parse_python("broken.py", "def nope(:\n").nodes == []


def test_parse_markdown_splits_sections_and_records_symbol_references():
    tick = chr(96)
    text = (
        "# First\n"
        + "Uses "
        + tick
        + "binnacle.jobs.run"
        + tick
        + ".\n"
        + "## Second\n"
        + "Uses "
        + tick
        + "Policy"
        + tick
        + ".\n"
    )

    parsed = parse_markdown("docs/example.md", text)

    assert [node.symbol for node in parsed.nodes] == ["First", "Second"]
    assert {(ref.name, ref.relation) for ref in parsed.refs} == {
        ("run", "doc_ref"),
        ("Policy", "doc_ref"),
    }


def test_config_like_requires_config_name_and_skips_project_tooling():
    assert config_like(Path("service-config.yaml"))
    assert config_like(Path("network-policy.toml"))
    assert not config_like(Path("values.yaml"))
    assert not config_like(Path("pyproject.toml"))


def test_parse_config_preserves_section_and_normalizes_consumer_names():
    parsed = parse_config(
        "settings/app-config.ini",
        "[server]\nlisten-address = 127.0.0.1\nworker.count = 4\nx = ignored\n",
    )

    assert [node.symbol for node in parsed.nodes] == ["listen-address", "worker.count"]
    assert "server listen-address 127.0.0.1" in parsed.nodes[0].body
    refs = {ref.name for ref in parsed.refs}
    assert {"listen_address", "count", "worker_count"} <= refs


def test_parse_file_dispatches_supported_types_and_ignores_other_files(tmp_path):
    py = tmp_path / "module.py"
    md = tmp_path / "guide.md"
    cfg = tmp_path / "app-config.yaml"
    other = tmp_path / "image.bin"

    assert parse_file("module.py", py, "value = 1\n").nodes
    assert parse_file("guide.md", md, "# Guide\n").nodes
    assert parse_file("app-config.yaml", cfg, "server-port: 8000\n").nodes
    assert parse_file("image.bin", other, "server-port: 8000\n").nodes == []
