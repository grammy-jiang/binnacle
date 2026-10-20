"""P1.6 synthetic subprocess/filesystem integration, no provider safety claims."""

import json
import os
import signal

import pytest

from tests.fixtures.lsp.analyzer_audit import OUTPUT_LIMIT, audit
from tests.fixtures.lsp.process_observer import ProcessObserver
from tests.fixtures.lsp.side_effects import differences, manifest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX fixture observer")


@pytest.fixture
def sandbox(tmp_path):
    (tmp_path / ".fixture-sandbox").touch()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "external-cache").mkdir()
    (workspace / "fixture.py").write_text("x = 1\n")
    (workspace / ".gitignore").write_text(".ignored-cache/\n")
    return tmp_path


@pytest.mark.parametrize(
    "scenario", ["clean", "findings", "nonzero-findings", "stderr"]
)
def test_complete_cli_results(sandbox, scenario):
    result = audit(sandbox, scenario)
    assert result.status == "complete"
    assert result.exit_code == (1 if scenario == "nonzero-findings" else 0)
    assert result.cleanup_verified
    assert not any(result.changes.values())
    if "findings" in scenario:
        assert not result.clean
        assert result.diagnostics == [
            {
                "path": "fixture.py",
                "severity": "error",
                "code": "FIX001",
                "message": "Synthetic finding → 文\nsecond line",
                "range": {
                    "start": {"line": 0, "character": 1},
                    "end": {"line": 0, "character": 2},
                },
            }
        ]
    else:
        assert result.clean
    assert result.stderr_retained == (26 if scenario == "stderr" else 0)


@pytest.mark.parametrize(
    ("scenario", "status"),
    [
        ("malformed", "invalid"),
        ("oversize", "oversize"),
        ("timeout", "timeout"),
        ("crash", "crash"),
        ("partial", "partial"),
        ("truncated", "invalid"),
        ("empty", "invalid"),
        ("signal", "crash"),
        ("valid-json-crash", "crash"),
    ],
)
def test_failed_cli_never_becomes_clean(sandbox, scenario, status):
    result = audit(sandbox, scenario, timeout=0.5)
    assert result.status == status
    assert not result.clean
    assert result.cleanup_verified
    assert result.stdout_retained <= OUTPUT_LIMIT
    assert result.elapsed < 4
    assert not any(result.changes.values())
    if scenario == "signal":
        assert result.exit_code == -signal.SIGTERM
    if scenario == "timeout":
        events = [
            json.loads(line)["event"] for line in result.trace.read_text().splitlines()
        ]
        assert "timeout-entered" in events
        assert result.elapsed >= 0.5


@pytest.mark.parametrize(
    ("scenario", "root", "path"),
    [
        ("workspace-write", "workspace", "sentinel.txt"),
        ("ignored-cache", "workspace", ".ignored-cache/sentinel.txt"),
        ("external-cache", "external-cache", "sentinel.txt"),
        ("write-crash", "workspace", "sentinel.txt"),
        ("write-malformed", "workspace", "sentinel.txt"),
        ("write-partial", "workspace", "sentinel.txt"),
        ("write-timeout", "workspace", "sentinel.txt"),
    ],
)
def test_side_effects_reported_even_when_output_fails(sandbox, scenario, root, path):
    result = audit(sandbox, scenario, timeout=0.5)
    assert not result.clean and result.cleanup_verified
    before, after = result.changes[root][path]
    assert before is None
    assert after.kind == "file" and after.size == 22
    assert after.digest and after.mode == 0o600
    other = "external-cache" if root == "workspace" else "workspace"
    assert result.changes[other] == {}
    expected = {
        "write-crash": "crash",
        "write-malformed": "invalid",
        "write-partial": "partial",
        "write-timeout": "timeout",
    }
    assert result.status == expected.get(scenario, "complete")


def test_analyzer_child_is_observed_and_reaped(sandbox):
    result = audit(sandbox, "child")
    events = [json.loads(line) for line in result.trace.read_text().splitlines()]
    child = next(e for e in events if e["event"] == "child-ready")
    assert any(e["event"] == "child-reaped" for e in events)
    assert not ProcessObserver.pid_exists(child["pid"])
    assert not result.clean and result.cleanup_verified
    assert result.status == "complete"
    assert result.child_pids == (child["pid"],)


