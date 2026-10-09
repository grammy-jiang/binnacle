"""Usage statistics from the server's journal (`binnacle stats`).

Parses MCP/jobs journals into request, tool, latency, command, target, timeline,
error, and durable-job statistics. Stdlib only; journalctl is the external process.

Parsing notes learned the hard way: a record may start mid-second as an
*indented* ``INFO event=`` line (rich omits the repeated timestamp), the
timestamp only ever appears at column 0, and wrapped payload lines must be
rejoined without separators because rich breaks anywhere, including inside
tokens.

binnacle's own records (``tool_call``, ``tool_result``, ``job_start``,
``job_exit``, ``jobs_pruned``, ``config``) are single ``LEVEL: event=``
lines through the root handler, never wrapped: ``INFO: event=...`` up to
2026-09-13, then ``2026-09-13T22:30:00.123 INFO: event=...`` with their own
millisecond timestamp (docs/logging.md). Both shapes parse here.
"""

import re
from collections import defaultdict, deque

from binnacle.observability.logstats_adaptive import analyze_adaptive_discovery
from binnacle.observability.logstats_io import fetch_journal
from binnacle.observability.logstats_jobs import analyze_job_telemetry
from binnacle.observability.logstats_models import Record, Stats
from binnacle.observability.logstats_parse import (
    _base_turn as _parse_base_turn,
)
from binnacle.observability.logstats_parse import (
    _int as _parse_int,
)
from binnacle.observability.logstats_parse import (
    _json_args,
    plain_fields,
)
from binnacle.observability.logstats_parse import (
    _path_hash as _parse_path_hash,
)
from binnacle.observability.logstats_render import render
from binnacle.observability.logstats_run_command import analyze_run_command_workflow
from binnacle.observability.logstats_search_exact import analyze_exact_search
from binnacle.observability.logstats_tools import (
    analyze_tool_call,
    analyze_tool_config,
    analyze_tool_result,
)

# Helper-level aliases remain for this canonical parser's tests and consumers.
# The retired binnacle.logstats module path is intentionally not restored.
_base_turn = _parse_base_turn
_int = _parse_int
_path_hash = _parse_path_hash

_REC_START = re.compile(
    r"^\s*(?:\[(\d{2}/\d{2}/\d{2}) (\d{2}:\d{2}:\d{2})\] )?(?:INFO|ERROR|WARNING)\s+event=(\w+)"
)
_TS_COL0 = re.compile(r"^\[(\d{2}/\d{2}/\d{2}) (\d{2}:\d{2}:\d{2})\]")
# binnacle's single-line records: an optional ISO local timestamp (2026-09-13
# on), the level with a colon, then the event.
_PLAIN_START = re.compile(
    r"^(?:(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)? )?"
    r"(?:INFO|WARNING|ERROR): event=(\w+)(.*)$"
)
_PLAIN_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?) ")
_LOGREF = re.compile(r"\s+logging\.py:\d+")
_METHOD = re.compile(r"method=([\w/]+)")
_DURATION = re.compile(r"duration_ms=([\d.]+)")
_TOOL = re.compile(r'"name":"([a-z_]+)","arguments"')
_CLIENT = re.compile(r'clientInfo\\?":\s*{\\?"name\\?":\\?"([^"\\]+)')
# Keys the server's RequestLoggingMiddleware appends (2026-09-02 on), in
# emission order; older journal windows lack them and fall back to the
# payload regexes and order-based duration pairing. Two parsing traps,
# both from rejoining wrapped lines without separators: adjacent keys can
# glue ("request_id=0session=aaaa"), and payloads may contain lookalike
# text. So values end only at one of OUR OWN key names (closed set), and
# each key is searched after the previous one's match (the appended block
# always follows the payload).
_APPENDED_KEYS = ("request_id", "session", "client", "tool")
_BOUNDARY = r"(?=(?:{})=|\s|$)".format("|".join(_APPENDED_KEYS))
_REQUEST_ID = re.compile(r"request_id=([\w-]+?)" + _BOUNDARY)
_SESSION_KEY = re.compile(r"session=([\w-]+?)" + _BOUNDARY)
_CLIENT_KEY = re.compile(r"client=(\S+?)" + _BOUNDARY)
_TOOL_KEY = re.compile(r"tool=([a-z_]+)")


def _appended_fields(body: str) -> dict[str, str]:
    """The middleware-appended key block, parsed by positional chaining."""
    fields: dict[str, str] = {}
    pos = 0
    m = _REQUEST_ID.search(body)
    if m:
        fields["request_id"] = m.group(1)
        pos = m.end()
    for name, rx in (
        ("session", _SESSION_KEY),
        ("client", _CLIENT_KEY),
        ("tool", _TOOL_KEY),
    ):
        m = rx.search(body, pos)
        if m:
            fields[name] = m.group(1)
            pos = m.end()
    return fields


_COMMAND = re.compile(r'"command":"((?:[^"\\]|\\.){0,120})')
_PATH = re.compile(r'"path":"((?:[^"\\]|\\.){0,160})')
_ERROR = re.compile(r"error=(.*)$")

STARTUP_MARK = "Application startup complete"

__all__ = [
    "Record",
    "Stats",
    "analyze",
    "fetch_journal",
    "parse",
    "plain_fields",
    "render",
]


