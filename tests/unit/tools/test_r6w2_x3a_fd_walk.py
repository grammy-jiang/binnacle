"""Linux list_files LIST mode walks descriptors, as Darwin does (r6 W2 X3a).

SD-74 closes R-L4b-N1 / SR6-N3 for list: the listed directory and every
component of a link walk are opened with O_NOFOLLOW|O_DIRECTORY relative to
the descriptor of the root being listed, and every metadata or link read is
relative to an opened directory. A same-uid swap of an in-root component for
a symlink between the check and the read cannot type an outside target.
LIST-FOLLOWUP-nested-roots-parity: link resolution is confined to the root
being listed, so '..' into an outer root is omitted, as on Darwin.
"""

import json
import os
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files import fd_walk
from binnacle.features.files.tools import list_files as lf

# The process descriptor table: /proc/self/fd on Linux, /dev/fd on Darwin.
FD_DIR = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"

SECRET = "s" * 4321  # A size that appears nowhere else in the fixture.


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    base = tmp_path.resolve()
    root, out = base / "root", base / "out"
    for d in (root, out, root / "d", root / "d" / "e", out / "e"):
        d.mkdir()
    (root / "hello.txt").write_text("hello\n")
    (root / "d" / "in.txt").write_text("x")
    (root / "d" / "e" / "f.txt").write_text("ff")
    (out / "in.txt").write_text(SECRET)
    (out / "secret.txt").write_text(SECRET)
    (out / "e" / "f.txt").write_text(SECRET)
    return {
        "root": root,
        "out": out,
        "roots": RootsSettings(default_root=root, extra_roots=()),
    }


def run(roots: RootsSettings, path: Path, max_results: int = 200):
    return lf.list_files_impl(str(path), None, max_results, False, roots=roots)


def names(result) -> dict:
    payload = result.structured_content
    assert payload is not None
    return {
        Path(e["path"]).name: (e["type"], e.get("bytes")) for e in payload["entries"]
    }


def blob(result) -> str:
    text = " ".join(getattr(c, "text", "") for c in result.content)
    return json.dumps(result.structured_content, sort_keys=True) + "\n" + text


def swap_for_link(path: Path, target: Path | str) -> None:
    """Replace an in-root directory with a symlink (the same-uid racer)."""
    path.rename(path.with_name(path.name + ".moved"))
    path.symlink_to(target, target_is_directory=True)


# The listed directory: a component swapped after the gate is never followed.


@pytest.mark.parametrize("target", ["absolute", "relative"])
@pytest.mark.parametrize("component", ["listed", "intermediate"])
def test_listed_path_swapped_after_the_gate_is_not_followed(
    tree, monkeypatch, component, target
):
    root, out = tree["root"], tree["out"]
    listed = root / "d" / "e"
    swapped = listed if component == "listed" else root / "d"
    outside = out / "e" if component == "listed" else out
    real_resolve = lf.resolve_path

    def resolve_then_swap(*args, **kwargs):
        resolved = real_resolve(*args, **kwargs)
        rel = os.path.relpath(outside, swapped.parent)
        swap_for_link(swapped, outside if target == "absolute" else rel)
        return resolved

    monkeypatch.setattr(lf, "resolve_path", resolve_then_swap)
    with pytest.raises(ToolError, match="Directory changed during the listing") as exc:
        run(tree["roots"], listed)
    assert isinstance(exc.value, CodedToolError)
    assert exc.value.telemetry_code == "path_changed"
    assert str(len(SECRET)) not in str(exc.value)


def test_listed_directory_removed_after_the_checks_is_not_found(tree, monkeypatch):
    # The removal lands after resolve_path and the is_dir check, just before
    # the descriptor walk opens the root.
    listed = tree["root"] / "gone"
    listed.mkdir()
    real_open_root = fd_walk.open_root

    def remove_then_open(root):
        listed.rmdir()
        return real_open_root(root)

    monkeypatch.setattr(fd_walk, "open_root", remove_then_open)
    with pytest.raises(ToolError, match="Directory not found") as exc:
        run(tree["roots"], listed)
    assert isinstance(exc.value, CodedToolError)
    assert exc.value.telemetry_code == "directory_not_found"


