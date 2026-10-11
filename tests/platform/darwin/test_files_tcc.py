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


def _search_text(root, pattern, context_lines, *, darwin=True):
    """search_text_impl via the Darwin adapter, or the shared Linux rg path."""
    from binnacle.config import RootsSettings, SearchTextSettings
    from binnacle.features.files.paths import FileToolAccess
    from binnacle.features.search.tools.search_text import search_text_impl
    from binnacle.platform.contracts.capability_contracts import (
        Capability,
        CapabilityState,
    )

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
        args = (pattern, str(root), None, False, context_lines, False, 100)
        if not darwin:
            return search_text_impl(
                *args, roots=roots, settings=SearchTextSettings(), rg_bin="rg"
            )
        return search_text_impl(*args, roots=roots, file_access=access)
    finally:
        access.close()


@pytest.mark.parametrize("mode", ["oversize", "remaining", "exhausted", "output"])
def test_search_budget_continues_or_preserves_matches_and_explains_truncation(
    tmp_path, mode
):
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
    pattern = "hello.*" if mode == "output" else "hello"
    result = _search_text(root, pattern, 0)
    payload = result.structured_content
    text = result.content[0].text
    # Linux rg searches every byte and consumes all rg output: Pi CASES.json
    # st.basic (21 MB fx.big: truncated=false, no note) and, for [output], Pi
    # LINUX-AGG-CAP.json tcc_output (count=3, truncated=false, same bytes).
    names = ["00-first.txt", "hello.txt"]
    names[1:1] = ["a.txt"] if mode == "output" else []
    assert payload["truncated"] is False and "truncated=true" not in text
    assert payload["count"] == len(names)
    assert [e["file"] for e in payload["entries"]] == [str(root / n) for n in names]
    assert text == f"Found {len(names)} matches for {pattern!r} under {root}."


MiB = 1024 * 1024
# Pi LINUX-AGG-CAP.json (review R-J6b-a1, agg_cap_linux.py): byte-identical
# fixtures; measured Linux count, truncated, entry count and entry files, equal
# for context_lines None and 0. Over 16 MiB of rg JSON except the control.
LINUX_AGG_CAP = {
    "control_fx_big": (
        "needle",
        {"sub/n.txt": b"alpha\nbeta needle\ngamma\n", "huge.txt": b"a" * 21_000_000},
        (1, False, 1, ["sub/n.txt"]),
    ),
    "one_long_line": (
        "hello",
        {"hello.txt": b"hello\n", "big.txt": b"hello" + b"A" * (16 * MiB + 1024)},
        (2, False, 2, ["big.txt", "hello.txt"]),
    ),
    "few_long_lines": (
        "needle",
        {
            "long.txt": b"".join(
                b"needle " + b"b" * (2 * MiB) + b"\n" for _ in range(10)
            ),
            "small.txt": b"needle small\n",
        },
        (11, False, 11, ["long.txt", "small.txt"]),
    ),
    "many_matches": (
        "needle",
        {
            "many.txt": b"".join(
                b"needle %06d padding padding padding padding padding\n" % i
                for i in range(250_000)
            )
        },
        (250_000, True, 100, ["many.txt"]),
    ),
    "tcc_output": (
        "hello.*",
        {
            "00-first.txt": b"hello\n",
            "a.txt": b"hello " + b"x" * (9 * MiB),
            "hello.txt": b"hello e0\n",
        },
        (3, False, 3, ["00-first.txt", "a.txt", "hello.txt"]),
    ),
}


@pytest.mark.parametrize("context_lines", [None, 0])
@pytest.mark.parametrize("case", sorted(LINUX_AGG_CAP))
def test_search_over_16_mib_of_rg_output_equals_linux(tmp_path, case, context_lines):
    pattern, fixture, (count, truncated, n_entries, names) = LINUX_AGG_CAP[case]
    root = tmp_path.resolve()
    for rel, data in fixture.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    result = _search_text(root, pattern, context_lines)
    payload, text = result.structured_content, result.content[0].text
    entries = payload["entries"]
    assert (payload["count"], payload["truncated"], len(entries)) == (
        count,
        truncated,
        n_entries,
    )
    assert sorted({e["file"].removeprefix(f"{root}/") for e in entries}) == names
    # Entry text (clipped long lines, context) equals the shared Linux rg path;
    # Linux rg emits entries in unspecified order, Darwin in path order.
    linux = _search_text(root, pattern, context_lines, darwin=False)
    key = lambda e: (e["file"], e["line"])
    assert sorted(entries, key=key) == sorted(
        linux.structured_content["entries"], key=key
    )
    found = f"Found {count} matches for {pattern!r} under {root}"
    if truncated:  # Linux's note and '; showing first 100.' live in the shared layer.
        assert text.startswith(found + ".")
    else:
        assert text == found + "." and "note" not in payload
