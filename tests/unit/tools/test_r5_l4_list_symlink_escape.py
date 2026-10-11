"""Linux list_files LIST mode omits links that escape the roots (SD-60 item 1).

Reference semantics: Darwin's descriptor listing (platform/darwin/file_access.py
``link_target_info``) types an in-root link by its target and omits outside,
dangling and looping links. These tests pin the same result on the Linux legacy
path; glob mode is pinned unchanged (``rg --files`` never reports a symlink).
"""

import json
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.features.files.tools import list_files as lf

SECRET = "s" * 4321  # A size that appears nowhere else in the fixture.


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    base = tmp_path.resolve()
    root, other, out = base / "root", base / "other", base / "out"
    for d in (root, other, out):
        d.mkdir()
    (root / "hello.txt").write_text("hello\n")
    (root / "d").mkdir()
    (root / "d" / "in.txt").write_text("x")
    (other / "o.txt").write_text("other!!")
    (out / "secret.txt").write_text(SECRET)
    (out / "sub").mkdir()
    (out / "sub" / "deep.txt").write_text(SECRET)
    return {
        "root": root,
        "other": other,
        "out": out,
        "roots": RootsSettings(default_root=root, extra_roots=(other,)),
    }


def run(tree: dict, glob: str | None = None, max_results: int = 200):
    return lf.list_files_impl(
        str(tree["root"]), glob, max_results, False, roots=tree["roots"]
    )


def typed(tree: dict, glob: str | None = None) -> dict:
    payload = run(tree, glob).structured_content
    assert payload is not None
    return {
        Path(e["path"]).relative_to(tree["root"]).as_posix(): (
            e["type"],
            e.get("bytes"),
        )
        for e in payload["entries"]
    }


def test_link_to_outside_file_is_omitted(tree):
    root, out = tree["root"], tree["out"]
    (root / "abs_out").symlink_to(out / "secret.txt")
    (root / "rel_out").symlink_to("../out/secret.txt")
    assert typed(tree) == {"d": ("dir", None), "hello.txt": ("file", 6)}


def test_link_to_outside_dir_is_omitted(tree):
    root, out = tree["root"], tree["out"]
    (root / "out_dir").symlink_to(out / "sub", target_is_directory=True)
    (root / "slash").symlink_to("/", target_is_directory=True)
    assert typed(tree) == {"d": ("dir", None), "hello.txt": ("file", 6)}


def test_dangling_and_looping_links_are_omitted_as_on_darwin(tree):
    # Darwin omits a dangling or looping link and does not count it; Linux
    # already omitted the entry and now no longer counts it in the total.
    root = tree["root"]
    (root / "dangle").symlink_to("nope")
    (root / "loop").symlink_to("loop")
    assert typed(tree) == {"d": ("dir", None), "hello.txt": ("file", 6)}
    payload = run(tree, max_results=1).structured_content
    assert payload is not None
    assert payload["note"].startswith("Showing first 1 of 2 entries")


def test_in_root_links_are_listed_unchanged(tree):
    root, other = tree["root"], tree["other"]
    (root / "flink").symlink_to("hello.txt")
    (root / "dlink").symlink_to("d", target_is_directory=True)
    (root / "abs_flink").symlink_to(root / "hello.txt")
    (root / "cross_root").symlink_to(other / "o.txt")
    # r6 X2 (SD-67): absolute link text under the link's own root is listed
    # as on Darwin (file_access.py link_target_info); another root's is not.
    assert typed(tree) == {
        "abs_flink": ("file", 6),
        "d": ("dir", None),
        "dlink": ("dir", None),
        "flink": ("file", 6),
        "hello.txt": ("file", 6),
    }
    names = list(typed(tree))
    assert names[:2] == ["d", "dlink"]  # Dirs first, as before.


def test_no_outside_metadata_anywhere_in_the_result(tree):
    root, out = tree["root"], tree["out"]
    (root / "abs_out").symlink_to(out / "secret.txt")
    (root / "out_dir").symlink_to(out / "sub", target_is_directory=True)
    (root / "dangle").symlink_to("nope")
    for max_results in (200, 1):
        result = run(tree, max_results=max_results)
        structured = json.dumps(result.structured_content)
        text = " ".join(getattr(c, "text", "") for c in result.content)
        for blob in (structured, text):
            for leaked in ("abs_out", "out_dir", "dangle", str(len(SECRET)), str(out)):
                assert leaked not in blob
    payload = run(tree, max_results=1).structured_content
    assert payload is not None
    assert payload["note"].startswith("Showing first 1 of 2 entries")


@pytest.mark.parametrize("glob", ["*", "**/*"])
def test_glob_mode_reports_no_symlink_unchanged(tree, glob):
    # Before and after SD-60: rg --files does not follow or report symlinks,
    # in-root or not, so glob mode never carried outside metadata.
    root, out = tree["root"], tree["out"]
    (root / "abs_out").symlink_to(out / "secret.txt")
    (root / "out_dir").symlink_to(out / "sub", target_is_directory=True)
    (root / "flink").symlink_to("hello.txt")
    (root / "dangle").symlink_to("nope")
    assert typed(tree, glob) == {"d/in.txt": ("file", 1), "hello.txt": ("file", 6)}


def test_default_roots_also_omit_an_escaping_link(tmp_path):
    (tmp_path / "keep.txt").write_text("k")
    (tmp_path / "slash").symlink_to("/", target_is_directory=True)
    payload = lf.list_files_impl(str(tmp_path), None, 200, False).structured_content
    assert payload is not None
    assert [Path(e["path"]).name for e in payload["entries"]] == ["keep.txt"]


def test_unknown_entry_state_is_omitted_as_on_darwin(monkeypatch, tmp_path):
    # SD-60 (R-L4-F4, L4b): an entry whose lstat fails is omitted, as the
    # Darwin walk omits EACCES/EPERM/ENOENT entries (file_traversal.py walk).
    real_lstat = lf.os.lstat

    def unreadable(path, *args, **kwargs):
        if Path(path).name == "denied":
            raise PermissionError("lstat denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(lf.os, "lstat", unreadable)
    assert lf._list_entry(tmp_path / "denied", (tmp_path,)) is None
