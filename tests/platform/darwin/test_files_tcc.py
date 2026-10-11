"""Typed permission boundary, injected TCC-like errno plus real mode denials.

An injected EPERM is not a native TCC receipt. No privacy settings are changed.
"""

import errno
import os
from contextlib import closing

import pytest

from binnacle.platform.contracts.capability_contracts import PermissionDenied
from binnacle.platform.contracts.file_access_contracts import ListRequest, SearchRequest
from binnacle.platform.darwin.file_access import DarwinFileAccess
from binnacle.platform.darwin.search_access import DarwinSearchAccess


@pytest.mark.parametrize("error", [errno.EACCES, errno.EPERM])
@pytest.mark.parametrize(
    "operation", ["grant", "read", "write", "list", "hint", "search"]
)
def test_tcc_like_denial_is_typed_without_widening(
    tmp_path, monkeypatch, error, operation
):
    root = tmp_path.resolve()
    (root / "denied").write_bytes(b"secret")
    calls = []
    real_open = os.open
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")

        def denied_open(path, flags, *args, **kwargs):
            calls.append((path, kwargs.get("dir_fd")))
            raise OSError(error, "secret-bearing native error")

        monkeypatch.setattr(os, "open", denied_open)
        operations = {
            "grant": lambda: files.grant(root, generation="g2"),
            "read": lambda: files.open_read(grant, "denied"),
            "write": lambda: files.write_bytes(grant, "denied", b"bad"),
            "list": lambda: files.list_entries(
                grant, ListRequest(".", None, False, 10, 100, 1)
            ),
            "hint": lambda: files.nearby_hint(grant, "missing", max_entries=10),
            "search": lambda: DarwinSearchAccess(files, rg_bin="rg").search(
                grant, SearchRequest(".", "secret", True, 0, None, 1, 10000, 10)
            ),
        }
        with pytest.raises(PermissionDenied) as failure:
            operations[operation]()
        assert failure.value.code == "permission_denied_tcc_possible"
        assert "secret" not in str(failure.value)
        assert len(calls) == 1  # No retry, privilege request or ancestor fallback.
        if operation != "grant":
            assert calls[0][1] is not None
        assert grant.generation == "g"
        monkeypatch.setattr(os, "open", real_open)
    assert (root / "denied").read_bytes() == b"secret"


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses POSIX mode denials")
def test_native_unreadable_file_and_unauthorized_write(tmp_path):
    root = tmp_path.resolve()
    target = root / "denied"
    target.write_bytes(b"secret")
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        try:
            target.chmod(0)
            with pytest.raises(PermissionDenied):
                files.open_read(grant, "denied")
            with pytest.raises(PermissionDenied):
                files.write_bytes(grant, "denied", b"bad")
            with pytest.raises(PermissionDenied):
                DarwinSearchAccess(files, rg_bin="rg").search(
                    grant,
                    SearchRequest("denied", "secret", True, 0, None, 1, 10000, 10),
                )
            target.chmod(0o444)
            with pytest.raises(PermissionDenied):
                files.write_bytes(grant, "denied", b"bad")
            assert target.stat().st_mode & 0o777 == 0o444
            root.chmod(0o555)
            with pytest.raises(PermissionDenied):
                files.write_bytes(grant, "new", b"bad")
            assert not (root / "new").exists()
        finally:
            root.chmod(0o700)
            target.chmod(0o600)
    assert target.read_bytes() == b"secret"
    assert not list(root.glob(".binnacle-write-*"))


@pytest.mark.parametrize("error", [errno.EACCES, errno.EPERM])
@pytest.mark.parametrize("directory", [False, True])
def test_denied_child_listed_without_descent_and_siblings_continue(
    tmp_path, monkeypatch, error, directory
):
    root = tmp_path.resolve()
    target = root / "denied"
    if directory:
        target.mkdir()
        (target / "secret").write_text("needle")
    else:
        target.write_text("needle")
    (root / "good").write_text("needle")
    real_open = os.open

    def deny_child(path, flags, *args, **kwargs):
        if path == "denied":
            raise OSError(error, "denied")
        return real_open(path, flags, *args, **kwargs)

    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        monkeypatch.setattr(os, "open", deny_child)
        result = files.list_entries(grant, ListRequest(".", "**/*", False, 100, 100, 5))
        assert {e.relative_path for e in result.entries} == (
            {"good"} if directory else {"denied", "good"}
        )
        search = DarwinSearchAccess(files, rg_bin="rg")
        batch = search.search(
            grant, SearchRequest(".", "needle", True, 0, None, 5, 10000, 100)
        )
        assert batch.files_searched == 1
        with pytest.raises(PermissionDenied):
            search.search(
                grant, SearchRequest("denied", "needle", True, 0, None, 5, 10000, 100)
            )


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses POSIX mode denials")
def test_native_unreadable_directory_is_listed_not_descended(tmp_path):
    root = tmp_path.resolve()
    denied = root / "denied"
    denied.mkdir()
    (denied / "secret").write_text("needle")
    (root / "good").write_text("needle")
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        try:
            denied.chmod(0)
            result = files.list_entries(
                grant, ListRequest(".", "**/*", False, 100, 100, 5)
            )
            assert {(e.relative_path, e.kind) for e in result.entries} == {
                ("good", "file"),
            }
            with pytest.raises(PermissionDenied):
                files.list_entries(
                    grant, ListRequest("denied", None, False, 100, 100, 5)
                )
        finally:
            denied.chmod(0o700)


