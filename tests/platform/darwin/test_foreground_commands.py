"""Default gate and native bounded foreground behavior, without durable jobs."""

from __future__ import annotations

import json
import os
import shlex
import signal
import sys
import time
from dataclasses import replace
from threading import Event, Thread

import pytest

from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    CapabilityUnavailable,
    NativeCapabilityError,
)
from binnacle.platform.contracts.darwin_contracts import ForegroundRequest
from binnacle.platform.darwin import process_authority, process_backend
from binnacle.platform.darwin.process_backend import (
    DarwinProcessBackend,
    _ForegroundRunner,
)

native = pytest.mark.skipif(
    sys.platform != "darwin", reason="requires Darwin posix_spawn owned-child mechanism"
)


def request(tmp_path, command="printf hello", **changes):
    return replace(
        ForegroundRequest(command, tmp_path, None, 3, False, 3, 10000), **changes
    )


def python_command(code):
    return f"exec {shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def test_runtime_gate_cannot_be_enabled_by_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BINNACLE_DARWIN_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("BINNACLE_DARWIN_FOREGROUND_APPROVED", "true")
    monkeypatch.setattr(
        os, "posix_spawn", lambda *a, **kw: pytest.fail("unapproved spawn")
    )
    with pytest.raises(CapabilityUnavailable) as error:
        DarwinProcessBackend().run_foreground(request(tmp_path), cancel=Event())
    assert error.value.code == "native_capability_unavailable"
    with pytest.raises(CapabilityUnavailable):
        DarwinProcessBackend().launch(
            [], workdir=tmp_path, env={}, stdin=None, output=None
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"background": True},
        {"wait_seconds": 4},
        {"foreground_limit_s": 4},
        {"wait_seconds": 0},
    ],
)
def test_background_or_over_limit_is_zero_spawn(tmp_path, monkeypatch, changes):
    monkeypatch.setattr(process_backend, "_is_darwin", lambda: True)
    monkeypatch.setattr(
        os, "posix_spawn", lambda *a, **kw: pytest.fail("refusal spawned")
    )
    with pytest.raises(CapabilityUnavailable) as error:
        _ForegroundRunner(3, 3).run_foreground(
            request(tmp_path, **changes), cancel=Event()
        )
    assert error.value.code == "darwin_background_jobs_unavailable"


@pytest.mark.parametrize(
    "limit,maximum", [(0, 3), (4, 3), (3, 51), (float("inf"), 50), (float("nan"), 3)]
)
def test_invalid_captured_limit_is_refused(limit, maximum):
    with pytest.raises(CapabilityUnavailable):
        _ForegroundRunner(limit, maximum)


@pytest.mark.parametrize(
    "changes",
    [
        {"wait_seconds": -1},
        {"wait_seconds": float("nan")},
        {"foreground_limit_s": 0},
        {"max_output_bytes": -1},
    ],
)
def test_invalid_request_is_zero_spawn(tmp_path, monkeypatch, changes):
    monkeypatch.setattr(process_backend, "_is_darwin", lambda: True)
    monkeypatch.setattr(
        os, "posix_spawn", lambda *a, **kw: pytest.fail("invalid spawn")
    )
    with pytest.raises(CapabilityUnavailable):
        _ForegroundRunner(3, 3).run_foreground(
            request(tmp_path, **changes), cancel=Event()
        )


def test_precancelled_is_zero_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(process_backend, "_is_darwin", lambda: True)
    monkeypatch.setattr(
        os, "posix_spawn", lambda *a, **kw: pytest.fail("cancelled spawn")
    )
    cancel = Event()
    cancel.set()
    with pytest.raises(CapabilityUnavailable, match="darwin_foreground_cancelled"):
        _ForegroundRunner(3, 3).run_foreground(request(tmp_path), cancel=cancel)


