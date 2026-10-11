"""Darwin list_files LIST mode lists absolute in-root link text (r6 X2, SD-67).

The descriptor adapter (file_access.py ``link_target_info``) walks absolute
link text from the root descriptor only when ``absolute_in_root`` accepts it
for the granted root: no ``..`` component, under the root, decided lexically.
Each probe runs the Darwin adapter and the Linux legacy path on the same tree
and requires the same tool output. These cases run on every POSIX host; only
the ``/tmp`` firmlink cases need macOS.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.features.files import paths
from binnacle.features.files.tools import list_files as lf
from binnacle.platform.contracts.capability_contracts import (
    Capability,
    CapabilityState,
)
from binnacle.platform.darwin import file_access
from binnacle.platform.darwin.file_access import DarwinFileAccess

_DARWIN = pytest.mark.skipif(
    sys.platform != "darwin", reason="/tmp is a symlink to /private/tmp on macOS"
)
SECRET = "s" * 4321  # A size that appears nowhere else in the fixture.
BASE = {"d": ("dir", None), "hello.txt": ("file", 6)}


def access_for(roots: RootsSettings) -> paths.FileToolAccess:
    return paths.FileToolAccess(
        roots=roots,
        files=DarwinFileAccess(),
        search=None,
        generation="r6-x2",
        capability=Capability(CapabilityState.LIMITED, "test_only", "opened-object"),
    )


@pytest.fixture
def tree(tmp_path: Path):
    base = tmp_path.resolve()
    root, other, out = base / "root", base / "other", base / "out"
    for d in (root, other, out, out / "exists"):
        d.mkdir()
    (root / "hello.txt").write_text("hello\n")
    (root / "d").mkdir()
    (root / "d" / "in.txt").write_text("x")
    (other / "o.txt").write_text("other!!")
    (out / "secret.txt").write_text(SECRET)
    roots = RootsSettings(default_root=root, extra_roots=(other,))
    with closing(access_for(roots)) as access:
        yield {
            "root": root,
            "other": other,
            "out": out,
            "roots": roots,
            "access": access,
        }


def run(tree: dict, *, native: bool, max_results: int = 200, path: Path | None = None):
    return lf.list_files_impl(
        str(path or tree["root"]),
        None,
        max_results,
        False,
        roots=tree["roots"],
        file_access=tree["access"] if native else None,
    )


def blob(result) -> str:
    text = " ".join(getattr(c, "text", "") for c in result.content)
    return json.dumps(result.structured_content, sort_keys=True) + "\n" + text


def both(tree: dict, path: Path | None = None) -> str:
    """Darwin and Linux output for every page size; they must be identical."""
    outputs = []
    for max_results in (200, 1):
        darwin, linux = (
            blob(run(tree, native=native, max_results=max_results, path=path))
            for native in (True, False)
        )
        assert darwin == linux
        outputs.append(darwin)
    return "\n".join(outputs)


def typed(tree: dict, path: Path | None = None) -> dict:
    base = path or tree["root"]
    payload = run(tree, native=True, path=path).structured_content
    assert payload is not None
    return {
        Path(e["path"]).relative_to(base).as_posix(): (e["type"], e.get("bytes"))
        for e in payload["entries"]
    }


def link(at: Path, text: Path | str, is_dir: bool = False) -> None:
    at.symlink_to(text, target_is_directory=is_dir)


def listed(r: Path, o: Path, x: Path) -> None:
    link(r / "abs_file", r / "hello.txt")
    link(r / "abs_dir", r / "d", True)
    link(r / "aroot", r, True)
    link(r / "aslash", f"/{r}//d/./", True)


def dotdot(r: Path, o: Path, x: Path) -> None:
    link(r / "dd_in", f"{r}/d/../hello.txt")
    link(r / "dd_root", f"{r}/../root/hello.txt")


def elsewhere(r: Path, o: Path, x: Path) -> None:
    link(r / "cross", o / "o.txt")
    link(r / "out_file", x / "secret.txt")
    link(r / "out_dir", x, True)
    link(r / "slash", "/", True)
    trick = Path(f"{r}x")  # A string prefix of the root, not a component one.
    trick.mkdir()
    (trick / "f").write_text(SECRET)
    link(r / "prefix", trick / "f")


def unresolvable(r: Path, o: Path, x: Path) -> None:
    link(r / "dangle", r / "nope")
    link(r / "self", r / "self")
    link(r / "through_file", r / "hello.txt" / "x")
    link(r / "abs_mid", r / "abs_end")  # An absolute intermediate link.
    link(r / "abs_end", r / "hello.txt")


PROBES: dict[str, tuple[Callable[[Path, Path, Path], None], dict]] = {
    "listed_file_dir_root": (
        listed,
        {
            **BASE,
            "abs_dir": ("dir", None),
            "abs_file": ("file", 6),
            "aroot": ("dir", None),
            "aslash": ("dir", None),
        },
    ),
    "dotdot_even_inside": (dotdot, BASE),
    "cross_root_outside_prefix": (elsewhere, BASE),
    "dangling_loop_intermediate": (unresolvable, {**BASE, "abs_end": ("file", 6)}),
}


@pytest.mark.parametrize("probe", sorted(PROBES))
def test_darwin_matches_linux_per_probe(tree, probe):
    setup, expected = PROBES[probe]
    setup(tree["root"], tree["other"], tree["out"])
    output = both(tree)
    assert typed(tree) == expected
    assert str(len(SECRET)) not in output


def test_darwin_absolute_link_in_a_subdirectory(tree):
    root = tree["root"]
    link(root / "rel", "hello.txt")
    link(root / "d" / "via_rel", root / "rel")
    link(root / "d" / "up_in", root / "d" / "in.txt")
    both(tree, root / "d")
    assert typed(tree, root / "d") == {
        "in.txt": ("file", 1),
        "up_in": ("file", 1),
        "via_rel": ("file", 6),
    }


@pytest.mark.parametrize("links", [39, 40, 41])
def test_darwin_hop_limit_after_the_gate(tree, links):
    root = tree["root"]
    names = [f"h{k:02d}" for k in range(links - 1)]
    for name, nxt in zip(names, [*names[1:], "hello.txt"], strict=True):
        link(root / name, nxt)
    link(root / "abs_head", root / names[0])
    both(tree)
    assert ("abs_head" in typed(tree)) is (links <= file_access.MAX_LINK_HOPS)


@pytest.mark.parametrize("absolute", [True, False], ids=["absolute", "relative"])
def test_darwin_probe_gh_is_no_existence_oracle(tree, absolute):
    root, out = tree["root"], tree["out"]
    lead = f"{out}/" if absolute else "../out/"
    outputs = []
    for middle in ("exists", "missing"):
        link(root / "probe", f"{lead}{middle}/../../root/hello.txt")
        outputs.append(both(tree))
        (root / "probe").unlink()
    assert outputs[0] == outputs[1]
    assert '/probe"' not in outputs[0]


@pytest.mark.parametrize("escape", ["absolute", "relative"])
@pytest.mark.parametrize("kind", ["file", "dir"])
def test_darwin_probe_steer01_through_an_escaping_link(tree, escape, kind):
    root, out = tree["root"], tree["out"]
    link(root / "a", out if escape == "absolute" else "../out", True)
    link(root / "l", root / "a" / "x")
    outputs = []
    for exists in (True, False):
        if exists:
            (out / "x").write_text(SECRET) if kind == "file" else (out / "x").mkdir()
        outputs.append(both(tree))
        if exists:
            (out / "x").unlink() if kind == "file" else (out / "x").rmdir()
    assert outputs[0] == outputs[1]
    for leaked in ('/l"', str(len(SECRET)), str(out)):
        assert leaked not in outputs[0]
    assert typed(tree) == BASE


def test_darwin_probe_m_retarget_after_the_read(tree, monkeypatch):
    root, out = tree["root"], tree["out"]
    race = root / "race"
    link(race, root / "hello.txt")
    real_readlink = os.readlink
    fired = []

    def readlink_then_retarget(path, *args, **kwargs):
        text = real_readlink(path, *args, **kwargs)
        if os.fspath(path) == "race" and not fired:
            fired.append(text)
            race.unlink()
            link(race, out / "secret.txt")
        return text

    monkeypatch.setattr(os, "readlink", readlink_then_retarget)
    result = run(tree, native=True)
    monkeypatch.undo()
    assert fired == [str(root / "hello.txt")]
    assert str(len(SECRET)) not in blob(result)
    assert result.structured_content is not None
    assert {
        Path(e["path"]).name: e.get("bytes")
        for e in result.structured_content["entries"]
    } == {"d": None, "hello.txt": 6, "race": 6}
    assert typed(tree) == BASE


def test_darwin_root_path_is_required_for_absolute_text(tree):
    root = tree["root"]
    link(root / "abs_file", root / "hello.txt")
    with closing(DarwinFileAccess()) as files:
        grant = files.grant(root, generation="r6-x2-direct")
        with files._root(grant) as fd:
            known = file_access.link_target_info(fd, (), "abs_file", str(root))
            unknown = file_access.link_target_info(fd, (), "abs_file", None)
    assert known is not None and known.st_size == 6
    assert unknown is None


# macOS: a root configured as /tmp, canonical /private/tmp (STEER-01 item 3).


@pytest.fixture
def tmp_alias():
    with tempfile.TemporaryDirectory(prefix="r6-x2-", dir="/tmp") as made:
        name = Path(made).name
        alias, canonical = Path("/tmp"), Path("/tmp").resolve()
        work = canonical / name
        (work / "d").mkdir()
        (work / "f.txt").write_text("ff")
        roots = RootsSettings(default_root=alias, extra_roots=())
        with closing(access_for(roots)) as access:
            yield {
                "work": work,
                "alias_work": alias / name,
                "roots": roots,
                "access": access,
            }


def tmp_typed(env: dict) -> dict:
    payload = lf.list_files_impl(
        str(env["alias_work"]),
        None,
        200,
        False,
        roots=env["roots"],
        file_access=env["access"],
    ).structured_content
    assert payload is not None
    return {
        Path(e["path"]).name: (e["type"], e.get("bytes")) for e in payload["entries"]
    }


@_DARWIN
def test_darwin_tmp_root_canonical_text_and_omissions(tmp_alias):
    work = tmp_alias["work"]
    assert work.parts[:3] == ("/", "private", "tmp")
    link(work / "canon", work / "f.txt")
    link(work / "canon_dir", work / "d", True)
    link(work / "canon_dd", f"{work}/d/../f.txt")
    link(work / "alias_dd", f"{tmp_alias['alias_work']}/d/../f.txt")
    link(work / "outside", "/etc/hosts")
    assert tmp_typed(tmp_alias) == {
        "canon": ("file", 2),
        "canon_dir": ("dir", None),
        "d": ("dir", None),
        "f.txt": ("file", 2),
    }


@_DARWIN
@pytest.mark.xfail(
    strict=True,
    reason="STEER-01 item 3 BLOCKED: the provider is granted only the canonical "
    "root (features/files/paths.py _open_grants: files.grant(canonical, ...); "
    "contract FileAccess.grant), so text under the configured /tmp alias is "
    "omitted; outside the R6-X2 grant",
)
def test_darwin_tmp_root_alias_text_is_listed(tmp_alias):
    work = tmp_alias["work"]
    link(work / "via_alias", tmp_alias["alias_work"] / "f.txt")
    assert tmp_typed(tmp_alias)["via_alias"] == ("file", 2)
