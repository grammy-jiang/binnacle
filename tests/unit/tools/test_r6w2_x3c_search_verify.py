"""search_text verify-after-open (r6 W2 X3c, SD-76).

ripgrep opens each file by path string. A race wrapper stands in for rg:
it swaps a matched file (or its directory) for a symlink to an outside
object and runs the real rg with -L, so rg reads the outside object exactly
as it would when a swap lands between its directory read and its open.
r6 reported that outside content; the head reopens every reported file
no-follow from '/' and reads the reported lines from that descriptor.
The parity cases pin the benign results, which are unchanged.
"""

import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from binnacle.config import RootsSettings, get_settings
from binnacle.features.search.tools import search_text as st

# The process descriptor table: /proc/self/fd on Linux, /dev/fd on Darwin.
FD_DIR = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
RG = shutil.which("rg") or "rg"


# Parity finding PF-T3-02 (R6W2-T3): the Darwin pathname core reports the NUL
# line of an explicit file differently; Pi (rg 14), CI Linux (rg 15) and the
# Mac (rg 15) show it follows the platform, not the rg major (CI 38197526494);
# the production provider path matches Linux; reported, never loosened.
PF_T3_02 = pytest.mark.xfail(
    sys.platform == "darwin",
    strict=True,
    reason="PF-T3-02: explicit-file NUL line text differs on the Darwin pathname core",
)
OUTSIDE = "OUTSIDE-SECRET"


def search(pattern: str, path: Path, roots: RootsSettings, **kw: Any) -> dict:
    args: dict[str, Any] = {
        "glob": None,
        "fixed_strings": False,
        "context_lines": None,
        "names_only": False,
        "max_results": 100,
    }
    settings = kw.pop("settings", get_settings().search_text)
    args.update(kw)
    result = st.search_text_impl(
        pattern, str(path), **args, roots=roots, settings=settings, rg_bin=RG
    )
    payload = result.structured_content
    assert payload is not None
    return payload


