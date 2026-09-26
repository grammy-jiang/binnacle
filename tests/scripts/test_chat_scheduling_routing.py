import json
import subprocess
from pathlib import Path

import pytest

from scripts import chat_scheduling_chat as chat


@pytest.mark.parametrize("lane", ["A", "B", "C300", "H"])
def test_rendered_prompt_uses_frozen_lane_connector_without_bare_production_name(lane):
    manifest_path = (
        chat.PROJECT_ROOT
        / "benchmarks"
        / "chat-mode-scheduling-v2"
        / "phase4-lanes"
        / f"{lane}.json"
    )
    connector = json.loads(manifest_path.read_text())["connector_logical_name"]
    prompt = "Use only Raspberry Pi MCP read_file. Reply only DONE."
    rendered = chat.render_lane_prompt(prompt, connector)

    assert connector in rendered
    assert not chat.BARE_PRODUCTION_CONNECTOR.search(rendered)
    assert lane in connector


def test_lane_send_options_use_manifest_hint_and_frozen_model_effort(tmp_path):
    manifest = {
        "app_id": "asdk_app_lane",
        "system_hint": "plugin:plugin_asdk_app_lane",
    }
    path = tmp_path / "B.json"
    path.write_text(json.dumps(manifest))
    selected = {
        "lane_manifest_path": str(path),
        "model_thinking": {
            "server_last_used_model_config": {
                "model": "gpt-5-6-thinking",
                "thinking_effort": "max",
            }
        },
    }

    assert chat.lane_send_options(selected) == {
        "system_hint": "plugin:plugin_asdk_app_lane",
        "model": "gpt-5-6-thinking",
        "effort": "max",
        "app_id": "asdk_app_lane",
    }


def test_routed_send_argv_pins_lane_project_hint_model_effort(monkeypatch, tmp_path):
    calls = []
    cid = "12345678-1234-1234-1234-123456789abc"

    def fake_run(args, **kwargs):
        calls.append(args)
        if str(chat.API_SEND_PROMPT) in args:
            out = Path(args[args.index("--json") + 1])
            send_body = Path(args[args.index("--record-send-body") + 1])
            send_body.write_text('{"sent":"body"}')
            out.write_text(
                json.dumps(
                    {
                        "conversation_id": cid,
                        "url": f"https://chatgpt.com/c/{cid}",
                        "sent_at": "2026-09-25T11:30:00+00:00",
                        "resolved": True,
                    }
                )
            )
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(
            args,
            0,
            "title\n2 message(s), last is text, 1 visible reply(ies)\n"
            "turn finished: yes, ready to collect\n\nDONE\n",
            "",
        )

    monkeypatch.setattr(chat, "_run", fake_run)
    monkeypatch.setattr(chat.time, "sleep", lambda _value: None)
    timing = tmp_path / "chat-timing.json"
    url = tmp_path / "chat-url.txt"
    result = chat.send_project_chat(
        "g-p-lane",
        "Use Raspberry Pi MCP Scheduling B read_file.",
        80,
        url,
        timing_file=timing,
        system_hint="plugin:plugin_asdk_app_lane",
        model="gpt-5-6-thinking",
        effort="max",
    )

    send = calls[0]
    assert send[0:2] == ["python3", str(chat.API_SEND_PROMPT)]
    assert send[send.index("--project") + 1] == "g-p-lane"
    assert send[send.index("--system-hint") + 1] == "plugin:plugin_asdk_app_lane"
    assert send[send.index("--model") + 1] == "gpt-5-6-thinking"
    assert send[send.index("--effort") + 1] == "max"
    assert send[send.index("--record-send-body") + 1].endswith("chat-send-body.json")
    assert "--no-wait" in send
    assert Path(send[2]).read_text() == "Use Raspberry Pi MCP Scheduling B read_file."
    assert url.read_text().strip().endswith(cid)
    timing_doc = json.loads(timing.read_text())
    assert timing_doc["status"] == "complete"
    assert timing_doc["first_seen_at_epoch_s"] >= timing_doc["sent_at_epoch_s"]
    assert result["reply"] == "DONE"
    assert result["submit_attempts"] == 1


def test_routed_send_does_not_retry_sender_failure(monkeypatch, tmp_path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(chat, "_run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        chat.send_project_chat(
            "g-p-lane",
            "prompt",
            80,
            tmp_path / "chat-url.txt",
            timing_file=tmp_path / "chat-timing.json",
            system_hint="plugin:plugin_asdk_app_lane",
            model="gpt-5-6-thinking",
            effort="max",
        )

    assert len(calls) == 1
    assert not (tmp_path / "chat-url.txt").exists()
