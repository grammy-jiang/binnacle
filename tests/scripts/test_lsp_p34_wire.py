"""No installed providers: adversarial protocol and process lifecycle checks."""

import base64
import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from scripts.lsp_p34_wire import MAX_BODY, Peer, ProbeError

FIXTURE = Path(__file__).parents[1] / "fixtures/lsp/p34_server.py"


def peer(tmp_path, *args, timeout=2):
    return Peer([sys.executable, "-u", str(FIXTURE), *args], tmp_path, {}, timeout)


def _terminated_or_zombie(child, psutil):
    """A child disappearing between two psutil calls is successful cleanup.

    Still-running, non-zombie children remain a hard failure; do not hide
    permission, observation, or process-identity errors.
    """
    try:
        return not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


@pytest.mark.parametrize("mode", ["normal", "stderr", "reverse"])
@pytest.mark.skipif(os.name != "posix", reason="P3.4 POSIX stdio/process group test")
def test_handshake_shutdown_and_reverse_denial(tmp_path, mode):
    instance = peer(tmp_path, mode)
    try:
        response = instance.request("initialize", {}, {})
        assert response["capabilities"]["documentSymbolProvider"] is True
        assert instance.reverse_denied == (3 if mode == "reverse" else 0)
        assert instance.request("shutdown", None, {}) is None
        instance.notify("exit")
        assert instance.process.wait(timeout=1) == 0
    finally:
        instance.close()
    assert instance.cleanup == "group_signaled_leader_reaped"
    assert instance.process.stdin.closed and instance.process.stdout.closed


@pytest.mark.parametrize(
    "wire,code",
    [
        (b"Content-Length: -1\r\n\r\n", "invalid_length"),
        (b"Content-Length: 1\r\nContent-Length: 1\r\n\r\nx", "invalid_length"),
        (b"Content-Length: 9999999\r\n\r\n", "body_limit"),
        (b"x" * 9000, "header_limit"),
        (b"Content-Length: 2\r\n\r\n{", "stdout_eof"),
        (b"Content-Length: 1\r\n\r\n{", "invalid_json"),
        (b"Content-Length: 2\r\n\r\n[]", "invalid_envelope"),
        (b'Content-Length: 13\r\n\r\n{"x":1,"x":2}', "duplicate_json_key"),
    ],
)
@pytest.mark.skipif(os.name != "posix", reason="P3.4 POSIX stdio/process group test")
def test_bad_frames_are_bounded(tmp_path, wire, code):
    encoded = base64.b64encode(wire).decode()
    instance = Peer(
        [
            sys.executable,
            "-c",
            f"import os,base64;os.write(1,base64.b64decode('{encoded}'))",
        ],
        tmp_path,
        {},
        2,
    )
    try:
        with pytest.raises(ProbeError, match=code):
            instance.receive()
        assert len(instance.buffer) <= MAX_BODY + 4096
    finally:
        instance.close()
    assert instance.process.poll() is not None


@pytest.mark.skipif(os.name != "posix", reason="P3.4 POSIX stdio/process group test")
def test_timeout_cleans_term_ignoring_parent_and_child(tmp_path):
    psutil = pytest.importorskip("psutil")
    ready = tmp_path / "synthetic-child-ready"
    instance = peer(tmp_path, "hang-child", str(ready), timeout=5)
    children = []
    started = time.monotonic()
    try:
        startup_deadline = time.monotonic() + 5
        while not ready.is_file():
            assert instance.process.poll() is None, "fixture exited before ready"
            assert time.monotonic() < startup_deadline, "fixture startup timed out"
            time.sleep(0.01)
        # The adversarial deadline begins only after the child exists and the
        # parent has installed SIGTERM_IGN. Otherwise this test races Python
        # startup on busy CI hosts instead of testing group cleanup.
        children = psutil.Process(instance.process.pid).children()
        assert len(children) == 1
        instance.deadline = time.monotonic() + 0.3
        started = time.monotonic()
        with pytest.raises(ProbeError, match="deadline"):
            instance.request("initialize", {}, {})
    finally:
        instance.close()
    assert time.monotonic() - started < 4
    assert instance.process.returncode == -signal.SIGKILL
    assert all(_terminated_or_zombie(child, psutil) for child in children)


def test_reaped_child_disappearance_between_psutil_checks_is_clean():
    psutil = pytest.importorskip("psutil")

    class GoneAfterCheck:
        def is_running(self):
            return True

        def status(self):
            raise psutil.NoSuchProcess(pid=92321)

    assert _terminated_or_zombie(GoneAfterCheck(), psutil)


