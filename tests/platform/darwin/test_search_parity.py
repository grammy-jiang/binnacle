"""Native rg differential evidence for the explicitly supported search subset."""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
from contextlib import closing
from dataclasses import replace

import pytest

from binnacle.platform.contracts.capability_contracts import (
    BudgetExceeded,
    CapabilityState,
    CapabilityUnavailable,
    UnsafePath,
)
from binnacle.platform.contracts.file_access_contracts import (
    ListRequest,
    SearchAccess,
    SearchRequest,
)
from binnacle.platform.darwin import search_access
from binnacle.platform.darwin.file_access import DarwinFileAccess
from binnacle.platform.darwin.search_access import DarwinSearchAccess


@pytest.fixture
def tree(tmp_path):
    root = tmp_path.resolve() / "root"
    root.mkdir()
    rg = shutil.which("rg")
    assert rg, "ripgrep is a required development tool"
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        search: SearchAccess = DarwinSearchAccess(files, rg_bin=rg)
        yield root, files, grant, search, rg


def request(**kwargs):
    return replace(
        SearchRequest(".", "needle", False, 0, None, 5, 1000000, 100), **kwargs
    )


def content(events):
    return sorted(
        (
            event["type"],
            event["data"]["path"],
            event["data"]["line_number"],
            event["data"]["lines"],
            event["data"].get("submatches"),
        )
        for event in [
            {
                "type": e["type"],
                "data": {
                    **e["data"],
                    "path": e["data"].get("path", {}).get("text", ""),
                },
            }
            for e in events
            if e["type"] in ("match", "context")
        ]
    )


def baseline(root, rg, req):
    argv = [rg, "--no-config", "--json", "--smart-case"]
    if req.fixed_strings:
        argv.append("--fixed-strings")
    if req.context_lines:
        argv += ["--context", str(req.context_lines)]
    result = subprocess.run(
        argv + ["--regexp", req.pattern, "."],
        cwd=root,
        capture_output=True,
        check=False,
    )
    assert result.returncode in (0, 1)
    events = [json.loads(line) for line in result.stdout.splitlines()]
    for event in events:
        if "path" in event["data"]:
            path = event["data"]["path"]["text"]
            event["data"]["path"]["text"] = path.removeprefix("./")
    return events


@pytest.mark.parametrize(
    "pattern,fixed,context",
    [
        ("needle", False, 0),
        ("Needle", False, 1),
        ("needle.*", False, 2),
        ("needle.*", True, 1),
        ("not-present", True, 0),
        ("^", False, 1),
    ],
)
def test_native_rg_case_literal_regex_context_and_no_match(
    tree, pattern, fixed, context
):
    root, _, grant, search, rg = tree
    (root / "a.txt").write_bytes(b"before\nNeedle\nneedle.*\nafter\n")
    (root / "newline\nname.txt").write_bytes(b"needle\n")
    (root / "invalid-utf8").write_bytes(b"needle\xff\n")
    (root / ".hidden").write_bytes(b"needle\n")
    (root / "empty").write_bytes(b"")
    req = request(pattern=pattern, fixed_strings=fixed, context_lines=context)
    result = search.search(grant, req)
    assert content(result.events) == content(baseline(root, rg, req))
    assert result.files_searched == 4
    assert not result.truncated
    assert result.capability.state == CapabilityState.LIMITED


def test_native_local_ignore_and_glob_parity(tree):
    root, files, grant, search, rg = tree
    (root / ".ignore").write_text("*.log\n/skip/\n")
    (root / ".rgignore").write_text("omit.txt\n")
    (root / "skip").mkdir()
    (root / "skip/hidden-by-rule.txt").write_text("needle")
    (root / "nested").mkdir()
    (root / "nested/.ignore").write_text("local.txt\n")
    for name in (
        "keep.txt",
        "noise.log",
        "omit.txt",
        "nested/local.txt",
        "nested/good.txt",
    ):
        (root / name).write_text("needle\n")
    result = search.search(grant, request())
    assert content(result.events) == content(baseline(root, rg, request()))
    result = search.search(grant, request(glob="**/*.txt"))
    assert {e[1] for e in content(result.events)} == {"keep.txt", "nested/good.txt"}
    listing = files.list_entries(
        grant, ListRequest(".", "**/*.txt", False, 100, 1000, 5)
    )
    assert {e.relative_path for e in listing.entries} == {"keep.txt", "nested/good.txt"}


