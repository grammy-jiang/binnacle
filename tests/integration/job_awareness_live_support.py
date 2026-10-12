"""Shared fixtures for the production Job Awareness hint tests.

``Jobs`` is an in-memory command backend with many jobs: each start returns a
new 12-hex job id in state ``running``, and ``finish`` makes it exit. The
application is the real ``create_application`` tree. Calls go over native
streamable HTTP (stateful, as in production) with the strict FastMCP client,
which validates every structured result against the listed output schema.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import httpx2
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.types import Implementation

from binnacle.application import create_application
from binnacle.config import JobAwarenessSettings, RootsSettings, Settings

TOKEN = "synthetic-live-token"
CHATGPT = "openai-mcp"


def session_value(seed: str) -> str:
    """A synthetic well-formed ``openai/session`` value (79 characters)."""
    body = (seed * 80).replace(" ", "_")[:76]
    return "v1/" + body


def subject_value(seed: str = "subject") -> str:
    return "v1/" + (seed * 60)[:54]


def conversation(seed: str) -> tuple[dict[str, str], dict[str, str]]:
    """Matching headers and ``_meta`` for one synthetic conversation."""
    session, subject = session_value(seed), subject_value()
    headers = {"x-openai-session": session, "x-openai-subject": subject}
    meta = {"openai/session": session, "openai/subject": subject}
    return headers, meta


class Jobs:
    owner_mode = "test-owner"
    warmup_s = 0.0
    max_output_chars = 1000

    def __init__(self) -> None:
        self.states: dict[str, dict] = {}
        self.reads: list[str] = []
        self.fail_reads = False
        self.started = 0

    def __bool__(self) -> bool:
        return False

    def __deepcopy__(self, memo):
        raise AssertionError("a backend is shared, never copied")

    def start_and_wait(self, command, workdir, stdin, wait_seconds):
        self.started += 1  # deterministic ids keep golden bytes comparable
        job_id = f"{0xA0B0C0D00000 + self.started:012x}"
        self.states[job_id] = {
            "job_id": job_id,
            "state": "running",
            "exit_code": None,
            "signal": None,
            "runtime_s": 0.5,
            "last_output_age_s": 0.1,
            "started_at": "2026-10-12T00:00:00+00:00",
            "pgid": 4242,
            "log_bytes": 6,
            "log_path": f"/fake/{job_id}/out.log",
            "command": command,
            "workdir": str(workdir),
        }
        return job_id

    def finish(self, job_id: str, exit_code: int = 0, signal: int | None = None):
        self.states[job_id] = {
            **self.states[job_id],
            "state": "exited",
            "exit_code": None if signal is not None else exit_code,
            "signal": signal,
        }

    def job_state(self, job_id):
        self.reads.append(job_id)
        if self.fail_reads:
            raise RuntimeError("synthetic read failure")
        state = self.states.get(job_id)
        return dict(state) if state else None

    def list_jobs(self):
        return [dict(s) for s in self.states.values()]

    def await_exit(self, job_id, timeout):
        return self.job_state(job_id)

    def read_log(self, job_id):
        return b"ready\n"

    def read_log_range(self, job_id, start, max_bytes):
        return b"ready\n"[start : start + max_bytes], 6

    def job_processes(self, job_id, max_cmd_chars=200):
        return []

    def stop_job(self, job_id):
        if job_id not in self.states:
            return None
        self.finish(job_id, signal=15)
        return dict(self.states[job_id])


def settings(root: Path, *, enabled: bool | None) -> Settings:
    roots = RootsSettings(default_root=root, extra_roots=())
    if enabled is None:
        built = Settings(roots=roots)
    else:
        built = Settings(
            roots=roots, job_awareness=JobAwarenessSettings(hints_enabled=enabled)
        )
    built.jobs.socket_path = root / "manager.sock"
    built.jobs.owner = "embedded"
    return built


def application(root: Path, *, enabled: bool | None, backend: Jobs | None = None):
    backend = Jobs() if backend is None else backend
    app = create_application(
        settings=settings(root, enabled=enabled), token=TOKEN, backend=backend
    )
    return app, backend


@asynccontextmanager
async def http_client(app, *, name=CHATGPT, headers=None, raw=None):
    """A strict client over stateful streamable HTTP; ``raw`` collects bodies."""
    http_app = app.http_app()

    async def record(response):
        body = await response.aread()
        if raw is not None and body:
            raw.append(body)

    def factory(**kwargs):
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=http_app),
            event_hooks={"response": [record]},
            **kwargs,
        )

    async with http_app.router.lifespan_context(http_app):
        transport = StreamableHttpTransport(
            "http://binnacle/mcp",
            httpx_client_factory=factory,
            headers={"authorization": f"Bearer {TOKEN}", **(headers or {})},
        )
        with patch("mcp.client.session.LATEST_HANDSHAKE_VERSION", "2025-06-18"):
            async with Client(
                transport,
                mode="legacy",
                client_info=Implementation(name=name, version="0"),
            ) as client:
                yield client


def hint_of(result) -> str | None:
    structured = result.structured_content or {}
    return structured.get("job_awareness_hint")


def payloads(raw: list[bytes]) -> list[bytes]:
    """The JSON-RPC message bytes of each recorded HTTP body (SSE or JSON)."""
    out: list[bytes] = []
    for body in raw:
        lines = [
            line[5:].strip() for line in body.splitlines() if line.startswith(b"data:")
        ]
        out.extend(line for line in lines if line) if lines else out.append(body)
    return out


def message(payload: bytes) -> dict:
    return json.loads(payload)
