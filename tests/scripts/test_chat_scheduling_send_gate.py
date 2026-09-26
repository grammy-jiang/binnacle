import io
import json
import subprocess
import threading
from pathlib import Path
from typing import ClassVar

import pytest

from scripts import chat_scheduling_chat as chat
from scripts import chat_scheduling_runtime as runtime


class _GateStdin(io.StringIO):
    def __init__(self, lock: threading.Lock, statuses: list[str]):
        super().__init__()
        self.lock = lock
        self.statuses = statuses

    def write(self, value: str) -> int:
        self.statuses.append(value.rstrip("\n"))
        if self.lock.locked():
            self.lock.release()
        return len(value)


class _GateStdout:
    def __init__(self, lock: threading.Lock):
        self.lock = lock

    def readline(self) -> str:
        self.lock.acquire()
        return "READY\n"


class _GateProcess:
    lock: ClassVar[threading.Lock] = threading.Lock()
    statuses: ClassVar[list[str]] = []

    def __init__(self, *args, **kwargs):
        self.stdout = _GateStdout(self.lock)
        self.stdin = _GateStdin(self.lock, self.statuses)

    def wait(self, timeout=None):
        return 0


@pytest.fixture(autouse=True)
def _reset_fake_gate():
    if _GateProcess.lock.locked():
        _GateProcess.lock.release()
    _GateProcess.statuses.clear()
    yield
    if _GateProcess.lock.locked():
        _GateProcess.lock.release()


def test_trial_gap_floor_is_15_seconds():
    assert '[ "$1" != trialgap ] || [ "$G" -ge 15 ] || G=15;' in runtime.SEND_GATE_SH
    assert "G=60" not in runtime.SEND_GATE_SH


def test_gate_release_allows_second_trial_while_first_context_is_still_open(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(runtime.subprocess, "Popen", _GateProcess)
    first_posted = threading.Event()
    second_entered = threading.Event()
    allow_first_finish = threading.Event()

    def first_trial():
        with runtime.shared_send_gate(
            trial=True,
            url_file=tmp_path / "first-url",
            timing_file=tmp_path / "first-timing",
        ) as post_confirmed:
            post_confirmed()
            first_posted.set()
            assert allow_first_finish.wait(2)

    def second_trial():
        assert first_posted.wait(2)
        with runtime.shared_send_gate(
            trial=True,
            url_file=tmp_path / "second-url",
            timing_file=tmp_path / "second-timing",
        ) as post_confirmed:
            second_entered.set()
            post_confirmed()

    first = threading.Thread(target=first_trial)
    second = threading.Thread(target=second_trial)
    first.start()
    second.start()
    assert second_entered.wait(2), "second trial stayed blocked behind reply polling"
    assert first.is_alive(), "first trial must still be outside the released send gate"
    allow_first_finish.set()
    first.join(2)
    second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert _GateProcess.statuses == ["sent", "sent"]


def test_routed_send_releases_gate_before_reply_poll(monkeypatch, tmp_path):
    events: list[str] = []
    cid = "12345678-1234-1234-1234-123456789abc"
    url_file = tmp_path / "chat-url.txt"
    timing_file = tmp_path / "chat-timing.json"

    def fake_run(args, **kwargs):
        if str(chat.API_SEND_PROMPT) in args:
            events.append("send")
            out = Path(args[args.index("--json") + 1])
            body = Path(args[args.index("--record-send-body") + 1])
            body.write_text('{"sent": true}')
            out.write_text(
                json.dumps(
                    {
                        "conversation_id": cid,
                        "url": f"https://chatgpt.com/c/{cid}",
                        "resolved": True,
                    }
                )
            )
            return subprocess.CompletedProcess(args, 0, "", "")
        events.append("poll")
        assert events == ["send", "posted", "poll"]
        return subprocess.CompletedProcess(args, 0, "title\nmeta\n\nDONE\n", "")

    def post_confirmed():
        assert url_file.read_text().strip().endswith(cid)
        assert json.loads(timing_file.read_text())["status"] == "running"
        events.append("posted")

    monkeypatch.setattr(chat, "_run", fake_run)
    monkeypatch.setattr(chat.time, "sleep", lambda _value: None)
    result = chat.send_project_chat(
        "g-p-lane",
        "prompt",
        30,
        url_file,
        timing_file=timing_file,
        system_hint="plugin:lane",
        model="gpt-5-6-thinking",
        effort="max",
        on_posted=post_confirmed,
    )

    assert result["reply"] == "DONE"
    assert events == ["send", "posted", "poll"]


def test_prepost_failure_releases_gate_as_not_sent(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime.subprocess, "Popen", _GateProcess)

    with (
        pytest.raises(RuntimeError, match="before post"),
        runtime.shared_send_gate(
            trial=True,
            url_file=tmp_path / "missing-url",
            timing_file=tmp_path / "missing-timing",
        ),
    ):
        raise RuntimeError("before post")

    assert _GateProcess.statuses == [""]
