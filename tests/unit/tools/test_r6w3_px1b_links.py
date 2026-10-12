"""list_files and search_text through in-root symlinks, as on Linux (r6 W3 PX1b, PF-PX1-1).

Linux resolves the request (resolve_path) and lists or searches what it
names. Darwin's no-follow walk refused every link with the bare adapter text
"symlink_or_wrong_path_type."; now both tools resolve the request once, as
read_file does (R-OS1-F3), and open the in-root target with the same no-follow
descriptor walk from the grant. Each case runs the Linux path
(file_access=None) and the Darwin path (FileToolAccess over DarwinFileAccess
and DarwinSearchAccess, built directly) on the same tree and requires the same
code, text, structured path and entries. Every case runs on both OSes; none
is skipped.
"""

import errno
import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.features.files import error_text, fd_walk, paths
from binnacle.features.files.tools import list_files as lf
from binnacle.features.search.tools import search_text as st
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.darwin import file_traversal
from binnacle.platform.darwin.file_access import DarwinFileAccess
from binnacle.platform.darwin.search_access import DarwinSearchAccess

RG = shutil.which("rg") or "rg"
PATHS = pytest.mark.parametrize(
    "darwin", [False, True], ids=["linux_path", "darwin_path"]
)
TOOLS: dict[str, Callable] = {
    "list": lambda p, r, a: lf.list_files_impl(
        p, None, 100, False, roots=r, file_access=a, rg_bin=RG
    ),
    "glob": lambda p, r, a: lf.list_files_impl(
        p, "**/*.txt", 100, False, roots=r, file_access=a, rg_bin=RG
    ),
    "search": lambda p, r, a: st.search_text_impl(
        "needle", p, None, True, 0, False, 100, True, roots=r, file_access=a, rg_bin=RG
    ),
}
EACH_TOOL = pytest.mark.parametrize("tool", sorted(TOOLS))
# The tool name each mode words its refusals with.
TOOL_NAME = {"list": "list_files", "glob": "list_files", "search": "search_text"}
NOT_FOUND = {
    "list": "directory_not_found",
    "glob": "directory_not_found",
    "search": "path_not_found",
}


