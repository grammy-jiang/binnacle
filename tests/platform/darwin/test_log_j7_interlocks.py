"""Actual cross-process J7 flock compatibility, isolated to test-owned dirs."""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from binnacle.companions.darwin_log_j7_interlocks import (
    J7InterlockBusy,
    J7InterlockRefused,
    J7Interlocks,
)


@pytest.fixture
def state(tmp_path: Path) -> Path:
    root = tmp_path / "binnacle"
    root.mkdir(mode=0o700)
    (root / "j7").mkdir(mode=0o700)
    root.chmod(0o700)
    (root / "j7").chmod(0o700)
    return root


def test_both_fixed_j7_locks_are_exclusive_and_private(state: Path) -> None:
    with J7Interlocks(state) as held:
        held.verify()
        for file in (state / "mac-deploy-gate.lock", state / "j7/jobs-service.lock"):
            assert file.is_file()
            assert file.stat().st_uid == os.getuid()
            assert file.stat().st_nlink == 1
            assert file.stat().st_mode & 0o777 == 0o600
            with file.open("r+b") as competing, pytest.raises(BlockingIOError):
                fcntl.flock(competing.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    with J7Interlocks(state):
        pass  # Closing without flock(LOCK_UN) released both locks.


def test_no_extra_lock_name_or_service_mutation(state: Path) -> None:
    with J7Interlocks(state):
        assert sorted(p.name for p in state.iterdir()) == [
            "j7",
            "mac-deploy-gate.lock",
        ]
        assert [p.name for p in (state / "j7").iterdir()] == ["jobs-service.lock"]


@pytest.mark.parametrize("target", ["mac-deploy-gate.lock", "j7/jobs-service.lock"])
def test_contention_with_real_j7_flock_refuses_without_stopping_services(
    state: Path, target: str
) -> None:
    p = state / target
    p.write_bytes(b"existing J7 lease marker")
    p.chmod(0o600)
    with p.open("r+b") as fd:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (
            pytest.raises(J7InterlockBusy, match="another J7 writer"),
            J7Interlocks(state),
        ):
            pytest.fail("must not acquire a busy J7 lock")
        assert p.read_bytes() == b"existing J7 lease marker"
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    with J7Interlocks(state):
        pass


@pytest.mark.parametrize("target", ["mac-deploy-gate.lock", "j7/jobs-service.lock"])
def test_existing_lock_bytes_and_inode_are_preserved(state: Path, target: str):
    p = state / target
    p.write_bytes(b"j7 original exact data")
    p.chmod(0o600)
    before = p.stat()
    with J7Interlocks(state):
        assert p.read_bytes() == b"j7 original exact data"
        after = p.stat()
        assert after.st_ino == before.st_ino
    assert p.read_bytes() == b"j7 original exact data"


@pytest.mark.parametrize("target", ["mac-deploy-gate.lock", "j7/jobs-service.lock"])
@pytest.mark.parametrize(
    "violation", ["symlink", "hardlink", "public_mode", "directory"]
)
def test_unsafe_existing_lock_refused_without_overwrite(
    state: Path, target: str, violation: str
) -> None:
    p = state / target
    if violation == "directory":
        p.mkdir()
    else:
        source = state / "protected.data"
        source.write_bytes(b"preserve me")
        source.chmod(0o600)
        if violation == "symlink":
            p.symlink_to(source)
        elif violation == "hardlink":
            os.link(source, p)
        else:
            p.write_bytes(b"preserve me")
            p.chmod(0o644)
    with pytest.raises(J7InterlockRefused), J7Interlocks(state):
        pytest.fail("must not enter with a bad existing lock")
    assert p.exists()
    if violation != "directory":
        assert (p.stat().st_mode & 0o777) == (
            0o644 if violation == "public_mode" else 0o600
        )
        assert p.read_bytes() == b"preserve me"


@pytest.mark.parametrize("where", ["root", "j7"])
def test_public_state_directory_is_not_accepted(state: Path, where: str) -> None:
    bad = state if where == "root" else state / "j7"
    bad.chmod(0o777 if where == "root" else 0o755)
    try:
        with (
            pytest.raises(J7InterlockRefused, match="(owned|private)"),
            J7Interlocks(state),
        ):
            pytest.fail("not a safe J7 state")
    finally:
        bad.chmod(0o700)


def test_symlinked_j7_directory_refuses(state: Path) -> None:
    (state / "j7").rename(state / "real-j7")
    (state / "j7").symlink_to(state / "real-j7", target_is_directory=True)
    with pytest.raises(J7InterlockRefused), J7Interlocks(state):
        pytest.fail("must not follow a J7 link")


def test_symlinked_state_root_refuses(state: Path) -> None:
    previous = state.with_name("previous-state")
    state.rename(previous)
    state.symlink_to(previous, target_is_directory=True)
    with pytest.raises(J7InterlockRefused), J7Interlocks(state):
        pytest.fail("must not accept a symlinked root")


@pytest.mark.parametrize("target", ["mac-deploy-gate.lock", "j7/jobs-service.lock"])
def test_name_swap_during_held_lock_refuses(state: Path, target: str) -> None:
    with J7Interlocks(state) as held:
        p = state / target
        old = p.with_suffix(".old")
        p.rename(old)
        p.write_bytes(b"replacement")
        p.chmod(0o600)
        with pytest.raises(J7InterlockRefused, match="replaced"):
            held.verify()
        assert old.is_file()


def test_j7_subdirectory_swap_during_held_lease_refuses(state: Path) -> None:
    with J7Interlocks(state) as held:
        (state / "j7").rename(state / "old-j7")
        (state / "j7").mkdir(mode=0o700)
        with pytest.raises(J7InterlockRefused, match="replaced"):
            held.verify()


def test_state_root_swap_during_held_lease_refuses(state: Path) -> None:
    with J7Interlocks(state) as held:
        state.rename(state.with_name("old-binnacle"))
        state.mkdir(mode=0o700)
        with pytest.raises(J7InterlockRefused, match="root identity changed"):
            held.verify()


def test_nesting_and_post_release_verification_refuse(state: Path) -> None:
    hold = J7Interlocks(state)
    with hold, pytest.raises(J7InterlockRefused, match="nested"):
        hold.__enter__()
    with pytest.raises(J7InterlockRefused, match="owner generation"):
        hold.verify()
    with hold:
        hold.verify()


def test_wrong_process_identity_cannot_prove_lease(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.getpid
    with J7Interlocks(state) as held:
        monkeypatch.setattr(
            "binnacle.companions.darwin_log_j7_interlocks.os.getpid", lambda: real() + 1
        )
        with pytest.raises(J7InterlockRefused, match="owner generation"):
            held.verify()


def test_foreign_owner_does_not_count_as_a_j7_lock(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.getuid
    monkeypatch.setattr(
        "binnacle.companions.darwin_log_j7_interlocks.os.getuid", lambda: real() + 1
    )
    with pytest.raises(J7InterlockRefused, match="owned"), J7Interlocks(state):
        pytest.fail("must not pretend to own another user directory")


def test_relative_state_root_refuses_without_creation(tmp_path: Path) -> None:
    with (
        pytest.raises(J7InterlockRefused, match="absolute"),
        J7Interlocks(Path("relative-private-root")),
    ):
        pytest.fail("relative path would depend on changing cwd")
    assert not (tmp_path / "relative-private-root").exists()


def test_missing_j7_dir_is_not_created(state: Path) -> None:
    (state / "j7").rmdir()
    with pytest.raises(J7InterlockRefused, match="unavailable"), J7Interlocks(state):
        pytest.fail("missing J7 directory must refuse")
    assert not (state / "mac-deploy-gate.lock").exists()


def test_other_process_holds_both_locks_until_owner_exits(state: Path) -> None:
    script = (
        "import fcntl,os,sys,time;"
        "f=open(sys.argv[1],'r+b');fcntl.flock(f.fileno(),fcntl.LOCK_EX);"
        "open(sys.argv[2],'w').write('ready');"
        "time.sleep(15)"
    )
    (state / "j7/jobs-service.lock").touch(mode=0o600)
    sentinel = state / "competitor.ready"
    p = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(state / "j7/jobs-service.lock"),
            str(sentinel),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        limit = time.monotonic() + 5
        while not sentinel.exists() and time.monotonic() < limit:
            time.sleep(0.025)
        assert sentinel.exists(), "independent process never acquired flock"
        with pytest.raises(J7InterlockBusy), J7Interlocks(state):
            pytest.fail("must not proceed while foreign process owns J7 lock")
    finally:
        p.terminate()
        p.wait(timeout=8)
    with J7Interlocks(state):
        pass


def test_existing_j7_root_mode_0755_is_safe_but_never_writable(state: Path) -> None:
    # Production Binnacle's outer state root is listable (0755), but
    # the J7 child is 0700 and the lock files are strictly 0600.
    state.chmod(0o755)
    with J7Interlocks(state) as held:
        held.verify()
        assert (state / "mac-deploy-gate.lock").stat().st_mode & 0o777 == 0o600
    state.chmod(0o775)
    try:
        with pytest.raises(J7InterlockRefused, match="owned"), J7Interlocks(state):
            pytest.fail("group-writable root enables pathname replacement")
    finally:
        state.chmod(0o700)
