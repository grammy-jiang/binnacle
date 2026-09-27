"""chatgpt-send runs the chatgpt-web-operations skill's send_prompt.py (2026-09-27).

No browser and no network: send_prompt.py is replaced by a fake process that
writes what the real one writes (the POST-body record when it posts, the
--json document and its output when it ends) on a schedule of poll() calls.
"""

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "chatgpt-mcp-dev"
    / "scripts"
    / "chatgpt-send"
)
CID = "12345678-1234-1234-1234-123456789abc"
PROJECT = "g-p-" + "a" * 32


def _module():
    loader = SourceFileLoader("chatgpt_send_skill_script", str(SCRIPT))
    spec = importlib.util.spec_from_loader("chatgpt_send_skill_script", loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _doc(cid=CID, reply="DONE", resolved=True):
    return {
        "conversation_id": cid,
        "url": f"https://chatgpt.com/c/{cid}",
        "resolved": resolved,
        "reply": reply,
        "sent_at": "2026-09-27T00:36:51+00:00",
    }


class FakeProc:
    """send_prompt.py as seen by chatgpt-send: files appear as poll() is called."""

    def __init__(self, argv, kwargs, *, post_at, exit_at, rc, doc, output, watch):
        self.argv, self.kwargs = argv, kwargs
        self.post_at, self.exit_at, self.rc = post_at, exit_at, rc
        self.doc, self.output, self.watch = doc, output, watch
        self.polls, self.returncode, self.terminated = 0, None, False
        self.seen: dict[str, bool] = {}

    def _arg(self, flag):
        return Path(self.argv[self.argv.index(flag) + 1])

    def poll(self):
        self.polls += 1
        if self.post_at is not None and self.polls == self.post_at:
            self._arg("--record-send-body").write_text("{}")
        if self.post_at is not None and self.polls == self.post_at + 1:
            # what a caller can see while the skill is still waiting
            self.seen = {name: path.exists() for name, path in self.watch.items()}
        if self.exit_at is not None and self.polls >= self.exit_at:
            self._finish()
        return self.returncode

    def _finish(self):
        if self.returncode is None:
            if self.rc == 0 and self.doc is not None:
                self._arg("--json").write_text(json.dumps(self.doc))
            self.kwargs["stdout"].write(self.output)
            self.kwargs["stdout"].flush()
            self.returncode = self.rc

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def _run(
    module,
    tmp_path,
    *,
    chat=None,
    project=PROJECT,
    post_at=2,
    exit_at=4,
    rc=0,
    doc=None,
    output="",
    timeout=120.0,
):
    url_file, timing_file = tmp_path / "url.txt", tmp_path / "timing.json"
    procs = []

    def popen(argv, **kwargs):
        procs.append(
            FakeProc(
                argv,
                kwargs,
                post_at=post_at,
                exit_at=exit_at,
                rc=rc,
                doc=_doc() if doc is None and rc == 0 else doc,
                output=output,
                watch={"url": url_file, "timing": timing_file},
            )
        )
        return procs[-1]

    t = [1000.0]

    def clock():
        return t[0]

    def sleep(seconds):
        t[0] += seconds

    result = module.run(
        chat,
        "hello",
        "chrome",
        timeout,
        False,
        project,
        str(url_file),
        str(timing_file),
        popen=popen,
        clock=clock,
        sleep=sleep,
    )
    return result, procs[0]


def _timing(tmp_path):
    return json.loads((tmp_path / "timing.json").read_text())


def test_send_argv_runs_send_prompt_in_its_waiting_mode(tmp_path):
    module = _module()
    base = module.send_argv(
        tmp_path / "p",
        tmp_path / "j",
        tmp_path / "b",
        chat=None,
        project=None,
        browser="auto",
        visible=False,
        timeout_s=180.0,
    )
    assert base[1].endswith("send_prompt.py") and base[2] == str(tmp_path / "p")
    assert "--no-wait" not in base
    assert base[base.index("--timeout") + 1] == "180"
    assert base[base.index("--browser") + 1] == "auto"
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
        timeout_s=42.5,
    )
    assert full[full.index("--chat") + 1] == CID
    assert full[full.index("--project") + 1] == PROJECT
    assert "--visible" in full and full[full.index("--timeout") + 1] == "42.5"


def test_success_builds_the_outputs_from_the_skill_json(tmp_path):
    module = _module()
    result, proc = _run(module, tmp_path)
    assert result["url"] == f"https://chatgpt.com/c/{CID}"
    assert result["reply"] == "DONE" and result["confirmations_clicked"] == 0
    assert result["buttons_seen"] == [] and result["conversation_id"] == CID
    assert result["sent_at_source"] == "post_record"
    assert result["settle_time_source"] == "send_prompt_poll"
    assert (tmp_path / "url.txt").read_text().strip() == result["url"]
    timing = _timing(tmp_path)
    assert timing["status"] == "complete"
    assert timing["sent_at_epoch_s"] == result["sent_at_epoch_s"]
    # evidence of the POST exists while the skill is still waiting ...
    assert proc.seen == {"url": False, "timing": True}
    env = proc.kwargs["env"]
    assert env["RP_NEWCHAT_FAST"] == "1" and env["RP_RECORD_STREAM"] == "0"
    assert proc.kwargs["preexec_fn"] is module._die_with_parent