@pytest.fixture
def tree() -> Iterator[Path]:
    """A non-secret fixture tree under /tmp; links point inside, outside, nowhere."""
    base = Path(tempfile.mkdtemp(prefix="r6w3-px1b-links-", dir="/tmp")).resolve()
    root, out = base / "root", base / "out"
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "sub" / "deep" / "n.txt").write_text("needle deep\n")
    (root / "sub" / "top.txt").write_text("needle top\n")
    out.mkdir()
    (out / "s.txt").write_text("needle outside\n")
    links = {
        "dir_link": "sub",
        "abs_link": str(root / "sub"),
        "chain": "dir_link",
        "chain_abs": str(root / "abs_link"),
        "deep_link": "sub/deep",
        "via_link": "dir_link/deep",
        "file_link": "sub/deep/n.txt",
        "out_link": str(out),
        "dangling_dir": "nope",
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
    files = DarwinFileAccess()
    return paths.FileToolAccess(
        roots=roots_for(root),
        files=files,
        search=DarwinSearchAccess(files, rg_bin=RG),
        generation="r6w3-px1b",
        capability=Capability(CapabilityState.LIMITED, "test_only", "px1b"),
    )


def outcome(root: Path, darwin: bool, tool: str, request: str) -> dict:
    """Code, text, structured path and sorted entries, with the base as <BASE>."""
    access = access_for(root) if darwin else None
    try:
        result = TOOLS[tool](request, roots_for(root), access)
        payload = result.structured_content
        found = {
            "code": "ok",
            "text": result.content[0].text,
            "path": payload["path"],
            "entries": sorted(
                e.get("path") or e.get("file") for e in payload["entries"]
            ),
        }
    except ToolError as exc:
        found = {"code": getattr(exc, "telemetry_code", None), "text": str(exc)}
    finally:
        if access is not None:
            access.close()
    base = str(root.parent)
    return {
        k: [e.replace(base, "<BASE>") for e in v]
        if isinstance(v, list)
        else v.replace(base, "<BASE>")
        for k, v in found.items()
    }


def request_for(root: Path, form: str, name: str) -> str:
    return name if form == "rel" else str(root / name)


FORMS = pytest.mark.parametrize("form", ["rel", "abs"])


@PATHS
@EACH_TOOL
@FORMS
@pytest.mark.parametrize(
    "name,target",
    [
        ("dir_link", "sub"),
        ("abs_link", "sub"),
        ("chain", "sub"),
        ("chain_abs", "sub"),
        ("deep_link", "sub/deep"),
        ("via_link", "sub/deep"),
        ("dir_link/deep", "sub/deep"),
        ("chain/deep", "sub/deep"),
    ],
)
def test_an_in_root_link_is_listed_and_searched_as_its_target(
    tree, darwin, tool, form, name, target
):
    got = outcome(tree, darwin, tool, request_for(tree, form, name))
    assert got == outcome(tree, False, tool, str(tree / target))
    assert got["code"] == "ok"
    assert got["path"] == f"<BASE>/root/{target}"
    assert got["entries"]


@PATHS
@EACH_TOOL
@FORMS
@pytest.mark.parametrize("name", ["out_link", "out_link/s.txt"])
def test_an_outside_target_is_path_outside_root(tree, darwin, tool, form, name):
    shown = "<BASE>/out" + ("/s.txt" if name.endswith("s.txt") else "")
    assert outcome(tree, darwin, tool, request_for(tree, form, name)) == {
        "code": "path_outside_root",
        "text": f"Path outside allowed roots (<BASE>/root): {shown}",
    }


@PATHS
@EACH_TOOL
@FORMS
def test_a_dangling_link_names_its_missing_target(tree, darwin, tool, form):
    got = outcome(tree, darwin, tool, request_for(tree, form, "dangling_dir"))
    assert got == outcome(tree, False, tool, str(tree / "dangling_dir"))
    word = "Path" if tool == "search" else "Directory"
    assert got["code"] == NOT_FOUND[tool]
    assert got["text"].startswith(
        f"{word} not found: <BASE>/root/nope. Files in <BASE>/root: abs_link/, "
    )


@PATHS
@EACH_TOOL
@FORMS
@pytest.mark.parametrize(
    "name,shown",
    [
        ("loop", "<BASE>/root/loop"),
        ("loop/x", "<BASE>/root/loop/x"),
        ("dangling_dir/x", "<BASE>/root/nope/x"),
        ("sub/top.txt/x", "<BASE>/root/sub/top.txt/x"),
    ],
)
def test_a_loop_or_a_non_directory_component_is_not_found(
    tree, darwin, tool, form, name, shown
):
    got = outcome(tree, darwin, tool, request_for(tree, form, name))
    assert got == outcome(tree, False, tool, str(tree / name))
    word = "Path" if tool == "search" else "Directory"
    assert got["code"] == NOT_FOUND[tool]
    assert got["text"].split(" Files in ")[0] == f"{word} not found: {shown}."


@PATHS
@pytest.mark.parametrize("tool", ["list", "glob"])
def test_a_link_to_a_file_is_path_is_file_naming_the_target(tree, darwin, tool):
    assert outcome(tree, darwin, tool, str(tree / "file_link")) == {
        "code": "path_is_file",
        "text": (
            "Path is a file, not a directory: <BASE>/root/sub/deep/n.txt. "
            "Use read_file to read it."
        ),
    }


@PATHS
def test_search_through_a_link_to_a_file_searches_the_target(tree, darwin):
    got = outcome(tree, darwin, "search", "file_link")
    assert got == {
        "code": "ok",
        "text": "Found 1 matches for 'needle' under <BASE>/root/sub/deep/n.txt.",
        "path": "<BASE>/root/sub/deep/n.txt",
        "entries": ["<BASE>/root/sub/deep/n.txt"],
    }


@PATHS
@EACH_TOOL
def test_no_model_visible_bare_link_code(tree, darwin, tool):
    for name in ("dir_link", "via_link", "dangling_dir", "loop/x", "file_link"):
        got = outcome(tree, darwin, tool, name)
        assert "symlink_or_wrong_path_type" not in got["text"], (name, got)


# A link swapped after the resolve: the second, no-follow walk refuses it.


def swapping(tree: Path, monkeypatch, replacement: Path) -> None:
    """After the resolve picks sub, sub becomes a link to replacement (a race)."""
    real = error_text.link_target

    def raced(*args):
        target = real(*args)
        if target is not None and target.is_relative_to(tree / "sub"):
            (tree / "sub").rename(tree / "sub_moved")
            (tree / "sub").symlink_to(replacement)
        return target

    monkeypatch.setattr(error_text, "link_target", raced)


@EACH_TOOL
def test_a_link_swapped_to_outside_after_the_resolve_is_refused(
    tree, monkeypatch, tool
):
    swapping(tree, monkeypatch, tree.parent / "out")
    got = outcome(tree, True, tool, "dir_link")
    assert got == {
        "code": "path_outside_root",
        "text": "Path outside allowed roots (<BASE>/root): <BASE>/out",
    }


@EACH_TOOL
def test_a_link_swapped_inside_after_the_resolve_is_path_changed(
    tree, monkeypatch, tool
):
    (tree / "other").mkdir()
    (tree / "other" / "o.txt").write_text("needle other\n")
    swapping(tree, monkeypatch, tree / "other")
    got = outcome(tree, True, tool, "dir_link")
    # Nothing is followed a second time, even inside the root.
    assert got == {
        "code": "path_changed",
        "text": str(fd_walk.path_changed("<BASE>/root/sub", TOOL_NAME[tool])),
    }


# One path_changed text per tool, shared by Linux and Darwin.


def test_the_linux_and_darwin_listing_race_say_the_same(tree):
    refused = lf._refusal(OSError(errno.ELOOP, "loop"), tree / "sub")
    assert (refused.telemetry_code, str(refused)) == (
        "path_changed",
        str(fd_walk.path_changed(tree / "sub", "list_files")),
    )
    assert str(refused) == (
        f"Directory changed during the listing: {tree / 'sub'}. "
        "A path component is no longer a directory; list it again."
    )


def test_the_linux_read_race_uses_the_shared_template():
    assert str(fd_walk._changed("/r/a.txt")) == (
        "File changed while it was opened: /r/a.txt. Read it again."
    )
    assert str(fd_walk.path_changed("/r/a.txt")) == (
        fd_walk.PATH_CHANGED_DEFAULT.format(shown="/r/a.txt")
    )
    for tool, text in fd_walk.PATH_CHANGED_TEXTS.items():
        refused = fd_walk.path_changed("/r/x", tool)
        assert refused.telemetry_code == fd_walk.PATH_CHANGED_CODE == "path_changed"
        assert str(refused) == text.format(shown="/r/x")
        assert "symlink_or_wrong_path_type" not in str(refused)


@pytest.mark.parametrize(
    "tool", ["read_file", "edit_file", "write_file", "list_files", "search_text"]
)
def test_an_unworded_link_refusal_is_path_changed_for_every_tool(tree, tool):
    # linux_error has no sentence for it (an existing in-root directory):
    # the operation words it as path_changed, never the bare code.
    access = access_for(tree)
    try:
        with (
            pytest.raises(ToolError) as exc,
            access.operation(str(tree / "sub"), tool) as (_g, _r, display),
        ):
            raise file_traversal.unsafe("symlink_or_wrong_path_type")
    finally:
        access.close()
    assert (exc.value.telemetry_code, str(exc.value)) == (
        "path_changed",
        str(fd_walk.path_changed(display, tool)),
    )


def test_the_target_is_resolved_only_after_a_link_refusal(tree):
    calls = []

    def roots():
        calls.append(1)
        return [tree]

    def step(grant, relative, display):
        return display

    access = access_for(tree)
    try:
        assert error_text.followed(
            access.operation, "sub", "list_files", roots, step
        ) == (tree / "sub")
        assert calls == []
        assert os.path.islink(tree / "dir_link")
    finally:
        access.close()
