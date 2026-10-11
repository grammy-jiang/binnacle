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
    argv = [rg, "--no-config", "--json", "--smart-case", "--text"]
    if req.fixed_strings:
        argv.append("--fixed-strings")
    if req.context_lines:
        argv += ["--context", str(req.context_lines)]
    result = subprocess.run(
        argv + ["--regexp", req.pattern, req.relative_path],
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


def make_repository_fixture(root):
    """Portable tree for the Pi equality receipt; no git subprocess or config."""
    (root / ".git").mkdir()
    files = {
        ".git/config": "needle\n",
        ".gitignore": "node_modules/\n*.log\n*.tmp\n",
        ".ignore": "*.ignored\n!priority.log\n",
        ".rgignore": "*.rg\n!override.ignored\n",
        "nested/.gitignore": "!keep.tmp\n!priority.ignored\n",
        "node_modules/dependency": "needle\n",
        "ignored.log": "needle\n",
        "dropped.tmp": "needle\n",
        "drop.ignored": "needle\n",
        "drop.rg": "needle\n",
        "nested/drop.tmp": "needle\n",
        "nested/keep.tmp": "needle\n",
        "nested/priority.ignored": "needle\n",
        "priority.log": "needle\n",
        "override.ignored": "needle\n",
        "keep.txt": "needle\n",
        ".hidden": "needle\n",
        "nested/good.txt": "needle\n",
    }
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data)
    (root / "binary").write_bytes(b"\0needle\n")


@pytest.mark.parametrize("hidden", [False, True])
def test_repository_ignore_and_binary_equality_with_rg(tree, hidden):
    root, files, grant, search, rg = tree
    make_repository_fixture(root)
    batch = search.search(grant, request())
    assert content(batch.events) == content(baseline(root, rg, request()))
    assert batch.events[-1]["data"]["stats"]["binary_files_skipped"] == 0
    argv = [rg, "--no-config", "--files"]
    if hidden:
        argv += ["--hidden", "--glob", "!**/.git/**"]
    expected = subprocess.run(
        argv, cwd=root, capture_output=True, text=True, check=True
    )
    listing = files.list_entries(grant, ListRequest(".", "**/*", hidden, 100, 1000, 5))
    assert {e.relative_path for e in listing.entries} == set(
        expected.stdout.splitlines()
    )


@pytest.mark.parametrize("glob", ["*.py", "*.hidden", ".hidden", "**/*", "sub/*"])
def test_direct_file_search_and_glob(tree, glob):
    root, _, grant, search, _ = tree
    (root / ".hidden").write_text("needle\n")
    result = search.search(grant, request(relative_path=".hidden"))
    assert result.files_searched == 1
    assert content(result.events)[0][1] == ".hidden"
    from binnacle.features.search.search_text_collect import matches_glob

    expected = matches_glob(str(root / ".hidden"), root / ".hidden", glob)
    filtered = search.search(grant, request(relative_path=".hidden", glob=glob))
    assert filtered.files_searched == int(expected)


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
    # An oversize file is skipped and reported, not a capped result set.
    assert not result.truncated and not content(result.events)
    assert result.files_searched == 0
    assert result.events[-1]["data"]["stats"]["skipped_oversize"] == 1
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


@pytest.mark.parametrize("replacement", ["symlink", "directory", "missing"])
def test_search_leaf_swap_between_enumeration_and_open_is_denied(
    tree, monkeypatch, replacement
):
    root, files, grant, search, _ = tree
    (root / "good").write_text("needle sibling")
    target = root / "file"
    target.write_text("needle owned")
    outside = root.with_name("secret")
    outside.write_text("needle SECRET")
    original_list = files.list_entries

    def swap(*args):
        result = original_list(*args)
        target.unlink()
        if replacement == "symlink":
            target.symlink_to(outside)
        elif replacement == "directory":
            target.mkdir()
        return result

    monkeypatch.setattr(files, "list_entries", swap)
    result = search.search(grant, request())
    assert {e[1] for e in content(result.events)} == {"good"}
    assert result.events[-1]["data"]["stats"]["skipped_changed"] == 1
    assert "SECRET" not in repr(result.events)
    monkeypatch.setattr(files, "list_entries", original_list)
    with pytest.raises(UnsafePath):
        search.search(
            grant,
            request(
                relative_path="file/missing" if replacement == "directory" else "file"
            ),
        )
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
        if sys.platform == "darwin" and exc.errno in (errno.EPERM, errno.EILSEQ):
            pytest.skip(
                "APFS rejects non-UTF-8 names (EPERM/EILSEQ); A4 owns this skip; pure remapping tested separately"
            )
        raise
    os.write(fd, b"needle\n")
    os.close(fd)
    result = search.search(grant, request())
    match = next(e for e in result.events if e["type"] == "match")
    assert match["data"]["path"] == {"bytes": "YmFkLf8="}


