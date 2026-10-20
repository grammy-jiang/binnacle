"""P1.5 synthetic process integration, not production lifecycle acceptance."""

import os
import signal
import stat
import time

import pytest

from tests.fixtures.lsp.process_observer import ProcessObserver

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX pipe/session fixture")


@pytest.mark.parametrize("fault", ["hang-initialize", "delay-initialize"])
def test_initialize_timeout_and_late_response(tmp_path, fault):
    with ProcessObserver(tmp_path, fault) as peer:
        peer.send({"id": 1, "method": "initialize", "params": {"secret": "never-log"}})
        peer.wait_event("withheld" if fault == "hang-initialize" else "delay-start")
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="response deadline"):
            peer.receive(0.03)
        assert 0.02 <= time.monotonic() - started < 2
        assert peer.process.poll() is None
        if fault == "delay-initialize":
            assert peer.receive()["id"] == 1
            peer.wait_event("delay-end")
        assert "never-log" not in peer.trace.read_text()
        assert stat.S_IMODE(peer.trace.stat().st_mode) == 0o600
    assert peer.cleanup_verified
    assert not peer.pid_exists(peer.process.pid)


@pytest.mark.parametrize("phase", ["initialize", "request"])
@pytest.mark.parametrize("failure", ["crash", "eof"])
def test_crash_and_live_stdout_eof(tmp_path, phase, failure):
    with ProcessObserver(tmp_path, f"{failure}-{phase}") as peer:
        if phase == "request":
            peer.request("initialize")
        peer.send(
            {
                "id": 2,
                "method": "initialize"
                if phase == "initialize"
                else "textDocument/definition",
            }
        )
        with pytest.raises(EOFError, match="stdout EOF"):
            peer.receive()
        peer.wait_event("crash" if failure == "crash" else "stdout-closed")
        if failure == "crash":
            assert peer.process.wait(timeout=3) == 23
        else:
            assert peer.process.poll() is None
    assert peer.cleanup_verified
    assert not peer.pid_exists(peer.process.pid)


def test_stderr_flood_is_drained_and_retention_bounded(tmp_path):
    with ProcessObserver(tmp_path, "stderr-flood") as peer:
        assert peer.request("initialize")["id"] == 1
        peer.wait_event("stderr-written")
        # The writer's flush is not evidence the independent pipe reader has
        # consumed every byte. Drain with a deadline on both Darwin and Linux.
        deadline = time.monotonic() + 3
        while peer.stderr_size < 256 * 1024 and time.monotonic() < deadline:
            peer.read_chunk(min(0.05, deadline - time.monotonic()))
        assert peer.stderr_size == 256 * 1024
        assert len(peer.stderr_sample) == 4096
    assert peer.cleanup_verified


def test_shutdown_timeout_term_resistance_and_kill_witness(tmp_path):
    with ProcessObserver(tmp_path, "non-exit") as peer:
        peer.wait_event("ready")  # Signal handler installed before TERM.
        peer.send({"id": 1, "method": "shutdown"})
        peer.send({"method": "exit"})
        peer.wait_event("ignored-shutdown")
        with pytest.raises(TimeoutError):
            peer.receive(0.03)
    assert peer.escalated and peer.cleanup_verified
    assert peer.process.returncode == -signal.SIGKILL


@pytest.mark.parametrize("fault", ["child", "escaped-child"])
@pytest.mark.parametrize("fail_assertion", [False, True])
def test_descendant_cleanup_even_on_test_failure(tmp_path, fault, fail_assertion):
    peer = ProcessObserver(tmp_path, fault)
    try:
        with peer:
            child = peer.wait_event("child-ready")
            assert peer.pid_exists(child["pid"])
            assert (child["pgid"] != peer.process.pid) == (fault == "escaped-child")
            if fail_assertion:
                raise AssertionError("injected test failure")
    except AssertionError as error:
        assert fail_assertion and str(error) == "injected test failure"
    assert peer.escaped == (fault == "escaped-child")
    assert peer.cleanup_verified
    assert not peer.pid_exists(child["pid"])
    assert not peer.pid_exists(peer.process.pid)


def test_exit_trace_alone_never_proves_cleanup(tmp_path, monkeypatch):
    peer = ProcessObserver(tmp_path, "escaped-child")
    child = peer.wait_event("child-ready")
    real_exists = peer.pid_exists
    monkeypatch.setattr(peer, "pid_exists", lambda pid: True)
    with pytest.raises(TimeoutError, match="cleanup unverified"), peer:
        pass
    assert peer.escaped and not peer.cleanup_verified
    assert not real_exists(child["pid"])  # Fault injection affects observation only.
    assert not real_exists(peer.process.pid)


def test_cancel_notification_witness_and_immediate_failure_cleanup(tmp_path):
    with ProcessObserver(tmp_path, "hang-initialize") as peer:
        peer.send({"id": 1, "method": "initialize"})
        peer.wait_event("withheld")
        peer.send({"method": "$/cancelRequest", "params": {"id": 1}})
        peer.wait_event("cancel-observed")
        with pytest.raises(TimeoutError):
            peer.receive(0.03)
    assert peer.cleanup_verified
    peer = ProcessObserver(tmp_path, "escaped-child")
    with pytest.raises(RuntimeError, match="immediate failure"), peer:
        raise RuntimeError("immediate failure")
    assert peer.cleanup_verified and peer.escaped