def wrapper(tmp: Path, before: str, after: str = "") -> str:
    """An rg stand-in: run 'before', the real rg -L, then 'after'."""
    script = tmp / "rg-race.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"{before}\n"
        f'out=$("{RG}" -L "$@"); code=$?\n'
        f"{after}\n"
        'printf "%s\\n" "$out"\n'
        "exit $code\n"
    )
    script.chmod(0o700)
    return str(script)


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    root = tmp_path / "root"
    (root / "d").mkdir(parents=True)
    (root / "m.txt").write_text("needle inside\n")
    (root / "d" / "n.txt").write_text("needle deep\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "m.txt").write_text(f"needle {OUTSIDE}\n")
    (outside / "n.txt").write_text(f"needle {OUTSIDE} deep\n")
    roots = RootsSettings(default_root=root, extra_roots=())
    return {"root": root, "outside": outside, "roots": roots, "tmp": tmp_path}


def mode(name: str):
    return get_settings().search_text.model_copy(update={"exact_execution": name})


def texts(payload: dict) -> str:
    return repr(payload["entries"])


@pytest.mark.parametrize("execution", ["materialized", "streaming"])
@pytest.mark.parametrize("names_only", [False, True])
def test_a_file_swapped_for_an_outside_symlink_is_omitted(tree, execution, names_only):
    root, outside = tree["root"], tree["outside"]
    rg = wrapper(
        tree["tmp"], f'rm "{root}/m.txt"; ln -s "{outside}/m.txt" "{root}/m.txt"'
    )
    payload = st.search_text_impl(
        "needle",
        str(root),
        None,
        False,
        None,
        names_only,
        100,
        roots=tree["roots"],
        settings=mode(execution),
        rg_bin=rg,
    ).structured_content
    assert payload is not None
    assert OUTSIDE not in texts(payload)
    files = {Path(e["file"]).name for e in payload["entries"]}
    assert files == {"n.txt"}
    assert payload["count"] == 1


def test_a_file_swapped_back_after_rg_read_is_the_documented_residual(tree):
    # X3c-a3 (SD-78) removed the per-match content re-read: a swap that is
    # undone before the check leaves an in-root regular file, so rg's text
    # is reported as in r6 (docs/tools/search_text.md, content residual).
    root, outside = tree["root"], tree["outside"]
    rg = wrapper(
        tree["tmp"],
        f'mv "{root}/m.txt" "{root}/m.keep"; ln -s "{outside}/m.txt" "{root}/m.txt"',
        f'rm "{root}/m.txt"; mv "{root}/m.keep" "{root}/m.txt"',
    )
    payload = st.search_text_impl(
        "needle", str(root), None, False, 0, False, 100, roots=tree["roots"], rg_bin=rg
    ).structured_content
    assert payload is not None
    assert {e["file"] for e in payload["entries"]} == {
        str(root / "m.txt"),
        str(root / "d" / "n.txt"),
    }


def test_a_directory_swapped_for_an_outside_symlink_is_omitted(tree):
    root, outside = tree["root"], tree["outside"]
    rg = wrapper(
        tree["tmp"], f'mv "{root}/d" "{root}/d.keep"; ln -s "{outside}" "{root}/d"'
    )
    payload = search("needle", root, tree["roots"], context_lines=0)
    assert {Path(e["file"]).name for e in payload["entries"]} == {"m.txt", "n.txt"}
    payload = st.search_text_impl(
        "needle", str(root), None, False, 0, False, 100, roots=tree["roots"], rg_bin=rg
    ).structured_content
    assert payload is not None
    assert OUTSIDE not in texts(payload)
    # d.keep is the moved in-root directory; nothing is reported through d.
    assert sorted(e["text"] for e in payload["entries"]) == [
        "needle deep",
        "needle inside",
    ]
    assert all("/d/" not in e["file"] for e in payload["entries"])


def test_context_lines_come_from_the_verified_file(tree):
    root, outside = tree["root"], tree["outside"]
    (root / "m.txt").write_text("a\nneedle inside\nb\n")
    (outside / "m.txt").write_text(f"{OUTSIDE}\nneedle x\n{OUTSIDE}\n")
    rg = wrapper(
        tree["tmp"], f'rm "{root}/m.txt"; ln -s "{outside}/m.txt" "{root}/m.txt"'
    )
    payload = st.search_text_impl(
        "needle", str(root), None, False, 1, False, 100, roots=tree["roots"], rg_bin=rg
    ).structured_content
    assert payload is not None
    assert OUTSIDE not in texts(payload)


def adaptive_settings():
    return get_settings().search_text.model_copy(
        update={"result_max_bytes": 4000, "adaptive_discovery_enabled": True}
    )


def test_adaptive_discovery_omits_a_swapped_file(tree):
    root, outside = tree["root"], tree["outside"]
    for index in range(40):
        (root / f"f{index:02}.txt").write_text("needle " + "x" * 200 + "\n")
    # Many matches rank the swapped file first, so r6 details it.
    (outside / "m.txt").write_text(f"needle {OUTSIDE}\n" * 6)
    rg = wrapper(
        tree["tmp"], f'rm "{root}/m.txt"; ln -s "{outside}/m.txt" "{root}/m.txt"'
    )
    payload = st.search_text_impl(
        "needle",
        str(root),
        None,
        False,
        0,
        False,
        100,
        roots=tree["roots"],
        settings=adaptive_settings(),
        rg_bin=rg,
    ).structured_content
    assert payload is not None
    assert "Adaptive" in payload.get("note", "")
    assert OUTSIDE not in texts(payload)
    assert all(Path(e["file"]).name != "m.txt" for e in payload["entries"])


def test_adaptive_discovery_benign_result_is_unchanged(tree):
    root = tree["root"]
    for index in range(40):
        (root / f"f{index:02}.txt").write_text("needle " + "y" * 400 + "\n")
    payload = search(
        "needle", root, tree["roots"], context_lines=0, settings=adaptive_settings()
    )
    assert "Adaptive" in payload.get("note", "")
    clipped = [e for e in payload["entries"] if e.get("text", "").endswith("…")]
    assert clipped and all(e["text"] == "needle " + "y" * 173 + "…" for e in clipped)
    names = {Path(e["file"]).name for e in payload["entries"]}
    assert len(names) > 5


# -- parity: the line model equals rg's for benign files ----------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\xef\xbb\xbfneedle bom\nx\n", ["needle bom"]),
        ("needle utf16\nz\n".encode("utf-16"), ["needle utf16"]),
        (b"needle crlf\r\nneedle two\r\n", ["needle crlf\r", "needle two\r"]),
        (b"needle \xff bad\n", [""]),
        (b"no newline needle", ["no newline needle"]),
    ],
)
def test_benign_encodings_are_reported_as_before(tmp_path, raw, expected):
    root = tmp_path / "root"
    root.mkdir()
    (root / "f.txt").write_bytes(raw)
    roots = RootsSettings(default_root=root, extra_roots=())
    payload = search("needle", root, roots, context_lines=0)
    assert [e["text"] for e in payload["entries"]] == expected


