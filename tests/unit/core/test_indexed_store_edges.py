import sqlite3
import subprocess

from binnacle.indexed_parse import ParsedFile
from binnacle.indexed_retrieval import PersistentRelationIndex
from tests.unit.core.test_indexed_index import make_repo


def test_schema_mismatch_is_dropped_before_schema_recreation(tmp_path):
    root = make_repo(tmp_path)
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES('schema_version', '999')")
    conn.commit()
    conn.close()

    index = PersistentRelationIndex(root, db, create=False)
    assert index._meta_int("schema_version") is None
    assert index.db.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
    index.close()


def test_tracked_files_skip_vanished_large_and_unsupported_paths(tmp_path):
    root = make_repo(tmp_path)
    (root / "broken.py").symlink_to(root / "does-not-exist.py")
    (root / "huge.py").write_bytes(b"x" * 1_000_001)
    (root / "asset.bin").write_bytes(b"x")

    index = PersistentRelationIndex(root, tmp_path / "index.db")
    tracked = index.tracked_files()

    assert "broken.py" not in tracked
    assert "huge.py" not in tracked
    assert "asset.bin" not in tracked
    index.close()


def test_store_helpers_handle_missing_binary_empty_and_unknown_git(
    tmp_path, monkeypatch
):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")

    assert index._read_text("missing.py") is None
    binary = root / "src" / "binary.py"
    binary.write_bytes(b"a\0b")
    assert index._read_text("src/binary.py") is None
    assert index._kind_for(root / "asset.bin") is None
    assert index._names_for_paths([]) == (set(), set())

    monkeypatch.setattr(
        "binnacle.indexed_store.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout="", stderr=""),
    )
    assert index.git_head() == "unknown"
    index.close()


def test_rebuild_skips_unreadable_candidate(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db", create=False)
    monkeypatch.setattr(
        index,
        "tracked_files",
        lambda: {"gone.py": (10, 1, "python")},
    )
    monkeypatch.setattr(index, "_read_text", lambda rel: None)

    stats = index.rebuild()

    assert stats["files"] == 0
    assert stats["generation"] == 1
    index.close()


def test_replace_empty_parsed_file_and_incremental_edge_noops(tmp_path):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")

    index._replace_file(
        "empty.py",
        0,
        1,
        "python",
        index._hash(b""),
        ParsedFile([], [], []),
    )
    assert (
        index.db.execute("SELECT COUNT(*) FROM files WHERE path='empty.py'").fetchone()[
            0
        ]
        == 1
    )
    assert (
        index.db.execute("SELECT COUNT(*) FROM nodes WHERE path='empty.py'").fetchone()[
            0
        ]
        == 0
    )

    index._resolve_edges_incremental(set(), set())
    index._resolve_edges_incremental({"persist_value"}, {"retry_limit"})
    index.close()