def test_symlink_ignore_file_never_opens_external_policy(tmp_path, monkeypatch):
    root = tmp_path.resolve() / "root"
    root.mkdir()
    outside = root.parent / "external-ignore"
    outside.write_text("*\n")
    (root / ".ignore").symlink_to(outside)
    (root / "good").write_text("needle")
    real_open = os.open

    def guarded(path, flags, *args, **kwargs):
        assert path != ".ignore"
        return real_open(path, flags, *args, **kwargs)

    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="g")
        monkeypatch.setattr(os, "open", guarded)
        result = files.list_entries(grant, ListRequest(".", "**/*", False, 100, 100, 5))
        assert [e.relative_path for e in result.entries] == ["good"]


@pytest.mark.parametrize("glob", ["*.py", "**/*"])
def test_glob_listing_filters_special_and_unreadable_entries(
    tmp_path, monkeypatch, glob
):
    import socket
    from tempfile import TemporaryDirectory

    root = tmp_path.resolve()
    for name in ("a.py", "secret.key"):
        (root / name).write_text("needle\n")
    (root / "locked").mkdir()
    (root / "link.py").symlink_to(root / "a.py")
    os.mkfifo(root / "pipe.py")
    real_open = os.open
    denied_calls = []

    def deny(path, flags, *args, **kwargs):
        if path in ("secret.key", "locked"):
            denied_calls.append(path)
            raise PermissionError(errno.EACCES, "denied")
        return real_open(path, flags, *args, **kwargs)

    with (
        TemporaryDirectory(dir="/tmp") as short,
        closing(socket.socket(socket.AF_UNIX)) as sock,
        closing(DarwinFileAccess()) as files,
    ):
        sock.bind(short + "/socket")
        os.rename(short + "/socket", root / "socket.py")
        grant = files.grant(root, generation="g")
        monkeypatch.setattr(os, "open", deny)
        listing = files.list_entries(grant, ListRequest(".", glob, False, 100, 100, 5))
        expected = {"a.py"} if glob == "*.py" else {"a.py", "secret.key"}
        assert {e.relative_path for e in listing.entries} == expected
        search = DarwinSearchAccess(files, rg_bin="rg")
        batch = search.search(
            grant, SearchRequest(".", "needle", True, 0, glob, 5, 10000, 100)
        )
        assert batch.files_searched == 1
        assert batch.events[-1]["data"]["stats"]["unreadable_files_skipped"] == int(
            glob == "**/*"
        )
        if glob == "*.py":
            assert "secret.key" not in denied_calls
        plain = files.list_entries(grant, ListRequest(".", None, False, 100, 100, 5))
        assert {e.relative_path for e in plain.entries} == {
            "a.py",
            "secret.key",
            "locked",
            "link.py",
            "pipe.py",
            "socket.py",
        }


@pytest.mark.parametrize("mode", ["oversize", "remaining", "exhausted", "output"])
def test_search_budget_continues_or_preserves_matches_and_explains_truncation(
    tmp_path, mode
):
    from binnacle.config import RootsSettings
    from binnacle.features.files.paths import FileToolAccess
    from binnacle.features.search.tools.search_text import search_text_impl
    from binnacle.platform.contracts.capability_contracts import (
        Capability,
        CapabilityState,
    )

    root = tmp_path.resolve()
    budget = 16 * 1024 * 1024
    (root / "00-first.txt").write_bytes(b"hello\n")
    if mode == "oversize":
        (root / "big.bin").write_bytes(b"A" * (21 * 1024 * 1024))
    elif mode == "remaining":
        for index in range(300):
            (root / f"a{index:03}.txt").write_bytes(b"x" * (60 * 1024))
    elif mode == "exhausted":
        (root / "a.txt").write_bytes(b"x" * (budget - 6))
        (root / "b.txt").write_bytes(b"x" * (4 * 1024 * 1024))
    else:
        (root / "a.txt").write_bytes(b"hello " + b"x" * (9 * 1024 * 1024))
    (root / "hello.txt").write_text("hello e0\n")
    files = DarwinFileAccess()
    roots = RootsSettings(default_root=root, extra_roots=())
    access = FileToolAccess(
        roots=roots,
        files=files,
        search=DarwinSearchAccess(files, rg_bin="rg"),
        generation="budget-test",
        capability=Capability(CapabilityState.LIMITED, "test_only", "opened-object"),
    )
    try:
        result = search_text_impl(
            "hello.*" if mode == "output" else "hello",
            str(root),
            None,
            False,
            0,
            False,
            100,
            roots=roots,
            file_access=access,
        )
        payload = result.structured_content
        text = result.content[0].text
        assert payload["entries"][0]["file"] == str(root / "00-first.txt")
        if mode in ("oversize", "remaining", "exhausted"):
            # Linux rg searches every byte (Pi CASES.json st.basic with the 21 MB
            # fx.big file: truncated=false, no skip note): no input limit.
            assert payload["truncated"] is False and "truncated=true" not in text
            assert payload["count"] == 2
            assert [e["file"] for e in payload["entries"]] == [
                str(root / "00-first.txt"),
                str(root / "hello.txt"),
            ]
            assert text == f"Found 2 matches for 'hello' under {root}."
        else:
            assert payload["truncated"] and "truncated=true" in text
            assert payload["count"] == 1
            assert "Aggregate output budget exhausted" in text
    finally:
        access.close()