def test_failed_pipe_setup_closes_partial_fds_before_controlled_error(
    tmp_path, monkeypatch
):
    pipe = os.pipe
    opened = []

    def partial_pipe():
        if opened:
            raise OSError("secret native diagnostic")
        pair = pipe()
        opened.extend(pair)
        return pair

    monkeypatch.setattr(process_backend, "_is_darwin", lambda: True)
    monkeypatch.setattr(os, "pipe", partial_pipe)
    monkeypatch.setattr(
        os, "posix_spawn", lambda *a, **kw: pytest.fail("setup failure spawned")
    )
    with pytest.raises(AuthorityUnknown) as error:
        _ForegroundRunner(3, 3).run_foreground(request(tmp_path), cancel=Event())
    assert error.value.code == "darwin_foreground_io_failed"
    assert "secret" not in str(error.value)
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_spawn_failure_closes_pipes_and_sanitizes_error(tmp_path, monkeypatch):
    pipe = os.pipe
    opened = []

    def tracked_pipe():
        pair = pipe()
        opened.extend(pair)
        return pair

    def fail_spawn(*args, **kwargs):
        raise OSError("secret native diagnostic")

    monkeypatch.setattr(os, "pipe", tracked_pipe)
    monkeypatch.setattr(os, "posix_spawn", fail_spawn)
    monkeypatch.setattr(process_backend, "_is_darwin", lambda: True)
    monkeypatch.setattr(process_authority, "_is_darwin", lambda: True)
    with pytest.raises(AuthorityUnknown) as error:
        _ForegroundRunner(3, 3).run_foreground(request(tmp_path), cancel=Event())
    assert error.value.code == "darwin_foreground_io_failed"
    assert "secret" not in str(error.value)
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


@native
def test_native_normal_exit_cwd_stdin_binary_combined_output(tmp_path):
    directory = tmp_path / "space ' $dollar"
    directory.mkdir()
    code = """
import json, os, sys
print(json.dumps({'pid': os.getpid(), 'pgid': os.getpgrp(), 'cwd': os.getcwd()}), flush=True)
sys.stdout.buffer.write(sys.stdin.buffer.read())
sys.stdout.buffer.flush()
os.write(2, b'\\x00\\xffstderr')
sys.exit(7)
"""
    payload = "hello ☃\n" * 20000
    result = _ForegroundRunner(3, 3).run_foreground(
        request(
            directory, python_command(code), stdin=payload, max_output_bytes=1000000
        ),
        cancel=Event(),
    )
    header, body = result.output.split(b"\n", 1)
    observation = json.loads(header)
    assert observation["pid"] == observation["pgid"]
    assert observation["pgid"] != os.getpgrp()
    assert observation["cwd"] == str(directory.resolve())
    assert body == payload.encode() + b"\x00\xffstderr"
    assert result.exit_code == 7 and result.signal is None
    assert result.descendants_unverified is True
    assert result.output_bytes == len(result.output) and not result.truncated
    assert result.owner_generation and result.execution_id


@native
def test_native_signal_exit_reports_leader_only(tmp_path):
    result = _ForegroundRunner(3, 3).run_foreground(
        request(tmp_path, "kill -TERM $$"), cancel=Event()
    )
    assert result.signal == signal.SIGTERM and result.exit_code is None
    assert result.descendants_unverified


@native
def test_native_output_budget_does_not_deadlock_writer(tmp_path):
    result = _ForegroundRunner(3, 3).run_foreground(
        request(
            tmp_path,
            python_command("import os; os.write(1, b'x' * 1000000)"),
            max_output_bytes=100,
        ),
        cancel=Event(),
    )
    assert result.exit_code == 0 and result.truncated
    assert result.output == b"x" * 100
    assert result.output_bytes == 1000000


