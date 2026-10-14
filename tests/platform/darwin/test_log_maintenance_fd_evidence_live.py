"""Linux-only disposable open-FD positive control (no production paths)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from binnacle.platform.darwin import log_maintenance_fd_evidence as evidence

_LSOF_LINUX = Path("/usr/bin/lsof")


@pytest.fixture
def fixture_files(tmp_path: Path):
    if not _LSOF_LINUX.is_file() or sys.platform != "linux":
        pytest.skip("isolated Linux lsof fixture only")
    source = tmp_path / "private-source.log"
    canary = tmp_path / "private-canary.tmp"
    source.write_bytes(b"test-owned source\n")
    canary.write_bytes(b"test-owned canary\n")
    source.chmod(0o600)
    canary.chmod(0o600)
    opened = os.open(canary, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        identity = os.fstat(opened)
        control = evidence.WritableCanary(
            canary,
            identity.st_dev,
            identity.st_ino,
            os.getpid(),
            opened,
        )
        source_info = source.stat()
        raw = evidence.FDIdentity(source, source_info.st_dev, source_info.st_ino)
        yield raw, control
    finally:
        os.close(opened)


def _lsof(raw: evidence.FDIdentity, canary: evidence.WritableCanary):
    argv = evidence.lsof_readonly_argv(raw, canary)
    assert argv[0] == "/usr/sbin/lsof"
    result = subprocess.run(
        [str(_LSOF_LINUX), *argv[1:]],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    return evidence.classify_lsof_census(
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
        source=raw,
        canary=canary,
    )


def test_real_lsof_sees_canary_even_without_an_open_source(
    fixture_files,
) -> None:
    source, canary = fixture_files
    observation = _lsof(source, canary)
    assert observation.diagnostic == "source_absent_or_scan_incomplete_advisory_only"
    assert observation.observed_writers == ()
    assert observation.observed_readers == ()
    assert observation.manual_review_required
    assert not observation.complete_privileged_fd_census
    assert not observation.production_authorized


def test_real_lsof_distinguishes_read_only_source_fd(
    fixture_files,
) -> None:
    source, canary = fixture_files
    src_fd = os.open(source.path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        result = _lsof(source, canary)
        assert (os.getpid(), src_fd) in result.observed_readers
        assert not result.observed_writers
        assert result.diagnostic == "no_source_writer_observed_advisory_only"
        assert not result.production_authorized
    finally:
        os.close(src_fd)


def test_real_lsof_detects_a_writable_source_fd(
    fixture_files,
) -> None:
    source, canary = fixture_files
    src_fd = os.open(source.path, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        result = _lsof(source, canary)
        assert (os.getpid(), src_fd) in result.observed_writers
        assert result.diagnostic == "writable_source_fds_observed"
        assert not result.production_authorized
    finally:
        os.close(src_fd)


def test_real_lsof_sees_other_fixture_process_writable_fd(
    fixture_files,
) -> None:
    source, canary = fixture_files
    code = (
        "import os,sys,time\n"
        "fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CLOEXEC|os.O_NOFOLLOW)\n"
        "print('READY',flush=True)\n"
        "time.sleep(8)\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(source.path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "READY"
        report = _lsof(source, canary)
        assert any(pid == child.pid for pid, _fd in report.observed_writers)
        assert report.diagnostic == "writable_source_fds_observed"
        assert report.production_authorized is False
    finally:
        if child.poll() is None:
            child.terminate()  # Only the child created by this test.
        child.communicate(timeout=5)
    assert source.path.read_bytes() == b"test-owned source\n"
