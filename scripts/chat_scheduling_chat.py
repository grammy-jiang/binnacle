"""ChatGPT Project/chat lifecycle helpers for scheduling benchmarks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from scripts.chat_scheduling_postsend import sleep_poll_backoff, transient_read_failure
from scripts.chat_scheduling_runtime import HarnessError, RestoreError, _run

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = PROJECT_ROOT / ".claude" / "skills" / "chatgpt-mcp-dev" / "scripts"
CHAT_BACKUP_DIR = Path.home() / ".local" / "share" / "chatgpt-chats" / "backups"
CHAT_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

WEB_OPS_SCRIPTS = (
    Path.home() / ".claude" / "skills" / "chatgpt-web-operations" / "scripts"
)
API_SEND_PROMPT = WEB_OPS_SCRIPTS / "send_prompt.py"
API_READ_CHAT = WEB_OPS_SCRIPTS / "read_chat.py"

BARE_PRODUCTION_CONNECTOR = re.compile(r"\bRaspberry Pi MCP\b(?! Scheduling\b)")


def render_lane_prompt(prompt: str, connector_logical_name: str) -> str:
    rendered = BARE_PRODUCTION_CONNECTOR.sub(connector_logical_name, prompt)
    if BARE_PRODUCTION_CONNECTOR.search(rendered):
        raise HarnessError("rendered prompt still names the production connector")
    return rendered


def lane_send_options(selected: dict[str, Any]) -> dict[str, str]:
    manifest = json.loads(
        Path(selected["lane_manifest_path"]).read_text(encoding="utf-8")
    )
    app_id = str(manifest.get("app_id") or "")
    system_hint = str(manifest.get("system_hint") or "")
    expected_hint = f"plugin:plugin_{app_id}" if app_id else ""
    if not app_id or system_hint != expected_hint:
        raise HarnessError("lane manifest has invalid connector system hint identity")
    config = selected["model_thinking"].get(
        "server_last_used_model_config", selected["model_thinking"]
    )
    model = str(config.get("model") or "")
    effort = str(config.get("thinking_effort") or "")
    if not model or not effort:
        raise HarnessError("frozen model/thinking state is incomplete")
    return {
        "system_hint": system_hint,
        "model": model,
        "effort": effort,
        "app_id": app_id,
    }


class ProjectClient:
    """Exact Project-instruction read/write through the existing CLI helper."""

    def __init__(self, project_name: str, browser: str = "chrome") -> None:
        self.project_name = project_name
        self.browser = browser
        self.script = SKILL_SCRIPTS / "chatgpt-project"
        self.system_python = Path("/usr/bin/python3")

    def _invoke(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        last_error: subprocess.SubprocessError | None = None
        for attempt in range(3):
            try:
                return _run(args, timeout=30)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(3.0 * (attempt + 1))
        if last_error is None:
            raise HarnessError("Project helper failed without an error")
        raise last_error

    def instructions(self) -> str:
        proc = self._invoke(
            [
                str(self.system_python),
                str(self.script),
                "--browser",
                self.browser,
                "get-instructions",
                self.project_name,
            ]
        )
        out = proc.stdout
        if not out.endswith("\n"):
            raise HarnessError(
                "chatgpt-project returned instructions without print newline"
            )
        # chatgpt-project uses print(stored_text); remove only that print newline.
        return out[:-1]

    def set_instructions(self, text: str) -> None:
        self._invoke(
            [
                str(self.system_python),
                str(self.script),
                "--browser",
                self.browser,
                "set-instructions",
                self.project_name,
                "--text",
                text,
            ]
        )
        if self.instructions() != text:
            raise HarnessError("Project instruction read-back differs after update")


class InstructionLease:
    """Apply one instruction variant and restore exact prior text in all paths."""

    def __init__(
        self,
        client: ProjectClient,
        desired: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.desired = desired
        self.sleep = sleep
        self.original: str | None = None
        self.changed = False

    def __enter__(self) -> InstructionLease:  # noqa: PYI034 - Python 3.10-compatible forward reference
        self.original = self.client.instructions()
        if self.original != self.desired:
            self.client.set_instructions(self.desired)
            self.changed = True
        return self

    def _restore(self) -> None:
        if self.original is None:
            return
        last: Exception | None = None
        for attempt in range(3):
            try:
                if self.client.instructions() != self.original:
                    self.client.set_instructions(self.original)
                if self.client.instructions() != self.original:
                    raise HarnessError("Project instruction restore read-back differs")
                return
            except Exception as exc:  # noqa: BLE001 - restoration must retry normal failures
                last = exc
                if attempt < 2:
                    self.sleep(1.0)
        if last is None:
            raise HarnessError("instruction restore failed without an error")
        raise last

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        try:
            self._restore()
        except Exception as restore_exc:
            raise RestoreError(exc, restore_exc) from restore_exc
        return False


@dataclass
class ChatArtifact:
    project_id: str
    state_dir: Path
    browser: str = "chrome"
    url: str | None = None
    chat_id: str | None = None
    tracked: bool = False
    conversation_saved: bool = False

    @property
    def chats_script(self) -> Path:
        return SKILL_SCRIPTS / "chatgpt-chats"

    def discover(self, url_file: Path) -> None:
        if not url_file.exists():
            return
        value = url_file.read_text(encoding="utf-8").strip()
        match = CHAT_ID_RE.search(value)
        if match:
            self.url = value
            self.chat_id = match.group(0).lower()

    def track(self, note: str) -> None:
        if self.chat_id is None or self.tracked:
            return
        _run(
            [str(self.chats_script), "--track", self.chat_id, "--note", note],
            timeout=10,
        )
        self.tracked = True

    def _copy_delete_backup(self) -> Path:
        if self.chat_id is None:
            raise HarnessError("cannot copy chat backup without a chat id")
        matches = sorted(
            CHAT_BACKUP_DIR.glob(f"*_{self.chat_id}.json"),
            key=lambda path: path.stat().st_mtime_ns,
        )
        if not matches:
            raise HarnessError(
                f"chat {self.chat_id} was deleted but its JSON backup was not found"
            )
        target = self.state_dir / "conversation.json"
        shutil.copy2(matches[-1], target)
        self.conversation_saved = True
        return target

    def cleanup(self) -> dict[str, Any]:
        if self.chat_id is None:
            return {
                "chat_id": None,
                "deleted": False,
                "reason": "no chat id discovered",
            }
        if not self.tracked:
            self.track("Chat scheduling v2 benchmark trial")
        delete_args = [
            "/usr/bin/python3",
            str(self.chats_script),
            "--browser",
            self.browser,
            "--id",
            self.chat_id,
            "--delete",
        ]
        last_delete_error: subprocess.SubprocessError | None = None
        for attempt in range(3):
            try:
                _run(delete_args, timeout=30)
                last_delete_error = None
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                last_delete_error = exc
                if attempt < 2:
                    time.sleep(3.0 * (attempt + 1))
        if last_delete_error is not None:
            raise last_delete_error
        backup = self._copy_delete_backup()
        if self.tracked:
            _run([str(self.chats_script), "--untrack", self.chat_id], timeout=10)
            self.tracked = False
        return {
            "chat_id": self.chat_id,
            "deleted": True,
            "conversation_saved": True,
            "conversation_path": str(backup),
        }


def branch_chatgpt_send() -> Path:
    return SKILL_SCRIPTS / "chatgpt-send"


def _write_timing(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _routed_project_chat(
    project_id: str,
    prompt: str,
    timeout_s: float,
    url_file: Path,
    *,
    browser: str,
    timing_file: Path | None,
    system_hint: str,
    model: str,
    effort: str,
    on_posted: Callable[[], None] | None,
) -> dict[str, Any]:
    prompt_file = url_file.with_name("chat-prompt.txt")
    result_file = url_file.with_name("chat-send.json")
    send_body_file = url_file.with_name("chat-send-body.json")
    prompt_file.write_text(prompt, encoding="utf-8")
    args = [
        "python3",
        str(API_SEND_PROMPT),
        str(prompt_file),
        "--project",
        project_id,
        "--system-hint",
        system_hint,
        "--model",
        model,
        "--effort",
        effort,
        "--json",
        str(result_file),
        "--record-send-body",
        str(send_body_file),
        "--timeout",
        str(timeout_s),
        "--browser",
        browser,
        "--no-wait",
    ]

    # send_prompt.py's single-send failure path deliberately writes no JSON.
    # Once it starts, a non-zero exit can mean the message posted but resolve
    # failed, so trial sends are never automatically retried.
    _run(args, timeout=max(timeout_s + 30, 120))
    result = json.loads(result_file.read_text(encoding="utf-8"))
    conversation_id = str(result.get("conversation_id") or "")
    url = str(result.get("url") or "")
    if (
        not conversation_id
        or not result.get("resolved")
        or not CHAT_ID_RE.fullmatch(conversation_id)
    ):
        raise HarnessError("API-path sender did not resolve an exact conversation id")
    if not url:
        url = f"https://chatgpt.com/c/{conversation_id}"
    url_file.write_text(url + "\n", encoding="utf-8")

    sent_at = result.get("sent_at")
    if send_body_file.exists():
        # The request recorder is written on the f/conversation POST, so its
        # mtime preserves the old harness's Enter/send timing origin much more
        # closely than send_prompt.py's pre-browser "sent_at" bookkeeping.
        sent_epoch = send_body_file.stat().st_mtime
    else:
        try:
            sent_epoch = datetime.fromisoformat(str(sent_at)).timestamp()
        except (TypeError, ValueError):
            sent_epoch = time.time()
    _write_timing(
        timing_file,
        {
            "status": "running",
            "sent_at_epoch_s": sent_epoch,
        },
    )
    if on_posted is not None:
        on_posted()

    deadline = time.monotonic() + timeout_s
    last_text = ""
    transient_failures = 0
    while time.monotonic() < deadline:
        poll_args = ["python3", str(API_READ_CHAT), conversation_id, "--text"]
        try:
            poll = _run(poll_args, timeout=30, check=False)
        except subprocess.TimeoutExpired as exc:
            transient_failures += 1
            if isinstance(exc.output, str) and exc.output.strip():
                last_text = exc.output.strip()
            sleep_poll_backoff(transient_failures, deadline)
            continue
        if poll.returncode == 0:
            _header, separator, reply = poll.stdout.partition("\n\n")
            if not separator:
                raise HarnessError("read_chat.py returned an unexpected reply shape")
            settled_epoch = time.time()
            wall_s = round(max(0.0, settled_epoch - sent_epoch), 3)
            _write_timing(
                timing_file,
                {
                    "status": "complete",
                    "sent_at_epoch_s": sent_epoch,
                    "settled_at_epoch_s": settled_epoch,
                    "wall_s": wall_s,
                },
            )
            result.update(
                {
                    "url": url,
                    "reply": reply.strip(),
                    "sent_at_epoch_s": sent_epoch,
                    "settled_at_epoch_s": settled_epoch,
                    "wall_s": wall_s,
                    "submit_attempts": 1,
                }
            )
            return result
        if poll.returncode != 1:
            if transient_read_failure(f"{poll.stdout}\n{poll.stderr}"):
                transient_failures += 1
                sleep_poll_backoff(transient_failures, deadline)
                continue
            raise HarnessError(
                f"read_chat.py failed with exit code {poll.returncode}: "
                f"{poll.stderr.strip()}"
            )
        _header, separator, tail = poll.stdout.partition("\n\n")
        if separator:
            last_text = tail.strip()
        transient_failures = 0
        time.sleep(1.0)

    observed_epoch = time.time()
    _write_timing(
        timing_file,
        {
            "status": "timeout",
            "sent_at_epoch_s": sent_epoch,
            "observed_at_epoch_s": observed_epoch,
            "wall_s": round(max(0.0, observed_epoch - sent_epoch), 3),
            "last_text": last_text,
        },
    )
    raise subprocess.TimeoutExpired(args, timeout_s, output=last_text)


def send_project_chat(
    project_id: str,
    prompt: str,
    timeout_s: float,
    url_file: Path,
    *,
    browser: str = "chrome",
    timing_file: Path | None = None,
    system_hint: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    on_posted: Callable[[], None] | None = None,
) -> dict[str, Any]:
    routed = (system_hint, model, effort)
    if any(value is not None for value in routed):
        if not system_hint or not model or not effort:
            raise HarnessError(
                "routed trial send requires system_hint, model and effort"
            )
        return _routed_project_chat(
            project_id,
            prompt,
            timeout_s,
            url_file,
            browser=browser,
            timing_file=timing_file,
            system_hint=system_hint,
            model=model,
            effort=effort,
            on_posted=on_posted,
        )

    args = [
        str(branch_chatgpt_send()),
        "--browser",
        browser,
        "--project",
        project_id,
        "--json",
        "--url-file",
        str(url_file),
        *(["--timing-file", str(timing_file)] if timing_file is not None else []),
        "--timeout",
        str(timeout_s),
        prompt,
    ]

    last_error: subprocess.SubprocessError | None = None
    for attempt in range(3):
        try:
            proc = _run(args, timeout=timeout_s + 30)
            result = json.loads(proc.stdout)
            result["submit_attempts"] = attempt + 1
            if on_posted is not None:
                on_posted()
            return result
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            # Safe automatic retry is only allowed before any evidence that
            # Enter created/submitted a conversation. Once either artifact
            # exists, retrying could duplicate a real ChatGPT turn.
            submitted = url_file.exists() or (
                timing_file is not None and timing_file.exists()
            )
            if submitted or attempt == 2:
                raise
            time.sleep(3.0)

    if last_error is None:
        raise HarnessError("chat submit failed without an error")
    raise last_error