@pytest.mark.parametrize(
    "name,data",
    [(".gitignore", "*.log"), (".ignore", "!keep.txt"), (".rgignore", "[abc].txt")],
)
def test_unsupported_ignore_policy_is_explicit_not_empty_success(tree, name, data):
    root, _, grant, search, _ = tree
    (root / name).write_text(data)
    (root / "keep.txt").write_text("needle")
    with pytest.raises(CapabilityUnavailable, match="ignore_policy"):
        search.search(grant, request())


def test_git_repository_policy_refuses_external_discovery(tree):
    root, _, grant, search, _ = tree
    (root / ".git").mkdir()
    with pytest.raises(CapabilityUnavailable, match="git_ignore_policy"):
        search.search(grant, request())


def test_direct_file_search_and_glob(tree):
    root, _, grant, search, _ = tree
    (root / ".hidden").write_text("needle\n")
    result = search.search(grant, request(relative_path=".hidden"))
    assert result.files_searched == 1
    assert content(result.events)[0][1] == ".hidden"
    assert (
        search.search(
            grant, request(relative_path=".hidden", glob="*.py")
        ).files_searched
        == 0
    )


def test_native_rg_bad_pattern_empty_tree_and_missing_binary(tree):
    root, files, grant, search, _ = tree
    with pytest.raises(CapabilityUnavailable, match="rg_rejected"):
        search.search(grant, request(pattern="["))
    missing = DarwinSearchAccess(files, rg_bin=str(root / "missing-rg"))
    with pytest.raises(CapabilityUnavailable, match="rg_unavailable"):
        missing.search(grant, request())
    assert search.search(grant, request()).files_searched == 0


def test_search_budgets_report_truncation_without_partial_line_matches(tree):
    root, _, grant, search, _ = tree
    (root / "file").write_text("needle\n" * 100)
    result = search.search(grant, request(max_bytes=10))
    assert result.truncated and not result.events and result.files_searched == 0
    (root / "file").write_text("needle\n")
    result = search.search(grant, request(max_bytes=100))
    assert result.truncated  # JSON output budget, not just input bytes.
    (root / "other").write_text("needle\n")
    assert search.search(grant, request(max_files=1)).truncated
    for req in (
        request(max_files=0),
        request(timeout_s=float("nan")),
        request(context_lines=-1),
    ):
        with pytest.raises(BudgetExceeded):
            search.search(grant, req)


def test_search_root_swap_at_native_launch_preserves_opened_bytes(tree, monkeypatch):
    root, _, grant, search, _ = tree
    (root / "file").write_text("needle owned\n")
    original_popen = subprocess.Popen
    seen = []

    def swap(argv, **kwargs):
        root.rename(root.with_name("moved"))
        root.mkdir()
        (root / "file").write_text("needle SECRET\n")
        seen.append(argv)
        return original_popen(argv, **kwargs)

    monkeypatch.setattr(search_access.subprocess, "Popen", swap)
    result = search.search(grant, request())
    assert "SECRET" not in repr(result.events)
    assert "owned" in repr(result.events)
    assert seen[0][-1] == "-"
    assert not any(str(root) in arg for arg in seen[0])


def test_search_leaf_swap_between_enumeration_and_open_is_denied(tree, monkeypatch):
    root, files, grant, search, _ = tree
    target = root / "file"
    target.write_text("needle owned")
    outside = root.with_name("secret")
    outside.write_text("needle SECRET")
    original_list = files.list_entries

    def swap(*args):
        result = original_list(*args)
        target.unlink()
        target.symlink_to(outside)
        return result

    monkeypatch.setattr(files, "list_entries", swap)
    with pytest.raises(UnsafePath):
        search.search(grant, request())
    assert outside.read_text() == "needle SECRET"


