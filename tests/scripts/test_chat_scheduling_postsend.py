import json
import subprocess
from pathlib import Path

from scripts import chat_scheduling_chat as chat
from scripts.chat_scheduling_postsend import (
    captured_send_reply,
    cleanup_failure_is_fatal,
)


def test_captured_send_reply_falls_back_without_conversation_backup():
    reply, complete = captured_send_reply(
        {"submission_status": "completed", "chat": {"send_result": {"reply": "DONE"}}}
    )
    assert reply == "DONE"
    assert complete is True


def test_completed_submission_cleanup_failure_is_nonfatal():
    assert cleanup_failure_is_fatal("completed") is False
    assert cleanup_failure_is_fatal("failed_after_submission") is True


def test_routed_project_chat_retries_read_timeout_and_429(monkeypatch, tmp_path):
    cid = "12345678-1234-1234-1234-123456789abc"
    read_attempts = 0
    sleeps: list[float] = []

    def fake_run(args, **kwargs):
        nonlocal read_attempts
        if str(chat.API_SEND_PROMPT) in args:
            result_path = Path(args[args.index("--json") + 1])
            body_path = Path(args[args.index("--record-send-body") + 1])
            result_path.write_text(
                json.dumps(
                    {
                        "conversation_id": cid,
                        "url": f"https://chatgpt.com/c/{cid}",
                        "resolved": True,
                        "sent_at": "2026-09-25T00:00:00+00:00",
                    }
                )
            )
            body_path.write_text("{}")
            return subprocess.CompletedProcess(args, 0, "", "")
        read_attempts += 1
        if read_attempts == 1:
            raise subprocess.TimeoutExpired(args, 30, output="")
        if read_attempts == 2:
            return subprocess.CompletedProcess(
                args, 2, "", "HTTP 429: Too many requests"
            )
        return subprocess.CompletedProcess(args, 0, "header\n\nDONE\n", "")

    monkeypatch.setattr(chat, "_run", fake_run)
    monkeypatch.setattr(chat.time, "sleep", lambda value: sleeps.append(value))
    monkeypatch.setattr(
        "scripts.chat_scheduling_postsend.time.sleep",
        lambda value: sleeps.append(value),
    )

    result = chat.send_project_chat(
        "g-p-project",
        "prompt",
        10,
        tmp_path / "chat-url.txt",
        timing_file=tmp_path / "chat-timing.json",
        system_hint="plugin:plugin_asdk_app_test",
        model="gpt-5-6-thinking",
        effort="max",
    )

    assert result["reply"] == "DONE"
    assert read_attempts == 3
    assert sleeps[:2] == [1.0, 2.0]
