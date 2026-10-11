"""Linux list walk permissions, one walk per link, open_verified (X3a-a2).

SD-76 fixes R-X3a: RX3a-F1, execute-only directories in the root chain or
inside a root list as in r6 (the walk traverses with O_PATH; only the listed
directory is opened O_RDONLY). RX3a-F2, EACCES/EPERM from the walk is the
coded refusal permission_denied. RX3a-F3, a link resolves through the open
descriptor chain of the listed directory, with no new walk from the root.
open_verified is the verify-after-open helper that X3b (read_file) wires in.
"""

import errno
import os
import socket
import stat
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk
from binnacle.features.files.tools import list_files as lf

SECRET = "s" * 4321  # A size that appears nowhere else in the fixture.
not_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores modes")


def run(roots: RootsSettings, path: Path):
    return lf.list_files_impl(str(path), None, 200, False, roots=roots)


def types(result) -> dict:
    payload = result.structured_content
    assert payload is not None
    return {Path(e["path"]).name: e["type"] for e in payload["entries"]}


@pytest.fixture
def chmod_back():
    """Restore every directory mode a test lowered, so tmp_path cleans up."""
    changed: list[tuple[Path, int]] = []

    def lower(path: Path, mode: int) -> None:
        changed.append((path, stat.S_IMODE(path.stat().st_mode)))
        path.chmod(mode)

    yield lower
    for path, mode in reversed(changed):
        path.chmod(mode)


# RX3a-F1/F2 beyond the PROBE-perm cases (test_r6w2_x3a2_probe_perm.py).


@pytest.fixture
def r2(tmp_path: Path) -> dict:
    base = tmp_path.resolve()
    root = base / "r2"
    (root / "x" / "y").mkdir(parents=True)
    (root / "x" / "y" / "g.txt").write_text("g")
    (root / "via").symlink_to("x/y/g.txt")
    return {"root": root, "roots": RootsSettings(default_root=root, extra_roots=())}


@not_root
def test_an_unsearchable_ancestor_is_permission_denied(r2, chmod_back, monkeypatch):
    # The mode changes after the path checks, as the walk opens the root.
    listed = r2["root"] / "x" / "y"
    real_open_root = fd_walk.open_root

    def lock_then_open(root, *args):
        chmod_back(r2["root"] / "x", 0o600)
        return real_open_root(root, *args)

    monkeypatch.setattr(fd_walk, "open_root", lock_then_open)
    with pytest.raises(ToolError, match="Permission denied") as exc:
        run(r2["roots"], listed)
    assert isinstance(exc.value, CodedToolError)
    assert exc.value.telemetry_code == "permission_denied"


@not_root
def test_a_readable_listed_root_with_no_search_lists_names_as_r6(tmp_path, chmod_back):
    root = tmp_path.resolve() / "root"
    (root / "sub").mkdir(parents=True)
    roots = RootsSettings(default_root=root, extra_roots=())
    assert roots.canonical_allowed
    chmod_back(root, 0o444)  # Names readable, every lstat EACCES: omitted.
    payload = run(roots, root).structured_content
    assert payload is not None
    assert payload["entries"] == [] and payload["count"] == 0


def test_the_walk_traverses_with_o_path_and_reads_only_the_listed_dir(r2, monkeypatch):
    opened: list[tuple[str, int]] = []
    real_open = os.open

    def record(path, flags, *args, **kwargs):
        opened.append((os.fspath(path), flags))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(fd_walk.os, "open", record)
    run(r2["roots"], r2["root"] / "x" / "y")
    monkeypatch.undo()
    readable = [name for name, flags in opened if flags == fd_walk.DIRECTORY_FLAGS]
    assert readable == ["y"]
    assert fd_walk.TRAVERSE_FLAGS & os.O_PATH
    assert all(flags == fd_walk.TRAVERSE_FLAGS for name, flags in opened if name != "y")


# RX3a-F3: one walk per link, through the open chain of the listed directory.


def test_a_link_opens_each_further_component_once(tmp_path, monkeypatch):
    root = tmp_path.resolve() / "root"
    listed = root / "a" / "b" / "c"
    (root / "d" / "e").mkdir(parents=True)
    listed.mkdir(parents=True)
    (root / "d" / "e" / "f.txt").write_text("ff")
    roots = RootsSettings(default_root=root, extra_roots=())
    count = [0]
    real_open = os.open

    def counting(*args, **kwargs):
        count[0] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(fd_walk.os, "open", counting)
    run(roots, listed)
    baseline = count[0]
    (listed / "l").symlink_to("../../../d/e/f.txt")
    count[0] = 0
    result = run(roots, listed)
    monkeypatch.undo()
    assert types(result) == {"l": "file"}
    # '..' x3 return to opened parents; only d and e are opened.
    assert count[0] - baseline == 2


def test_a_link_resolves_in_the_enumerated_directory(tmp_path, monkeypatch):
    # The listed directory is renamed inside the root after it was opened; its
    # entries are typed from the enumerated directory, not from the new one.
    root = tmp_path.resolve() / "root"
    (root / "a").mkdir(parents=True)
    (root / "a" / "t").write_text("t")
    (root / "a" / "l").symlink_to("t")
    roots = RootsSettings(default_root=root, extra_roots=())
    real_listdir = os.listdir

    def listdir_then_rename(fd):
        names = real_listdir(fd)
        (root / "a").rename(root / "a.old")
        (root / "a").mkdir()
        (root / "a" / "t").write_text(SECRET)
        (root / "a" / "l").symlink_to("t")
        return names

    monkeypatch.setattr(os, "listdir", listdir_then_rename)
    payload = run(roots, root / "a").structured_content
    monkeypatch.undo()
    assert payload is not None
    sizes = {Path(e["path"]).name: e.get("bytes") for e in payload["entries"]}
    assert sizes == {"l": 1, "t": 1}


