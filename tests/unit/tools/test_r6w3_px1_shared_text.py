"""One special-file text and one too_many_open_files text everywhere (r6 W3 PX1 2/5).

Every file and search tool (read_file, edit_file, write_file, list_files in
list and glob mode, search_text) refuses a FIFO or a socket with the code and
text of platform/contracts/special_file_contracts.py, on the Linux path
(file_access=None) and on the Darwin path (FileToolAccess over
DarwinFileAccess and DarwinSearchAccess). Every descriptor-shortage refusal
is built from the one TOO_MANY_OPEN_FILES_TEXT template. Every case runs on
both OSes; none is skipped.
"""

import errno
import os
import shutil
import socket
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.config import RootsSettings
from binnacle.features.files import list_files_glob, paths
from binnacle.features.files.tools import edit_file as ef
from binnacle.features.files.tools import list_files as lf
from binnacle.features.files.tools import read_file as rf
from binnacle.features.files.tools import write_file as wf
from binnacle.features.search import search_text_verify
from binnacle.features.search.fd_chain import DirectoryChain
from binnacle.features.search.tools import search_text as st
from binnacle.platform.composition import create_search_access
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.contracts.special_file_contracts import (
    SPECIAL_FILE_CODE,
    SPECIAL_FILE_TEXT,
    TOO_MANY_OPEN_FILES_CODE,
    TOO_MANY_OPEN_FILES_TEXT,
    too_many_open_files_text,
)
from binnacle.platform.darwin.file_access import DarwinFileAccess

RG = shutil.which("rg") or "rg"
TOOLS: dict[str, Callable] = {
    "read_file": lambda p, r, a: rf.read_file_impl(p, 1, None, roots=r, file_access=a),
    "edit_file": lambda p, r, a: ef.edit_file_impl(
        p, "x", "y", False, roots=r, file_access=a
    ),
    "write_file": lambda p, r, a: wf.write_file_impl(
        p, "new\n", roots=r, file_access=a
    ),
    "list_files": lambda p, r, a: lf.list_files_impl(
        p, None, 50, False, roots=r, file_access=a, rg_bin=RG
    ),
    "list_files_glob": lambda p, r, a: lf.list_files_impl(
        p, "*", 50, False, roots=r, file_access=a, rg_bin=RG
    ),
    "search_text": lambda p, r, a: st.search_text_impl(
        "needle",
        p,
        None,
        True,
        None,
        False,
        50,
        True,
        roots=r,
        file_access=a,
        rg_bin=RG,
    ),
}


@pytest.fixture
def root() -> Iterator[Path]:
    # A short /tmp path: an AF_UNIX socket path is limited to 104 bytes on Darwin.
    base = Path(tempfile.mkdtemp(prefix="r6w3-px1-", dir="/tmp")).resolve()
    os.mkfifo(base / "fifo")
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(base / "sock"))
    try:
        yield base
    finally:
        server.close()
        shutil.rmtree(base)


def refusal(tool: str, path: Path, root: Path, darwin: bool) -> tuple:
    roots = RootsSettings(default_root=root, extra_roots=())
    access = None
    if darwin:
        files = DarwinFileAccess()
        access = paths.FileToolAccess(
            roots=roots,
            files=files,
            search=create_search_access(files=files, rg_bin=RG),
            generation="r6w3-px1",
            capability=Capability(CapabilityState.LIMITED, "test_only", "px1"),
        )
    try:
        with pytest.raises(ToolError) as exc:
            TOOLS[tool](str(path), roots, access)
    finally:
        if access is not None:
            access.close()
    return getattr(exc.value, "telemetry_code", None), str(exc.value)


@pytest.mark.timeout(20)
@pytest.mark.parametrize("darwin", [False, True], ids=["linux_path", "darwin_path"])
@pytest.mark.parametrize("kind", ["fifo", "sock"])
@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_every_tool_refuses_a_special_file_with_the_shared_text(
    root, tool, kind, darwin
):
    assert refusal(tool, root / kind, root, darwin) == (
        SPECIAL_FILE_CODE,
        SPECIAL_FILE_TEXT,
    )


def test_a_write_never_replaces_a_special_file(root):
    for darwin in (False, True):
        refusal("write_file", root / "fifo", root, darwin)
        assert (root / "fifo").exists() and not (root / "fifo").is_file()


# too_many_open_files: one template, filled in per tool and task.


def test_the_template_is_one_constant():
    assert TOO_MANY_OPEN_FILES_CODE == "too_many_open_files"
    assert too_many_open_files_text("t", "do x", "Retry.") == (
        TOO_MANY_OPEN_FILES_TEXT.format(tool="t", task="do x", advice="Retry.")
    )
    assert too_many_open_files_text("t", "do x") == (
        "t could not do x: the server has too many open files. Retry."
    )


def test_list_mode_shortage_uses_the_template(root):
    exc = OSError(errno.EMFILE, os.strerror(errno.EMFILE))
    refused = lf._refusal(exc, root)
    assert (refused.telemetry_code, str(refused)) == (
        TOO_MANY_OPEN_FILES_CODE,
        too_many_open_files_text("list_files", f"open {root}"),
    )
    assert str(refused) == (
        f"list_files could not open {root}: the server has too many open files. Retry."
    )


def test_glob_shortage_uses_the_template():
    refused = list_files_glob.descriptor_shortage(
        "check the listed files", "Retry, or narrow the glob."
    )
    assert (refused.telemetry_code, str(refused)) == (
        TOO_MANY_OPEN_FILES_CODE,
        (
            "list_files could not check the listed files: the server has too many "
            "open files. Retry, or narrow the glob."
        ),
    )


def test_search_shortage_uses_the_template(root, monkeypatch):
    def exhausted(self, parts):
        raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))

    monkeypatch.setattr(DirectoryChain, "directory", exhausted)
    with DirectoryChain() as chain, pytest.raises(ToolError) as exc:
        search_text_verify.is_regular(chain, [*str(root)[1:].split("/"), "fifo"])
    assert (exc.value.telemetry_code, str(exc.value)) == (
        TOO_MANY_OPEN_FILES_CODE,
        too_many_open_files_text(
            "search_text", "check the reported files", "Retry, or narrow the search."
        ),
    )
