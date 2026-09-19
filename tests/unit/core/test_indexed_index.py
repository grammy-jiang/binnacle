"""Unit/component tests for the persistent relation-index engine."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from binnacle.indexed_retrieval import PersistentRelationIndex
from binnacle.indexed_surface import to_search_payload


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


def table_rows(index: PersistentRelationIndex, table: str) -> set[tuple]:
    columns = {
        "nodes": "node_id,path,kind,symbol,start_line,end_line,body",
        "definitions": "name,node_id,path",
        "refs": "source_node,name,relation,path",
        "identifiers": "name,node_id,path",
        "edges": "source_node,target_node,relation,ref_name",
    }[table]
    return {tuple(row) for row in index.db.execute(f"SELECT {columns} FROM {table}")}


def test_persistent_reopen_keeps_ranking_and_generation(tmp_path: Path):
    root = make_repo(tmp_path)
    db = tmp_path / "index.db"
    query = "documented storage normalization durable incoming data"
    first = PersistentRelationIndex(root, db)
    rank1 = first.retrieve_files(query, 10)
    stats1 = first.stats()
    first.close()

    reopened = PersistentRelationIndex(root, db)
    rank2 = reopened.retrieve_files(query, 10)
    fresh = reopened.freshness()
    stats2 = reopened.stats()
    reopened.close()

    assert rank1 == rank2
    assert stats1["nodes"] > 0 and stats1["edges"] > 0
    assert stats1["generation"] == stats2["generation"] == 1
    assert fresh["changed"] == [] and fresh["deleted"] == [] and fresh["hashes"] == 0


def test_incremental_python_edit_matches_clean_rebuild(tmp_path: Path):
    root = make_repo(tmp_path)
    inc = PersistentRelationIndex(root, tmp_path / "inc.db")
    source = root / "src" / "app.py"
    source.write_text(
        source.read_text() + "\n\ndef quasar_sentinel(value: str) -> str:\n"
        '    """Transform a unique quasar sentinel for parity validation."""\n'
        "    return normalize_value(value)\n"
    )
    result = inc.update_paths(["src/app.py"])
    assert result["changed_files"] == 1 and result["hashed_files"] == 1
    assert result["generation"] == 2

    full = PersistentRelationIndex(root, tmp_path / "full.db")
    for table in ("nodes", "definitions", "refs", "identifiers", "edges"):
        assert table_rows(inc, table) == table_rows(full, table)

    query = "unique quasar sentinel parity transformation"
    assert inc.retrieve_files(query, 10) == full.retrieve_files(query, 10)
    assert inc.retrieve_files(query, 10)[0] == "src/app.py"
    inc.close()
    full.close()


def test_context_package_budget_and_existing_search_shape(tmp_path: Path):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")
    query = "documented storage normalization retry configuration behavior"
    package = index.context_package(query, max_bytes=8_500)
    payload = to_search_payload(root, "@context " + query, package)

    assert package["structured_bytes"] <= 8_500
    assert package["item_count"] <= 10
    assert payload["path"] == str(root.resolve())
    assert payload["count"] == len(payload["entries"])
    assert payload["truncated"] is True
    assert all(
        {"file", "line", "text", "context_first_line", "context"} <= set(entry)
        for entry in payload["entries"]
    )
    assert (
        len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
        < 10_000
    )
    index.close()
