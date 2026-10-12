"""The R-X3a PROBE-perm cases P1, P2a, P2b and P3 as unit tests (X3a-a2).

RX3a-F1: r6 lists P1/P2a/P2b; the X3a head raised a raw PermissionError
(P1, P2a) or omitted the link (P2b). X3a-a2 traverses with O_PATH and lists
them as r6 does. RX3a-F2: P3, an unreadable listed directory, was a raw
PermissionError on r6 and X3a; it is now the coded refusal
permission_denied. This file imports only the tool, so it runs unchanged
against the r6 base, the X3a head and X3a-a2.
"""

import os
import stat
import sys
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files.tools import list_files as lf

not_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores modes")
# Parity finding PF-T3-01 (R6W2-T3): Darwin keeps TRAVERSE_FLAGS = O_RDONLY
# (fd_walk.py, DARWIN-FOLLOWUP-exec-only-dirs), so an execute-only directory
# differs from Linux; reported to the Supervisor, never loosened.
PF_T3_01 = pytest.mark.xfail(
    sys.platform == "darwin",
    strict=True,
    reason="PF-T3-01: execute-only directory parity (DARWIN-FOLLOWUP-exec-only-dirs)",
)


def run(roots: RootsSettings, path: Path):
    return lf.list_files_impl(str(path), None, 200, False, roots=roots)


def types(result) -> dict:
    payload = result.structured_content
    assert payload is not None
    return {Path(e["path"]).name: e["type"] for e in payload["entries"]}


@pytest.fixture
def chmod_back():
    """Restore every mode a test lowered, so tmp_path cleans up."""
    changed: list[tuple[Path, int]] = []

    def lower(path: Path, mode: int) -> None:
        changed.append((path, stat.S_IMODE(path.stat().st_mode)))
        path.chmod(mode)

    yield lower
    for path, mode in reversed(changed):
        path.chmod(mode)


@PF_T3_01
@not_root
@pytest.mark.parametrize("mode", [0o100, 0o300])
def test_p1_execute_only_ancestor_above_the_root_lists_as_r6(
    tmp_path, chmod_back, mode
):
    gate = tmp_path.resolve() / "gate"
    root = gate / "root"
    (root / "d").mkdir(parents=True)
    (root / "f.txt").write_text("x")
    (root / "lnk").symlink_to("d")
    roots = RootsSettings(default_root=root, extra_roots=())
    assert roots.canonical_allowed
    chmod_back(gate, mode)
    assert types(run(roots, root)) == {"d": "dir", "lnk": "dir", "f.txt": "file"}


@pytest.fixture
def r2(tmp_path: Path) -> dict:
    base = tmp_path.resolve()
    root = base / "r2"
    (root / "x" / "y").mkdir(parents=True)
    (root / "x" / "y" / "g.txt").write_text("g")
    (root / "via").symlink_to("x/y/g.txt")
    return {"root": root, "roots": RootsSettings(default_root=root, extra_roots=())}


@PF_T3_01
@not_root
def test_p2a_listing_below_an_execute_only_in_root_directory(r2, chmod_back):
    chmod_back(r2["root"] / "x", 0o100)
    assert types(run(r2["roots"], r2["root"] / "x" / "y")) == {"g.txt": "file"}


@PF_T3_01
@not_root
def test_p2b_links_through_an_execute_only_in_root_directory(r2, chmod_back):
    root = r2["root"]
    (root / "abs").symlink_to(root / "x" / "y" / "g.txt")
    (root / "up").symlink_to("x/y/../y/g.txt")
    chmod_back(root / "x", 0o100)
    result = types(run(r2["roots"], root))
    assert result == {"abs": "file", "up": "file", "via": "file", "x": "dir"}


@not_root
@pytest.mark.parametrize("mode", [0o300, 0o000])
def test_p3_an_unreadable_listed_directory_is_permission_denied(r2, chmod_back, mode):
    listed = r2["root"] / "x" / "y"
    chmod_back(listed, mode)
    with pytest.raises(ToolError, match="Permission denied") as exc:
        run(r2["roots"], listed)
    assert isinstance(exc.value, CodedToolError)
    assert exc.value.telemetry_code == "permission_denied"
    assert str(listed) in str(exc.value)
