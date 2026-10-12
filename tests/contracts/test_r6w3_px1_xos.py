"""Cross-OS exec-only fixture, byte for byte (r6 W3 PX1 5/5; was XOS-exec-only-fixture.py).

Builds a NON-secret fixture under /tmp/r6w3-px1-xos-*, whose configured ROOT
is execute-only (0o100) and which holds execute-only in-root directories. It
runs list_files (list and glob), read_file and search_text through the
production tool implementations, composed as each host's production server
composes them:

* Darwin: FileToolAccess over platform.composition.create_file_access() and
  create_search_access() (DarwinFileAccess + DarwinSearchAccess), with the
  production DARWIN_RELEASE_SCOPE file-tool capabilities.
* Linux: file_access=None (the Linux pathname/fd_walk path), exactly as
  server.create_server() does on Linux.

Settings are explicit model defaults with the fixture root as the only root;
get_settings is patched to raise, to prove it is never reached. The document
is canonical JSON (sorted keys; the fixture root replaced by <ROOT>; timing
fields dropped). The one deliberate OS difference is Darwin's code
permission_denied_tcc_possible where Linux says permission_denied (SD-77);
the texts are equal. The test normalizes that code and pins the SHA-256 of
the normalized document, so it passes on both OSes only if they agree byte
for byte. Run as a script, it prints the raw document for QA:

    .venv/bin/python tests/contracts/test_r6w3_px1_xos.py > XOS-<host>.json

Cases added by PX1: in-root links (R-OS1-F3, read_link_*), unreadable
children (F1/F4, glob/search_mix_*), the shared special-file text
(*_fifo), and a glob entry that vanished before its stat (PF-SP1-2,
glob_vanished_entry).

Cases added by PX1b (PF-PX1-1, R-PX1-4): list_files (list and glob) and
search_text on a path that is, or passes through, an in-root symlink, in
<ROOT>/lnk: relative, absolute and chained link text, a link on the way
(ancestor), absolute and root-relative requests, an outside target, a
dangling link and a loop (lnk_*); and a listing that omits a link to a FIFO
and the dangling, looping and outside links (list_lnk).

Cases added by FDW-B1 and FDW-B1-a2 (SD-91, fdw_*; FDW_CASES): a hook at
os.open swaps a file at its final open, or fails an open with EMFILE.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from binnacle.config import (
    ListFilesSettings,
    ReadFileSettings,
    RootsSettings,
    SearchTextSettings,
)
from binnacle.errors import CodedToolError
from binnacle.features.files.paths import FileToolAccess
from binnacle.features.files.tools.list_files import list_files_impl
from binnacle.features.files.tools.read_file import read_file_impl
from binnacle.features.search.tools.search_text import search_text_impl
from binnacle.platform.composition import (
    create_file_access,
    create_search_access,
    host_os_family,
)

SCHEMA = "r6w3-px1-xos/1"
TIMING_WORDS = ("elapsed", "duration", "latency", "_ms", "seconds", "timing")
MTIME = 1_700_000_000  # Fixed mtimes: glob mode orders newest first.
TCC_CODE, LINUX_CODE = "permission_denied_tcc_possible", "permission_denied"
# SHA-256 of the normalized document; equal on Linux and Darwin by design.
GOLDEN_SHA256 = "f66a3061b6561037d49be8d240c7a8c89f4b9a035f10322cb64c0b059fc7db12"

FILES = {
    "a.txt": ("alpha needle\n", 500),
    "sub/b.txt": ("beta needle\nsecond line\n", 400),
    "sub/c.py": ("needle = 1\n", 300),
    "sub/.hidden.txt": ("hidden needle\n", 250),
    "x/y/g.txt": ("gamma needle\n", 200),
    "x/y/h.md": ("no match here\n", 100),
    "mix/m.txt": ("mix needle\n", 150),
    "mix/x2/y2/k.txt": ("kappa needle\n", 50),
    "van/keep.txt": ("keep needle\n", 40),
    "van/gone.txt": ("gone needle\n", 30),
    "lnk/t/f.txt": ("link needle\n", 20),
    "lnk/t/u/v.txt": ("deep link needle\n", 10),
    "fdw/swap_regular.txt": ("swap\n", 5),
    "fdw/swap_fifo.txt": ("swap\n", 5),
    "fdw/swap_dir.txt": ("swap\n", 5),
}
# fdw_* case: (tool, path below <ROOT>, os.open name hooked, hook, times).
# A swap hook replaces the file by another regular file, a FIFO or a
# directory (check order: type, then identity); "shortage" fails with EMFILE
# in the read, the listed directory or the link walk (to_fifo opens sub).
FDW_CASES = {
    "fdw_read_swap_regular": ("read", "fdw/swap_regular.txt", None, "regular", 1),
    "fdw_read_swap_fifo": ("read", "fdw/swap_fifo.txt", None, "fifo", 1),
    "fdw_read_swap_dir": ("read", "fdw/swap_dir.txt", None, "dir", 1),
    "fdw_read_shortage": ("read", "a.txt", None, "shortage", None),
    "fdw_list_shortage_once": ("list", "sub", None, "shortage", 1),
    "fdw_list_shortage_twice": ("list", "sub", None, "shortage", None),
    "fdw_list_link_walk_shortage_once": ("list", "lnk", "sub", "shortage", 1),
    "fdw_list_link_walk_shortage_twice": ("list", "lnk", "sub", "shortage", None),
}
# In-root links below <ROOT>/lnk (PF-PX1-1); "<ROOT>" and "<BASE>" are
# filled in by build(). <BASE>/out is outside every root.
LINKS = {
    "lnk/dir_rel": "t",
    "lnk/dir_abs": "<ROOT>/lnk/t",
    "lnk/chain": "dir_rel",
    "lnk/out": "<BASE>/out",
    "lnk/dangling": "nope",
    "lnk/loop": "loop",
    "lnk/to_fifo": "../sub/fifo",
}
# In-root x/ and mix/x2/ first, then the ROOT itself (""); mix/ stays readable.
EXEC_ONLY = ("x", "mix/x2", "")
VANISHED = "gone.txt"  # Its no-follow stat sees ENOENT (PF-SP1-2).


def _no_settings(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("get_settings reached: the fixture must not read config")


def build(base: Path) -> Path:
    root = base / "root"
    for rel, (text, age) in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        os.utime(path, (MTIME + age, MTIME + age))
    (root / "link_b").symlink_to("sub/b.txt")
    (root / "link_g").symlink_to("x/y/g.txt")
    os.mkfifo(root / "sub" / "fifo")
    (base / "out").mkdir()
    (base / "out" / "o.txt").write_text("outside needle\n", encoding="utf-8")
    for rel, text in LINKS.items():
        target = text.replace("<ROOT>", str(root)).replace("<BASE>", str(base))
        (root / rel).symlink_to(target)
    for rel in EXEC_ONLY:
        (root / rel).chmod(0o100) if rel else root.chmod(0o100)
    return root


def teardown(base: Path) -> None:
    root = base / "root"
    for rel in reversed(EXEC_ONLY):
        target = root / rel if rel else root
        if target.exists() or target.is_symlink():
            target.chmod(0o700)
    shutil.rmtree(base)


def scrub(value: Any, root: str, base: str, dropped: set[str]) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if any(word in key.lower() for word in TIMING_WORDS):
                dropped.add(key)
                continue
            out[key] = scrub(item, root, base, dropped)
        return out
    if isinstance(value, list | tuple):
        return [scrub(item, root, base, dropped) for item in value]
    if isinstance(value, str):
        return value.replace(root, "<ROOT>").replace(base, "<BASE>")
    return value


def run(call: Callable[[], Any]) -> dict:
    try:
        result = call()
    except CodedToolError as exc:
        return {"error": {"code": exc.telemetry_code, "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001 - recorded, compared across hosts
        return {"error": {"type": type(exc).__name__, "message": str(exc)}}
    texts = [getattr(block, "text", None) for block in result.content]
    return {"ok": {"content": texts, "structured": result.structured_content}}


def _vanishing(stat_call: Callable[..., Any]) -> Callable[..., Any]:
    """os.stat/os.lstat that see VANISHED gone, for a descriptor-relative call."""

    def call(path: Any, *args: Any, **kwargs: Any) -> Any:
        if os.fspath(path) == VANISHED and kwargs.get("dir_fd") is not None:
            raise FileNotFoundError(2, "vanished", path)
        return stat_call(path, *args, **kwargs)

    return call


def _fdw_open(target: Path, name: str, hook: str, times: int | None) -> Any:
    """os.open that runs hook before opening name relative to a dir_fd."""
    real_open, fired = os.open, list[str]()

    def call(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        wanted = path == name and kwargs.get("dir_fd") is not None
        if wanted and (times is None or len(fired) < times):
            fired.append(path)
            if hook == "shortage":
                raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))
            target.rename(target.with_name(name + ".kept"))  # Keeps the inode.
            if hook == "regular":
                target.write_text("swapped in\n", encoding="utf-8")
            elif hook == "fifo":
                os.mkfifo(target)
            else:
                target.mkdir()
        return real_open(path, flags, *args, **kwargs)

    return call


def document(set_attr: Callable[[Any, str, Any], None]) -> dict:
    """Run every case; set_attr patches (monkeypatch.setattr or setattr)."""
    rg_bin = shutil.which("rg") or "rg"
    base = Path(tempfile.mkdtemp(prefix="r6w3-px1-xos-", dir="/tmp")).resolve()
    try:
        root = build(base)
        roots = RootsSettings(default_root=root, extra_roots=())
        list_settings = ListFilesSettings()
        read_settings = ReadFileSettings()
        search_settings = SearchTextSettings()
        for name, module in list(sys.modules.items()):
            if name.startswith("binnacle") and hasattr(module, "get_settings"):
                set_attr(module, "get_settings", _no_settings)
        access = None
        files = create_file_access()
        if files is not None:  # Darwin production composition.
            from binnacle.platform.contracts.darwin_release_scope import (
                DARWIN_RELEASE_SCOPE,
                FILE_TOOLS,
            )

            rows = {tool: DARWIN_RELEASE_SCOPE[tool].capability for tool in FILE_TOOLS}
            access = FileToolAccess(
                roots=roots,
                files=files,
                search=create_search_access(files=files, rg_bin=rg_bin),
                generation="r6w3-px1-xos",
                capability=rows["read_file"],
                capabilities=rows,
            )
        r = str(root)

        def lst(path: str, glob: str | None = None, hidden: bool = False) -> dict:
            return run(
                lambda: list_files_impl(
                    path,
                    glob,
                    100,
                    hidden,
                    roots=roots,
                    file_access=access,
                    settings=list_settings,
                    rg_bin=rg_bin,
                )
            )

        def read(path: str) -> dict:
            return run(
                lambda: read_file_impl(
                    path,
                    1,
                    None,
                    roots=roots,
                    file_access=access,
                    settings=read_settings,
                )
            )

        def search(
            path: str, glob: str | None = None, names_only: bool = False
        ) -> dict:
            return run(
                lambda: search_text_impl(
                    "needle",
                    path,
                    glob,
                    True,
                    None,
                    names_only,
                    50,
                    True,
                    roots=roots,
                    file_access=access,
                    settings=search_settings,
                    rg_bin=rg_bin,
                )
            )

        def vanished() -> dict:
            with _Patch() as patch:
                patch(os, "lstat", _vanishing(os.lstat))
                patch(os, "stat", _vanishing(os.stat))
                return lst(f"{r}/van", "*.txt")

        cases: list[tuple[str, Callable[[], dict]]] = [
            ("list_root_exec_only", lambda: lst(r)),
            ("list_sub_readable", lambda: lst(f"{r}/sub")),
            ("list_sub_hidden", lambda: lst(f"{r}/sub", hidden=True)),
            ("list_x_exec_only", lambda: lst(f"{r}/x")),
            ("list_x_y_below_exec_only", lambda: lst(f"{r}/x/y")),
            ("glob_root_exec_only", lambda: lst(r, "*.txt")),
            ("glob_sub", lambda: lst(f"{r}/sub", "*.txt")),
            ("glob_x_y", lambda: lst(f"{r}/x/y", "**/*")),
            ("list_mix_with_exec_only_child", lambda: lst(f"{r}/mix")),
            ("glob_mix_over_exec_only_child", lambda: lst(f"{r}/mix", "**/*.txt")),
            ("list_mix_x2_y2", lambda: lst(f"{r}/mix/x2/y2")),
            ("read_a_in_exec_only_root", lambda: read(f"{r}/a.txt")),
            ("read_sub_b", lambda: read(f"{r}/sub/b.txt")),
            ("read_x_y_g", lambda: read(f"{r}/x/y/g.txt")),
            ("read_link_b", lambda: read(f"{r}/link_b")),
            ("read_link_g", lambda: read(f"{r}/link_g")),
            ("read_missing", lambda: read(f"{r}/x/missing.txt")),
            ("search_root_exec_only", lambda: search(r)),
            ("search_sub", lambda: search(f"{r}/sub")),
            ("search_sub_glob_py", lambda: search(f"{r}/sub", "*.py")),
            ("search_x_y", lambda: search(f"{r}/x/y")),
            ("search_x_y_names_only", lambda: search(f"{r}/x/y", names_only=True)),
            ("search_mix_over_exec_only_child", lambda: search(f"{r}/mix")),
            ("search_mix_x2_y2", lambda: search(f"{r}/mix/x2/y2")),
            ("read_mix_x2_y2_k", lambda: read(f"{r}/mix/x2/y2/k.txt")),
            ("search_file_a", lambda: search(f"{r}/a.txt")),
            ("search_file_x_y_g", lambda: search(f"{r}/x/y/g.txt")),
            ("read_fifo", lambda: read(f"{r}/sub/fifo")),
            ("list_fifo", lambda: lst(f"{r}/sub/fifo")),
            ("glob_fifo", lambda: lst(f"{r}/sub/fifo", "*")),
            ("search_fifo", lambda: search(f"{r}/sub/fifo")),
            ("glob_vanished_entry", vanished),
            ("list_lnk", lambda: lst(f"{r}/lnk")),
        ]

        def fdw(tool: str, rel: str, name: str | None, hook: str, times: Any) -> Any:
            def case() -> dict:
                target = root / rel
                with _Patch() as patch:
                    patch(
                        os, "open", _fdw_open(target, name or target.name, hook, times)
                    )
                    return (read if tool == "read" else lst)(str(target))

            return case

        cases += [(label, fdw(*spec)) for label, spec in FDW_CASES.items()]
        # PF-PX1-1: each request through a link, for all three modes.
        through_links = {
            "dir_rel": f"{r}/lnk/dir_rel",
            "dir_abs": f"{r}/lnk/dir_abs",
            "chain": f"{r}/lnk/chain",
            "ancestor": f"{r}/lnk/dir_rel/u",
            "ancestor_chain": f"{r}/lnk/chain/u",
            "relative_request": "lnk/dir_rel",
            "relative_ancestor": "lnk/chain/u",
            "file_through_link": f"{r}/lnk/dir_abs/f.txt",
            "outside": f"{r}/lnk/out",
            "outside_below": f"{r}/lnk/out/o.txt",
            "dangling": f"{r}/lnk/dangling",
            "dangling_below": f"{r}/lnk/dangling/x",
            "loop": f"{r}/lnk/loop",
            "loop_below": f"{r}/lnk/loop/x",
        }
        for label, path in through_links.items():
            cases += [
                (f"lnk_list_{label}", partial(lst, path)),
                (f"lnk_glob_{label}", partial(lst, path, "**/*.txt")),
                (f"lnk_search_{label}", partial(search, path)),
            ]
        dropped: set[str] = set()
        try:
            results = {
                name: scrub(case(), r, str(base), dropped) for name, case in cases
            }
        finally:
            if access is not None:
                access.close()
        return {
            "fixture": {
                "exec_only": ["<ROOT>/x", "<ROOT>/mix/x2", "<ROOT>"],
                "files": {k: v[0] for k, v in FILES.items()},
                "links": {
                    "link_b": "sub/b.txt",
                    "link_g": "x/y/g.txt",
                    **{f"<ROOT>/{k}": v for k, v in LINKS.items()},
                },
                "fifo": "<ROOT>/sub/fifo",
                "vanished": f"<ROOT>/van/{VANISHED}",
            },
            "results": results,
            "schema": SCHEMA,
        }
    finally:
        teardown(base)


class _Patch:
    """setattr with restore, for one case inside the document run."""

    def __enter__(self) -> Callable[[Any, str, Any], None]:
        self._saved: list[tuple[Any, str, Any]] = []

        def patch(target: Any, name: str, value: Any) -> None:
            self._saved.append((target, name, getattr(target, name)))
            setattr(target, name, value)

        return patch

    def __exit__(self, *_exc: object) -> None:
        for target, name, value in reversed(self._saved):
            setattr(target, name, value)


def dump(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, indent=1) + "\n"


def normalized(doc: dict) -> dict:
    """The document with Darwin's deliberate TCC code read as Linux's."""
    results = {}
    for name, outcome in doc["results"].items():
        error = outcome.get("error")
        if error is not None and error.get("code") == TCC_CODE:
            outcome = {"error": {**error, "code": LINUX_CODE}}
        results[name] = outcome
    return {**doc, "results": results}


def test_the_xos_document_is_equal_on_both_oses(monkeypatch):
    if os.geteuid() == 0:  # pragma: no cover - root ignores modes; never in CI
        raise AssertionError("run as an unprivileged user: modes must apply")
    text = dump(normalized(document(monkeypatch.setattr)))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert digest == GOLDEN_SHA256, text


def test_the_only_os_difference_is_the_tcc_code(monkeypatch):
    doc = document(monkeypatch.setattr)
    errors = {
        name: outcome["error"]["code"]
        for name, outcome in doc["results"].items()
        if "error" in outcome
    }
    denied = LINUX_CODE if host_os_family() == "linux" else TCC_CODE
    missing = {
        "list": "directory_not_found",
        "glob": "directory_not_found",
        "search": "path_not_found",
    }
    assert errors == {
        # FDW-B1 + a2: the same refusals on both OSes (SD-91).
        "fdw_read_swap_regular": "path_changed",
        "fdw_read_swap_fifo": "special_file_unsupported",
        "fdw_read_swap_dir": "path_is_directory",
        "fdw_read_shortage": "too_many_open_files",
        "fdw_list_shortage_twice": "too_many_open_files",
        "fdw_list_link_walk_shortage_twice": "too_many_open_files",
        "glob_fifo": "special_file_unsupported",
        "glob_root_exec_only": denied,
        "list_fifo": "special_file_unsupported",
        "list_root_exec_only": denied,
        "list_x_exec_only": denied,
        "read_fifo": "special_file_unsupported",
        "read_missing": "file_not_found",
        "search_fifo": "special_file_unsupported",
        "search_root_exec_only": denied,
        # PF-PX1-1: the same code on both OSes through an in-root link.
        **{
            f"lnk_{mode}_{case}": code
            for mode in ("list", "glob", "search")
            for case, code in (
                ("dangling", missing[mode]),
                ("dangling_below", missing[mode]),
                ("loop", missing[mode]),
                ("loop_below", missing[mode]),
                ("outside", "path_outside_root"),
                ("outside_below", "path_outside_root"),
            )
        },
        "lnk_glob_file_through_link": "path_is_file",
        "lnk_list_file_through_link": "path_is_file",
    }


if __name__ == "__main__":

    def _set(target: Any, name: str, value: Any) -> None:
        setattr(target, name, value)

    sys.stdout.write(dump(document(_set)))
