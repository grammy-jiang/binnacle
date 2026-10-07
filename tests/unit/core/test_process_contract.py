"""The process port preserves native handles and caller-owned launch inputs."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from binnacle import job_process

if TYPE_CHECKING:
    from binnacle.platform.contracts.process_contracts import (
        ProcessBackend,
        ProcessHandle,
    )


@pytest.fixture
def backend() -> ProcessBackend:
    return job_process.LinuxProcessBackend()


def test_launch_preserves_argv_environment_binary_files_and_exit(
    tmp_path, monkeypatch, backend
):
    monkeypatch.setenv("G3_PARENT_ONLY", "must not leak")
    body = b"binary\x00\xff\n" * 25_000
    source = tmp_path / "stdin"
    source.write_bytes(body)
    output = tmp_path / "out.log"
    argument = "spaces ; $HOME 'quotes'"
    code = """
import json, os, sys
print(json.dumps({
    "cwd": os.getcwd(), "argument": sys.argv[1],
    "value": os.environ["G3_VALUE"], "pager": os.environ["PAGER"],
    "parent": os.environ.get("G3_PARENT_ONLY"),
    "binnacle": os.environ.get("BINNACLE"),
    "pid": os.getpid(), "pgid": os.getpgrp(), "sid": os.getsid(0),
}), flush=True)
sys.stdout.buffer.write(sys.stdin.buffer.read())
sys.stdout.buffer.flush()
os.write(2, b"stderr-marker")
sys.exit(7)
"""
    argv = [sys.executable, "-c", code, argument]
    env = {"G3_VALUE": "caller value", "PAGER": "caller-pager"}
    with source.open("rb") as inf, output.open("wb") as outf:
        handle = backend.launch(argv, workdir=tmp_path, env=env, stdin=inf, output=outf)
        try:
            assert isinstance(handle, subprocess.Popen)
            assert handle.args == argv
            assert handle.wait(timeout=10) == 7
            assert handle.returncode == 7
            assert not inf.closed and not outf.closed
        finally:
            if handle.returncode is None:
                backend.signal_job(handle.pid, set(), "kill")
            handle.wait(timeout=5)
    header, rest = output.read_bytes().split(b"\n", 1)
    assert json.loads(header) == {
        "cwd": str(tmp_path),
        "argument": argument,
        "value": "caller value",
        "pager": "caller-pager",
        "parent": None,
        "binnacle": None,
        "pid": handle.pid,
        "pgid": handle.pid,
        "sid": handle.pid,
    }
    assert rest == body + b"stderr-marker"
    assert source.read_bytes() == body
    assert argv == [sys.executable, "-c", code, argument]
    assert env == {"G3_VALUE": "caller value", "PAGER": "caller-pager"}


def _assert_wait_timeout(handle: ProcessHandle) -> None:
    with pytest.raises(subprocess.TimeoutExpired) as error:
        handle.wait(timeout=0)
    assert error.value.timeout == 0
    assert handle.returncode is None


@pytest.mark.parametrize("intent, expected", [("terminate", -15), ("kill", -9)])
def test_timeout_keeps_child_alive_after_parent_closes_files(
    tmp_path, backend, intent, expected
):
    argv = [sys.executable, "-c", "import signal; signal.pause()"]
    with (tmp_path / "stdin").open("w+b") as inf, (tmp_path / "out").open("wb") as outf:
        handle = backend.launch(argv, workdir=tmp_path, env={}, stdin=inf, output=outf)
    try:
        _assert_wait_timeout(handle)
        token = backend.starttime(handle.pid)
        assert token is not None
        assert backend.alive(handle.pid, token)
        assert backend.alive(handle.pid)
        assert not backend.alive(handle.pid, token + 1)
        assert os.getpgid(handle.pid) == handle.pid
        backend.signal_job(handle.pid, set(), intent)
        assert handle.wait(timeout=5) == expected
        assert handle.returncode == expected
        assert not backend.alive(handle.pid, token)
    finally:
        if handle.returncode is None:
            backend.signal_job(handle.pid, set(), "kill")
        handle.wait(timeout=5)


@pytest.mark.parametrize("missing", ["executable", "workdir"])
def test_launch_errors_leave_caller_files_open(tmp_path, backend, missing):
    absent = tmp_path / "missing"
    argv = [str(absent)] if missing == "executable" else [sys.executable, "-c", ""]
    workdir = tmp_path if missing == "executable" else absent
    with (tmp_path / "stdin").open("w+b") as inf, (tmp_path / "out").open("wb") as outf:
        with pytest.raises(FileNotFoundError) as error:
            backend.launch(argv, workdir=workdir, env={}, stdin=inf, output=outf)
        assert error.value.filename == str(absent)
        assert not inf.closed and not outf.closed


def test_handle_fake_supports_the_same_wait_contract() -> None:
    class FakeHandle:
        pid = 123
        returncode: int | None = None

        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is None:
                assert timeout is not None, "complete the fake before an unbounded wait"
                raise subprocess.TimeoutExpired(["fake"], timeout)
            return self.returncode

    fake = FakeHandle()
    _assert_wait_timeout(fake)
    fake.returncode = -signal.SIGTERM
    handle: ProcessHandle = fake
    assert handle.wait() == -15
    assert handle.returncode == -15


def test_contract_import_does_not_load_engine_settings_or_linux():
    code = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('binnacle.') and fullname not in {'binnacle.platform', 'binnacle.platform.contracts', 'binnacle.platform.contracts.process_contracts'}:
            raise AssertionError('unexpected dependency: ' + fullname)
sys.meta_path.insert(0, Block())
from binnacle.platform.contracts.process_contracts import ProcessBackend, ProcessHandle
assert ProcessBackend and ProcessHandle
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
