"""Workspace discovery, snapshots and changes in ordinary authorized projects."""

import pytest

from binnacle.features.development_intelligence.lsp_workspace_access import (
    AuthorizedWorkspace,
    WorkspaceAccessError,
    WorkspaceStaleError,
)


@pytest.fixture
def project(tmp_path):
    base = (tmp_path / "approved").resolve()
    repo = base / "worktree"
    repo.mkdir(parents=True)
    (repo / ".git").write_text("gitdir: ../metadata/worktrees/worktree\n")
    (repo / "pkg").mkdir()
    source = repo / "pkg" / "module.py"
    source.write_text("name = 'original'\n", encoding="utf-8")
    return base, repo, source


def test_git_worktree_marker_and_disk_hash(project):
    base, repo, source = project
    root = AuthorizedWorkspace((base,), source)
    assert root.workspace_root == repo
    assert root.source_file == "pkg/module.py"
    document = root.snapshot("pkg/module.py")
    assert document.uri == source.as_uri()
    assert document.contents == "name = 'original'\n"
    assert len(document.sha256) == 64
    assert root.snapshot_uri(source.as_uri()) == document
    root.assert_fresh(document)


def test_change_version_detected_by_freshness(project):
    base, _repo, source = project
    root = AuthorizedWorkspace((base,), source)
    before = root.snapshot("pkg/module.py")
    source.write_text("name = 'updated'\n", encoding="utf-8")
    with pytest.raises(WorkspaceStaleError):
        root.assert_fresh(before)
    after = root.snapshot("pkg/module.py")
    assert before.sha256 != after.sha256
    assert after.contents == "name = 'updated'\n"
    root.assert_fresh(after)


def test_project_marker_and_explicit_standalone_fallback(tmp_path):
    base = (tmp_path / "approved").resolve()
    repo = base / "standalone"
    repo.mkdir(parents=True)
    source = repo / "sample.py"
    source.write_text("value = 123\n")
    with pytest.raises(WorkspaceAccessError, match="marker_required"):
        AuthorizedWorkspace((base,), source)
    (repo / "pyrightconfig.json").write_text("{}\n")
    assert AuthorizedWorkspace((base,), source).workspace_root == repo
    (repo / "pyrightconfig.json").unlink()
    assert (
        AuthorizedWorkspace((base,), source, allow_parent_fallback=True).workspace_root
        == repo
    )


def test_nested_repository_takes_priority_over_outer_repository(project):
    base, repo, _source = project
    inside = repo / "nested"
    inside.mkdir()
    (inside / ".git").mkdir()
    (inside / "inner.py").write_text("inner = 1\n")
    root = AuthorizedWorkspace((base,), inside / "inner.py")
    assert root.workspace_root == inside
    assert root.source_file == "inner.py"


def test_only_audited_source_extensions_are_accepted(project):
    base, repo, source = project
    root = AuthorizedWorkspace((base,), source)
    (repo / "settings.toml").write_text("title = 'config'\n")
    with pytest.raises(WorkspaceAccessError, match="extension"):
        root.snapshot("settings.toml")
    (repo / "stubs.pyi").write_text("def greeting() -> str: ...\n")
    assert "def greeting()" in root.snapshot("stubs.pyi").contents
