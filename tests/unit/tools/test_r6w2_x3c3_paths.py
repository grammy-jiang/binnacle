"""search_text and list_files glob path checks (r6 W2 X3c-a3, SD-78).

F3: a path that rg reports outside the resolved base is dropped, and a glob
line that is absolute or has a '..' component is rejected. Races that still
apply: a reported file that is no longer a regular file is omitted. Scale:
1500 directories with one file each under a soft RLIMIT_NOFILE of 256 (set
in a subprocess) lose no entry and no size; the descriptors that the checks
hold stay within the path depth plus a small constant.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from binnacle.config import RootsSettings
from binnacle.features.files.tools import list_files as lf
from binnacle.features.search.tools import search_text as st

RG = shutil.which("rg") or "rg"
OUTSIDE = "OUTSIDE-SECRET"


def wrapper(tmp: Path, body: str) -> str:
    script = tmp / "rg-wrap.sh"
    script.write_text(f"#!/bin/sh\n{body}\n")
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
    (outside / "o.txt").write_text(f"needle {OUTSIDE}\n")
    roots = RootsSettings(default_root=tmp_path, extra_roots=())
    return {"root": root, "outside": outside, "roots": roots, "tmp": tmp_path}


def search(rg: str, tree: dict, path: Path | None = None, **kw: Any) -> dict:
    args: dict[str, Any] = {
        "glob": None,
        "fixed_strings": False,
        "context_lines": 0,
        "names_only": False,
        "max_results": 100,
    }
    args.update(kw)
    result = st.search_text_impl(
        "needle", str(path or tree["root"]), **args, roots=tree["roots"], rg_bin=rg
    )
    assert result.structured_content is not None
    return result.structured_content


@pytest.mark.parametrize("names_only", [False, True])
def test_an_rg_reported_path_outside_the_base_is_dropped(tree, names_only):
    # rg is asked to search the base only; this rg adds an outside path.
    rg = wrapper(tree["tmp"], f'exec "{RG}" "$@" "{tree["outside"]}"')
    payload = search(rg, tree, names_only=names_only)
    assert OUTSIDE not in repr(payload["entries"])
    assert all(e["file"].startswith(f"{tree['root']}/") for e in payload["entries"])
    assert payload["count"] == 2


def test_an_rg_reported_sibling_of_a_file_base_is_dropped(tree):
    rg = wrapper(tree["tmp"], f'exec "{RG}" "$@" "{tree["outside"]}/o.txt"')
    payload = search(rg, tree, path=tree["root"] / "m.txt")
    assert [e["file"] for e in payload["entries"]] == [str(tree["root"] / "m.txt")]
    assert payload["count"] == 1


def test_a_reported_file_replaced_by_a_directory_is_omitted(tree):
    root = tree["root"]
    rg = wrapper(
        tree["tmp"],
        f'out=$("{RG}" "$@"); code=$?\n'
        f'rm "{root}/m.txt"; mkdir "{root}/m.txt"\n'
        'printf "%s\\n" "$out"; exit $code',
    )
    payload = search(rg, tree)
    assert [Path(e["file"]).name for e in payload["entries"]] == ["n.txt"]
    assert payload["count"] == 1


def glob(tree: dict, rg: str, pattern: str = "*.txt") -> list[dict]:
    result = lf._glob_mode(tree["root"], pattern, 100, False, rg_bin=rg, timeout_s=30)
    assert result.structured_content is not None
    return result.structured_content["entries"]


def test_absolute_and_dotdot_glob_lines_are_rejected(tree):
    rg = wrapper(
        tree["tmp"],
        f'"{RG}" "$@"; code=$?\n'
        f'printf "%s\\n" "{tree["outside"]}/o.txt" "../outside/o.txt" '
        '"d/../../outside/o.txt"\nexit $code',
    )
    entries = glob(tree, rg)
    assert sorted(e["path"] for e in entries) == [
        str(tree["root"] / "d" / "n.txt"),
        str(tree["root"] / "m.txt"),
    ]
    assert all("bytes" in e for e in entries)


def test_a_glob_file_replaced_after_listing_is_typed_and_sized_in_root(tree):
    root, outside = tree["root"], tree["outside"]
    rg = wrapper(
        tree["tmp"],
        f'out=$("{RG}" "$@"); code=$?\n'
        f'rm "{root}/m.txt"; ln -s "{outside}/o.txt" "{root}/m.txt"\n'
        f'printf "%s" "grown" >> "{root}/d/n.txt"\n'
        'printf "%s\\n" "$out"; exit $code',
    )
    entries = glob(tree, rg)
    assert [(Path(e["path"]).name, e["bytes"]) for e in entries] == [
        ("n.txt", len("needle deep\n") + len("grown"))
    ]


SCALE = r"""
import json, os, resource, sys, threading
from pathlib import Path
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (256, hard))
from binnacle.config import RootsSettings
from binnacle.features.search import fd_chain
from binnacle.features.files.tools import list_files as lf
from binnacle.features.search.tools import search_text as st
base, rg = Path(sys.argv[1]), sys.argv[2]
FD_DIR = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
roots = RootsSettings(default_root=base, extra_roots=())
peak = [0]
real = fd_chain.DirectoryChain._descend
def sampled(self, parts):
    fd = real(self, parts)
    peak[0] = max(peak[0], len(os.listdir(FD_DIR)))
    return fd
fd_chain.DirectoryChain._descend = sampled
def search(max_results):
    return st.search_text_impl("NEEDLE", str(base), None, False, 0, True,
        max_results, roots=roots, rg_bin=rg).structured_content
out = {"soft": resource.getrlimit(resource.RLIMIT_NOFILE)[0]}
start = len(os.listdir(FD_DIR))
p = search(1000)
out["search"] = {"count": p["count"], "entries": len(p["entries"]),
    "files": sum(e.get("count", 1) for e in p["entries"]), "peak": peak[0] - start}
peak[0] = 0
start = len(os.listdir(FD_DIR))
g = lf._glob_mode(base, "*.txt", 2000, False, rg_bin=rg, timeout_s=60).structured_content
out["glob"] = {"count": g["count"], "sized": sum("bytes" in e for e in g["entries"]),
    "peak": peak[0] - start}
results = []
def one():
    results.append(search(600)["count"])
threads = [threading.Thread(target=one) for _ in range(2)]
[t.start() for t in threads]
[t.join() for t in threads]
out["concurrent"] = results
out["after"] = len(os.listdir(FD_DIR)) - start
print(json.dumps(out))
"""


def test_1500_directories_under_a_soft_fd_limit_of_256(tmp_path):
    base = tmp_path / "many"
    for index in range(1500):
        directory = base / f"d{index:04}"
        directory.mkdir(parents=True)
        (directory / "f.txt").write_text("NEEDLE\n")
    proc = subprocess.run(
        [sys.executable, "-c", SCALE, str(base), RG],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env={k: v for k, v in os.environ.items() if k != "RIPGREP_CONFIG_PATH"},
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    depth = len(base.parts)  # '/' plus every component down to d####
    assert out["soft"] == 256
    assert out["search"]["count"] == 1500
    assert out["glob"] == {**out["glob"], "count": 1500, "sized": 1500}
    assert out["concurrent"] == [1500, 1500]
    assert 0 < out["search"]["peak"] <= depth + 3
    assert 0 < out["glob"]["peak"] <= depth + 3
    assert out["after"] <= 0
