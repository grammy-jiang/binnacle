"""In-root symlinks read as on Linux on both paths (r6 W3 PX1 commit 1, R-OS1-F3).

Linux resolves the request and opens what it names. Darwin's no-follow walk
refused every link (as special_file_unsupported for a final link); now
FileToolAccess resolves the request once, as Linux does, and opens the
in-root target with the same no-follow descriptor walk. Each case runs the
Linux path (file_access=None) and the Darwin path (FileToolAccess over
DarwinFileAccess) on the same tree and requires the same code and text.
Every case runs on both OSes; none is skipped.
"""

import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.features.files import error_text, paths
from binnacle.features.files.tools import edit_file as ef
from binnacle.features.files.tools import read_file as rf
from binnacle.features.files.tools import write_file as wf
from binnacle.platform.contracts.capability_contracts import (
    Capability,
    CapabilityState,
    NativeCapabilityError,
)
from binnacle.platform.contracts.special_file_contracts import (
    SPECIAL_FILE_CODE,
    SPECIAL_FILE_TEXT,
)
from binnacle.platform.darwin import file_traversal
from binnacle.platform.darwin.file_access import DarwinFileAccess

PATHS = pytest.mark.parametrize(
    "darwin", [False, True], ids=["linux_path", "darwin_path"]
)


@pytest.fixture
def tree() -> Iterator[Path]:
    base = Path(tempfile.mkdtemp(prefix="r6w3-px1-links-", dir="/tmp")).resolve()
    root, out = base / "root", base / "out"
    (root / "sub").mkdir(parents=True)
    out.mkdir()
    (root / "sub" / "b.txt").write_text("beta needle\n")
    (out / "secret.txt").write_text("outside\n")
    os.mkfifo(root / "fifo")
    links = {
        "rel": "sub/b.txt",
        "abs": str(root / "sub" / "b.txt"),
        "chain": "rel",
        "chain_abs": str(root / "abs"),
        "dir_link": "sub",
        "outside": str(out / "secret.txt"),
        "to_fifo": "fifo",
        "dangling": "sub/missing.txt",
        "loop": "loop",
    }
    for name, target in links.items():
        (root / name).symlink_to(target)
    try:
        yield root
    finally:
        shutil.rmtree(base)


def roots_for(root: Path) -> RootsSettings:
    return RootsSettings(default_root=root, extra_roots=())


def access_for(root: Path) -> paths.FileToolAccess:
    return paths.FileToolAccess(
        roots=roots_for(root),
        files=DarwinFileAccess(),
        search=None,
        generation="r6w3-px1",
        capability=Capability(CapabilityState.LIMITED, "test_only", "px1"),
    )


def outcome(root: Path, darwin: bool, call: Callable) -> tuple:
    """(code or "ok", text) of one tool call, with the tree's base as <BASE>."""
    access = access_for(root) if darwin else None
    try:
        result = call(roots_for(root), access)
        text = result.content[0].text
        code: str | None = "ok"
    except ToolError as exc:
        text, code = str(exc), getattr(exc, "telemetry_code", None)
    finally:
        if access is not None:
            access.close()
    return code, text.replace(str(root.parent), "<BASE>")


def read(path: Path) -> Callable:
    return lambda roots, access: rf.read_file_impl(
        str(path), 1, None, roots=roots, file_access=access
    )


@PATHS
@pytest.mark.parametrize("name", ["rel", "abs", "chain", "chain_abs", "dir_link/b.txt"])
def test_an_in_root_link_reads_its_target(tree, darwin, name):
    assert outcome(tree, darwin, read(tree / name)) == (
        "ok",
        "Read all 1 lines from <BASE>/root/sub/b.txt.",
    )


@PATHS
def test_the_structured_path_is_the_target(tree, darwin):
    access = access_for(tree) if darwin else None
    try:
        result = rf.read_file_impl(
            str(tree / "chain"), 1, None, roots=roots_for(tree), file_access=access
        )
    finally:
        if access is not None:
            access.close()
    assert result.structured_content["path"] == str(tree / "sub" / "b.txt")
    assert result.structured_content["content"] == "beta needle\n"


