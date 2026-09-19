import os
from pathlib import Path

from binnacle.indexed_retrieval import PersistentRelationIndex
from tests.unit.core.test_indexed_index import make_repo


def test_full_update_detects_changed_deleted_and_metadata_only(tmp_path):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")

    source = root / "src" / "app.py"
    source.write_text(source.read_text() + "\n# changed\n")
    guide = root / "docs" / "guide.md"
    guide.unlink()
    config = root / "config" / "defaults.toml"
    stat = config.stat()
    os.utime(config, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))

    fresh = index.freshness()
    assert "src/app.py" in fresh["changed"]
    assert "docs/guide.md" in fresh["deleted"]
    assert any(item[0] == "config/defaults.toml" for item in fresh["metadata_only"])

    result = index.update()
    assert result["changed_files"] == 1
    assert result["deleted_files"] == 1
    assert result["hashed_files"] >= 2
    assert result["generation"] == 2
    index.close()


def test_update_paths_handles_absolute_outside_missing_and_metadata_only(tmp_path):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")

    source = root / "src" / "app.py"
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
    guide = root / "docs" / "guide.md"
    guide.unlink()

    result = index.update_paths(
        [
            Path("/outside/repo.py"),
            source.resolve(),
            "docs/guide.md",
            "does-not-exist.py",
        ]
    )

    assert result["changed_files"] == 0
    assert result["deleted_files"] == 1
    assert result["hashed_files"] == 1
    assert result["generation"] == 2
    index.close()


def test_update_paths_removes_file_that_becomes_too_large(tmp_path):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")
    source = root / "src" / "app.py"
    source.write_bytes(b"x" * 1_000_001)

    result = index.update_paths(["src/app.py"])

    assert result["deleted_files"] == 1
    assert "src/app.py" not in {
        row[0] for row in index.db.execute("SELECT path FROM files")
    }
    index.close()


def test_update_paths_removes_file_that_becomes_binary(tmp_path):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")
    source = root / "src" / "app.py"
    source.write_bytes(b"a\0b")

    result = index.update_paths(["src/app.py"])

    assert result["deleted_files"] == 1
    index.close()


def test_apply_update_skips_changed_path_missing_from_current_or_unreadable(
    tmp_path, monkeypatch
):
    root = make_repo(tmp_path)
    index = PersistentRelationIndex(root, tmp_path / "index.db")
    before = index.stats()["generation"]

    index._apply_update(
        changed=["missing.py"],
        deleted=[],
        metadata_only=[],
        current={},
        head="head-a",
    )
    monkeypatch.setattr(index, "_read_text", lambda rel: None)
    index._apply_update(
        changed=["unreadable.py"],
        deleted=[],
        metadata_only=[],
        current={"unreadable.py": (1, 1, "python")},
        head="head-b",
    )

    assert index.stats()["generation"] == before + 2
    index.close()