def parse(text: str) -> tuple[list[Record], int]:
    """Rejoin the wrapped middleware records; also count server startups."""
    records: list[Record] = []
    cur: Record | None = None
    day = time = None
    startups = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if STARTUP_MARK in line:
            startups += 1
        ts = _TS_COL0.match(line)
        if ts:
            day, time = ts.group(1), ts.group(2)
        plain = _PLAIN_START.match(line)
        if plain:
            timestamp_match = _PLAIN_TIMESTAMP.match(line)
            # A binnacle single-line record closes any open rich record.
            if cur:
                records.append(cur)
                cur = None
            year, month, dom, clock, event, rest = plain.groups()
            records.append(
                Record(
                    event=event,
                    body="event=" + event + rest,
                    day=f"{month}/{dom}/{year[2:]}" if year else day,
                    time=clock or time,
                    timestamp=timestamp_match.group(1) if timestamp_match else None,
                )
            )
            continue
        start = _REC_START.match(line)
        if start:
            if cur:
                records.append(cur)
            body = _LOGREF.sub("", line.split("event=", 1)[1]).strip()
            cur = Record(event=start.group(3), body="event=" + body, day=day, time=time)
            continue
        if cur is not None and line.startswith("        "):
            cur.body += _LOGREF.sub("", line).strip()
            continue
        if cur is not None:
            records.append(cur)
            cur = None
    if cur:
        records.append(cur)
    return records, startups


def _first_word(command: str) -> str:
    words = command.split()
    return words[0] if words else "?"


def _area(path: str) -> str:
    p = path.replace("\\/", "/")
    parts = p.split("/")
    if "Projects" in parts:
        i = parts.index("Projects")
        return "/".join(parts[: i + 2])
    if p.startswith("/tmp"):
        return "/tmp/..."
    return p


def _request_key(fields: dict[str, str]) -> str | None:
    """(session, request_id) pairing key: request ids restart per session."""
    rid = fields.get("request_id")
    if not rid or rid == "-":
        return None
    return f"{fields.get('session', '-')}:{rid}"


def analyze(records: list[Record], startups: int = 0) -> Stats:
    st = Stats(records=len(records), startups=startups)
    pending: dict[str, deque] = defaultdict(deque)
    by_id: dict[tuple[str, str], str | None] = {}
    for r in records:
        st.events[r.event] += 1
        method_m = _METHOD.search(r.body)
        method = method_m.group(1) if method_m else "?"
        fields = _appended_fields(r.body)
        if r.event == "request_start":
            st.methods[method] += 1
            if r.day:
                st.per_day[r.day] += 1
                st.per_hour[f"{r.day} {(r.time or '??')[:2]}:00"] += 1
            if fields.get("client", "-") != "-":
                st.clients[fields["client"]] += 1
            else:
                client = _CLIENT.search(r.body)
                st.clients[
                    client.group(1) if client else "(no per-request clientInfo)"
                ] += 1
            tool = None
            if method == "tools/call":
                tool_m = _TOOL.search(r.body)
                tool = fields.get("tool") or (tool_m.group(1) if tool_m else None)
                st.tools[tool or "(name beyond payload clip)"] += 1
                cmd_m = _COMMAND.search(r.body)
                if cmd_m:
                    st.commands[_first_word(cmd_m.group(1))] += 1
                path_m = _PATH.search(r.body)
                if path_m:
                    st.areas[_area(path_m.group(1))] += 1
            rid = _request_key(fields)
            if rid is not None:
                by_id[(method, rid)] = tool
            else:
                pending[method].append(tool)
        elif r.event in ("request_success", "request_error"):
            rid = _request_key(fields)
            if rid is not None and (method, rid) in by_id:
                tool = by_id.pop((method, rid))
            else:
                tool = pending[method].popleft() if pending[method] else None
            dur_m = _DURATION.search(r.body)
            if dur_m:
                st.durations[tool or method].append(float(dur_m.group(1)))
            if r.event == "request_error":
                err_m = _ERROR.search(r.body)
                stamp = f"{r.day} {r.time}" if r.day else "?"
                st.errors.append(
                    f"[{stamp}] {method}: {err_m.group(1) if err_m else r.body[:160]}"
                )
        elif r.event == "tool_call":
            f = plain_fields(r.body)
            if "turn" in f:
                st.turn_calls[f["turn"].split("/")[0]] += 1
            analyze_tool_call(st, f, _json_args(r.body))
        elif r.event == "tool_config":
            analyze_tool_config(st, plain_fields(r.body))
        elif r.event == "tool_result":
            analyze_tool_result(st, plain_fields(r.body))
        elif r.event == "job_exit":
            f = plain_fields(r.body)
            signal = f.get("signal")
            if signal not in (None, "None", "null"):
                st.job_exits[f"signal {signal}"] += 1
            else:
                st.job_exits[f.get("exit_code", "?")] += 1
    st.adaptive = analyze_adaptive_discovery(records)
    st.jobs = analyze_job_telemetry(records, plain_fields)
    st.run_command = analyze_run_command_workflow(records, plain_fields)
    st.exact_search = analyze_exact_search(records, plain_fields)
    return st