def test_manifest_includes_ignored_hidden_symlinks_modes_sizes_and_hashes(sandbox):
    root = sandbox / "workspace"
    hidden = root / ".ignored-cache"
    hidden.mkdir()
    file = hidden / "data"
    file.write_bytes(b"abcd")
    file.chmod(0o600)
    link = root / "link"
    link.symlink_to("../external-cache")
    (root / "dangling").symlink_to("missing")
    before = manifest(root)
    assert set(before) == {
        ".",
        ".gitignore",
        "fixture.py",
        ".ignored-cache",
        ".ignored-cache/data",
        "link",
        "dangling",
    }
    assert before["link"].target == "../external-cache"
    assert before["dangling"].target == "missing"
    file.write_bytes(b"wxyz")  # Same size: only hashing exposes the content edit.
    changed = differences(before, manifest(root))
    assert set(changed) == {".ignored-cache/data"}
    assert (
        changed[".ignored-cache/data"][0].size == changed[".ignored-cache/data"][1].size
    )
    assert (
        changed[".ignored-cache/data"][0].digest
        != changed[".ignored-cache/data"][1].digest
    )
    before = manifest(root)
    file.chmod(0o644)
    assert differences(before, manifest(root))[".ignored-cache/data"][1].mode == 0o644
    before = manifest(root)
    link.unlink()
    link.symlink_to("fixture.py")
    file.unlink()
    (root / "added").write_bytes(b"x")
    changed = differences(before, manifest(root))
    assert changed["link"][1].target == "fixture.py"
    assert changed[".ignored-cache/data"][1] is None
    assert changed["added"][0] is None


def test_external_target_is_audited_as_separate_explicit_root(sandbox):
    root = sandbox / "workspace"
    cache = sandbox / "external-cache"
    (root / "link").symlink_to(cache, target_is_directory=True)
    before_workspace, before_cache = manifest(root), manifest(cache)
    (cache / "sentinel").write_text("external")
    assert differences(before_workspace, manifest(root)) == {}
    assert "sentinel" in differences(before_cache, manifest(cache))


def test_snapshot_failure_cannot_be_reported_clean(sandbox, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("synthetic unreadable file")

    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(PermissionError, match="synthetic unreadable"):
        audit(sandbox, "clean")


def test_post_run_snapshot_error_propagates_after_cleanup(sandbox, monkeypatch):
    from tests.fixtures.lsp import analyzer_audit

    original = analyzer_audit.manifest
    calls = 0

    def fail_after_run(root):
        nonlocal calls
        calls += 1
        if calls > 2:
            raise PermissionError("post-run snapshot failed")
        return original(root)

    monkeypatch.setattr(analyzer_audit, "manifest", fail_after_run)
    with pytest.raises(PermissionError, match="post-run snapshot failed"):
        audit(sandbox, "clean")
    events = [
        json.loads(line)
        for trace in sandbox.glob("trace-*.jsonl")
        for line in trace.read_text().splitlines()
    ]
    parent = next(e["pid"] for e in events if e["event"] == "analyzer-ready")
    assert not ProcessObserver.pid_exists(parent)


def test_fake_analyzer_refuses_redirected_sentinel(sandbox):
    outside = sandbox / "external-cache" / "untouched"
    outside.write_text("original")
    (sandbox / "workspace" / "sentinel.txt").symlink_to(outside)
    result = audit(sandbox, "workspace-write")
    assert not result.clean
    assert outside.read_text() == "original"
    assert not any(result.changes.values())


def test_analyzer_child_cleanup_on_interrupted_audit(sandbox):
    from tests.fixtures.lsp.analyzer_audit import ANALYZER

    peer = ProcessObserver(
        sandbox,
        fault="child",
        command=[str(ANALYZER), "--sandbox", str(sandbox), "--scenario", "child"],
    )
    with pytest.raises(RuntimeError, match="interrupted audit"), peer:
        raise RuntimeError("interrupted audit")
    child = peer.wait_event("child-ready")
    assert peer.cleanup_verified
    assert not peer.pid_exists(child["pid"])
    assert not peer.pid_exists(peer.process.pid)
