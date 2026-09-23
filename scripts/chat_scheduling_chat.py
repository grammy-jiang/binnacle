"""ChatGPT Project/chat lifecycle helpers for scheduling benchmarks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from scripts.chat_scheduling_runtime import HarnessError, RestoreError, _run

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = PROJECT_ROOT / ".claude" / "skills" / "chatgpt-mcp-dev" / "scripts"
CHAT_BACKUP_DIR = Path.home() / ".local" / "share" / "chatgpt-chats" / "backups"
CHAT_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


class ProjectClient:
    """Exact Project-instruction read/write through the existing CLI helper."""

    def __init__(self, project_name: str, browser: str = "chrome") -> None:
        self.project_name = project_name
        self.browser = browser
        self.script = SKILL_SCRIPTS / "chatgpt-project"

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


def send_project_chat(
    project_id: str,
    prompt: str,
    timeout_s: float,
    url_file: Path,
    *,
    browser: str = "chrome",
    timing_file: Path | None = None,
) -> dict[str, Any]:
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
    for attempt in range(2):
        try:
            proc = _run(args, timeout=timeout_s + 30)
            result = json.loads(proc.stdout)
            result["submit_attempts"] = attempt + 1
            return result
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            # Safe automatic retry is only allowed before any evidence that
            # Enter created/submitted a conversation. Once either artifact
            # exists, retrying could duplicate a real ChatGPT turn.
            submitted = url_file.exists() or (
                timing_file is not None and timing_file.exists()
            )
            if submitted or attempt == 1:
                raise
            time.sleep(3.0)

    if last_error is None:
        raise HarnessError("chat submit failed without an error")
    raise last_error
