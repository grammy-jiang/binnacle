"""Linux list_files LIST mode lists absolute in-root link text (r6 X2, SD-67).

Rule, identical on Darwin (platform/darwin/file_access.py ``absolute_in_root``
and ``link_target_info``): absolute link text is walked only when, lexically
(no filesystem call), it has no ``..`` component and lies under the root that
holds the link. The r5 L4/L4b checks still apply after that gate: every
component stays inside the roots, an absolute intermediate link is omitted,
more than 40 hops is omitted, and the entry is typed from ONE no-follow
lstat of the contained target. Everything else stays omitted, as in r5.
"""

import json
import os
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.features.files.tools import list_files as lf
from binnacle.platform.darwin import file_access as darwin

SECRET = "s" * 4321  # A size that appears nowhere else in the fixture.
BASE = {"d": ("dir", None), "hello.txt": ("file", 6)}


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    base = tmp_path.resolve()
    root, other, out = base / "root", base / "other", base / "out"
    for d in (root, other, out, out / "exists"):
        d.mkdir()
    (root / "hello.txt").write_text("hello\n")
    (root / "d").mkdir()
    (root / "d" / "in.txt").write_text("x")
    (other / "o.txt").write_text("other!!")
    (out / "secret.txt").write_text(SECRET)
    return {
        "root": root,
        "other": other,
        "out": out,
        "roots": RootsSettings(default_root=root, extra_roots=(other,)),
    }


def run(tree: dict, max_results: int = 200, path: Path | None = None):
    return lf.list_files_impl(
        str(path or tree["root"]), None, max_results, False, roots=tree["roots"]
    )


def typed(tree: dict, path: Path | None = None) -> dict:
    payload = run(tree, path=path).structured_content
    assert payload is not None
    base = path or tree["root"]
    return {
        Path(e["path"]).relative_to(base).as_posix(): (e["type"], e.get("bytes"))
        for e in payload["entries"]
    }


def blob(result) -> str:
    text = " ".join(getattr(c, "text", "") for c in result.content)
    return json.dumps(result.structured_content, sort_keys=True) + "\n" + text


# The lexical gate.


LEXICAL = [
    ("/r/a", "/r", ["a"]),
    ("/r", "/r", []),
    ("/r/", "/r", [""]),  # A trailing '/' or '/.' keeps one '' marker (RX2-F2).
    ("/r/.", "/r", [""]),
    ("//r//a/./b/", "/r", ["a", "b", ""]),
    ("/r/a/.", "/r", ["a", ""]),
    ("/r/./a", "/r", ["a"]),
    ("/r/a/../b", "/r", None),  # Any '..', even one that stays inside.
    ("/r/..", "/r", None),
    ("/out/x/../../r/a", "/r", None),  # Probes G/H.
    ("/rx/a", "/r", None),  # A string prefix is not a component prefix.
    ("/other/a", "/r", None),
    ("/", "/r", None),
    ("/a/b", "/", ["a", "b"]),
    ("/a/b/", "/", ["a", "b", ""]),
]


@pytest.mark.parametrize(("text", "root", "below"), LEXICAL)
def test_lexical_gate_is_identical_on_both_oses(text, root, below):
    assert lf._absolute_in_root(text, root) == below
    assert darwin.absolute_in_root(text, root) == below