def test_running_child_must_not_count_as_clean():
    psutil = pytest.importorskip("psutil")

    class StillRunning:
        def is_running(self):
            return True

        def status(self):
            return psutil.STATUS_RUNNING

    assert not _terminated_or_zombie(StillRunning(), psutil)


@pytest.mark.skipif(os.name != "posix", reason="P3.4 POSIX stdio/process group test")
def test_reverse_configuration_and_unknown_request_are_not_reflected(
    tmp_path, monkeypatch
):
    instance = peer(tmp_path)
    messages = []
    monkeypatch.setattr(instance, "send", messages.append)
    try:
        instance.reverse(
            {
                "id": 9,
                "method": "workspace/configuration",
                "params": {
                    "items": [{"section": "yaml.schemaStore"}, {"section": "secrets"}]
                },
            },
            {"yaml": {"schemaStore": {"enable": False}}},
        )
        assert messages[-1]["result"] == [{"enable": False}, {}]
        instance.reverse({"id": 10, "method": "evil /private/data"}, {})
        assert messages[-1]["error"]["code"] == -32601
        assert "private" not in json.dumps(messages)
    finally:
        instance.close()


@pytest.mark.skipif(os.name != "posix", reason="P3.4 POSIX stdio/process group test")
def test_blocked_stdin_write_has_deadline(tmp_path):
    instance = Peer(
        [sys.executable, "-c", "import time;time.sleep(60)"], tmp_path, {}, 0.2
    )
    try:
        with pytest.raises(ProbeError, match="deadline"):
            instance.send({"data": "x" * (MAX_BODY // 2)})
    finally:
        instance.close()


@pytest.mark.skipif(os.name != "posix", reason="P3.4 POSIX stdio/process group test")
def test_stream_of_notifications_cannot_extend_deadline(tmp_path):
    code = 'import os; data=b\'Content-Length: 33\\r\\n\\r\\n{"jsonrpc":"2.0","method":"tick"}\';\nwhile True: os.write(1,data)'
    instance = Peer([sys.executable, "-c", code], tmp_path, {}, 0.2)
    try:
        with pytest.raises(ProbeError, match="deadline|message_limit"):
            instance.request("initialize", {}, {})
    finally:
        instance.close()


@pytest.mark.skipif(os.name != "posix", reason="P3.4 POSIX stdio/process group test")
def test_bash_readiness_wait_handles_document_notification(tmp_path):
    instance = peer(tmp_path)
    try:
        instance.request("initialize", {}, {})
        instance.notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": "file:///synthetic/main.sh"}},
        )
        instance.await_diagnostics("file:///synthetic/main.sh", {})
        assert instance.request("shutdown", None, {}) is None
    finally:
        instance.close()


@pytest.mark.parametrize(
    "message",
    [
        {"id": True, "method": "evil"},
        {"id": [], "method": "evil"},
        {"id": 1, "method": []},
        {"id": 1, "method": "workspace/configuration", "params": []},
        {"id": 1, "method": "workspace/configuration", "params": {"items": [None]}},
    ],
)
@pytest.mark.skipif(os.name != "posix", reason="P3.4 POSIX stdio/process group test")
def test_invalid_reverse_request_is_stable_error(tmp_path, message):
    instance = peer(tmp_path)
    try:
        with pytest.raises(
            ProbeError, match="invalid_reverse_request|invalid_configuration_item"
        ):
            instance.reverse(message, {})
    finally:
        instance.close()


@pytest.mark.skipif(os.name != "posix", reason="P3.4 POSIX stdio/process group test")
def test_cleanup_signal_error_is_never_a_clean_verdict(tmp_path, monkeypatch):
    instance = Peer([sys.executable, "-c", "pass"], tmp_path, {}, 2)
    instance.process.wait(timeout=2)

    def refused(*args):
        raise PermissionError("private path must not escape")

    monkeypatch.setattr(os, "killpg", refused)
    instance.close()
    assert instance.cleanup == "cleanup_unverified"


@pytest.mark.skipif(os.name != "posix", reason="P3.4 POSIX stdio/process group test")
def test_child_cleanup_after_leader_has_exited(tmp_path):
    psutil = pytest.importorskip("psutil")
    code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); print(p.pid,flush=True)"
    instance = Peer([sys.executable, "-c", code], tmp_path, {}, 2)
    try:
        assert instance.process.wait(timeout=2) == 0
        child = psutil.Process(int(os.read(instance.process.stdout.fileno(), 100)))
    finally:
        instance.close()
    assert instance.cleanup == "group_signaled_leader_reaped"
    try:
        child.wait(timeout=1)
    except psutil.TimeoutExpired:
        # An orphan can remain a zombie until the container's init reaps it.
        assert child.status() == psutil.STATUS_ZOMBIE