def test_native_timeout_and_cancel_reap_direct_child(tree, monkeypatch):
    root, _, grant, search, _ = tree
    (root / "file").write_text("needle\n")
    original_popen = subprocess.Popen
    children = []

    def slow_rg(argv, **kwargs):
        child = original_popen(
            [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs
        )
        children.append(child)
        return child

    monkeypatch.setattr(search_access.subprocess, "Popen", slow_rg)
    with pytest.raises(BudgetExceeded, match="rg_timeout"):
        search.search(grant, request(timeout_s=0.1))
    assert children[0].returncode is not None
    assert all(
        p.closed for p in (children[0].stdin, children[0].stdout, children[0].stderr)
    )

    def cancelled(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(search_access, "_pump", cancelled)
    with pytest.raises(KeyboardInterrupt):
        search.search(grant, request())
    assert children[1].returncode is not None
    assert all(
        p.closed for p in (children[1].stdin, children[1].stdout, children[1].stderr)
    )


def test_non_utf8_filename_remapped_as_rg_bytes(tree):
    root, _, grant, search, _ = tree
    try:
        fd = os.open(os.fsencode(root) + b"/bad-\xff", os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError as exc:
        if sys.platform == "darwin" and exc.errno == errno.EPERM:
            pytest.skip(
                "Darwin filesystem rejects invalid UTF-8 names; pure remapping tested separately"
            )
        raise
    os.write(fd, b"needle\n")
    os.close(fd)
    result = search.search(grant, request())
    match = next(e for e in result.events if e["type"] == "match")
    assert match["data"]["path"] == {"bytes": "YmFkLf8="}


def test_binary_policy_is_explicit(tree):
    root, _, grant, search, _ = tree
    (root / "binary").write_bytes(b"needle\0binary\n")
    for req in (request(), request(relative_path="binary")):
        with pytest.raises(CapabilityUnavailable, match="binary_search_unavailable"):
            search.search(grant, req)


def test_surrogate_filename_remapping_without_filesystem_support():
    raw = b'{"type":"begin","data":{"path":{"text":"<stdin>"}}}\n'
    events = search_access._events(raw, os.fsdecode(b"bad-\xff"), False)
    assert events[0]["data"]["path"] == {"bytes": "YmFkLf8="}


def test_subdirectory_ancestor_ignore_policy_refused(tree):
    root, _, grant, search, _ = tree
    (root / ".ignore").write_text("*.txt\n")
    (root / "sub").mkdir()
    (root / "sub/file.txt").write_text("needle")
    with pytest.raises(CapabilityUnavailable, match="ancestor_ignore_policy"):
        search.search(grant, request(relative_path="sub"))


def test_rg_configuration_cannot_inject_path_or_preprocessor(tree, monkeypatch):
    root, _, grant, search, _ = tree
    config = root.with_name("rg-config")
    config.write_text("--glob\n!*\n")
    monkeypatch.setenv("RIPGREP_CONFIG_PATH", str(config))
    (root / "file").write_text("needle\n")
    assert len(content(search.search(grant, request()).events)) == 1


def test_real_ripgrep_child_cleanup_on_expired_deadline_and_cancel(tree, monkeypatch):
    root, _, grant, search, _ = tree
    (root / "file").write_text("needle\n")
    original_popen, original_pump = subprocess.Popen, search_access._pump
    children = []

    def capture(argv, **kwargs):
        child = original_popen(argv, **kwargs)
        children.append(child)
        return child

    def expired(child, data, deadline, max_output):
        return original_pump(child, data, 0, max_output)

    monkeypatch.setattr(search_access.subprocess, "Popen", capture)
    monkeypatch.setattr(search_access, "_pump", expired)
    with pytest.raises(BudgetExceeded, match="rg_timeout"):
        search.search(grant, request())

    def cancelled(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(search_access, "_pump", cancelled)
    with pytest.raises(KeyboardInterrupt):
        search.search(grant, request())
    assert len(children) == 2
    for child in children:
        assert child.returncode is not None
        assert all(pipe.closed for pipe in (child.stdin, child.stdout, child.stderr))
