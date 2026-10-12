"""Native/Linux descriptor-race cases introduced by FDW-B1-a3."""

from __future__ import annotations

import errno
import os
import shutil
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from binnacle.platform.contracts.special_file_contracts import (
    SPECIAL_FILE_CODE,
    SPECIAL_FILE_TEXT,
)
from tests.unit.tools.test_r6w3_fdwb1_a2_order import (
    PATHS,
    linux_read_path,
    no_reads,
    outcome,
    reading,
    swap_at_open,
)
from tests.unit.tools.test_r6w3_fdwb1_a2_order import (
    base as base,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.unit.tools.test_r6w3_fdwb1_a2_order import (
    patch as patch,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.unit.tools.test_r6w3_fdwb1_a2_order import (
    root as root,  # noqa: PLC0414 - pytest fixture re-export
)


def symlink_swap_in(path: Path) -> None:
    path.unlink()
    path.symlink_to("sub/f.txt")


def symlink_swap_out(path: Path) -> None:
    # The outside file is never opened; its path is checked only for error wording.
    path.unlink()
    path.symlink_to("../outside.txt")


def socket_swap(path: Path) -> None:
    """Place a closed AF_UNIX socket at the entry previously checked regular."""
    path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
        endpoint.bind(str(path))


@pytest.fixture
def socket_root() -> Iterator[Path]:
    # A socket path on Darwin is small; never put sockets in /tmp or a
    # production state directory. Teardown only the test-owned child.
    state = Path.home() / ".local/state/bt/fdwb1a3"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    made = Path(tempfile.mkdtemp(prefix="s-", dir=state))
    root = made / "r"
    root.mkdir()
    (root / "a.txt").write_text("original\\n")
    try:
        yield root
    finally:
        assert made.parent == state and made.is_dir()
        shutil.rmtree(made)


@PATHS
@pytest.mark.timeout(10)
def test_a_socket_swapped_after_the_stat_is_shared_special_file(
    socket_root, patch, darwin
):
    target = socket_root / "a.txt"
    if not darwin:
        linux_read_path(patch)
    fired = swap_at_open(patch, target, socket_swap)
    reads = no_reads(patch)
    assert outcome(socket_root, darwin, reading(target)) == (
        SPECIAL_FILE_CODE,
        SPECIAL_FILE_TEXT,
    )
    assert fired == ["a.txt"]
    assert reads == []


@pytest.mark.parametrize("darwin", [False, True], ids=["linux_path", "darwin_path"])
def test_a_regular_file_permission_denial_is_not_special_file(root, patch, darwin):
    target = root / "a.txt"
    if not darwin:
        linux_read_path(patch)
    real_open = os.open

    def denied(name, flags, *args, **kwargs):
        if name == "a.txt" and kwargs.get("dir_fd") is not None:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES))
        return real_open(name, flags, *args, **kwargs)

    patch.setattr(os, "open", denied)
    code, message = outcome(root, darwin, reading(target))
    assert code == ("permission_denied_tcc_possible" if darwin else "permission_denied")
    assert SPECIAL_FILE_TEXT not in message


@PATHS
@pytest.mark.timeout(10)
def test_a_new_in_root_symlink_is_not_followed_after_the_initial_resolve(
    root, patch, darwin
):
    target = root / "a.txt"
    if not darwin:
        linux_read_path(patch)
    fired = swap_at_open(patch, target, symlink_swap_in)
    reads = no_reads(patch)
    assert outcome(root, darwin, reading(target)) == (
        "path_changed",
        f"File changed while it was opened: {target}. Read it again.",
    )
    assert fired == [target.name]
    assert reads == []


@PATHS
@pytest.mark.timeout(10)
def test_a_new_outside_symlink_names_the_original_request_and_never_reads(
    root, patch, darwin
):
    target = root / "a.txt"
    (root.parent / "outside.txt").write_text("outside contents\\n")
    if not darwin:
        linux_read_path(patch)
    fired = swap_at_open(patch, target, symlink_swap_out)
    reads = no_reads(patch)
    assert outcome(root, darwin, reading(target)) == (
        "path_outside_root",
        f"Path outside allowed roots ({root}): {target}",
    )
    assert fired == [target.name]
    assert reads == []
