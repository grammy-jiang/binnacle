"""chatgpt-send posts through the chatgpt-web-operations skill (2026-09-27).

No browser and no network: the skill's send_prompt.py is replaced by a fake
runner that writes what the real one writes, and the skill's client and
session by small fakes.
"""

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_DIR = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "chatgpt-mcp-dev"
    / "scripts"
)
SCRIPT = SCRIPT_DIR / "chatgpt-send"
CID = "12345678-1234-1234-1234-123456789abc"
PROJECT = "g-p-" + "a" * 32


def _module():
    loader = SourceFileLoader("chatgpt_send_skill_script", str(SCRIPT))
    spec = importlib.util.spec_from_loader("chatgpt_send_skill_script", loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _conversation(turns=1, create_time=1_790_000_050.0, text="DONE"):
    message = {
        "author": {"role": "assistant"},
        "status": "finished_successfully",
        "end_turn": True,
        "metadata": {"is_complete": True},
        "content": {"parts": [text]},
    }
    if create_time is not None:
        message["create_time"] = create_time
    return {"turns": turns, "current_node": "a", "mapping": {"a": {"message": message}}}


class FakeCC:
    class TransportError(RuntimeError):
        pass

    def __init__(self, reply="DONE", error=None):
        self.reply, self.error, self.wait_kwargs = reply, error, None

    @staticmethod
    def user_turns(conv):
        return conv["turns"]

    @staticmethod
    def is_provisional(chat):
        return chat.startswith(("WEB:", "local-chatgpt:"))

    def wait_for_reply(self, session, chat, **kwargs):
        self.wait_kwargs = dict(kwargs, chat=chat)
        session.get_conversation(chat)
        if self.error is not None:
            raise self.error
        return self.reply


class FakeSession:
    def __init__(self, conv):
        self.conv, self.reads = conv, 0

    def get_conversation(self, chat):
        self.reads += 1
        return self.conv


def _runner(doc=None, rc=0, write_body=True, calls=None):
    """A stand-in for subprocess.run over the skill's send_prompt.py."""

    def run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        if write_body:
            Path(argv[argv.index("--record-send-body") + 1]).write_text("{}")
        if rc == 0 and doc is not None:
            Path(argv[argv.index("--json") + 1]).write_text(json.dumps(doc))
        return subprocess.CompletedProcess(argv, rc, stdout="", stderr="boom\n")

    return run


def _doc(cid=CID, resolved=True):
    return {
        "conversation_id": cid,
        "url": f"https://chatgpt.com/c/{cid}",
        "resolved": resolved,
    }


def _clock():
    t = [1000.0]

    def clock():
        t[0] += 1.0
        return t[0]

    return clock


def _run(
    module,
    tmp_path,
    *,
    chat=None,
    project=PROJECT,
    runner=None,
    cc=None,
    conv=None,
    factory=None,
):
    cc = cc or FakeCC()
    session = FakeSession(conv or _conversation())
    return (
        module.run(
            chat,
            "hello",
            "chrome",
            120.0,
            False,
            project,
            str(tmp_path / "url.txt"),
            str(tmp_path / "timing.json"),
            cc=cc,
            session_factory=factory or (lambda browser: session),
            runner=runner or _runner(_doc()),
            clock=_clock(),
        ),
        cc,
        session,
    )


def test_send_argv_maps_every_option(tmp_path):
    module = _module()
    base = module.send_argv(
        tmp_path / "p",
        tmp_path / "j",
        tmp_path / "b",
        chat=None,
        project=None,
        browser="chrome",
        visible=False,
    )
    assert base[1].endswith("send_prompt.py") and base[2] == str(tmp_path / "p")
    assert "--no-wait" in base and base[base.index("--browser") + 1] == "chrome"
    assert base[base.index("--json") + 1] == str(tmp_path / "j")
    assert base[base.index("--record-send-body") + 1] == str(tmp_path / "b")
    assert "--chat" not in base and "--project" not in base and "--visible" not in base
    full = module.send_argv(
        tmp_path / "p",
        tmp_path / "j",
        tmp_path / "b",
        chat=CID,
        project=PROJECT,
        browser="chromium",
        visible=True,
    )
    assert full[full.index("--chat") + 1] == CID
    assert full[full.index("--project") + 1] == PROJECT
    assert "--visible" in full and full[full.index("--browser") + 1] == "chromium"


def test_success_writes_evidence_and_returns_the_old_result_keys(tmp_path):
    module = _module()
    calls = []
    result, cc, _ = _run(module, tmp_path, runner=_runner(_doc(), calls=calls))
    assert result["url"] == f"https://chatgpt.com/c/{CID}"
    assert result["reply"] == "DONE" and result["confirmations_clicked"] == 0
    assert result["buttons_seen"] == []
    assert result["settle_time_source"] == "conversation_final_assistant_timestamp"
    assert result["settled_at_epoch_s"] == 1_790_000_050.0
    assert (tmp_path / "url.txt").read_text().strip() == result["url"]
    timing = json.loads((tmp_path / "timing.json").read_text())
    assert timing["status"] == "complete"
    assert timing["sent_at_epoch_s"] == result["sent_at_epoch_s"]
    assert cc.wait_kwargs["min_user_turns"] == 1 and cc.wait_kwargs["chat"] == CID
    assert cc.wait_kwargs["interval"] == module.POLL_INTERVAL_S
    env = calls[0][1]["env"]
    assert env["RP_NEWCHAT_FAST"] == "1" and env["RP_RECORD_STREAM"] == "0"
    assert calls[0][1]["timeout"] <= module.POST_BUDGET_S


def test_existing_chat_waits_for_the_turn_after_the_ones_already_there(tmp_path):
    module = _module()
    _, cc, session = _run(
        module, tmp_path, chat=CID, project=None, conv=_conversation(turns=3)
    )
    assert cc.wait_kwargs["min_user_turns"] == 4
    assert session.reads >= 2  # the count before the post, then the wait


def test_a_failure_before_the_post_leaves_no_evidence(tmp_path):
    module = _module()
    with pytest.raises(SystemExit):
        _run(module, tmp_path, runner=_runner(rc=1, write_body=False))
    assert (
        not (tmp_path / "url.txt").exists() and not (tmp_path / "timing.json").exists()
    )


def test_a_failure_after_the_post_body_was_recorded_blocks_a_retry(tmp_path):
    module = _module()
    with pytest.raises(SystemExit):
        _run(module, tmp_path, runner=_runner(rc=1, write_body=True))
    timing = json.loads((tmp_path / "timing.json").read_text())
    assert timing["status"] == "submitted_unconfirmed"
    assert not (tmp_path / "url.txt").exists()


def test_an_unresolved_new_chat_id_is_a_failure_with_evidence(tmp_path):
    module = _module()
    with pytest.raises(SystemExit):
        _run(module, tmp_path, runner=_runner(_doc(cid="WEB:" + CID, resolved=False)))
    assert (
        json.loads((tmp_path / "timing.json").read_text())["status"]
        == "submitted_unconfirmed"
    )


def test_a_reply_timeout_writes_timeout_timing(tmp_path):
    module = _module()
    cc = FakeCC(error=TimeoutError("assistant did not finish"))
    with pytest.raises(SystemExit):
        _run(module, tmp_path, cc=cc)
    timing = json.loads((tmp_path / "timing.json").read_text())
    assert timing["status"] == "timeout" and timing["last_text"] == "DONE"
    assert (tmp_path / "url.txt").exists()  # the chat exists and can be cleaned up


def test_a_session_failure_happens_before_anything_is_posted(tmp_path):
    module = _module()
    calls = []

    def factory(browser):
        raise RuntimeError("could not decode a decrypted cookie value")

    with pytest.raises(SystemExit):
        _run(module, tmp_path, runner=_runner(_doc(), calls=calls), factory=factory)
    assert calls == []
    assert not (tmp_path / "timing.json").exists()


def test_settle_time_falls_back_to_the_observed_time(tmp_path):
    module = _module()
    result, _, _ = _run(module, tmp_path, conv=_conversation(create_time=None))
    assert result["settle_time_source"] == "observed"


def test_chat_and_project_arguments_are_validated():
    module = _module()
    assert module.chat_arg(CID.upper()) == CID
    assert module.chat_arg(f"https://chatgpt.com/g/{PROJECT}/project/c/{CID}") == CID
    assert module.project_arg(f"https://chatgpt.com/g/{PROJECT}/project") == PROJECT
    with pytest.raises(SystemExit):
        module.chat_arg("not-a-chat")
    with pytest.raises(SystemExit):
        module.project_arg("g-p-short")


def test_main_prints_json_and_plain_output(tmp_path, monkeypatch, capsys):
    module = _module()
    result = {
        "url": f"https://chatgpt.com/c/{CID}",
        "confirmations_clicked": 0,
        "reply": "DONE",
    }
    monkeypatch.setattr(module, "_reexec_in_skill_venv", lambda: None)
    monkeypatch.setattr(module, "run", lambda *a, **k: result)
    fake_session_module = type(sys)("chatgpt_session")
    fake_session_module.pick_browser = lambda choice: "chrome"
    monkeypatch.setitem(sys.modules, "chatgpt_session", fake_session_module)
    fake_cc = type(sys)("chatgpt_client")
    fake_cc.ChatGPTSession = object
    monkeypatch.setitem(sys.modules, "chatgpt_client", fake_cc)
    monkeypatch.setattr(sys, "argv", ["chatgpt-send", "--chat", CID, "--json", "hi"])
    module.main()
    assert json.loads(capsys.readouterr().out)["reply"] == "DONE"
    monkeypatch.setattr(sys, "argv", ["chatgpt-send", "--chat", CID, "hi"])
    module.main()
    out = capsys.readouterr().out.splitlines()
    assert out == [f"[{result['url']}] confirmations clicked: 0", "DONE"]
