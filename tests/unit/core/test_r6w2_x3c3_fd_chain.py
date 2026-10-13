"""DirectoryChain keeps only the current chain open (r6 W2 X3c-a3, SD-78)."""

import errno
import os
from pathlib import Path

import pytest

from binnacle.features.files import fd_chain
from binnacle.features.files.fd_chain import DirectoryChain

# The process descriptor table: /proc/self/fd on Linux, /dev/fd on Darwin.
FD_DIR = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"


def open_fds() -> int:
    return len(os.listdir(FD_DIR))


def parts(path: Path) -> tuple[str, ...]:
    return path.parts[1:]


def test_the_chain_is_bounded_by_the_path_depth(tmp_path):
    for index in range(50):
        (tmp_path / f"d{index}" / "e").mkdir(parents=True)
    before = open_fds()
    depth = len(parts(tmp_path)) + 2
    with DirectoryChain() as chain:
        for index in range(50):
            chain.directory(parts(tmp_path / f"d{index}" / "e"))
            assert open_fds() - before <= depth + 1
        chain.directory(parts(tmp_path))
        assert open_fds() - before == len(parts(tmp_path)) + 1
    assert open_fds() == before


def test_a_common_prefix_is_reused_and_the_rest_is_closed(tmp_path, monkeypatch):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "c").mkdir()
    opened: list[str] = []
    real_open = os.open

    def counting_open(name, flags, *args, **kw):
        opened.append(name)
        return real_open(name, flags, *args, **kw)

    with DirectoryChain() as chain:
        chain.directory(parts(tmp_path / "a" / "b"))
        monkeypatch.setattr(fd_chain.os, "open", counting_open)
        chain.directory(parts(tmp_path / "a" / "b"))
        assert opened == []
        chain.directory(parts(tmp_path / "c"))
        assert opened == ["c"]


def test_a_symlink_component_is_refused(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with DirectoryChain() as chain:
        with pytest.raises(OSError) as info:
            chain.directory(parts(tmp_path / "link"))
        assert info.value.errno in (errno.ELOOP, errno.ENOTDIR)
        # The chain stays usable after a refusal.
        chain.directory(parts(tmp_path / "real"))


def test_a_descriptor_shortage_closes_the_chain_and_retries_once(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    real_open = os.open
    failures = [OSError(errno.EMFILE, "Too many open files")]

    def flaky_open(name, flags, *args, **kw):
        if name == "a" and failures:
            raise failures.pop()
        return real_open(name, flags, *args, **kw)

    monkeypatch.setattr(fd_chain.os, "open", flaky_open)
    before = open_fds()
    with DirectoryChain() as chain:
        assert chain.directory(parts(tmp_path / "a")) >= 0
    assert open_fds() == before

    failures[:] = [OSError(errno.EMFILE, "x"), OSError(errno.EMFILE, "x")]
    with DirectoryChain() as chain, pytest.raises(OSError) as info:
        chain.directory(parts(tmp_path / "a"))
    assert info.value.errno == errno.EMFILE
    assert open_fds() == before
