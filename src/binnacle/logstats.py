"""Usage statistics from the server's journal (`binnacle stats`).

Parses the rich-wrapped LoggingMiddleware records that binnacle-mcp writes
to the user journal and aggregates them: request and tool mix, latency
percentiles, clients, run_command verbs, target areas, timeline, errors.
Stdlib only; journalctl is the single external process.

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

import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
_PLAIN_KV = re.compile(r"(\w+)=(\S+)")
# Keys whose value is free text (spaces allowed); each is the last key on
# its line, so the value runs to the end of the record.
_PLAIN_TAIL_KEYS = (" args=", " error=")
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


def plain_fields(body: str) -> dict[str, str]:
    """key=value fields of a single-line binnacle record.

    The free-text tail (``args=`` on tool_call, ``error=`` on tool_result)
    is split off first at the earliest such key, so its content cannot
    masquerade as further keys.
    """
    head, tail_key, tail = body, None, None
    cut = min(
        (i for i in (body.find(k) for k in _PLAIN_TAIL_KEYS) if i >= 0),
        default=-1,
    )
    if cut >= 0:
        key = next(k for k in _PLAIN_TAIL_KEYS if body.find(k) == cut)
        head, tail_key, tail = body[:cut], key.strip()[:-1], body[cut + len(key) :]
    fields = dict(_PLAIN_KV.findall(head))
    if tail_key is not None and tail is not None:
        fields[tail_key] = tail
    return fields


_COMMAND = re.compile(r'"command":"((?:[^"\\]|\\.){0,120})')
_PATH = re.compile(r'"path":"((?:[^"\\]|\\.){0,160})')
_ERROR = re.compile(r"error=(.*)$")

STARTUP_MARK = "Application startup complete"


@dataclass
class Record:
    event: str
    body: str
    day: str | None = None
    time: str | None = None


@dataclass
class IndexedContextStats:
    successes: int = 0
    errors: int = 0
    error_phases: Counter = field(default_factory=Counter)
    pilot_versions: Counter = field(default_factory=Counter)
    schema_versions: Counter = field(default_factory=Counter)
    parser_versions: Counter = field(default_factory=Counter)
    cold_opens: int = 0
    changed_files: int = 0
    evidence_opened: int = 0
    evidence_reads: int = 0
    evidence_file_searches: int = 0
    result_tokens: list[int] = field(default_factory=list)
    package_est_tokens: list[int] = field(default_factory=list)
    package_bytes: list[int] = field(default_factory=list)
    package_items: list[int] = field(default_factory=list)
    total_ms: list[float] = field(default_factory=list)
    reconcile_ms: list[float] = field(default_factory=list)
    query_ms: list[float] = field(default_factory=list)
    followup_calls: list[int] = field(default_factory=list)
    followup_exact_searches: list[int] = field(default_factory=list)
    followup_reads: list[int] = field(default_factory=list)
    followup_result_tokens: list[int] = field(default_factory=list)
    investigation_result_tokens: list[int] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Stats:
    records: int = 0
    startups: int = 0
    events: Counter = field(default_factory=Counter)
    methods: Counter = field(default_factory=Counter)
    tools: Counter = field(default_factory=Counter)
    clients: Counter = field(default_factory=Counter)
    commands: Counter = field(default_factory=Counter)
    areas: Counter = field(default_factory=Counter)
    per_day: Counter = field(default_factory=Counter)
    per_hour: Counter = field(default_factory=Counter)
    durations: dict = field(default_factory=lambda: defaultdict(list))
    errors: list = field(default_factory=list)
    # From the single-line tool_call / tool_result / job_exit records
    # (2026-09-13 on; earlier windows leave these empty).
    results: Counter = field(default_factory=Counter)  # tool -> sized results
    result_tokens: dict = field(default_factory=lambda: defaultdict(list))
    call_durations: dict = field(default_factory=lambda: defaultdict(list))
    truncated: Counter = field(default_factory=Counter)  # tool -> truncated=true
    tool_errors: Counter = field(default_factory=Counter)  # "tool: class" -> n
    background_jobs: int = 0
    job_exits: Counter = field(default_factory=Counter)  # exit code / signal -> n
    turn_calls: Counter = field(default_factory=Counter)  # tunnel turn -> calls
    indexed: IndexedContextStats = field(default_factory=IndexedContextStats)


def fetch_journal(unit: str, since: str, until: str | None = None) -> str:
    cmd = [
        "journalctl",
        "--user",
        "-u",
        unit,
        "--since",
        since,
        "-o",
        "cat",
        "--no-pager",
    ]
    if until:
        cmd += ["--until", until]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"journalctl failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


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


def _json_args(body: str) -> dict[str, Any]:
    raw = plain_fields(body).get("args")
    if not raw or raw.endswith("..."):
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _base_turn(value: str | None) -> str:
    return (value or "-").split("/", 1)[0]


def _path_hash(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.home() / "Projects" / path
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]


def _int(value: str | None) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _float(value: str | None) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def analyze_indexed_context(records: list[Record]) -> IndexedContextStats:
    """Join indexed first hops to later repository-tool calls in the same turn."""
    out = IndexedContextStats()
    calls: dict[str, dict[str, Any]] = {}
    results: dict[str, dict[str, str]] = {}
    dispatch: dict[str, str] = {}
    indexed: list[tuple[int, dict[str, str]]] = []

    for seq, record in enumerate(records):
        if record.event == "tool_call":
            f = plain_fields(record.body)
            call = f.get("call")
            if call:
                calls[call] = {
                    "seq": seq,
                    "tool": f.get("tool", "?"),
                    "turn": _base_turn(f.get("turn")),
                    "args": _json_args(record.body),
                }
        elif record.event == "tool_result":
            f = plain_fields(record.body)
            if f.get("call"):
                results[f["call"]] = f
        elif record.event == "search_dispatch":
            f = plain_fields(record.body)
            if f.get("call"):
                dispatch[f["call"]] = f.get("mode", "unknown")
        elif record.event == "index_context_error":
            f = plain_fields(record.body)
            out.errors += 1
            out.error_phases[f.get("phase", "unknown")] += 1
        elif record.event == "index_context":
            indexed.append((seq, plain_fields(record.body)))

    ordered = sorted(calls.items(), key=lambda item: item[1]["seq"])
    for seq, f in indexed:
        call_id = f.get("call", "-")
        origin = calls.get(call_id, {})
        turn = origin.get("turn", "-")
        evidence = {
            item
            for item in f.get("evidence_hashes", "").split(",")
            if item and item != "-"
        }
        followups = [
            (cid, call)
            for cid, call in ordered
            if call["seq"] > seq
            and call["turn"] == turn
            and cid != call_id
            and call["tool"] in {"search_text", "read_file", "list_files"}
        ]
        exact = [
            item
            for item in followups
            if item[1]["tool"] == "search_text" and dispatch.get(item[0]) == "exact"
        ]
        reads = [item for item in followups if item[1]["tool"] == "read_file"]
        evidence_reads = sum(
            isinstance(call["args"].get("path"), str)
            and _path_hash(call["args"]["path"]) in evidence
            for _, call in reads
        )
        evidence_searches = sum(
            isinstance(call["args"].get("path"), str)
            and Path(call["args"]["path"]).suffix != ""
            and _path_hash(call["args"]["path"]) in evidence
            for _, call in exact
        )
        follow_tokens = sum(
            _int(results.get(cid, {}).get("est_tokens")) for cid, _ in followups
        )
        result_tokens = _int(results.get(call_id, {}).get("est_tokens"))
        row = {
            "call": call_id,
            "turn": turn,
            "pilot_version": f.get("pilot_version", "unknown"),
            "schema_version": _int(f.get("schema_version")),
            "parser_version": _int(f.get("parser_version")),
            "root_hash": f.get("root_hash", "-"),
            "query_hash": f.get("query_hash", "-"),
            "head": f.get("head", "unknown"),
            "generation": _int(f.get("generation")),
            "result_tokens": result_tokens,
            "package_est_tokens": _int(f.get("package_est_tokens")),
            "package_bytes": _int(f.get("package_bytes")),
            "package_items": _int(f.get("package_items")),
            "total_ms": _float(f.get("total_ms")),
            "reconcile_ms": _float(f.get("reconcile_ms")),
            "query_ms": _float(f.get("query_ms")),
            "changed_files": _int(f.get("changed_files")),
            "cold_open": f.get("cold_open") == "true",
            "followup_calls": len(followups),
            "followup_exact_searches": len(exact),
            "followup_reads": len(reads),
            "followup_result_tokens": follow_tokens,
            "investigation_result_tokens": result_tokens + follow_tokens,
            "evidence_reads": evidence_reads,
            "evidence_file_searches": evidence_searches,
        }
        out.successes += 1
        out.pilot_versions[row["pilot_version"]] += 1
        out.schema_versions[str(row["schema_version"])] += 1
        out.parser_versions[str(row["parser_version"])] += 1
        out.cold_opens += int(row["cold_open"])
        out.changed_files += int(row["changed_files"])
        out.evidence_opened += int(bool(evidence_reads or evidence_searches))
        out.evidence_reads += evidence_reads
        out.evidence_file_searches += evidence_searches
        for attr in (
            "result_tokens",
            "package_est_tokens",
            "package_bytes",
            "package_items",
            "total_ms",
            "reconcile_ms",
            "query_ms",
            "followup_calls",
            "followup_exact_searches",
            "followup_reads",
            "followup_result_tokens",
            "investigation_result_tokens",
        ):
            getattr(out, attr).append(row[attr])
        out.rows.append(row)
    return out


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
        elif r.event == "tool_result":
            _analyze_result(st, plain_fields(r.body))
        elif r.event == "job_exit":
            f = plain_fields(r.body)
            signal = f.get("signal")
            if signal not in (None, "None", "null"):
                st.job_exits[f"signal {signal}"] += 1
            else:
                st.job_exits[f.get("exit_code", "?")] += 1
    st.indexed = analyze_indexed_context(records)
    return st


def _analyze_result(st: Stats, f: dict[str, str]) -> None:
    """One tool_result record. Lines before 2026-09-13 carry only the
    summary's content_chars and no est_tokens; they count nowhere here."""
    tool = f.get("tool", "?")
    if f.get("est_tokens", "").isdigit():
        st.results[tool] += 1
        st.result_tokens[tool].append(int(f["est_tokens"]))
    if f.get("truncated") == "true":
        st.truncated[tool] += 1
    try:
        st.call_durations[tool].append(float(f["duration_ms"]))
    except (KeyError, ValueError):
        pass
    if f.get("is_error") == "True":
        st.tool_errors[f"{tool}: {f.get('error_class', '?')}"] += 1
    if f.get("background_job") == "true":
        st.background_jobs += 1


