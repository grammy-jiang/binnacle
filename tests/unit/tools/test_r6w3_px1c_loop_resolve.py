"""resolve_path answers a symlink loop the same on every Python (r6 W3 PX1c, SD-93).

Before Python 3.13, Path.resolve() raises RuntimeError("Symlink loop from ...")
for a link loop; 3.13+ is os.path.realpath(strict=False) and leaves the looping
tail in place, so the tools answer file_not_found / "Directory not found". CI
38219874921 failed on py310-py312 with path_resolve_failed "Symlink loop"
while the 3.13 hosts (Pi and Mac) passed. resolve_path now resolves with
os.path.realpath on every version.

These tests force the < 3.13 behavior on any interpreter (a Path.resolve that
raises the loop RuntimeError), so a 3.13 host catches a regression. No test is
skipped; each runs on both OSes through the Linux path (file_access=None).
The trees are non-secret fixtures under pytest's tmp_path.
"""

import errno
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.features.files import paths
from binnacle.features.files.tools import list_files as lf
from binnacle.features.files.tools import read_file as rf
from binnacle.platform.contracts.capability_contracts import (
    Capability,
    CapabilityState,
)
from binnacle.platform.darwin.file_access import DarwinFileAccess

LOOPS = ["loop", "loop/x", "ping", "ping/pong/x", "self/loop"]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = (tmp_path / "root").resolve()
    (root / "out").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (root / "loop").symlink_to("loop")
    (root / "ping").symlink_to("pong")
    (root / "pong").symlink_to("ping")
    (root / "self").symlink_to(".")
    (root / "to_outside").symlink_to(tmp_path / "outside")
    (root / "ok.txt").write_text("fine\n")
    return root


def roots_for(root: Path) -> RootsSettings:
    return RootsSettings(default_root=root, extra_roots=())


def old_resolve(self: Path, strict: bool = False) -> Path:
    """Path.resolve as 3.10-3.12 behave: a loop raises RuntimeError("Symlink
    loop from ..."), anything else resolves non-strictly. Other paths (the
    configured roots) must still resolve, so it is not an unconditional raise."""
    try:
        os.path.realpath(self, strict=True)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise RuntimeError(f"Symlink loop from {str(self)!r}") from None
    return Path(os.path.realpath(self))


def code_and_text(call: Callable[[], object]) -> tuple[str | None, str]:
    with pytest.raises(ToolError) as exc:
        call()
    return getattr(exc.value, "telemetry_code", None), str(exc.value)


@pytest.mark.parametrize("name", LOOPS)
def test_a_loop_resolves_to_the_unresolved_tail_under_the_old_resolve(
    tree, monkeypatch, name
):
    expected = Path(os.path.realpath(tree / name))
    monkeypatch.setattr(Path, "resolve", old_resolve)
    assert paths.resolve_path(str(tree / name), roots=roots_for(tree)) == expected


@pytest.mark.parametrize("name", LOOPS + ["ok.txt", "missing", "out/../ok.txt"])
def test_an_old_resolve_gives_the_same_answer_as_the_unpatched_one(
    tree, monkeypatch, name
):
    unpatched = paths.resolve_path(str(tree / name), roots=roots_for(tree))
    monkeypatch.setattr(Path, "resolve", old_resolve)
    assert paths.resolve_path(str(tree / name), roots=roots_for(tree)) == unpatched


@pytest.mark.parametrize("name", ["loop", "loop/x", "ping"])
def test_read_file_on_a_loop_is_file_not_found_under_the_old_resolve(
    tree, monkeypatch, name
):
    monkeypatch.setattr(Path, "resolve", old_resolve)
    code, text = code_and_text(
        lambda: rf.read_file_impl(
            str(tree / name), 1, None, roots=roots_for(tree), file_access=None
        )
    )
    assert code == "file_not_found"
    assert text.split(" Files in ")[0] == f"File not found: {tree / name}."


@pytest.mark.parametrize("name", ["loop", "loop/x", "ping"])
def test_list_files_on_a_loop_is_directory_not_found_under_the_old_resolve(
    tree, monkeypatch, name
):
    monkeypatch.setattr(Path, "resolve", old_resolve)
    code, text = code_and_text(
        lambda: lf.list_files_impl(
            str(tree / name),
            None,
            100,
            False,
            roots=roots_for(tree),
            file_access=None,
        )
    )
    assert code == "directory_not_found"
    assert text.split(" Files in ")[0] == f"Directory not found: {tree / name}."


# The existing failures keep their code and text.


@pytest.mark.parametrize("patch", [None, old_resolve])
def test_an_unknown_user_is_still_path_resolve_failed(tree, monkeypatch, patch):
    if patch is not None:
        monkeypatch.setattr(Path, "resolve", patch)
    code, text = code_and_text(
        lambda: paths.resolve_path("~nosuchuser_px1c/x", roots=roots_for(tree))
    )
    assert code == "path_resolve_failed"
    assert text.startswith("Cannot resolve path '~nosuchuser_px1c/x': ")


def test_an_oserror_from_the_resolve_is_still_path_resolve_failed(tree, monkeypatch):
    def boom(path: object, **kwargs: object) -> str:
        raise OSError(errno.ENAMETOOLONG, "File name too long")

    monkeypatch.setattr(os.path, "realpath", boom)
    code, text = code_and_text(
        lambda: paths.resolve_path(str(tree / "ok.txt"), roots=roots_for(tree))
    )
    assert code == "path_resolve_failed"
    assert text.startswith(f"Cannot resolve path {str(tree / 'ok.txt')!r}: ")


@pytest.mark.parametrize("patch", [None, old_resolve])
def test_a_link_to_outside_is_still_path_outside_root(tree, monkeypatch, patch):
    if patch is not None:
        monkeypatch.setattr(Path, "resolve", patch)
    code, text = code_and_text(
        lambda: paths.resolve_path(str(tree / "to_outside"), roots=roots_for(tree))
    )
    assert code == "path_outside_root"
    assert text.endswith(str(tree.parent / "outside"))


# The Darwin path (FileToolAccess over DarwinFileAccess, built directly so it runs
# on both OSes) words its refusals through features/files/error_text.py, which also
# resolved with Path.resolve(): the second half of the SD-93 red (TM, e6b4279).


def darwin_read_outcome(root: Path, name: str) -> tuple[str | None, str]:
    access = paths.FileToolAccess(
        roots=roots_for(root),
        files=DarwinFileAccess(),
        search=None,
        generation="r6w3-px1c",
        capability=Capability(CapabilityState.LIMITED, "test_only", "px1c"),
    )
    try:
        return code_and_text(
            lambda: rf.read_file_impl(
                str(root / name), 1, None, roots=roots_for(root), file_access=access
            )
        )
    finally:
        access.close()


@pytest.mark.parametrize("name", LOOPS)
def test_the_darwin_path_answers_a_loop_the_same_under_the_old_resolve(
    tree, monkeypatch, name
):
    expected = darwin_read_outcome(tree, name)
    monkeypatch.setattr(Path, "resolve", old_resolve)
    assert darwin_read_outcome(tree, name) == expected