def test_existing_chat_gets_its_url_file_at_the_post(tmp_path):
    module = _module()
    _, proc = _run(module, tmp_path, chat=CID, project=None)
    assert proc.seen == {"url": True, "timing": True}
    assert proc.argv[proc.argv.index("--chat") + 1] == CID


def test_a_failure_before_the_post_leaves_no_evidence(tmp_path, capsys):
    module = _module()
    with pytest.raises(SystemExit):
        _run(
            module,
            tmp_path,
            post_at=None,
            exit_at=2,
            rc=1,
            output="1/2 sending\nsend failed: composer did not appear\n",
        )
    assert (
        not (tmp_path / "url.txt").exists() and not (tmp_path / "timing.json").exists()
    )
    err = capsys.readouterr().err
    assert "not posted" in err and "composer did not appear" in err


def test_a_reply_timeout_after_the_post_is_a_timeout(tmp_path):
    module = _module()
    with pytest.raises(SystemExit):
        _run(
            module,
            tmp_path,
            rc=1,
            output="send failed: assistant did not finish within 120 s (x)\n",
        )
    timing = _timing(tmp_path)
    assert timing["status"] == "timeout" and "wall_s" in timing


def test_another_failure_after_the_post_blocks_a_retry(tmp_path):
    module = _module()
    with pytest.raises(SystemExit):
        _run(module, tmp_path, rc=1, output="send failed: message was not posted\n")
    assert _timing(tmp_path)["status"] == "submitted_unconfirmed"


def test_an_unresolved_new_chat_is_a_failure(tmp_path):
    module = _module()
    with pytest.raises(SystemExit):
        _run(module, tmp_path, doc=_doc(cid="WEB:" + CID, resolved=False))
    assert _timing(tmp_path)["status"] == "submitted_unconfirmed"


def test_the_send_is_stopped_after_timeout_plus_the_overrun(tmp_path, capsys):
    module = _module()
    with pytest.raises(SystemExit):
        _run(module, tmp_path, exit_at=None, timeout=10.0)
    assert _timing(tmp_path)["status"] == "timeout"
    assert f"stopped after {10 + module.OVERRUN_S:g} s" in capsys.readouterr().err


def test_the_post_time_falls_back_to_the_skill_start_time(tmp_path):
    module = _module()
    result, _ = _run(module, tmp_path, post_at=None)
    assert result["sent_at_source"] == "send_prompt_start"
    expected = datetime(2026, 9, 27, 0, 36, 51, tzinfo=timezone.utc).timestamp()
    assert result["sent_at_epoch_s"] == expected


def test_a_missing_send_prompt_is_a_clear_failure(tmp_path, capsys):
    module = _module()

    def popen(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    with pytest.raises(SystemExit):
        module.run(None, "hi", "chrome", 5.0, popen=popen)
    assert "could not start" in capsys.readouterr().err


def test_die_with_parent_asks_for_sigterm_and_tolerates_no_libc(monkeypatch):
    module = _module()
    calls = []

    class FakeLibc:
        def prctl(self, *args):
            calls.append(args)

    monkeypatch.setattr(module.ctypes, "CDLL", lambda *a, **k: FakeLibc())
    module._die_with_parent()
    assert calls == [(1, module.signal.SIGTERM)]

    def no_libc(*a, **k):
        raise OSError("no libc.so.6")

    monkeypatch.setattr(module.ctypes, "CDLL", no_libc)
    module._die_with_parent()  # not Linux: no death signal, no error


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
    python, script = tmp_path / "python", tmp_path / "send_prompt.py"
    python.write_text("")
    script.write_text("")
    monkeypatch.setattr(module, "SKILL_PYTHON", python)
    monkeypatch.setattr(module, "SEND_PROMPT", script)
    monkeypatch.setattr(module, "run", lambda *a, **k: result)
    monkeypatch.setattr(sys, "argv", ["chatgpt-send", "--chat", CID, "--json", "hi"])
    module.main()
    assert json.loads(capsys.readouterr().out)["reply"] == "DONE"
    monkeypatch.setattr(sys, "argv", ["chatgpt-send", "--chat", CID, "hi"])
    module.main()
    assert capsys.readouterr().out.splitlines() == [
        f"[{result['url']}] confirmations clicked: 0",
        "DONE",
    ]


def test_main_refuses_without_the_skill(tmp_path, monkeypatch, capsys):
    module = _module()
    monkeypatch.setattr(module, "SKILL_PYTHON", tmp_path / "missing")
    monkeypatch.setattr(sys, "argv", ["chatgpt-send", "--new", "hi"])
    with pytest.raises(SystemExit):
        module.main()
    assert "skill is missing" in capsys.readouterr().err


def test_subprocess_is_the_default_launcher():
    module = _module()
    assert module.run.__kwdefaults__["popen"] is subprocess.Popen
