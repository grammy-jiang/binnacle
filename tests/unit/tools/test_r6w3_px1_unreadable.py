"""Unreadable paths below a glob or search: partial result plus one note (r6 W3 PX1 3/5).

R-OS1-F1: Linux rg exited 2 and the tool failed (rg_failed for glob,
rg_rejected for search) where Darwin silently returned the readable part.
Both OSes now return the readable part plus a note naming the skipped paths
(count, then the first five, sorted). R-OS1-F4: an unreadable base is
permission_denied with one sentence on both OSes; Darwin keeps its code
permission_denied_tcc_possible (SD-77). Each case runs the Linux path
(file_access=None) and the Darwin path (FileToolAccess over DarwinFileAccess
and DarwinSearchAccess) on the same tree. Every case runs on both OSes;
none is skipped.
"""

import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.features.files import paths
from binnacle.features.files.tools import list_files as lf
from binnacle.features.search import rg_env
from binnacle.features.search.tools import search_text as st
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.darwin.file_access import DarwinFileAccess
from binnacle.platform.darwin.search_access import DarwinSearchAccess

RG = shutil.which("rg") or "rg"
PATHS = pytest.mark.parametrize(
    "darwin", [False, True], ids=["linux_path", "darwin_path"]
)
DENIED = (
    "The server cannot open this path; check its permissions or choose another path."
)


