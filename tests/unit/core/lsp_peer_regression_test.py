"""Shared framing and partial-construction regressions for synthetic peers."""

import importlib
import os
import selectors
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

from tests.fixtures.lsp.lsp_peer import LspPeer
from tests.fixtures.lsp.lsp_transport import frame
from tests.fixtures.lsp.process_observer import ProcessObserver

RESPONSE = {"jsonrpc": "2.0", "id": 1, "result": "文 →"}
WIRE = frame(RESPONSE)


@pytest.mark.parametrize("peer_type", [LspPeer, ProcessObserver])
@pytest.mark.parametrize("split", range(1, len(WIRE)))
def test_timeout_retains_every_header_and_body_split(peer_type, split):
    peer = object.__new__(peer_type)
    peer.buffer = bytearray()
    peer.pending_length = None
    peer.max_buffered = 0
    # A deterministic read boundary followed by a timeout, with no sleep race.
    peer.read_chunk = Mock(return_value=WIRE[:split])
    with (
        patch("tests.fixtures.lsp.lsp_peer.time.monotonic", side_effect=[0, 0, 4]),
        pytest.raises(TimeoutError, match="response deadline"),
    ):
        peer.receive()
    peer.read_chunk.assert_called_once()
    following = {"jsonrpc": "2.0", "id": 2, "result": None}
    peer.read_chunk = Mock(return_value=WIRE[split:] + frame(following))
    assert peer.receive() == RESPONSE
    assert peer.receive() == following
    peer.read_chunk.assert_called_once()
    assert peer.buffer == b""


@pytest.mark.parametrize(
    ("peer_type", "failure"),
    [(LspPeer, stage) for stage in ("selector", "register-1")]
    + [
        (ProcessObserver, stage)
        for stage in ("selector", "register-1", "register-2", "blocking")
    ],
)
@pytest.mark.parametrize("kill_fails", [False, True])
def test_constructor_rollback_reaps_owned_child(
    monkeypatch, tmp_path, peer_type, failure, kill_fails
):
    popen = subprocess.Popen
    selector_factory = selectors.DefaultSelector
    pipe_factory = os.pipe
    children, selectors_created, controls = [], [], []

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        if kill_fails:
            monkeypatch.setattr(child, "kill", Mock(side_effect=OSError("kill fault")))
        return child

    def pipe():
        pair = pipe_factory()
        controls.extend(pair)
        return pair

    def selector():
        if failure == "selector":
            raise OSError("injected selector")
        result = selector_factory()
        selectors_created.append(result)
        register = result.register
        count = 0

        def fault_register(*args, **kwargs):
            nonlocal count
            count += 1
            # Fail after registration to exercise a partially acquired selector.
            value = register(*args, **kwargs)
            if failure == f"register-{count}":
                raise OSError("injected register")
            return value

        monkeypatch.setattr(result, "register", fault_register)
        return result

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(selectors, "DefaultSelector", selector)
    monkeypatch.setattr(os, "pipe", pipe)
    if failure == "blocking":
        monkeypatch.setattr(
            os, "set_blocking", Mock(side_effect=OSError("injected blocking"))
        )
    with pytest.raises(OSError, match="injected"):
        peer_type(tmp_path) if peer_type is ProcessObserver else peer_type()
    assert len(children) == 1
    child = children[0]
    assert child.returncode is not None  # wait completed: direct child is reaped.
    with pytest.raises(ChildProcessError):
        os.waitpid(child.pid, os.WNOHANG)
    assert all(p.closed for p in (child.stdin, child.stdout, child.stderr))
    for result in selectors_created:
        assert result.get_map() is None
    for fd in controls:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_cleanup_closes_resources_even_when_all_signals_fail():
    peer = object.__new__(LspPeer)
    peer.selector = Mock()
    peer.process = Mock()
    peer.process.poll.return_value = None
    peer.process.kill.side_effect = OSError("kill denied")
    peer.process.terminate.side_effect = OSError("terminate denied")
    peer.process.wait.side_effect = subprocess.TimeoutExpired("synthetic", 3)
    with pytest.raises(OSError, match="cleanup failed"):
        peer.release_resources()
    peer.selector.close.assert_called_once()
    for pipe in (peer.process.stdin, peer.process.stdout, peer.process.stderr):
        pipe.close.assert_called_once()
    peer.process.wait.assert_called_once_with(timeout=3)


def test_fixture_modules_import_on_running_interpreter():
    # This test runs under 3.10 too; import the whole stdlib-only fixture surface.
    from pathlib import Path

    import tests.fixtures.lsp as fixtures

    modules = [p.stem for p in Path(next(iter(fixtures.__path__))).glob("*.py")]
    script = (
        f"import importlib, sys; sys.path.insert(0, {next(iter(fixtures.__path__))!r}); "
        + "; ".join(
            f"importlib.import_module('tests.fixtures.lsp.{name}')" for name in modules
        )
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert importlib.import_module("tests.fixtures.lsp.lsp_peer").LspPeer is LspPeer