def test_a_requested_alias_lists_its_resolved_in_root_directory(tree):
    root = tree["root"]
    (root / "dlink").symlink_to("d", target_is_directory=True)
    result = run(tree["roots"], root / "dlink")
    assert result.structured_content is not None
    assert result.structured_content["path"] == str(root / "d")
    assert names(result) == {"e": ("dir", None), "in.txt": ("file", 1)}


# A link walk: an intermediate component swapped for a symlink.


@pytest.mark.parametrize("target", ["absolute", "relative"])
def test_component_swapped_before_its_traversal_is_omitted(tree, monkeypatch, target):
    root, out = tree["root"], tree["out"]
    (root / "l").symlink_to("d/in.txt")
    real_readlink = os.readlink

    def readlink_then_swap(path, *args, **kwargs):
        text = real_readlink(path, *args, **kwargs)
        if (
            Path(path).name == "l"
            and (root / "d").is_dir()
            and not (root / "d").is_symlink()
        ):
            swap_for_link(root / "d", out if target == "absolute" else "../out")
        return text

    monkeypatch.setattr(os, "readlink", readlink_then_swap)
    result = run(tree["roots"], root)
    assert str(len(SECRET)) not in blob(result)
    assert "l" not in names(result)


def test_component_swapped_after_the_target_read_types_the_checked_target(
    tree, monkeypatch
):
    # R-L4b-N1: r6 re-read the target by path (os.lstat(root/d/in.txt)), which
    # follows a swapped 'd' out of the root. The fd walk reads it ONCE,
    # relative to the opened 'd', so the swap afterwards changes nothing.
    root, out = tree["root"], tree["out"]
    (root / "l").symlink_to("d/in.txt")
    real_lstat = os.lstat
    fired = []

    def lstat_then_swap(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if Path(path).name == "in.txt" and not fired:
            fired.append(os.fspath(path))
            swap_for_link(root / "d", out)
        return info

    monkeypatch.setattr(os, "lstat", lstat_then_swap)
    result = run(tree["roots"], root)
    monkeypatch.undo()
    assert fired == ["in.txt"]  # A name relative to a descriptor, not a path.
    assert str(len(SECRET)) not in blob(result)
    assert names(result)["l"] == ("file", 1)


def test_target_swapped_after_its_read_types_the_checked_target(tree, monkeypatch):
    root, out = tree["root"], tree["out"]
    (root / "t.txt").write_text("t")
    (root / "l").symlink_to("t.txt")
    real_readlink = os.readlink
    real_lstat = os.lstat
    state = {"link_read": False, "swapped": False}

    def readlink_marks(path, *args, **kwargs):
        if Path(path).name == "l":
            state["link_read"] = True
        return real_readlink(path, *args, **kwargs)

    def lstat_then_swap(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if Path(path).name == "t.txt" and state["link_read"] and not state["swapped"]:
            state["swapped"] = True
            (root / "t.txt").unlink()
            (root / "t.txt").symlink_to(out / "secret.txt")
        return info

    monkeypatch.setattr(os, "readlink", readlink_marks)
    monkeypatch.setattr(os, "lstat", lstat_then_swap)
    result = run(tree["roots"], root)
    monkeypatch.undo()
    assert state["swapped"]
    assert str(len(SECRET)) not in blob(result)
    assert names(result)["l"] == ("file", 1)


# Nested roots: the walk is confined to the root being listed (Darwin: omit).


@pytest.fixture
def nested(tmp_path: Path) -> dict:
    outer = tmp_path.resolve() / "outer"
    inner, other = outer / "inner", tmp_path.resolve() / "other"
    for d in (outer, inner, inner / "sub", other):
        d.mkdir()
    (outer / "o.txt").write_text("outer")
    (inner / "i.txt").write_text("in")
    (other / "x.txt").write_text(SECRET)
    return {
        "outer": outer,
        "inner": inner,
        "other": other,
        "roots": RootsSettings(default_root=outer, extra_roots=(inner, other)),
    }


def test_nested_inner_listing_omits_links_into_the_outer_root(nested):
    outer, inner = nested["outer"], nested["inner"]
    (inner / "rel_up").symlink_to("../o.txt")  # Listed in r6; omitted now.
    (inner / "rel_up_back").symlink_to("../inner/i.txt")
    (inner / "abs_outer").symlink_to(outer / "o.txt")
    (inner / "abs_outer_dir").symlink_to(outer, target_is_directory=True)
    (inner / "cross_rel").symlink_to("../../other/x.txt")
    (inner / "cross_abs").symlink_to(nested["other"] / "x.txt")
    (inner / "stays").symlink_to("sub/../i.txt")
    (inner / "abs_inner").symlink_to(inner / "i.txt")
    (inner / "sub" / "up").symlink_to("../i.txt")
    result = run(nested["roots"], inner)
    assert names(result) == {
        "abs_inner": ("file", 2),
        "i.txt": ("file", 2),
        "stays": ("file", 2),
        "sub": ("dir", None),
    }
    assert str(len(SECRET)) not in blob(result)
    assert names(run(nested["roots"], inner / "sub")) == {"up": ("file", 2)}
    payload = run(nested["roots"], inner, max_results=1).structured_content
    assert payload is not None
    assert payload["note"].startswith("Showing first 1 of 4 entries")


def test_nested_outer_listing_keeps_links_into_the_inner_root(nested):
    outer, inner = nested["outer"], nested["inner"]
    (outer / "rel_in").symlink_to("inner/i.txt")
    (outer / "abs_in").symlink_to(inner / "i.txt")
    (outer / "abs_in_dir").symlink_to(inner, target_is_directory=True)
    (outer / "cross").symlink_to("../other/x.txt")
    assert names(run(nested["roots"], outer)) == {
        "abs_in": ("file", 2),
        "abs_in_dir": ("dir", None),
        "inner": ("dir", None),
        "o.txt": ("file", 5),
        "rel_in": ("file", 2),
    }


# The helper itself.


def test_open_root_refuses_a_symlink_component(tmp_path):
    real = tmp_path.resolve() / "real"
    real.mkdir()
    (tmp_path.resolve() / "alias").symlink_to(real, target_is_directory=True)
    with fd_walk.open_root(real) as fd:
        assert os.path.samestat(os.fstat(fd), os.stat(real))
    with (
        pytest.raises(NotADirectoryError),
        fd_walk.open_root(tmp_path.resolve() / "alias"),
    ):
        pass


def test_link_target_info_is_lexical_above_the_root(tree):
    root = tree["root"]
    (root / "up").symlink_to("../out/secret.txt")
    (root / "d" / "back").symlink_to("../hello.txt")
    with fd_walk.open_root(root) as fd:
        assert fd_walk.link_target_info(fd, (), "up", str(root)) is None
        info = fd_walk.link_target_info(fd, ("d",), "back", str(root))
    assert info is not None and info.st_size == 6


def test_no_descriptor_leaks_on_success_and_failure(tree, monkeypatch):
    root = tree["root"]
    (root / "l").symlink_to("d/in.txt")
    (root / "dangle").symlink_to("nope/x")
    (root / "loop").symlink_to("loop")
    before = len(os.listdir(FD_DIR))
    for _ in range(20):
        run(tree["roots"], root)
        with pytest.raises(ToolError):
            run(tree["roots"], root / "hello.txt")
    real_resolve = lf.resolve_path

    def resolve_then_swap(*args, **kwargs):
        resolved = real_resolve(*args, **kwargs)
        if not (root / "d").is_symlink():
            swap_for_link(root / "d", tree["out"])
        return resolved

    monkeypatch.setattr(lf, "resolve_path", resolve_then_swap)
    with pytest.raises(ToolError, match="Directory changed"):
        run(tree["roots"], root / "d" / "e")
    assert len(os.listdir(FD_DIR)) == before