def test_binary_files_are_searched_as_text(tree):
    root, files, grant, search, _ = tree
    (root / "binary").write_bytes(b"needle\0binary\n")
    (root / "text").write_text("needle\n")
    for req, expected in (
        (request(), {"binary", "text"}),
        (request(relative_path="binary"), {"binary"}),
    ):
        batch = search.search(grant, req)
        assert batch.events[-1]["data"]["stats"]["binary_files_skipped"] == 0
        assert not batch.truncated
        assert {e[1] for e in content(batch.events)} == expected
    with pytest.raises(CapabilityUnavailable, match="rg_rejected"):
        search.search(grant, request(relative_path="binary", pattern="["))
    assert {
        e.relative_path
        for e in files.list_entries(
            grant, ListRequest(".", "**/*", False, 100, 1000, 5)
        ).entries
    } == {"binary", "text"}


def test_subdirectory_inherits_only_ignore_files_within_grant(tree, monkeypatch):
    root, _, grant, search, _ = tree
    (root.parent / ".ignore").write_text("*\n")
    (root / ".ignore").write_text("*.txt\n")
    (root / "sub").mkdir()
    (root / "sub/file.txt").write_text("needle")
    (root / "sub/keep").write_text("needle")
    real_open = os.open

    def scoped(path, flags, *args, **kwargs):
        assert kwargs.get("dir_fd") is not None
        assert not os.path.isabs(path) and ".." not in path.split("/")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", scoped)
    result = search.search(grant, request(relative_path="sub"))
    assert {e[1] for e in content(result.events)} == {"sub/keep"}


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


def test_pump_oserror_is_typed_and_reaps_child(tree, monkeypatch):
    from binnacle.platform.contracts.capability_contracts import AuthorityUnknown

    root, _, grant, search, _ = tree
    (root / "file").write_text("needle")
    real_popen = subprocess.Popen
    children = []

    def capture(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    def failed(*args):
        raise OSError(errno.EIO, "secret error")

    monkeypatch.setattr(subprocess, "Popen", capture)
    monkeypatch.setattr(search_access, "_pump", failed)
    with pytest.raises(AuthorityUnknown, match="file_io_failed"):
        search.search(grant, request())
    assert children[0].returncode is not None
    assert all(
        p.closed for p in (children[0].stdin, children[0].stdout, children[0].stderr)
    )


def test_rg_path_is_captured_at_composition(tree, monkeypatch):
    root, files, grant, _, rg = tree
    (root / "file").write_text("needle")
    search = DarwinSearchAccess(files, rg_bin="rg")
    assert os.path.isabs(search._rg_bin)
    assert search._rg_bin == os.path.abspath(rg)
    monkeypatch.setenv("PATH", str(root))
    assert search.search(grant, request()).files_searched == 1


def test_event_stream_shape_multi_file(tree):
    root, _, grant, search, rg = tree
    for index, name in enumerate(("z", "a", "m")):
        (root / name).write_text("needle\nneedle needle\n")
        os.utime(root / name, (100 + index, 100 + index))
    result = search.search(grant, request())
    summaries = [e for e in result.events if e["type"] == "summary"]
    assert len(summaries) == 1 and result.events[-1] == summaries[0]
    expected = next(e for e in baseline(root, rg, request()) if e["type"] == "summary")
    for key in (
        "searches",
        "searches_with_match",
        "matched_lines",
        "matches",
        "bytes_searched",
    ):
        assert summaries[0]["data"]["stats"][key] == expected["data"]["stats"][key]
    assert [
        e["data"]["path"]["text"] for e in result.events if e["type"] == "begin"
    ] == ["a", "m", "z"]


@pytest.mark.parametrize(
    "policy", ["!sub/\n", "sub/\n*.txt\n", "!sub/**\n", "!.hidden\n"]
)
def test_ignore_explicit_scope_and_hidden_negation(tree, policy):
    root, _, grant, search, rg = tree
    (root / ".ignore").write_text(policy)
    (root / "sub").mkdir()
    for name in ("sub/file", "sub/file.txt", "sub/.hidden", ".hidden"):
        (root / name).write_text("needle\n")
    for scope in (".", "sub"):
        req = request(relative_path=scope)
        assert content(search.search(grant, req).events) == content(
            baseline(root, rg, req)
        )


@pytest.mark.parametrize("error", [errno.EPERM, errno.EILSEQ])
def test_non_utf8_skip_guard_is_specific(tree, monkeypatch, error):
    monkeypatch.setattr(sys, "platform", "darwin")  # Test the APFS guard on Linux too.

    def rejected(*args, **kwargs):
        raise OSError(error, "invalid filename")

    monkeypatch.setattr(os, "open", rejected)
    with pytest.raises(pytest.skip.Exception, match="APFS"):
        test_non_utf8_filename_remapped_as_rg_bytes(tree)
