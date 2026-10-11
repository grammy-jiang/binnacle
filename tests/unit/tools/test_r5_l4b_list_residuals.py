"""Linux list_files LIST mode closes the R-L4 residuals F1-F4 (SD-60, L4b).

Darwin is the oracle: platform/darwin/file_access.py ``link_target_info``
(absolute targets and ``..`` above the root omitted, MAX_LINK_HOPS = 40) and
the file_traversal.py walk (an entry whose no-follow stat fails with EACCES,
EPERM or ENOENT is omitted and not counted).
"""

import json
import os
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.features.files.tools import list_files as lf

SECRET = "s" * 4321  # A size that appears nowhere else in the fixture.
DARWIN_MAX_LINK_HOPS = 40  # platform/darwin/file_access.py MAX_LINK_HOPS.


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    base = tmp_path.resolve()
    root, out = base / "root", base / "out"
    for d in (root, out, out / "exists"):
        d.mkdir()
    (root / "hello.txt").write_text("hello\n")
    (root / "d").mkdir()
    (out / "secret.txt").write_text(SECRET)
    return {
        "root": root,
        "out": out,
        "roots": RootsSettings(default_root=root, extra_roots=()),
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


# F1: the entry is typed from one lstat of the contained target, never the link.


def test_retarget_after_the_check_never_reports_the_outside_target(tree, monkeypatch):
    # Probe M: the link is retargeted outside right after its text is read.
    root, out = tree["root"], tree["out"]
    race = root / "race"
    race.symlink_to("hello.txt")
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
    assert fired == ["hello.txt"]
    assert typed(tree) == {"d": ("dir", None), "hello.txt": ("file", 6)}
    assert result.structured_content is not None
    assert str(len(SECRET)) not in blob(result)
    assert {
        Path(e["path"]).name: e.get("bytes")
        for e in result.structured_content["entries"]
    } == {
        "d": None,
        "hello.txt": 6,
        "race": 6,
    }


def test_target_swapped_for_a_link_after_the_walk_is_omitted(tree, monkeypatch):
    root, out = tree["root"], tree["out"]
    (root / "t.txt").write_text("t")
    (root / "flink").symlink_to("t.txt")
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
    assert "flink" not in blob(result)


def test_a_target_outside_the_roots_is_never_typed(tree, monkeypatch):
    # Defence in depth behind the walk's per-component containment check.
    (tree["root"] / "flink").symlink_to("hello.txt")
    monkeypatch.setattr(lf, "_link_target", lambda *_: tree["out"] / "secret.txt")
    assert typed(tree) == {"d": ("dir", None), "hello.txt": ("file", 6)}


# F2: link text that leaves the roots at any component is omitted.


@pytest.mark.parametrize("absolute", [True, False], ids=["absolute", "relative"])
def test_out_and_back_link_text_is_no_existence_oracle(tree, absolute):
    root, out = tree["root"], tree["out"]
    lead = f"{out}/" if absolute else "../out/"
    outputs = []
    for middle in ("exists", "missing"):
        link = root / "probe"
        link.symlink_to(f"{lead}{middle}/../../root/hello.txt")
        for max_results in (200, 1):
            outputs.append(blob(run(tree, max_results=max_results)))
        link.unlink()
    assert outputs[:2] == outputs[2:]
    assert "probe" not in "".join(outputs)
    assert typed(tree) == {"d": ("dir", None), "hello.txt": ("file", 6)}


def test_steps_out_of_the_root_omit_even_an_in_root_target(tree):
    root = tree["root"]
    (root / "up_in").symlink_to("../root/hello.txt")  # Out at '..', back in.
    (root / "dlink").symlink_to("d", target_is_directory=True)
    (root / "via_dlink").symlink_to("dlink/../hello.txt")  # Physical '..'.
    (root / "d" / "up").symlink_to("../hello.txt")  # '..' stays in the root.
    (root / "d" / "abs_mid").symlink_to("../abs")  # Absolute intermediate link.
    (root / "abs").symlink_to(root / "hello.txt")  # Listed since r6 X2.
    assert typed(tree) == {
        "abs": ("file", 6),
        "d": ("dir", None),
        "dlink": ("dir", None),
        "hello.txt": ("file", 6),
        "via_dlink": ("file", 6),
    }
    assert typed(tree, root / "d") == {"up": ("file", 6)}


def test_a_link_through_a_file_component_is_omitted(tree):
    (tree["root"] / "bad").symlink_to("hello.txt/x")
    assert typed(tree) == {"d": ("dir", None), "hello.txt": ("file", 6)}


# F3: more than MAX_LINK_HOPS links is omitted before the total is counted.


@pytest.mark.parametrize("links", [40, 41, 45])
def test_hop_limit_matches_darwin_and_totals_count_listable_entries(tree, links):
    root = tree["root"]
    (root / "hello.txt").unlink()
    (root / "d").rmdir()
    (root / "target.txt").write_text("t")
    names = [f"h{k:02d}" for k in range(links)]
    for name, nxt in zip(names, [*names[1:], "target.txt"], strict=True):
        (root / name).symlink_to(nxt)
    # h_k needs links - k hops; Darwin keeps it only within MAX_LINK_HOPS.
    kept = [n for k, n in enumerate(names) if links - k <= DARWIN_MAX_LINK_HOPS]
    assert typed(tree) == {
        **dict.fromkeys(kept, ("file", 1)),
        "target.txt": ("file", 1),
    }
    total = len(kept) + 1
    assert total == 41  # 40 listable links + target.txt in each case.
    payload = run(tree, max_results=1).structured_content
    assert payload is not None
    assert payload["note"].startswith(f"Showing first 1 of {total} entries")
    assert payload["count"] == 1 and payload["truncated"] is True


def test_hop_limit_equals_darwin():
    from binnacle.platform.darwin import file_access

    assert lf.MAX_LINK_HOPS == file_access.MAX_LINK_HOPS == DARWIN_MAX_LINK_HOPS


# F4: a readable but non-searchable directory lists as Darwin lists it.


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory modes")
def test_readable_unsearchable_directory_omits_its_entries(tree):
    locked = tree["root"] / "locked"
    locked.mkdir()
    (locked / "a.txt").write_text("a")
    (locked / "sub").mkdir()
    locked.chmod(0o444)  # Readable names, no search: every lstat is EACCES.
    try:
        payload = run(tree, path=locked).structured_content
    finally:
        locked.chmod(0o755)
    assert payload == {
        "path": str(locked),
        "mode": "list",
        "entries": [],
        "count": 0,
        "truncated": False,
    }


def test_follow_helper_types_a_real_file_and_dir(tree):
    root = tree["root"]
    assert lf._file_entry(root / "d") == {"path": str(root / "d"), "type": "dir"}
    assert lf._file_entry(root / "hello.txt") == {
        "path": str(root / "hello.txt"),
        "type": "file",
        "bytes": 6,
    }