def test_link_target_info_without_a_chain_opens_one(tmp_path):
    root = tmp_path.resolve() / "root"
    (root / "d").mkdir(parents=True)
    (root / "d" / "t").write_text("tt")
    (root / "d" / "l").symlink_to("../d/t")
    with fd_walk.open_root(root) as fd:
        info = fd_walk.link_target_info(fd, ("d",), "l", str(root))
        assert info is not None and info.st_size == 2
        assert fd_walk.link_target_info(fd, ("missing",), "l", str(root)) is None


def test_no_descriptor_leaks_across_permission_failures(r2, chmod_back):
    if os.geteuid() == 0:
        pytest.skip("root ignores modes")
    listed = r2["root"] / "x" / "y"
    before = len(os.listdir("/proc/self/fd"))
    chmod_back(listed, 0o300)
    for _ in range(10):
        with pytest.raises(ToolError):
            run(r2["roots"], listed)
    assert len(os.listdir("/proc/self/fd")) == before


# open_verified: the X3b verify-after-open helper (SD-76).


@pytest.fixture
def files(tmp_path: Path) -> dict:
    base = tmp_path.resolve()
    outer, other, out = base / "outer", base / "other", base / "out"
    inner = outer / "inner"
    for d in (outer, inner, other, out):
        d.mkdir()
    for path, text in (
        (outer / "o.txt", "outer"),
        (inner / "i.txt", "inner"),
        (other / "x.txt", "other"),
        (out / "secret.txt", SECRET),
    ):
        path.write_text(text)
    return {
        "outer": outer,
        "inner": inner,
        "other": other,
        "out": out,
        "roots": (outer, inner, other),
    }


def ident(path: Path) -> tuple[int, int]:
    info = os.lstat(path)
    return info.st_dev, info.st_ino


def refused(path: Path | str, roots, expected) -> CodedToolError:
    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(CodedToolError) as exc:
        fd_walk.open_verified(path, roots, expected)
    assert len(os.listdir("/proc/self/fd")) == before  # The fd was closed.
    assert str(len(SECRET)) not in str(exc.value)
    return exc.value


@pytest.mark.parametrize("name", ["o.txt", "inner/i.txt"])
def test_open_verified_returns_a_readable_fd_in_any_root(files, name):
    path = files["outer"] / name
    fd = fd_walk.open_verified(path, files["roots"], ident(path))
    try:
        assert os.read(fd, 100) == path.read_bytes()
        assert os.get_inheritable(fd) is False
    finally:
        os.close(fd)
    other = files["other"] / "x.txt"
    fd = fd_walk.open_verified(str(other), [files["other"]], ident(other))
    os.close(fd)


def test_open_verified_refuses_a_final_symlink(files):
    link = files["outer"] / "l"
    link.symlink_to("o.txt")
    err = refused(link, files["roots"], ident(files["outer"] / "o.txt"))
    assert err.telemetry_code == "path_changed"


def test_open_verified_refuses_a_missing_file(files):
    path = files["outer"] / "gone.txt"
    assert refused(path, files["roots"], (0, 0)).telemetry_code == "path_changed"


@not_root
def test_open_verified_refuses_an_unreadable_file(files, chmod_back):
    path = files["outer"] / "o.txt"
    chmod_back(path, 0o000)
    err = refused(path, files["roots"], ident(path))
    assert err.telemetry_code == "permission_denied"


def test_open_verified_refuses_an_unopenable_object(files):
    path = files["outer"] / "sock"
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind(str(path))
        err = refused(path, files["roots"], ident(path))
    assert err.telemetry_code == "file_io_failed"


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_open_verified_refuses_a_non_regular_file(files, kind):
    path = files["inner"] if kind == "directory" else files["outer"] / "fifo"
    if kind == "fifo":
        os.mkfifo(path)  # O_NONBLOCK: the open does not wait for a writer.
    err = refused(path, files["roots"], ident(path))
    assert err.telemetry_code == "not_a_regular_file"


def test_open_verified_refuses_a_real_path_outside_every_root(files):
    # An intermediate symlink is followed by the open; the kernel path of the
    # opened object is outside the roots, so the identity match is not enough.
    (files["outer"] / "dlink").symlink_to(files["out"], target_is_directory=True)
    path = files["outer"] / "dlink" / "secret.txt"
    err = refused(path, files["roots"], ident(files["out"] / "secret.txt"))
    assert err.telemetry_code == "path_outside_root"


def test_open_verified_refuses_another_object(files):
    path = files["outer"] / "o.txt"
    expected = ident(files["inner"] / "i.txt")
    assert refused(path, files["roots"], expected).telemetry_code == "path_changed"


def test_open_verified_maps_a_failure_after_the_open(files, monkeypatch):
    path = files["outer"] / "o.txt"

    def broken(fd: int) -> str:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(fd_walk, "_opened_path", broken)
    err = refused(path, files["roots"], ident(path))
    assert err.telemetry_code == "file_io_failed"


def test_open_verified_opens_no_follow_non_blocking(files, monkeypatch):
    flags_seen: list[int] = []
    real_open = os.open

    def record(path, flags, *args, **kwargs):
        flags_seen.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(fd_walk.os, "open", record)
    path = files["outer"] / "o.txt"
    os.close(fd_walk.open_verified(path, files["roots"], ident(path)))
    wanted = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY
    assert flags_seen == [wanted]
