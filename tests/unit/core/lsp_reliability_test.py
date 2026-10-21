"""P1.9 regression proof for transactional fake-peer startup and partial frames."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time

import pytest

from tests.fixtures.lsp import lsp_peer as peer_module
from tests.fixtures.lsp import process_observer as observer_module
from tests.fixtures.lsp.lsp_peer import LspPeer
from tests.fixtures.lsp.lsp_transport import frame
from tests.fixtures.lsp.process_observer import ProcessObserver


def capture_spawns(monkeypatch):
    """Record only Popen handles our fixture actually owns and later reaps."""
    real_spawn = subprocess.Popen
    spawned = []

    def capture(*args, **kwargs):
        process = real_spawn(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(peer_module.subprocess, "Popen", capture)
    return spawned


def faulty_selector(monkeypatch, module, *, failed_registration: int = 0):
    """Inject a selector failure before/after owned process creation."""
    actual_factory = selectors.DefaultSelector
    opened = []

    def factory():
        if failed_registration < 0:
            raise OSError("selector factory injected failure")
        selector = actual_factory()
        opened.append(selector)
        actual_register = selector.register
        count = 0

        def register(*args, **kwargs):
            nonlocal count
            count += 1
            if count == failed_registration:
                raise OSError("selector registration injected failure")
            return actual_register(*args, **kwargs)

        monkeypatch.setattr(selector, "register", register)
        return selector

    monkeypatch.setattr(module.selectors, "DefaultSelector", factory)
    return opened


def assert_spawn_rolled_back(spawned):
    assert len(spawned) == 1
    process = spawned[0]
    assert process.wait(timeout=3) is not None
    assert process.poll() is not None
    for pipe in (process.stdin, process.stdout, process.stderr):
        assert pipe is not None and pipe.closed


@pytest.mark.parametrize("stage", ["factory", "first-registration"])
def test_lsp_peer_constructor_failure_reaps_owned_child(monkeypatch, stage):
    spawned = capture_spawns(monkeypatch)
    opened = faulty_selector(
        monkeypatch,
        peer_module,
        failed_registration=-1 if stage == "factory" else 1,
    )
    with pytest.raises(OSError, match="injected failure"):
        LspPeer()
    assert_spawn_rolled_back(spawned)
    assert all(not selector.get_map() for selector in opened)


@pytest.mark.parametrize(
    "stage", ["factory", "first-registration", "second-registration", "set-blocking"]
)
def test_process_observer_constructor_rollback(tmp_path, monkeypatch, stage):
    spawned = capture_spawns(monkeypatch)
    ordinal = {
        "factory": -1,
        "first-registration": 1,
        "second-registration": 2,
        "set-blocking": 0,
    }[stage]
    opened = faulty_selector(monkeypatch, observer_module, failed_registration=ordinal)

    if stage == "set-blocking":

        def fail_blocking(_fd, _enabled):
            raise OSError("set-blocking injected failure")

        monkeypatch.setattr(observer_module.os, "set_blocking", fail_blocking)

    peer = ProcessObserver.__new__(ProcessObserver)
    with pytest.raises(OSError, match="injected failure"):
        peer.__init__(tmp_path)
    # Both pre- and post-spawn selector factory choices are valid, provided
    # any successfully spawned process is fully closed and reaped.
    assert_spawn_rolled_back(spawned)
    assert peer.control is None
    assert all(not selector.get_map() for selector in opened)


@pytest.mark.parametrize("split", ["header-partial", "body-partial"])
def test_partial_frame_remains_readable_after_timeout_and_coalesced_next(
    split,
):
    """Inject staged bytes without timing-dependent real subprocess writes."""
    response1 = {"jsonrpc": "2.0", "id": 41, "result": {"location": "文"}}
    response2 = {"jsonrpc": "2.0", "id": 42, "result": None}
    first = frame(response1)
    second = frame(response2)
    boundary = first.index(b"\r\n\r\n") + 4
    cutoff = 4 if split == "header-partial" else boundary + 7
    with LspPeer() as peer:
        peer.buffer.extend(first[:cutoff])
        with pytest.raises(TimeoutError, match="fixture response deadline"):
            peer.receive(timeout=0.02)
        if split == "body-partial":
            assert peer.pending_length == len(first) - boundary
        else:
            assert peer.pending_length is None
        peer.buffer.extend(first[cutoff:] + second)
        assert peer.receive(timeout=0.2) == response1
        assert peer.receive(timeout=0.2) == response2
        assert peer.pending_length is None
        assert peer.buffer == bytearray()
        assert peer.max_buffered <= 9216


def test_rollback_never_signals_a_pid_sourced_from_trace(tmp_path, monkeypatch):
    """Trace observations are never permitted to become a kill target."""
    spawned = capture_spawns(monkeypatch)
    faulty_selector(monkeypatch, observer_module, failed_registration=2)
    seen = []
    original_kill = os.kill

    def witness(pid, sig):
        seen.append((pid, sig))
        return original_kill(pid, sig)

    monkeypatch.setattr(observer_module.os, "kill", witness)
    with pytest.raises(OSError, match="registration injected failure"):
        ProcessObserver(tmp_path)
    assert_spawn_rolled_back(spawned)
    assert seen == [(spawned[0].pid, signal.SIGKILL)]


def test_constructor_rollback_of_cooperative_child(tmp_path, monkeypatch):
    """A failed peer constructor closes the child-control writer; no child is signaled."""
    spawned = capture_spawns(monkeypatch)
    original_set_blocking = os.set_blocking

    def fail_after_child_ready(fd, enabled):
        # Wait for the private fixture to actually spawn its cooperative descendant.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            for trace in tmp_path.glob("trace-*.jsonl"):
                if b'"event": "child-ready"' in trace.read_bytes():
                    raise OSError("set-blocking injected failure")
            time.sleep(0.005)
        raise TimeoutError("fixture child never reached ready")

    monkeypatch.setattr(observer_module.os, "set_blocking", fail_after_child_ready)
    peer = ProcessObserver.__new__(ProcessObserver)
    with pytest.raises(OSError, match="set-blocking injected failure"):
        peer.__init__(tmp_path, "escaped-child")
    assert_spawn_rolled_back(spawned)
    assert peer.control is None
    # Child exit is a cooperative outcome triggered by pipe EOF, NOT killpg.
    trace = next(tmp_path.glob("trace-*.jsonl"))
    events = trace.read_text().splitlines()
    assert any('"event": "child-ready"' in line for line in events)
    assert any('"event": "child-exit"' in line for line in events)
    assert any('"event": "child-reaped"' in line for line in events)
    monkeypatch.setattr(observer_module.os, "set_blocking", original_set_blocking)
