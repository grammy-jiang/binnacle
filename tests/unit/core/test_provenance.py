"""Package-version and source-revision provenance."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from binnacle import provenance
from binnacle.diagnostics import doctor_provenance


def _repo(path: Path) -> str:
    git = shutil.which("git")
    assert git is not None
    env = provenance._clean_git_env(git)
    subprocess.run([git, "init", "-q", str(path)], check=True, env=env)
    subprocess.run(
        [git, "-C", str(path), "config", "user.name", "test"],
        check=True,
        env=env,
    )
    subprocess.run(
        [git, "-C", str(path), "config", "user.email", "test@example.invalid"],
        check=True,
        env=env,
    )
    (path / "tracked.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(
        [git, "-C", str(path), "add", "tracked.txt"],
        check=True,
        env=env,
    )
    subprocess.run(
        [git, "-C", str(path), "commit", "-qm", "init"],
        check=True,
        env=env,
    )
    return subprocess.run(
        [git, "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def test_source_revision_reports_clean_commit_and_ignores_untracked(
    tmp_path: Path,
) -> None:
    sha = _repo(tmp_path)
    assert provenance.source_revision(tmp_path) == sha[:12]

    (tmp_path / "untracked.txt").write_text("note\n", encoding="utf-8")
    assert provenance.source_revision(tmp_path) == sha[:12]


def test_source_revision_marks_tracked_changes(tmp_path: Path) -> None:
    sha = _repo(tmp_path)
    (tmp_path / "tracked.txt").write_text("two\n", encoding="utf-8")
    assert provenance.source_revision(tmp_path) == f"{sha[:12]}+dirty"


def test_source_revision_reports_installed_without_git(tmp_path: Path) -> None:
    assert provenance.source_revision(tmp_path) == "installed"


def test_package_version_falls_back_when_distribution_is_missing(monkeypatch) -> None:
    def missing(name: str) -> str:
        raise provenance.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(provenance.importlib.metadata, "version", missing)
    assert provenance.package_version() == "?"


def test_source_revision_ignores_inherited_repository_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    outer = tmp_path / "outer"
    target = tmp_path / "target"
    outer.mkdir()
    target.mkdir()
    _repo(outer)
    target_sha = _repo(target)

    monkeypatch.setenv("GIT_DIR", str(outer / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outer))

    assert provenance.source_revision(target) == target_sha[:12]


def test_doctor_provenance_reports_package_and_revision(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor_provenance,
        "runtime_provenance",
        lambda: provenance.Provenance("1.2.3", "abcdef123456"),
    )
    checks = doctor_provenance.check_provenance()
    assert len(checks) == 1
    assert checks[0].group == "version"
    assert checks[0].status == "ok"
    assert checks[0].detail == "package=1.2.3 revision=abcdef123456"


def test_source_root_returns_none_when_checkout_markers_are_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(provenance.Path, "is_file", lambda self: False)
    assert provenance.source_root() is None


def test_clean_git_env_tolerates_rev_parse_failure(monkeypatch) -> None:
    monkeypatch.setenv("GIT_DIR", "/tmp/outer.git")
    monkeypatch.setattr(
        provenance.subprocess,
        "run",
        lambda *args, **kwargs: provenance.subprocess.CompletedProcess(
            args[0],
            1,
            "",
            "not a repository",
        ),
    )
    env = provenance._clean_git_env("/usr/bin/git")
    assert env["GIT_DIR"] == "/tmp/outer.git"


def test_source_revision_reports_unknown_without_git(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(provenance.shutil, "which", lambda name: None)
    assert provenance.source_revision(tmp_path) == "unknown"


def test_source_revision_reports_unknown_for_bad_or_short_head(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(provenance.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(provenance, "_clean_git_env", lambda git: {})

    monkeypatch.setattr(
        provenance.subprocess,
        "run",
        lambda *args, **kwargs: provenance.subprocess.CompletedProcess(
            args[0],
            1,
            "",
            "bad HEAD",
        ),
    )
    assert provenance.source_revision(tmp_path) == "unknown"

    monkeypatch.setattr(
        provenance.subprocess,
        "run",
        lambda *args, **kwargs: provenance.subprocess.CompletedProcess(
            args[0],
            0,
            "abc\n",
            "",
        ),
    )
    assert provenance.source_revision(tmp_path) == "unknown"


def test_source_revision_reports_unknown_on_git_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(provenance.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(provenance, "_clean_git_env", lambda git: {})

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 3)

    monkeypatch.setattr(provenance.subprocess, "run", timeout)
    assert provenance.source_revision(tmp_path) == "unknown"


def test_doctor_provenance_legacy_alias_preserves_module_identity() -> None:
    from binnacle.diagnostics import doctor_provenance as implementation

    assert doctor_provenance is implementation