@PF_T3_02
def test_an_explicit_file_with_nul_bytes_is_reported_as_before(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "b.bin").write_bytes(b"needle\x00one\nneedle two\n")
    roots = RootsSettings(default_root=root, extra_roots=())
    payload = search("needle", root / "b.bin", roots, context_lines=0)
    assert [e["text"] for e in payload["entries"]] == ["needle\x00one", "needle two"]


def test_auto_context_and_line_numbers_are_unchanged(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "f.txt").write_text("".join(f"l{n}\n" for n in range(1, 20)) + "needle\n")
    roots = RootsSettings(default_root=root, extra_roots=())
    payload = search("needle", root, roots, line_numbers=True)
    (entry,) = payload["entries"]
    assert entry["line"] == 20
    assert entry["context"].splitlines()[-1] == "20: needle"


def test_a_search_base_reached_through_a_cross_root_link_is_unchanged(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    (b / "s").mkdir(parents=True)
    (b / "s" / "f.txt").write_text("needle b\n")
    (a / "to_b").symlink_to(b / "s")
    roots = RootsSettings(default_root=a, extra_roots=(b,))
    payload = search("needle", a / "to_b", roots, context_lines=0)
    assert [e["text"] for e in payload["entries"]] == ["needle b"]
    outer = search("needle", a / ".." / "b", roots, context_lines=0)
    assert [e["text"] for e in outer["entries"]] == ["needle b"]


def test_nested_roots_and_an_execute_only_ancestor_are_unchanged(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root ignores modes")
    gate = tmp_path / "gate"
    inner = gate / "outer" / "inner"
    inner.mkdir(parents=True)
    (inner / "f.txt").write_text("needle nested\n")
    roots = RootsSettings(default_root=gate / "outer", extra_roots=(inner,))
    gate.chmod(stat.S_IXUSR)
    try:
        payload = search("needle", gate / "outer", roots, context_lines=0)
    finally:
        gate.chmod(0o700)
    assert [e["text"] for e in payload["entries"]] == ["needle nested"]


def test_verification_leaks_no_descriptor(tree):
    root, outside = tree["root"], tree["outside"]
    rg = wrapper(
        tree["tmp"],
        f'[ -L "{root}/m.txt" ] || {{ rm "{root}/m.txt"; '
        f'ln -s "{outside}/m.txt" "{root}/m.txt"; }}',
    )
    before = len(os.listdir(FD_DIR))
    for _ in range(30):
        st.search_text_impl(
            "needle",
            str(root),
            None,
            False,
            0,
            False,
            100,
            roots=tree["roots"],
            rg_bin=rg,
        )
        search("needle", root, tree["roots"], context_lines=2)
    after = len(os.listdir(FD_DIR))
    assert after == before
