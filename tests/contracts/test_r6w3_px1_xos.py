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
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
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
GOLDEN_SHA256 = "bfe548aaea0bdfc7359358aeb4416d5a2c02cd34b0ef67161502ebcb71f5c31e"

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
                "links": {"link_b": "sub/b.txt", "link_g": "x/y/g.txt"},
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
    assert errors == {
        "glob_fifo": "special_file_unsupported",
        "glob_root_exec_only": denied,
        "list_fifo": "special_file_unsupported",
        "list_root_exec_only": denied,
        "list_x_exec_only": denied,
        "read_fifo": "special_file_unsupported",
        "read_missing": "file_not_found",
        "search_fifo": "special_file_unsupported",
        "search_root_exec_only": denied,
    }


if __name__ == "__main__":

    def _set(target: Any, name: str, value: Any) -> None:
        setattr(target, name, value)

    sys.stdout.write(dump(document(_set)))