@native
def test_native_foreground_expiry_cleans_group_before_error(tmp_path, monkeypatch):
    events = []
    spawn = os.posix_spawn
    killpg = os.killpg
    waitpid = os.waitpid

    def owned_spawn(*args, **kwargs):
        pid = spawn(*args, **kwargs)
        events.append(("spawn", pid))
        return pid

    def owned_signal(pid, sig):
        assert events[0] == ("spawn", pid)
        assert not any(event[0] == "reap" for event in events)
        events.append(("signal", sig))
        return killpg(pid, sig)

    def owned_wait(pid, flags):
        assert events[0] == ("spawn", pid)
        result = waitpid(pid, flags)
        if result[0]:
            events.append(("reap", result[0]))
        return result

    monkeypatch.setattr(os, "posix_spawn", owned_spawn)
    monkeypatch.setattr(os, "killpg", owned_signal)
    monkeypatch.setattr(os, "waitpid", owned_wait)
    started = time.monotonic()
    with pytest.raises(CapabilityUnavailable) as error:
        _ForegroundRunner(3, 3).run_foreground(
            request(tmp_path, "trap '' TERM; while :; do :; done", wait_seconds=0.2),
            cancel=Event(),
        )
    assert error.value.code == "darwin_background_jobs_unavailable"
    assert "descendants_unverified=true" in str(error.value)
    assert [event[0] for event in events] == ["spawn", "signal", "signal", "reap"]
    assert [event[1] for event in events[1:3]] == [signal.SIGTERM, signal.SIGKILL]
    assert time.monotonic() - started < 3


@native
def test_native_cancel_and_leader_exit_race(tmp_path, monkeypatch):
    """Replay concurrent cancellation around short leader exits, never post-reap kill."""
    original_kill = os.killpg
    original_wait = os.waitpid
    original_spawn = os.posix_spawn
    unreaped = set()
    reaps = []
    spawn_ready = Event()

    def spawned(*args, **kwargs):
        pid = original_spawn(*args, **kwargs)
        unreaped.add(pid)
        spawn_ready.set()
        return pid

    def killed(pid, sig):
        assert pid in unreaped
        return original_kill(pid, sig)

    def waited(pid, flags):
        result = original_wait(pid, flags)
        if result[0]:
            assert pid in unreaped
            unreaped.remove(pid)
            reaps.append(pid)
        return result

    monkeypatch.setattr(os, "posix_spawn", spawned)
    monkeypatch.setattr(os, "killpg", killed)
    monkeypatch.setattr(os, "waitpid", waited)
    for delay in (0.001, 0.01, 0.03, 0.05, 0.08):
        spawn_ready.clear()
        cancel = Event()
        done = Event()

        def cancellation(done=done, delay=delay, cancel=cancel):
            if spawn_ready.wait(3) and not done.wait(delay):
                cancel.set()

        thread = Thread(target=cancellation)
        thread.start()
        try:
            result = _ForegroundRunner(3, 3).run_foreground(
                request(tmp_path, python_command("import time; time.sleep(0.01)")),
                cancel=cancel,
            )
            assert result.exit_code == 0 and result.descendants_unverified
        except NativeCapabilityError as exc:
            # Darwin may return ESRCH for the exited, still-unreaped group's
            # KILL. That is an explicit UNKNOWN cleanup error, never success.
            assert exc.code in (
                "darwin_foreground_cancelled",
                "darwin_foreground_signal_unverified",
            )
            assert "descendants_unverified=true" in str(exc)
        finally:
            done.set()
            thread.join(1)
        assert not unreaped
    assert len(reaps) == 5


@native
def test_native_escaped_descendant_pipe_has_bounded_drain(tmp_path):
    finished = tmp_path / "escaped-finished"
    code = f"""
import os, time
if os.fork() == 0:
    os.setsid()
    time.sleep(1)
    with open({str(finished) + ".pending"!r}, 'w') as stream:
        stream.write('self-exit')
    os.replace({str(finished) + ".pending"!r}, {str(finished)!r})
    os._exit(0)
os.write(1, b'leader-only')
"""
    try:
        result = _ForegroundRunner(3, 3).run_foreground(
            request(tmp_path, python_command(code)), cancel=Event()
        )
        assert result.exit_code == 0 and result.descendants_unverified
        assert result.output == b"leader-only" and result.truncated
        assert result.duration_s < 0.9
    finally:
        deadline = time.monotonic() + 3
        while not finished.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
    assert finished.read_text() == "self-exit"