def test_lexical_gate_never_touches_the_filesystem(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("filesystem consulted")

    with monkeypatch.context() as patched:
        for name in ("lstat", "stat", "readlink", "open", "scandir"):
            patched.setattr(os, name, refuse)
        linux = lf._absolute_in_root("/out/missing/../../r/a", "/r")
        native = darwin.absolute_in_root("/r/a", "/r")
    assert (linux, native) == (None, ["a"])


# Listed since r6: absolute text under the link's own root.


def test_absolute_in_root_file_and_dir_links_are_listed(tree):
    root = tree["root"]
    (root / "abs_file").symlink_to(root / "hello.txt")
    (root / "abs_dir").symlink_to(root / "d", target_is_directory=True)
    (root / "adeep").symlink_to(root / "d" / "in.txt")
    (root / "aroot").symlink_to(root, target_is_directory=True)
    (root / "aslash").symlink_to(f"/{root}//d/./")
    assert typed(tree) == {
        **BASE,
        "adeep": ("file", 1),
        "abs_dir": ("dir", None),
        "abs_file": ("file", 6),
        "aroot": ("dir", None),
        "aslash": ("dir", None),
    }


@pytest.mark.parametrize("suffix", ["/", "/.", "//"])
@pytest.mark.parametrize(
    ("target", "expected"),
    [("hello.txt", None), ("d", ("dir", None))],
    ids=["file", "dir"],
)
def test_trailing_slash_needs_a_directory_as_for_relative_text(
    tree, suffix, target, expected
):
    # RX2-F2: the kernel follows '<file>/' to nothing (ENOTDIR): a dangling
    # link, omitted; '<dir>/' is the directory. Absolute and relative text of
    # the same link give the same output.
    root = tree["root"]
    outputs = []
    for lead in (f"{root}/", ""):
        (root / "probe").symlink_to(f"{lead}{target}{suffix}")
        if expected is None:
            with pytest.raises(NotADirectoryError):
                os.stat(root / "probe")
        assert typed(tree).get("probe") == expected
        outputs.append(blob(run(tree)) + blob(run(tree, max_results=1)))
        (root / "probe").unlink()
    assert outputs[0] == outputs[1]


def test_absolute_link_in_a_subdirectory_and_relative_hops_after_it(tree):
    root = tree["root"]
    (root / "rel").symlink_to("hello.txt")
    (root / "d" / "via_rel").symlink_to(root / "rel")  # Then one relative hop.
    (root / "d" / "up_in").symlink_to(root / "d" / "in.txt")
    assert typed(tree, root / "d") == {
        "in.txt": ("file", 1),
        "up_in": ("file", 1),
        "via_rel": ("file", 6),
    }


def test_nested_roots_use_the_innermost_root_that_holds_the_link(tmp_path):
    outer = tmp_path.resolve()
    inner = outer / "inner"
    inner.mkdir()
    (outer / "o.txt").write_text("outer")
    (inner / "i.txt").write_text("in")
    (inner / "to_inner").symlink_to(inner / "i.txt")
    (inner / "to_outer").symlink_to(outer / "o.txt")  # Another (outer) root.
    roots = RootsSettings(default_root=outer, extra_roots=(inner,))
    payload = lf.list_files_impl(str(inner), None, 200, False, roots=roots)
    entries = payload.structured_content["entries"]
    assert {Path(e["path"]).name: e.get("bytes") for e in entries} == {
        "i.txt": 2,
        "to_inner": 2,
    }


# Still omitted, as in r5.


def test_absolute_text_with_dotdot_is_omitted_even_when_it_stays_inside(tree):
    root = tree["root"]
    (root / "dd_in").symlink_to(f"{root}/d/../hello.txt")
    (root / "dd_root").symlink_to(f"{root}/../root/hello.txt")
    assert typed(tree) == BASE


def test_cross_root_outside_and_prefix_trick_are_omitted(tree):
    root, other, out = tree["root"], tree["other"], tree["out"]
    (root / "cross").symlink_to(other / "o.txt")
    (root / "out_file").symlink_to(out / "secret.txt")
    (root / "out_dir").symlink_to(out, target_is_directory=True)
    (root / "slash").symlink_to("/", target_is_directory=True)
    trick = Path(f"{root}x")
    trick.mkdir()
    (trick / "f").write_text(SECRET)
    (root / "prefix").symlink_to(trick / "f")
    result = run(tree)
    assert typed(tree) == BASE
    for leaked in (str(len(SECRET)), str(out), '/cross"', '/prefix"', "/out_"):
        assert leaked not in blob(result)


def test_dangling_loop_and_absolute_intermediate_links_are_omitted(tree):
    root = tree["root"]
    (root / "dangle").symlink_to(root / "nope")
    (root / "self").symlink_to(root / "self")
    (root / "ping").symlink_to("pong")
    (root / "pong").symlink_to("ping")
    (root / "through_file").symlink_to(root / "hello.txt" / "x")
    (root / "abs_mid").symlink_to(root / "abs_end")  # abs_end: absolute text.
    (root / "abs_end").symlink_to(root / "hello.txt")
    assert typed(tree) == {**BASE, "abs_end": ("file", 6)}


@pytest.mark.parametrize("links", [39, 40, 41])
def test_hop_limit_still_applies_after_the_gate(tree, links):
    root = tree["root"]
    names = [f"h{k:02d}" for k in range(links - 1)]
    for name, nxt in zip(names, [*names[1:], "hello.txt"], strict=True):
        (root / name).symlink_to(nxt)
    (root / "abs_head").symlink_to(root / (names[0] if names else "hello.txt"))
    listed = typed(tree)
    # abs_head needs `links` hops: kept only within MAX_LINK_HOPS = 40.
    assert ("abs_head" in listed) is (links <= lf.MAX_LINK_HOPS)
    payload = run(tree, max_results=1).structured_content
    assert payload is not None
    assert payload["note"].startswith(f"Showing first 1 of {len(listed)} entries")


def test_unreadable_target_metadata_is_omitted(tree, monkeypatch):
    root = tree["root"]
    (root / "abs_file").symlink_to(root / "hello.txt")
    real_lstat = os.lstat

    def denied(path, *args, **kwargs):
        if Path(path) == root / "hello.txt":
            raise PermissionError("lstat denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", denied)
    assert typed(tree) == {"d": ("dir", None)}


# R-L4 probes stay closed with absolute in-root text listed.


@pytest.mark.parametrize("absolute", [True, False], ids=["absolute", "relative"])
def test_probe_gh_out_and_back_is_no_existence_oracle(tree, absolute):
    root, out = tree["root"], tree["out"]
    lead = f"{out}/" if absolute else "../out/"
    outputs = []
    for middle in ("exists", "missing"):
        (root / "probe").symlink_to(f"{lead}{middle}/../../root/hello.txt")
        for max_results in (200, 1):
            outputs.append(blob(run(tree, max_results=max_results)))
        (root / "probe").unlink()
    assert outputs[:2] == outputs[2:]
    assert '/probe"' not in "".join(outputs)


@pytest.mark.parametrize("escape", ["absolute", "relative"])
@pytest.mark.parametrize("kind", ["file", "dir"])
def test_probe_steer01_in_root_text_through_an_escaping_link(tree, escape, kind):
    # STEER-01 item 2: root/a -> outside, root/l -> <root>/a/x (absolute text).
    root, out = tree["root"], tree["out"]
    (root / "a").symlink_to(
        out if escape == "absolute" else "../out", target_is_directory=True
    )
    (root / "l").symlink_to(root / "a" / "x")
    outputs = []
    for exists in (True, False):
        if exists:
            if kind == "file":
                (out / "x").write_text(SECRET)
            else:
                (out / "x").mkdir()
        for max_results in (200, 1):
            outputs.append(blob(run(tree, max_results=max_results)))
        if exists:
            (out / "x").unlink() if kind == "file" else (out / "x").rmdir()
    assert outputs[:2] == outputs[2:]
    joined = "".join(outputs)
    for leaked in ('/l"', str(len(SECRET)), str(out)):
        assert leaked not in joined
    assert typed(tree) == BASE


def test_probe_m_retarget_after_the_read_types_the_checked_target(tree, monkeypatch):
    root, out = tree["root"], tree["out"]
    race = root / "race"
    race.symlink_to(root / "hello.txt")
    real_readlink = os.readlink
    fired = []

    def readlink_then_retarget(path, *args, **kwargs):
        text = real_readlink(path, *args, **kwargs)
        if os.fspath(path) == str(race) and not fired:
            fired.append(text)
            race.unlink()
            race.symlink_to(out / "secret.txt")
        return text

    monkeypatch.setattr(os, "readlink", readlink_then_retarget)
    result = run(tree)
    monkeypatch.undo()
    assert fired == [str(root / "hello.txt")]
    assert str(len(SECRET)) not in blob(result)
    assert result.structured_content is not None
    assert {
        Path(e["path"]).name: e.get("bytes")
        for e in result.structured_content["entries"]
    } == {"d": None, "hello.txt": 6, "race": 6}
    assert typed(tree) == BASE  # Now outside: omitted.


def test_target_swapped_for_a_link_after_the_walk_is_omitted(tree, monkeypatch):
    root, out = tree["root"], tree["out"]
    (root / "t.txt").write_text("t")
    (root / "alink").symlink_to(root / "t.txt")
    real_target = lf._link_target

    def target_then_swap(link, allowed):
        target = real_target(link, allowed)
        if target is not None and target.name == "t.txt":
            target.unlink()
            target.symlink_to(out / "secret.txt")
        return target

    monkeypatch.setattr(lf, "_link_target", target_then_swap)
    result = run(tree)
    assert str(len(SECRET)) not in blob(result)
    assert "alink" not in blob(result)


def test_omitted_links_do_not_count_toward_totals(tree):
    root, out = tree["root"], tree["out"]
    (root / "abs_file").symlink_to(root / "hello.txt")
    (root / "out_file").symlink_to(out / "secret.txt")
    (root / "dd").symlink_to(f"{root}/d/../hello.txt")
    payload = run(tree, max_results=1).structured_content
    assert payload is not None
    assert payload["note"].startswith("Showing first 1 of 3 entries")
    assert payload["count"] == 1 and payload["truncated"] is True


@pytest.mark.parametrize("glob", ["*", "**/*"])
def test_glob_mode_is_unchanged(tree, glob):
    root = tree["root"]
    (root / "abs_file").symlink_to(root / "hello.txt")
    payload = lf.list_files_impl(
        str(root), glob, 200, False, roots=tree["roots"]
    ).structured_content
    assert payload is not None
    assert sorted(Path(e["path"]).name for e in payload["entries"]) == [
        "hello.txt",
        "in.txt",
    ]


def test_configured_alias_prefix_follows_darwin(tmp_path):
    # Darwin's provider is granted only the canonical root, so alias-prefixed
    # text is omitted on both OSes (STEER-01 item 3 is reported, not changed).
    real = tmp_path.resolve() / "real"
    real.mkdir()
    (real / "f.txt").write_text("ff")
    alias = tmp_path.resolve() / "alias"
    alias.symlink_to(real, target_is_directory=True)
    (real / "via_alias").symlink_to(alias / "f.txt")
    (real / "via_real").symlink_to(real / "f.txt")
    roots = RootsSettings(default_root=alias, extra_roots=())
    payload = lf.list_files_impl(str(alias), None, 200, False, roots=roots)
    entries = payload.structured_content["entries"]
    assert {Path(e["path"]).name: e.get("bytes") for e in entries} == {
        "f.txt": 2,
        "via_real": 2,
    }
