import json
import subprocess
from pathlib import Path

from scripts import chat_scheduling_chat as chat
from scripts import chat_scheduling_postsend as postsend
from scripts.chat_scheduling_postsend import (
    captured_send_reply,
    cleanup_failure_is_fatal,
    finalize_conversation_timing,
)


def _fake_send(args, cid: str):
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


def test_captured_send_reply_falls_back_without_conversation_backup():
    reply, complete = captured_send_reply(
        {"submission_status": "completed", "chat": {"send_result": {"reply": "DONE"}}}
    )
    assert reply == "DONE"
    assert complete is True


def test_completed_submission_cleanup_failure_is_nonfatal():
    assert cleanup_failure_is_fatal("completed") is False
    assert cleanup_failure_is_fatal("failed_after_submission") is True


def test_routed_project_chat_gently_polls_at_ten_second_minimum(monkeypatch, tmp_path):
    cid = "12345678-1234-1234-1234-123456789abc"
    read_attempts = 0
    sleeps: list[float] = []

    def fake_run(args, **kwargs):
        nonlocal read_attempts
        if str(chat.API_SEND_PROMPT) in args:
            return _fake_send(args, cid)
        read_attempts += 1
        if read_attempts < 3:
            return subprocess.CompletedProcess(
                args, 1, "header\n\n(no visible reply yet)\n", ""
            )
        return subprocess.CompletedProcess(args, 0, "header\n\nDONE\n", "")

    monkeypatch.setattr(chat, "_run", fake_run)
    monkeypatch.setattr(postsend.secrets, "randbelow", lambda _n: 0)
    monkeypatch.setattr(postsend.time, "sleep", lambda value: sleeps.append(value))

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
    assert sleeps == [5.0, 10.0, 10.0]


def test_routed_project_chat_backs_off_timeout_403_and_429(monkeypatch, tmp_path):
    cid = "12345678-1234-1234-1234-123456789abc"
    read_attempts = 0
    sleeps: list[float] = []

    def fake_run(args, **kwargs):
        nonlocal read_attempts
        if str(chat.API_SEND_PROMPT) in args:
            return _fake_send(args, cid)
        read_attempts += 1
        if read_attempts == 1:
            raise subprocess.TimeoutExpired(args, 30, output="")
        if read_attempts == 2:
            return subprocess.CompletedProcess(
                args, 2, "", "HTTP 403: Cloudflare challenge"
            )
        if read_attempts == 3:
            return subprocess.CompletedProcess(
                args, 2, "", "HTTP 429: Too many requests"
            )
        return subprocess.CompletedProcess(args, 0, "header\n\nDONE\n", "")

    monkeypatch.setattr(chat, "_run", fake_run)
    monkeypatch.setattr(postsend.secrets, "randbelow", lambda _n: 0)
    monkeypatch.setattr(postsend.time, "sleep", lambda value: sleeps.append(value))

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
    assert read_attempts == 4
    assert sleeps == [5.0, 10.0, 20.0, 40.0]


def test_routed_project_chat_observes_past_turn_limit(monkeypatch, tmp_path):
    cid = "12345678-1234-1234-1234-123456789abc"
    read_attempts = 0
    clock = {"now": 0.0}

    def sleep(value):
        clock["now"] += value

    def fake_run(args, **kwargs):
        nonlocal read_attempts
        if str(chat.API_SEND_PROMPT) in args:
            return _fake_send(args, cid)
        read_attempts += 1
        if read_attempts == 1:
            return subprocess.CompletedProcess(
                args, 1, "header\n\n(no visible reply yet)\n", ""
            )
        return subprocess.CompletedProcess(args, 0, "header\n\nDONE\n", "")

    monkeypatch.setattr(chat, "_run", fake_run)
    monkeypatch.setattr(postsend.secrets, "randbelow", lambda _n: 0)
    monkeypatch.setattr(postsend.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(postsend.time, "sleep", sleep)

    result = chat.send_project_chat(
        "g-p-project",
        "prompt",
        1,
        tmp_path / "chat-url.txt",
        timing_file=tmp_path / "chat-timing.json",
        system_hint="plugin:plugin_asdk_app_test",
        model="gpt-5-6-thinking",
        effort="max",
    )

    assert result["reply"] == "DONE"
    assert read_attempts == 2
    assert clock["now"] == 15.0


def test_conversation_timestamp_overrides_late_first_seen_time(tmp_path):
    timing_path = tmp_path / "chat-timing.json"
    conversation_path = tmp_path / "conversation.json"
    timing_path.write_text(
        json.dumps(
            {
                "status": "complete",
                "sent_at_epoch_s": 100.0,
                "first_seen_at_epoch_s": 230.0,
                "observed_at_epoch_s": 230.0,
                "observed_wall_s": 130.0,
                "wall_s": 130.0,
                "turn_limit_s": 110.0,
            }
        )
    )
    conversation_path.write_text(
        json.dumps(
            {
                "current_node": "a",
                "mapping": {
                    "a": {
                        "message": {
                            "author": {"role": "assistant"},
                            "create_time": 118.0,
                            "update_time": 122.0,
                            "status": "finished_successfully",
                            "end_turn": True,
                            "content": {"parts": ["DONE"]},
                            "metadata": {"is_complete": True},
                        }
                    }
                },
            }
        )
    )

    timing = finalize_conversation_timing(timing_path, conversation_path)

    assert timing is not None
    assert timing["settled_at_epoch_s"] == 118.0
    assert timing["wall_s"] == 18.0
    assert timing["first_seen_at_epoch_s"] == 230.0
    assert timing["within_turn_limit"] is True