def _pct(values: Sequence[int | float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0}
    return {
        "mean": sum(values) / len(values),
        "p50": _pct(values, 0.5),
        "p90": _pct(values, 0.9),
        "max": max(values),
    }


def indexed_context_report(idx: IndexedContextStats) -> dict[str, Any]:
    """JSON-friendly summary used by the CLI section and detailed pilot script."""
    return {
        "indexed_successes": idx.successes,
        "indexed_errors": idx.errors,
        "error_phases": dict(idx.error_phases),
        "pilot_versions": dict(idx.pilot_versions),
        "schema_versions": dict(idx.schema_versions),
        "parser_versions": dict(idx.parser_versions),
        "cold_opens": idx.cold_opens,
        "changed_files": idx.changed_files,
        "evidence_open_conversion": (
            idx.evidence_opened / idx.successes if idx.successes else 0.0
        ),
        "evidence_reads": idx.evidence_reads,
        "evidence_file_searches": idx.evidence_file_searches,
        "result_tokens": _distribution([float(x) for x in idx.result_tokens]),
        "package_est_tokens": _distribution([float(x) for x in idx.package_est_tokens]),
        "package_bytes": _distribution([float(x) for x in idx.package_bytes]),
        "package_items": _distribution([float(x) for x in idx.package_items]),
        "latency_total_ms": _distribution(idx.total_ms),
        "latency_reconcile_ms": _distribution(idx.reconcile_ms),
        "latency_query_ms": _distribution(idx.query_ms),
        "followup_calls": _distribution([float(x) for x in idx.followup_calls]),
        "followup_exact_searches": _distribution(
            [float(x) for x in idx.followup_exact_searches]
        ),
        "followup_reads": _distribution([float(x) for x in idx.followup_reads]),
        "followup_result_tokens": _distribution(
            [float(x) for x in idx.followup_result_tokens]
        ),
        "investigation_result_tokens": _distribution(
            [float(x) for x in idx.investigation_result_tokens]
        ),
        "rows": idx.rows,
    }


def render(st: Stats) -> str:
    out: list[str] = []
    starts = st.events.get("request_start", 0)
    errors = st.events.get("request_error", 0)
    if starts:
        out.append(
            f"requests: {starts}   errors: {errors} ({100 * errors / starts:.2f}%)"
        )
    else:
        out.append("requests: 0")
    out.append(f"server startups in window: {st.startups}")

    out.append("\ntools/call by tool:")
    for name, n in st.tools.most_common():
        out.append(f"  {name:24s} {n}")

    out.append("\nrequests by method:")
    for name, n in st.methods.most_common():
        out.append(f"  {name:28s} {n}")

    out.append("\nduration_ms (n / p50 / p90 / max):")
    for name, values in sorted(st.durations.items(), key=lambda kv: -len(kv[1])):
        if len(values) >= 3:
            out.append(
                f"  {name:24s} n={len(values):5d}  p50={_pct(values, 0.5):9.1f}"
                f"  p90={_pct(values, 0.9):9.1f}  max={max(values):10.1f}"
            )

    out.append("\nclients (per-request clientInfo where present):")
    for name, n in st.clients.most_common():
        out.append(f"  {name:32s} {n}")

    if st.commands:
        out.append("\nrun_command first words (top 15):")
        for name, n in st.commands.most_common(15):
            out.append(f"  {name:24s} {n}")

    if st.areas:
        out.append("\nfile-tool target areas (top 12):")
        for name, n in st.areas.most_common(12):
            out.append(f"  {name:48s} {n}")

    out.append("\nrequests per day:")
    for day in sorted(st.per_day):
        out.append(f"  {day}  {st.per_day[day]}")

    out.append("\nbusiest hours (top 8):")
    for hour, n in st.per_hour.most_common(8):
        out.append(f"  {hour}  {n}")

    if st.errors:
        out.append("\nrequest_error details:")
        out.extend(f"  {e}" for e in st.errors)

    if st.results:
        out.append(
            "\nresult size by tool, est_tokens = chars/4 (n / p50 / p90 / max / total):"
        )
        for name, values in sorted(
            st.result_tokens.items(), key=lambda kv: -sum(kv[1])
        ):
            out.append(
                f"  {name:24s} n={len(values):5d}  p50={_pct(values, 0.5):7.0f}"
                f"  p90={_pct(values, 0.9):7.0f}  max={max(values):8.0f}"
                f"  total={sum(values):9d}"
            )
        out.append("\ntruncated results by tool (truncated / sized results):")
        for name, n in st.results.most_common():
            out.append(f"  {name:24s} {st.truncated.get(name, 0)} / {n}")
    if st.tool_errors:
        out.append("\ntool errors by class:")
        for name, n in st.tool_errors.most_common():
            out.append(f"  {name:40s} {n}")
    if st.job_exits:
        exits = ", ".join(f"{k}: {v}" for k, v in st.job_exits.most_common())
        out.append(f"\njob exits by code (job_exit lines): {exits}")
    if st.results:
        out.append(
            f"run_command results that became background jobs: {st.background_jobs}"
        )
    if st.turn_calls:
        per_turn = sorted(st.turn_calls.values())
        out.append(
            f"\nChatGPT turns (tunnel X-Request-Id): {len(per_turn)} turns, "
            f"{sum(per_turn)} tool calls; calls per turn median="
            f"{per_turn[len(per_turn) // 2]} max={per_turn[-1]}"
        )
    if st.indexed.successes or st.indexed.errors:
        idx = st.indexed
        out.append("\nindexed context pilot:")
        out.append(
            f"  success={idx.successes} errors={idx.errors} cold_opens={idx.cold_opens} "
            f"changed_files={idx.changed_files}"
        )
        if idx.pilot_versions:
            versions = ", ".join(
                f"{k}:{v}" for k, v in idx.pilot_versions.most_common()
            )
            out.append(f"  pilot versions: {versions}")
        if idx.error_phases:
            phases = ", ".join(f"{k}:{v}" for k, v in idx.error_phases.most_common())
            out.append(f"  error phases: {phases}")
        if idx.successes:
            conversion = 100 * idx.evidence_opened / idx.successes
            out.append(
                f"  evidence opened: {idx.evidence_opened}/{idx.successes} ({conversion:.1f}%) "
                f"reads={idx.evidence_reads} file_searches={idx.evidence_file_searches}"
            )
            for label, values in (
                ("result tokens", idx.result_tokens),
                ("package bytes", idx.package_bytes),
                ("total ms", idx.total_ms),
                ("reconcile ms", idx.reconcile_ms),
                ("query ms", idx.query_ms),
                ("follow-up calls", idx.followup_calls),
                ("follow-up exact", idx.followup_exact_searches),
                ("follow-up reads", idx.followup_reads),
                ("follow-up tokens", idx.followup_result_tokens),
                ("investigation tokens", idx.investigation_result_tokens),
            ):
                if values:
                    out.append(
                        f"  {label:20s} n={len(values):4d} p50={_pct(values, 0.5):8.1f} "
                        f"p90={_pct(values, 0.9):8.1f} max={max(values):9.1f}"
                    )
    return "\n".join(out)
