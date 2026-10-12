"""List mode omits a FIFO, a socket and a link to one on both paths (r6 W3 PX1b, R-PX1-4).

PX1 5/5 made Linux list mode omit special entries, as Darwin always did, but
no test pinned it (mutant M-OWN-4, "if info is None:", survived: a FIFO was
listed as a 0-byte file). Each case runs the Linux path (file_access=None) and
the Darwin path (FileToolAccess over DarwinFileAccess, built directly) on the
same tree and requires the same result. Every case runs on both OSes.
"""

import os
import shutil
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.features.files import paths
from binnacle.features.files.tools import list_files as lf
from binnacle.platform.contracts.capability_contracts import Capability, CapabilityState
from binnacle.platform.darwin.file_access import DarwinFileAccess

PATHS = pytest.mark.parametrize(
    "darwin", [False, True], ids=["linux_path", "darwin_path"]
)


@pytest.fixture
def root() -> Iterator[Path]:
    # A short /tmp path: an AF_UNIX socket path is limited to 104 bytes on Darwin.
    base = Path(tempfile.mkdtemp(prefix="px1b-sp-", dir="/tmp")).resolve()
    (base / "sub").mkdir()
    (base / "a.txt").write_text("alpha\n")
    os.mkfifo(base / "fifo")
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(base / "sock"))
    (base / "to_fifo").symlink_to("fifo")
    (base / "to_sock").symlink_to("sock")
    try:
        yield base
    finally:
        server.close()
        shutil.rmtree(base)


def listed(root: Path, darwin: bool, include_hidden: bool = False) -> dict:
    roots = RootsSettings(default_root=root, extra_roots=())
    access = None
    if darwin:
        access = paths.FileToolAccess(
            roots=roots,
            files=DarwinFileAccess(),
            search=None,
            generation="r6w3-px1b",
            capability=Capability(CapabilityState.LIMITED, "test_only", "px1b"),
        )
    try:
        result = lf.list_files_impl(
            str(root), None, 100, include_hidden, roots=roots, file_access=access
        )
    finally:
        if access is not None:
            access.close()
    text = getattr(result.content[0], "text", "")
    return {"text": text, **(result.structured_content or {})}


@PATHS
@pytest.mark.timeout(20)
def test_list_mode_omits_a_fifo_a_socket_and_links_to_them(root, darwin):
    assert listed(root, darwin) == {
        "text": f"Listed 2 entries in {root}.",
        "path": str(root),
        "mode": "list",
        "entries": [
            {"path": str(root / "sub"), "type": "dir"},
            {"path": str(root / "a.txt"), "type": "file", "bytes": 6},
        ],
        "count": 2,
        "truncated": False,
    }


@PATHS
@pytest.mark.timeout(20)
def test_omitted_special_entries_do_not_count_toward_truncation(root, darwin):
    roots = RootsSettings(default_root=root, extra_roots=())
    access = None
    if darwin:
        access = paths.FileToolAccess(
            roots=roots,
            files=DarwinFileAccess(),
            search=None,
            generation="r6w3-px1b",
            capability=Capability(CapabilityState.LIMITED, "test_only", "px1b"),
        )
    try:
        result = lf.list_files_impl(
            str(root), None, 2, False, roots=roots, file_access=access
        )
    finally:
        if access is not None:
            access.close()
    payload = result.structured_content
    assert (payload["count"], payload["truncated"]) == (2, False)
    assert "note" not in payload
