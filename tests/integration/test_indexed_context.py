from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult

from binnacle.callctx import current_call
from binnacle.config import IndexedContextSettings
from binnacle.indexed_context import IndexedContextService
from binnacle.tools import search_text as st


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "config").mkdir()
    (root / "src" / "app.py").write_text(
        '"""Tiny retrieval fixture."""\n\n'
        "def normalize_value(value: str) -> str:\n"
        '    """Normalize incoming values before durable storage."""\n'
        "    return value.strip()\n\n"
        "def persist_value(value: str) -> str:\n"
        "    return normalize_value(value)\n\n"
        "def use_retry_limit(retry_limit: int) -> int:\n"
        "    return retry_limit\n"
    )
    (root / "docs" / "guide.md").write_text(
        "# Storage behavior\n\nUse `persist_value` to normalize and persist incoming data.\n"
    )
    (root / "config" / "defaults.toml").write_text("[runtime]\nretry_limit = 3\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "poc@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "POC"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return root


def settings(tmp_path: Path) -> IndexedContextSettings:
    return IndexedContextSettings(enabled=True, index_dir=tmp_path / "indexes")


def test_service_emits_review_grade_telemetry_and_absolute_paths(
    tmp_path: Path, caplog
):
    root = make_repo(tmp_path)
    service = IndexedContextService(settings(tmp_path))
    token = current_call.set("indexed-test-call")
    try:
        with caplog.at_level("INFO", logger="binnacle.indexed_context"):
            result = service.search(
                "@context find documented durable storage normalization implementation",
                root,
            )
    finally:
        current_call.reset(token)
        service.close()

    payload = result.structured_content
    assert payload is not None and payload["entries"]
    assert all(Path(entry["file"]).is_absolute() for entry in payload["entries"])
    line = next(
        rec.getMessage()
        for rec in caplog.records
        if "event=index_context " in rec.getMessage()
    )
    fields = dict(re.findall(r"(\w+)=(\S+)", line))
    required = {
        "call",
        "pilot_version",
        "schema_version",
        "parser_version",
        "root_hash",
        "query_hash",
        "query_chars",
        "head",
        "generation",
        "cold_open",
        "open_ms",
        "reconcile_ms",
        "freshness_ms",
        "changed_files",
        "deleted_files",
        "hashed_files",
        "query_ms",
        "surface_ms",
        "total_ms",
        "files",
        "nodes",
        "edges",
        "db_bytes",
        "related_items",
        "direct_items",
        "package_items",
        "package_bytes",
        "package_est_tokens",
        "evidence_hashes",
    }
    assert required <= fields.keys()
    assert fields["call"] == "indexed-test-call"
    assert int(fields["package_items"]) == payload["count"]
    assert int(fields["package_bytes"]) > 0
    assert int(fields["nodes"]) > 0
    assert re.fullmatch(r"[0-9a-f]{12}(,[0-9a-f]{12})*", fields["evidence_hashes"])
    assert len(fields["evidence_hashes"].split(",")) == payload["count"]


def test_service_rejects_non_root_scope_and_logs_error(tmp_path: Path, caplog):
    root = make_repo(tmp_path)
    service = IndexedContextService(settings(tmp_path))
    with (
        caplog.at_level("INFO", logger="binnacle.indexed_context"),
        pytest.raises(ToolError, match="worktree root"),
    ):
        service.search("@context find storage code", root / "src")
    service.close()
    assert "event=index_context_error" in caplog.text
    assert "phase=scope" in caplog.text


def test_service_serializes_concurrent_queries_on_one_index(tmp_path: Path):
    from concurrent.futures import ThreadPoolExecutor

    root = make_repo(tmp_path)
    service = IndexedContextService(settings(tmp_path))

    def run(i: int) -> int:
        result = service.search(
            f"@context durable storage normalization implementation {i}", root
        )
        assert result.structured_content is not None
        return int(result.structured_content["count"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(run, range(8)))
    service.close()
    assert all(count > 0 for count in counts)


def test_search_text_dispatches_context_but_fixed_string_prefix_stays_exact(
    tmp_path: Path, monkeypatch
):
    root = make_repo(tmp_path)

    class FakeService:
        def __init__(self) -> None:
            self.calls = 0

        def search(self, pattern: str, resolved: Path) -> ToolResult:
            self.calls += 1
            return ToolResult(
                content="indexed",
                structured_content={
                    "path": str(resolved),
                    "pattern": pattern,
                    "entries": [],
                    "count": 0,
                    "truncated": True,
                },
            )

    fake = FakeService()
    monkeypatch.setattr(st, "get_indexed_context_service", lambda: fake)
    result = st.search_text_impl(
        "@context find storage",
        str(root),
        None,
        False,
        None,
        False,
        100,
    )
    assert result.content == ["indexed"] or result.content
    assert fake.calls == 1

    (root / "literal.txt").write_text("@context find storage\n")
    exact = st.search_text_impl(
        "@context find storage",
        str(root),
        None,
        True,
        0,
        False,
        100,
    )
    assert exact.structured_content is not None
    assert exact.structured_content["count"] == 1
    assert fake.calls == 1


def test_service_validates_disabled_prefix_empty_and_non_git(tmp_path: Path, caplog):
    root = make_repo(tmp_path / "valid")
    disabled = IndexedContextService(
        IndexedContextSettings(enabled=False, index_dir=tmp_path / "disabled-indexes")
    )
    with pytest.raises(ToolError, match="disabled"):
        disabled.search("@context find storage", root)
    disabled.close()

    service = IndexedContextService(settings(tmp_path))
    with pytest.raises(ToolError, match="must start"):
        service.search("find storage", root)
    with pytest.raises(ToolError, match="non-empty"):
        service.search("@context   ", root)

    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    with (
        caplog.at_level("INFO", logger="binnacle.indexed_context"),
        pytest.raises(ToolError, match="Git worktree"),
    ):
        service.search("@context find storage", outside)
    service.close()
    assert "event=index_context_error" in caplog.text
    assert "phase=scope" in caplog.text


def test_service_can_skip_reconcile_and_evict_lru_index(tmp_path: Path):
    root1 = make_repo(tmp_path / "one")
    root2 = make_repo(tmp_path / "two")
    cfg = IndexedContextSettings(
        enabled=True,
        index_dir=tmp_path / "indexes",
        reconcile_on_query=False,
        max_open_indexes=1,
    )
    service = IndexedContextService(cfg)
    first = service.search("@context durable storage normalization", root1)
    assert first.structured_content is not None
    assert len(service._cache) == 1
    second = service.search("@context durable storage normalization", root2)
    assert second.structured_content is not None
    assert list(service._cache) == [root2.resolve()]
    service.close()
    assert not service._cache


def test_service_wraps_unexpected_query_failure_and_logs_phase(
    tmp_path: Path, monkeypatch, caplog
):
    root = make_repo(tmp_path)
    service = IndexedContextService(settings(tmp_path))
    handle, _, _ = service._get_handle(root.resolve())

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic query failure")

    monkeypatch.setattr(handle.index, "context_package", explode)
    with (
        caplog.at_level("INFO", logger="binnacle.indexed_context"),
        pytest.raises(ToolError, match="failed during query"),
    ):
        service.search("@context durable storage normalization", root)
    service.close()
    assert "event=index_context_error" in caplog.text
    assert "phase=query" in caplog.text
    assert "error_class=RuntimeError" in caplog.text


def test_global_service_is_singleton(monkeypatch, tmp_path: Path):
    import binnacle.indexed_context as module

    monkeypatch.setattr(module, "_SERVICE", None)
    monkeypatch.setattr(
        module,
        "IndexedContextService",
        lambda: object(),
    )
    first = module.get_indexed_context_service()
    second = module.get_indexed_context_service()
    assert first is second