@pytest.fixture
def tree() -> Iterator[Path]:
    base = Path(tempfile.mkdtemp(prefix="r6w3-px1-unread-", dir="/tmp")).resolve()
    root = base / "root"
    for rel in ("mix/m.txt", "mix/x2/y2/k.txt", "mix/z0/s.txt", "many/ok.txt"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("needle\n")
    for n in range(7):
        (root / "many" / f"d{n}").mkdir()
        (root / "many" / f"d{n}" / "f.txt").write_text("needle\n")
    (root / "mix" / "secret.txt").write_text("needle\n")
    locked = [root / "mix" / "x2", root / "mix" / "z0"]
    locked += [root / "many" / f"d{n}" for n in range(7)]
    for path in locked:
        path.chmod(0o100)  # Execute-only: traversable, not listable.
    try:
        yield root
    finally:
        for path in locked:
            path.chmod(0o700)
        shutil.rmtree(base)


def outcome(root: Path, darwin: bool, call: Callable) -> tuple:
    roots = RootsSettings(default_root=root, extra_roots=())
    access = None
    if darwin:
        files = DarwinFileAccess()
        access = paths.FileToolAccess(
            roots=roots,
            files=files,
            search=DarwinSearchAccess(files, rg_bin=RG),
            generation="r6w3-px1",
            capability=Capability(CapabilityState.LIMITED, "test_only", "px1"),
        )
    try:
        result = call(roots, access)
        payload = dict(result.structured_content)
        return "ok", result.content[0].text, payload
    except ToolError as exc:
        return getattr(exc, "telemetry_code", None), str(exc), None
    finally:
        if access is not None:
            access.close()


def glob(path: Path, pattern: str = "**/*.txt") -> Callable:
    return lambda roots, access: lf.list_files_impl(
        str(path), pattern, 100, False, roots=roots, file_access=access, rg_bin=RG
    )


def search(path: Path, names_only: bool = False) -> Callable:
    return lambda roots, access: st.search_text_impl(
        "needle",
        str(path),
        None,
        True,
        0,
        names_only,
        100,
        True,
        roots=roots,
        file_access=access,
        rg_bin=RG,
    )


def note(*paths: Path) -> str:
    return rg_env.unreadable_note(str(p) for p in paths)


@PATHS
def test_a_glob_over_an_unlistable_child_is_partial_with_a_note(tree, darwin):
    code, text, payload = outcome(tree, darwin, glob(tree / "mix"))
    expected = note(tree / "mix" / "x2", tree / "mix" / "z0")
    assert code == "ok"
    assert sorted(e["path"] for e in payload["entries"]) == [
        str(tree / "mix" / "m.txt"),
        str(tree / "mix" / "secret.txt"),
    ]
    assert payload["note"] == expected
    assert text.endswith(" " + expected)


@PATHS
@pytest.mark.parametrize("names_only", [False, True], ids=["lines", "names_only"])
def test_a_search_over_an_unlistable_child_is_partial_with_a_note(
    tree, darwin, names_only
):
    code, text, payload = outcome(tree, darwin, search(tree / "mix", names_only))
    expected = note(tree / "mix" / "x2", tree / "mix" / "z0")
    assert code == "ok"
    files = sorted(e["file"] for e in payload["entries"])
    assert files == [str(tree / "mix" / "m.txt"), str(tree / "mix" / "secret.txt")]
    assert payload["note"].endswith(expected)
    assert text.endswith(" " + expected)


@PATHS
def test_the_note_counts_all_and_names_the_first_five(tree, darwin):
    code, _text, payload = outcome(tree, darwin, glob(tree / "many"))
    assert code == "ok"
    first = ", ".join(str(tree / "many" / f"d{n}") for n in range(5))
    assert payload["note"] == (
        f"Skipped 7 unreadable paths (permission denied): {first} and 2 more. "
        "Results exclude their contents."
    )


@PATHS
@pytest.mark.parametrize("tool", ["list", "glob", "search"])
def test_an_unreadable_base_is_permission_denied_with_one_text(tree, darwin, tool):
    base = tree / "mix" / "x2"
    call = {
        "list": lambda roots, access: lf.list_files_impl(
            str(base), None, 100, False, roots=roots, file_access=access, rg_bin=RG
        ),
        "glob": glob(base),
        "search": search(base),
    }[tool]
    code, text, _payload = outcome(tree, darwin, call)
    # Darwin keeps its TCC code (SD-77); the sentence is the same.
    assert code == ("permission_denied_tcc_possible" if darwin else "permission_denied")
    assert text == f"Permission denied: {base}. {DENIED}"


@PATHS
def test_a_readable_tree_has_no_note(tree, darwin):
    code, _text, payload = outcome(tree, darwin, search(tree / "many" / "ok.txt"))
    assert code == "ok" and "note" not in payload


def test_only_permission_only_stderr_is_partial(tmp_path):
    denied = (
        "rg: ./x2: IO error for operation on ./x2: Permission denied (os error 13)\n"
        f"rg: {tmp_path}/z: Permission denied (os error 13)\n"
    )
    assert rg_env.permission_paths(denied, tmp_path) == [
        str(tmp_path / "x2"),
        str(tmp_path / "z"),
    ]
    mixed = denied + "rg: regex parse error: unclosed group\n"
    assert rg_env.permission_paths(mixed, tmp_path) is None
    assert rg_env.permission_paths("", tmp_path) is None
    assert rg_env.accept_denied(mixed, tmp_path) is False


def test_an_unreadable_base_in_stderr_is_permission_denied(tmp_path):
    stderr = "rg: ./: IO error for operation on ./: Permission denied (os error 13)"
    token = rg_env.UNREADABLE.set([])
    try:
        with pytest.raises(ToolError) as exc:
            rg_env.accept_denied(stderr, tmp_path)
    finally:
        rg_env.UNREADABLE.reset(token)
    assert exc.value.telemetry_code == "permission_denied"


def test_outside_a_tool_call_rg_keeps_its_failure(tmp_path):
    # No note collector: a partial result would drop paths silently.
    stderr = f"rg: {tmp_path}/x: Permission denied (os error 13)"
    assert rg_env.accept_denied(stderr, tmp_path) is False


def test_paths_outside_a_call_are_dropped(tmp_path):
    rg_env.record_unreadable(["/nowhere"])
    assert rg_env.UNREADABLE.get() is None