@PATHS
def test_an_outside_target_is_path_outside_root(tree, darwin):
    assert outcome(tree, darwin, read(tree / "outside")) == (
        "path_outside_root",
        f"Path outside allowed roots ({tree}): <BASE>/out/secret.txt".replace(
            str(tree.parent), "<BASE>"
        ),
    )


@PATHS
@pytest.mark.timeout(10)
def test_a_fifo_target_is_special_file_unsupported(tree, darwin):
    assert outcome(tree, darwin, read(tree / "to_fifo")) == (
        SPECIAL_FILE_CODE,
        SPECIAL_FILE_TEXT,
    )


@PATHS
def test_a_dangling_in_root_link_names_its_missing_target(tree, darwin):
    assert outcome(tree, darwin, read(tree / "dangling")) == (
        "file_not_found",
        (
            "File not found: <BASE>/root/sub/missing.txt. Files in <BASE>/root/sub: "
            "b.txt. Use list_files for more."
        ),
    )


@PATHS
def test_a_link_loop_is_file_not_found(tree, darwin):
    code, text = outcome(tree, darwin, read(tree / "loop"))
    assert (code, text.split(" Files in ")[0]) == (
        "file_not_found",
        "File not found: <BASE>/root/loop.",
    )


@PATHS
def test_edit_through_a_link_edits_the_target_and_keeps_the_link(tree, darwin):
    def edit(roots, access):
        return ef.edit_file_impl(
            str(tree / "rel"), "beta", "BETA", False, roots=roots, file_access=access
        )

    assert outcome(tree, darwin, edit) == (
        "ok",
        "Replaced 1 occurrence in <BASE>/root/sub/b.txt (first change at line 1).",
    )
    assert (tree / "sub" / "b.txt").read_text() == "BETA needle\n"
    assert os.readlink(tree / "rel") == "sub/b.txt"


@PATHS
def test_write_through_a_link_writes_the_target_and_keeps_the_link(tree, darwin):
    def write(roots, access):
        return wf.write_file_impl(
            str(tree / "abs"), "new\n", roots=roots, file_access=access
        )

    assert outcome(tree, darwin, write) == (
        "ok",
        "Overwrote <BASE>/root/sub/b.txt (4 bytes, was 12).",
    )
    assert (tree / "sub" / "b.txt").read_text() == "new\n"
    assert (tree / "abs").is_symlink()


@PATHS
def test_write_through_an_outside_link_is_refused(tree, darwin):
    def write(roots, access):
        return wf.write_file_impl(
            str(tree / "outside"), "x\n", roots=roots, file_access=access
        )

    code, _text = outcome(tree, darwin, write)
    assert code == "path_outside_root"
    assert (tree.parent / "out" / "secret.txt").read_text() == "outside\n"


def test_the_darwin_walk_names_a_final_link_apart_from_a_special_file(tree):
    parent = os.open(tree, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name, code in (
            ("rel", "symlink_or_wrong_path_type"),
            ("fifo", SPECIAL_FILE_CODE),
        ):
            with pytest.raises(NativeCapabilityError) as exc:
                file_traversal.regular_fd(parent, name)
            assert exc.value.code == code
    finally:
        os.close(parent)


def test_only_one_hop_is_followed(tree, monkeypatch):
    # The target chosen by the resolve is a link again (a race): the second
    # no-follow walk refuses it; nothing is followed a second time.
    monkeypatch.setattr(error_text, "link_target", lambda *_args: tree / "rel")
    code, text = outcome(tree, True, read(tree / "chain"))
    # The coded path_changed text, never the bare adapter code (r6 W3 PX1b).
    assert (code, text) == (
        "path_changed",
        "File changed while it was opened: <BASE>/root/rel. Read it again.",
    )


def test_only_a_link_refusal_is_followed(tree):
    exc = file_traversal.unsafe("path_not_found")
    assert error_text.link_target(exc, tree / "rel", [tree]) is None
    link = file_traversal.unsafe("symlink_or_wrong_path_type")
    assert error_text.link_target(link, tree / "rel", [tree]) == tree / "sub" / "b.txt"
    assert error_text.link_target(link, tree / "outside", [tree]) is None
    assert error_text.link_target(link, tree / "sub" / "b.txt", [tree]) is None
