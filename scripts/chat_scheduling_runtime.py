"""Runtime primitives for the Chat scheduling v2 benchmark harness.

This module owns safety/lifecycle mechanics only: disposable fixtures, exact
Project-instruction restore, test-chat tracking/backup/deletion, local MCP
fixture jobs, and production-state invariants. It does not score benchmarks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastmcp import Client

from scripts.chat_scheduling_manifest import Scenario

FIXTURE_BASE = Path("/tmp/binnacle-chat-scheduling-v2")
STATE_BASE = Path.home() / ".local" / "state" / "binnacle" / "chat-scheduling-v2"
PRODUCTION_REPO = Path.home() / "Projects" / "binnacle"
CONFIG_PATH = Path.home() / ".config" / "binnacle" / "config.toml"
UNIT_PATH = Path.home() / ".config" / "systemd" / "user" / "binnacle-mcp.service"
TOKEN_PATH = Path.home() / ".config" / "binnacle" / "token"
LOCAL_MCP_URL = "http://127.0.0.1:8000/mcp"


class HarnessError(RuntimeError):
    """Benchmark lifecycle failure."""


class RestoreError(HarnessError):
    """Project instructions could not be restored."""

    def __init__(self, original: BaseException | None, restore: BaseException):
        self.original = original
        self.restore = restore
        detail = f"project-instruction restore failed: {restore}"
        if original is not None:
            detail += f"; original trial error was: {original}"
        super().__init__(detail)


@dataclass(frozen=True)
class TrialIdentity:
    scenario_id: str
    run_id: str
    nonce: str

    @classmethod
    def create(cls, scenario_id: str) -> TrialIdentity:
        stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
        run_id = f"{scenario_id.lower()}-{stamp}-{uuid.uuid4().hex[:10]}"
        return cls(scenario_id=scenario_id, run_id=run_id, nonce=secrets.token_hex(16))


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=check,
    )


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def render_text(
    text: str,
    identity: TrialIdentity,
    root: Path,
    jobs: dict[str, str] | None = None,
) -> str:
    replacements = {
        "id": identity.scenario_id,
        "run_id": identity.run_id,
        "nonce": identity.nonce,
        "root": str(root),
    }
    out = text
    for key, value in replacements.items():
        out = out.replace("{" + key + "}", value)
    for name, job_id in (jobs or {}).items():
        out = out.replace("{job:" + name + "}", job_id)
    return out


@dataclass
class ProductionSnapshot:
    head: str
    status: str
    config_sha256: str | None
    unit_sha256: str | None
    active_state: str
    sub_state: str

    @classmethod
    def capture(cls) -> ProductionSnapshot:
        head = _run(["git", "rev-parse", "HEAD"], cwd=PRODUCTION_REPO).stdout.strip()
        status = _run(
            ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
            cwd=PRODUCTION_REPO,
        ).stdout
        active = _run(
            [
                "systemctl",
                "--user",
                "show",
                "binnacle-mcp.service",
                "-p",
                "ActiveState",
                "--value",
            ]
        ).stdout.strip()
        sub = _run(
            [
                "systemctl",
                "--user",
                "show",
                "binnacle-mcp.service",
                "-p",
                "SubState",
                "--value",
            ]
        ).stdout.strip()
        return cls(
            head=head,
            status=status,
            config_sha256=_sha256(CONFIG_PATH),
            unit_sha256=_sha256(UNIT_PATH),
            active_state=active,
            sub_state=sub,
        )

    def assert_unchanged(self, after: ProductionSnapshot) -> None:
        changed = []
        for name in (
            "head",
            "status",
            "config_sha256",
            "unit_sha256",
            "active_state",
            "sub_state",
        ):
            if getattr(self, name) != getattr(after, name):
                changed.append(name)
        if changed:
            raise HarnessError(
                "production invariant changed during benchmark: " + ", ".join(changed)
            )


class LocalMCP:
    """Out-of-band local MCP client used only for benchmark fixture lifecycle."""

    def __init__(self, url: str = LOCAL_MCP_URL, token_path: Path = TOKEN_PATH) -> None:
        self.url = url
        self.token_path = token_path

    def _token(self) -> str:
        return (
            self.token_path.read_text(encoding="utf-8")
            .strip()
            .removeprefix("Bearer ")
            .strip()
        )

    async def _call_async(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with Client(self.url, auth=self._token()) as client:
            result = await client.call_tool(name, arguments)
            if result.structured_content is None:
                raise HarnessError(f"local MCP {name} returned no structured content")
            return result.structured_content

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._call_async(name, arguments))

    def start_job(self, command: str, workdir: Path) -> str:
        out = self.call(
            "run_command",
            {
                "command": command,
                "workdir": str(workdir),
                "wait_seconds": 1,
                "background": True,
                "tail_lines": 20,
            },
        )
        job_id = out.get("job_id")
        if not job_id:
            raise HarnessError("fixture job did not return a job_id")
        return str(job_id)

    def stop_root_jobs(self, root: Path) -> list[str]:
        stopped: list[str] = []
        listing = self.call("job_status", {})
        for item in listing.get("jobs", []):
            if item.get("state") != "running":
                continue
            workdir = Path(item.get("workdir") or "/")
            if not _is_under(workdir, root):
                continue
            job_id = str(item["job_id"])
            self.call("stop_job", {"job_id": job_id})
            stopped.append(job_id)
        return stopped


@dataclass
class FixtureLease:
    scenario: Scenario
    identity: TrialIdentity
    mcp: LocalMCP
    root: Path = field(init=False)
    jobs: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        template = self.scenario.fixture.root_template
        if template is None:
            self.root = FIXTURE_BASE / self.identity.run_id
        else:
            self.root = Path(
                render_text(
                    template, self.identity, FIXTURE_BASE / self.identity.run_id
                )
            )
        if not _is_under(self.root, FIXTURE_BASE):
            raise HarnessError(f"unsafe fixture root: {self.root}")

    def __enter__(self) -> FixtureLease:  # noqa: PYI034 - Python 3.10-compatible forward reference
        if self.root.exists():
            raise HarnessError(f"fixture root already exists: {self.root}")
        self.root.mkdir(parents=True)
        for item in self.scenario.fixture.files:
            target = self.root / item.path
            if not _is_under(target, self.root):
                raise HarnessError(f"unsafe fixture file: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                render_text(item.content, self.identity, self.root),
                encoding="utf-8",
            )
        if self.scenario.fixture.kind == "ephemeral_git_repo":
            self._init_git()
        for job in self.scenario.fixture.jobs:
            if not job.prelaunch:
                continue
            command = render_text(job.command, self.identity, self.root, self.jobs)
            self.jobs[job.name] = self.mcp.start_job(command, self.root)
        return self

    def _init_git(self) -> None:
        _run(["git", "init", "-q"], cwd=self.root)
        _run(["git", "add", "-A"], cwd=self.root)
        _run(
            [
                "git",
                "-c",
                "user.name=Binnacle Benchmark",
                "-c",
                "user.email=benchmark.invalid@example.invalid",
                "commit",
                "-qm",
                "fixture baseline",
            ],
            cwd=self.root,
        )

    def rendered_prompt(self) -> str:
        return render_text(
            self.scenario.prompt_template, self.identity, self.root, self.jobs
        )

    def cleanup(self) -> dict[str, Any]:
        stopped: list[str] = []
        errors: list[str] = []
        try:
            stopped = self.mcp.stop_root_jobs(self.root)
        except Exception as exc:  # noqa: BLE001 - cleanup must continue to fixture removal
            errors.append(f"job cleanup: {exc}")
        try:
            if self.root.exists():
                shutil.rmtree(self.root)
        except Exception as exc:  # noqa: BLE001 - report cleanup failure in trial state
            errors.append(f"fixture cleanup: {exc}")
        return {
            "stopped_jobs": stopped,
            "errors": errors,
            "root_removed": not self.root.exists(),
        }

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        cleanup = self.cleanup()
        if cleanup["errors"] and exc is None:
            raise HarnessError("; ".join(cleanup["errors"]))
        return False


def new_state_dir(identity: TrialIdentity, base: Path = STATE_BASE) -> Path:
    path = base / "runs" / identity.run_id
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_json(path: Path, value: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
