"""Parse Binnacle single-line journal evidence for scheduling benchmarks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from binnacle.logstats import plain_fields

_LOG_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?) "
    r"(?:INFO|WARNING|ERROR): event=(?P<event>\w+)(?P<body>.*)$"
)


@dataclass
class RawCall:
    call_id: str
    tool: str
    turn: str | None
    client: str
    start_epoch_s: float
    args: dict[str, Any]
    args_raw: str
    end_epoch_s: float | None = None
    result_fields: dict[str, str] | None = None


@dataclass
class RawJob:
    job_id: str
    start_epoch_s: float
    end_epoch_s: float | None = None
    exit_code: int | None = None
    signal: int | None = None


def local_epoch(timestamp: str) -> float:
    """Interpret Binnacle's embedded local ISO timestamp on the benchmark host."""
    return datetime.fromisoformat(timestamp).astimezone().timestamp()


def json_args(raw: str) -> dict[str, Any]:
    if not raw or raw.endswith("..."):
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def as_bool(value: str | None) -> bool:
    return (value or "").lower() == "true"


def as_int(value: str | None) -> int | None:
    if value in (None, "None", "null"):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def as_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def coerce_fields(fields: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    int_keys = {
        "exit_code",
        "signal",
        "tokenizer_tokens",
        "est_tokens",
        "structured_bytes",
        "content_chars",
        "log_bytes",
        "output_bytes",
        "wait_requested_s",
        "wait_effective_s",
        "blocking_budget_s",
    }
    float_keys = {"waited_s", "runtime_s", "last_output_age_s", "duration_ms"}
    bool_keys = {
        "is_error",
        "background_job",
        "truncated",
        "quiet",
        "blocking_budget_exhausted",
    }
    for key, value in fields.items():
        if key in int_keys:
            out[key] = as_int(value)
        elif key in float_keys:
            out[key] = as_float(value)
        elif key in bool_keys:
            out[key] = as_bool(value)
        else:
            out[key] = value
    return out


def parse_journal(text: str) -> tuple[list[RawCall], list[RawJob]]:
    calls: dict[str, RawCall] = {}
    jobs: dict[str, RawJob] = {}
    for line in text.splitlines():
        match = _LOG_LINE.match(line)
        if not match:
            continue
        epoch = local_epoch(match.group("ts"))
        event = match.group("event")
        body = "event=" + event + match.group("body")
        fields = plain_fields(body)
        if event == "tool_call":
            call_id = fields.get("call")
            if not call_id:
                continue
            args_raw = fields.get("args", "")
            calls[call_id] = RawCall(
                call_id=call_id,
                tool=fields.get("tool", "?"),
                turn=(fields.get("turn") or "").split("/", 1)[0] or None,
                client=fields.get("client", "-"),
                start_epoch_s=epoch,
                args=json_args(args_raw),
                args_raw=args_raw,
            )
        elif event == "tool_result":
            call_id = fields.get("call")
            if call_id in calls:
                calls[call_id].end_epoch_s = epoch
                calls[call_id].result_fields = fields
        elif event == "job_start":
            job_id = fields.get("job_id")
            if job_id:
                jobs[job_id] = RawJob(job_id=job_id, start_epoch_s=epoch)
        elif event == "job_exit":
            job_id = fields.get("job_id")
            if not job_id:
                continue
            job = jobs.setdefault(job_id, RawJob(job_id=job_id, start_epoch_s=epoch))
            job.end_epoch_s = epoch
            job.exit_code = as_int(fields.get("exit_code"))
            job.signal = as_int(fields.get("signal"))
    return (
        sorted(calls.values(), key=lambda call: call.start_epoch_s),
        sorted(jobs.values(), key=lambda job: job.start_epoch_s),
    )
