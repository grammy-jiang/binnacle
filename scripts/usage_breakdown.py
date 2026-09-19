#!/usr/bin/env python3
"""ChatGPT-attributed usage breakdown from the server journal.

Companion to `binnacle stats` for the before/after review of the
2026-09-03 changes (job_status wait_seconds/processes, run_command
tail_lines, search_text line_numbers). It attributes each tools/call to
ChatGPT by matching its timestamp against the tunnel client's
"dispatcher forwarded command" log lines, then reports the metrics those
changes are meant to move. Baseline numbers: docs/usage-analysis-2026-09-03.md.

    .venv/bin/python scripts/usage_breakdown.py --since 2026-09-04 [--until ...]

Two journal eras (docs/logging.md): up to 2026-09-13 a tools/call is one
rich-wrapped ``request_start`` record with the arguments in its payload;
from then on the server also writes a single-line ``tool_call`` record
(arguments, tunnel turn id) and a ``tool_result`` record (duration, sizes,
outcome). A call is counted once: the ``tool_call`` record wins over the
``request_start`` record with the same (session, request_id). The result
metrics exist only for the new era.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from binnacle import logstats

TUNNEL_LOG = Path.home() / ".local/state/tunnel-client/logs/binnacle.log"
NAME = re.compile(r'"name":"([a-z_]+)","arguments"')
CMD = re.compile(r'"command":"((?:[^"\\]|\\.)*)')
ARGS = re.compile(r'"arguments":(\{.*)')
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")
SPLIT = re.compile(r"\s*(?:;|&&|\|\||\||\n)\s*")


def tunnel_dispatch_times() -> set[datetime]:
    out: set[datetime] = set()
    if not TUNNEL_LOG.exists():
        return out
    for line in TUNNEL_LOG.read_text(errors="replace").splitlines():
        if '"msg":"dispatcher forwarded command' not in line:
            continue
        m = re.search(r'"time":"(\d{4}-\d\d-\d\d)T(\d\d:\d\d:\d\d)', line)
        if m:
            # Both logs are in local time; naive datetimes compare like for like.
            out.add(
                datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007
            )
    return out


_RFC3339 = re.compile(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?([+-]\d\d:\d\d|Z)$")


def _rfc3339_ts(text: str) -> float | None:
    """Epoch seconds from Go's RFC 3339 (variable fraction, trailing zeros trimmed)."""
    m = _RFC3339.match(text)
    if not m:
        return None
    frac = (m.group(2) or ".0")[:7].ljust(7, "0")
    return datetime.fromisoformat(
        f"{m.group(1)}{frac}{m.group(3).replace('Z', '+00:00')}"
    ).timestamp()


def tunnel_turns(since: str, until: str | None) -> dict:
    """Calls per ChatGPT turn and the gap between calls inside a turn.

    The tunnel logs every forwarded command with cmd_request_id
    `wfr_<turn>/<call>`; one `wfr_` id is one serial agent turn (2026-09-12:
    188 calls over 63 min under one id). This is the metric the 2026-09-07
    description rewrite ("as few calls as possible") is meant to move; the
    journal cannot see turns, so it lives here. Counts every forwarded RPC,
    not only tools/call, so totals exceed the attributed tool-call count.
    """
    turns: dict[str, list[float]] = defaultdict(list)
    if not TUNNEL_LOG.exists():
        return {}
    for line in TUNNEL_LOG.read_text(errors="replace").splitlines():
        if '"msg":"dispatcher forwarded command' not in line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        day = d.get("time", "")[:10]
        if day < since or (until and day > until):
            continue
        cid = d.get("cmd_request_id", "")
        ts = _rfc3339_ts(d.get("time", ""))
        if cid.startswith("wfr_") and ts is not None:
            turns[cid.split("/")[0]].append(ts)
    if not turns:
        return {}
    counts = sorted(len(v) for v in turns.values())
    gaps = sorted(
        b - a for v in turns.values() for a, b in zip(sorted(v), sorted(v)[1:])
    )

    def p90(xs: list) -> float:
        return xs[int(len(xs) * 0.9)] if xs else 0

    return {
        "turns": len(counts),
        "calls": sum(counts),
        "calls_per_turn_median": counts[len(counts) // 2],
        "calls_per_turn_p90": p90(counts),
        "calls_per_turn_max": counts[-1],
        "gap_median_s": round(gaps[len(gaps) // 2], 1) if gaps else 0,
        "gap_p90_s": round(p90(gaps), 1),
    }


def strip_heredocs(c: str) -> str:
    out, i = [], 0
    while True:
        m = HEREDOC.search(c, i)
        if not m:
            out.append(c[i:])
            break
        nl = c.find("\n", m.end())
        out.append(c[i : m.end()])
        if nl < 0:
            break
        end = re.search(r"\n" + re.escape(m.group(1)) + r"\s*(\n|$)", c[nl:])
        if not end:
            break
        i = nl + end.end()
    return "".join(out)


TEST_MARKERS = (
    "e2e-",
    "p2-",
    "p2w-",
    "binnacle-mcp-ok",
    "rotated-token-ok",
    "restored-token-ok",
)
# Nonce prefixes used by hand in probes (2026-09-07: `cc-001141`, `eco-164922`)
# and the one probe shape that carries no nonce at all (the skill's stop-job
# probe, `setsid sleep 40 & sleep 40; wait`). Bounded so `gcc-14` is not `cc-`.
TEST_MARKER_RES = (
    re.compile(r"(?<![\w-])cc-\d{4,}"),
    re.compile(r"(?<![\w-])eco-\d{4,}"),
    re.compile(r"setsid sleep \d+(?:\.\d+)? & sleep \d+(?:\.\d+)?; wait"),
)
GIT_SUB = re.compile(
    r"(?<![\w./-])git\s*(?:-C\s*\S+\s*)?(status|log|diff|show|add|commit|push|pull|fetch|"
    r"clone|checkout|switch|branch|tag|rev-parse|rev-list|ls-files|ls-tree|cat-file|grep|"
    r"blame|stash|reset|restore|merge|rebase|remote|config|describe|worktree|init)\b"
)
GREP_DIRECT = re.compile(r"(?:^|[;&\n]\s*)(?:set -\S+\s*;?\s*)?(?:e|f)?grep\b")
GREP_ANY = re.compile(r"(?<![\w./-])(?:e|f)?grep\b")


def is_test_traffic(cmd: str) -> bool:
    return any(m in cmd for m in TEST_MARKERS) or any(
        rx.search(cmd) for rx in TEST_MARKER_RES
    )


JOB_START = re.compile(
    r"event=job_start job_id=([0-9a-f]+) pid=\d+ command=(.*?) workdir="
)


def test_job_ids(journal_text: str) -> set[str]:
    """Job ids whose job_start command carries a test marker (plain log lines)."""
    return {
        m.group(1)
        for m in JOB_START.finditer(journal_text)
        if is_test_traffic(m.group(2))
    }


def read_file_stats(reads: list[tuple[str, int | None, int | None]]) -> dict:
    """How read_file is used: slice sizes and re-reading of the same file.

    Motivates and measures the 2026-09-06 description change ("start
    narrow" -> state the 2,000-line window): 492 reads on 21 files with a
    median slice of 26 lines in the 09-04/05 window.
    """
    spans = sorted(e - s_ + 1 for _, s_, e in reads if s_ is not None and e is not None)
    files = Counter(p for p, _, _ in reads)
    longest = run = 0
    prev = None
    continuations = 0
    prev_end: int | None = None
    for p, s_, e in reads:
        run = run + 1 if p == prev else 1
        longest = max(longest, run)
        if p == prev and s_ is not None and prev_end is not None and s_ == prev_end + 1:
            continuations += 1
        prev, prev_end = p, e
    return {
        "calls": len(reads),
        "distinct_files": len(files),
        "reads_per_file_max": max(files.values()) if files else 0,
        "whole_file_reads": sum(1 for _, s_, e in reads if s_ is None and e is None),
        "span_median": spans[len(spans) // 2] if spans else 0,
        "span_p90": spans[9 * len(spans) // 10] if spans else 0,
        "longest_same_file_run": longest,
        "sequential_continuations": continuations,
    }


def command_traits(c: str) -> set[str]:
    s = strip_heredocs(c)
    t: set[str] = set()
    if re.search(r"\|\s*(head|tail)\s*-n?\s*\d+", s):
        t.add("hand-tail/head")
    if re.search(r"\|\s*tail\s*-n?\s*\d+", s):
        t.add("hand-tail")  # what run_command.tail_lines replaces
    if re.search(r"\|\s*head\s*-n?\s*\d+", s):
        t.add("hand-head")  # first lines: no parameter replaces this
    if re.search(r"(?<![\w./-])grep\b", s):
        t.add("grep")
        # A grep that starts a `;`/`&&`/newline segment searches files; one
        # after a pipe filters another command's output (2026-09-13: the old
        # rule split on `|` too and counted `ps | grep x` as a file search).
        if GREP_DIRECT.search(s):
            t.add("grep-on-files")
    if re.search(r"(?<![\w./-])(ps|pgrep)\b", s):
        t.add("ps/pgrep")
    if re.search(r"(?<![\w./-])git\b", s):
        t.add("git")
    if re.search(r"python3?\s+-\s*<<", c):
        t.add("python-heredoc")
    return t


def _median(xs: list) -> float | int:
    return sorted(xs)[len(xs) // 2] if xs else 0


def _p90(xs: list) -> float | int:
    return sorted(xs)[int(len(xs) * 0.9)] if xs else 0


def build_report(
    records: list,
    journal: str,
    disp: set[datetime],
    since: str,
    until: str | None,
    all_clients: bool = False,
    keep_tests: bool = False,
) -> dict:
    """The attributed breakdown as one dict (the --json shape)."""
    day = time = None
    for r in records:
        if r.day:
            day, time = r.day, r.time
        else:
            r.day, r.time = day, time

    def stamp_matches_tunnel(r) -> bool:
        if not r.day:
            return False
        ts = datetime.strptime(f"{r.day} {r.time}", "%m/%d/%y %H:%M:%S")  # noqa: DTZ007
        return any(ts + timedelta(seconds=d) in disp for d in (-2, -1, 0, 1, 2))

    tools: Counter = Counter()
    params: Counter = Counter()
    traits: Counter = Counter()
    git_subs: Counter = Counter()
    grep_split: Counter = Counter()
    polls: dict[str, list] = defaultdict(list)
    days: Counter = Counter()
    n_run = 0
    listings = 0
    background = 0
    reads: list[tuple[str, int | None, int | None]] = []  # (path, start, end) in order
    test_jobs = test_job_ids(journal)  # jobs started by nonce-marked probes
    # New-era records: the tool_call for a call carries the same session and
    # request_id as its request_start, which is then skipped.
    plain_keys: set[tuple[str, str]] = set()
    for r in records:
        if r.event == "tool_call":
            f = logstats.plain_fields(r.body)
            if f.get("request_id", "-") != "-" and f.get("session", "-") != "-":
                plain_keys.add((f["session"], f["request_id"]))
    # call id -> (tool, counted) for the tool_result that follows; jobs the
    # counted run_commands created, for their job_exit lines.
    calls: dict[str, tuple[str, bool]] = {}
    counted_jobs: set[str] = set()
    result_tokens: dict[str, list[int]] = defaultdict(list)
    result_calls: Counter = Counter()
    truncated: Counter = Counter()
    result_errors: Counter = Counter()
    errors_by_class: Counter = Counter()
    latency: dict[str, list[float]] = defaultdict(list)
    became_jobs = 0
    est_tokens_total = 0
    exits: dict[str, str] = {}  # job_id -> exit label; filtered after the loop
    turn_calls: Counter = Counter()

    def count_call(tool: str, args: str, r, cmd_source: str) -> bool:
        """One tools/call by ChatGPT; False when filtered out as test traffic."""
        nonlocal n_run, listings, background
        if not keep_tests:
            if is_test_traffic(args):
                return False  # nonce-marked e2e probe, any tool
            jm = re.search(r'"job_id":"([0-9a-f]+)', args)
            if jm and jm.group(1) in test_jobs:
                return False  # follow-up job_status/stop_job on a probe's job
        days[r.day] += 1
        tools[tool] += 1
        # Uptake counts only non-default values: ChatGPT sends defaults
        # explicitly (wait_seconds:0, tail_lines:100, line_numbers:false).
        for key, rx, default in (
            ("wait_seconds", r'"wait_seconds":(\d+)', "0"),
            (
                "tail_lines",
                r'"tail_lines":(\d+)',
                "100" if tool == "job_status" else None,
            ),
            ("line_numbers", r'"line_numbers":(true|false)', "false"),
            ("context_lines", r'"context_lines":(\d+)', None),
        ):
            vm = re.search(rx, args)
            if vm and vm.group(1) != default:
                params[f"{tool}.{key}"] += 1
        if tool == "job_status":
            jm = re.search(r'"job_id":"([0-9a-f]+)', args)
            if jm:
                polls[jm.group(1)].append(r.time)
            else:
                listings += 1  # recent-jobs listing: a habit, not a poll
        if tool == "read_file":
            pm = re.search(r'"path":"([^"]*)', args)
            sm = re.search(r'"start_line":(\d+)', args)
            em = re.search(r'"end_line":(\d+)', args)
            reads.append(
                (
                    pm.group(1) if pm else "?",
                    int(sm.group(1)) if sm else None,
                    int(em.group(1)) if em else None,
                )
            )
        if tool == "run_command":
            if '"background":true' in args:
                background += 1
            cm = CMD.search(cmd_source)
            if cm:
                n_run += 1
                try:
                    cmd = json.loads('"' + cm.group(1) + '"')
                except json.JSONDecodeError:
                    cmd = cm.group(1)
                for tr in command_traits(cmd):
                    traits[tr] += 1
                stripped = strip_heredocs(cmd)
                for gm in GIT_SUB.finditer(stripped):
                    git_subs[gm.group(1)] += 1
                n_any = len(GREP_ANY.findall(stripped))
                n_direct = len(GREP_DIRECT.findall(stripped))
                grep_split["direct_on_files"] += n_direct
                grep_split["pipeline_filter"] += max(n_any - n_direct, 0)
        return True

    for r in records:
        if r.event == "request_start":
            fields = logstats._appended_fields(r.body)
            if (
                fields.get("session", "-"),
                fields.get("request_id", "-"),
            ) in plain_keys:
                continue  # counted from its tool_call record
            if not (all_clients or stamp_matches_tunnel(r)):
                continue
            m = NAME.search(r.body)
            if not m:
                continue
            am = ARGS.search(r.body)
            count_call(m.group(1), am.group(1) if am else "", r, r.body)
        elif r.event == "tool_call":
            f = logstats.plain_fields(r.body)
            tool = f.get("tool", "?")
            attributed = all_clients or "turn" in f or stamp_matches_tunnel(r)
            counted = attributed and count_call(
                tool, f.get("args", ""), r, f.get("args", "")
            )
            if f.get("call"):
                calls[f["call"]] = (tool, counted)
            if counted and "turn" in f:
                turn_calls[f["turn"].split("/")[0]] += 1
        elif r.event == "tool_result":
            f = logstats.plain_fields(r.body)
            tool, counted = calls.get(f.get("call", ""), (f.get("tool", "?"), False))
            if not counted:
                continue
            if f.get("est_tokens", "").isdigit():
                n = int(f["est_tokens"])
                result_tokens[tool].append(n)
                result_calls[tool] += 1
                est_tokens_total += n
            if f.get("truncated") == "true":
                truncated[tool] += 1
            if f.get("is_error") == "True":
                result_errors[tool] += 1
                errors_by_class[f"{tool}: {f.get('error_class', '?')}"] += 1
            try:
                latency[tool].append(float(f["duration_ms"]))
            except (KeyError, ValueError):
                pass
            if f.get("background_job") == "true":
                became_jobs += 1
            if f.get("job_id"):
                counted_jobs.add(f["job_id"])
        elif r.event == "job_exit":
            # A synchronous command's job_exit precedes the tool_result that
            # names its job, so the attribution filter runs after the loop.
            f = logstats.plain_fields(r.body)
            signal = f.get("signal")
            if signal not in (None, "None", "null"):
                exits[f.get("job_id", "?")] = f"signal {signal}"
            else:
                exits[f.get("job_id", "?")] = f.get("exit_code", "?")

    job_exits = Counter(label for jid, label in exits.items() if jid in counted_jobs)
    total = sum(tools.values())
    who = "all clients" if all_clients else "ChatGPT (tunnel-matched)"
    per_job_list = [len(v) for v in polls.values()]
    per_turn = sorted(turn_calls.values())
    return {
        "since": since,
        "until": until,
        "scope": who,
        "tool_calls": total,
        "tools": dict(tools.most_common()),
        "days": dict(sorted(days.items())),
        "job_status": {
            "listings": listings,
            "calls": sum(per_job_list),
            "jobs": len(polls),
            "median_per_job": _median(per_job_list),
            "max_per_job": max(per_job_list) if per_job_list else 0,
        },
        "param_uptake": dict(params),
        "read_file": read_file_stats(reads),
        "run_command": {
            "background": background,
            "calls": n_run,
            "traits": dict(traits.most_common()),
        },
        "grep": dict(grep_split),
        "turns": tunnel_turns(since, until),
        "git_subcommands": dict(git_subs.most_common()),
        # 2026-09-13 on: what the model received, per counted call.
        "results": {
            "calls_with_sizes": sum(result_calls.values()),
            "est_tokens_total": est_tokens_total,
            "by_tool": {
                t: {
                    "calls": result_calls[t],
                    "est_tokens_median": _median(result_tokens[t]),
                    "est_tokens_p90": _p90(result_tokens[t]),
                    "est_tokens_max": max(result_tokens[t]),
                    "est_tokens_total": sum(result_tokens[t]),
                    "truncated": truncated.get(t, 0),
                    "errors": result_errors.get(t, 0),
                }
                for t, _ in result_calls.most_common()
            },
            "errors_by_class": dict(errors_by_class.most_common()),
            "latency_ms": {
                t: {"median": _median(v), "p90": _p90(v)}
                for t, v in sorted(latency.items(), key=lambda kv: -len(kv[1]))
            },
            "became_jobs": became_jobs,
            "job_exits": dict(job_exits.most_common()),
        },
        "turns_journal": {
            "turns": len(per_turn),
            "calls": sum(per_turn),
            "calls_per_turn_median": _median(per_turn),
            "calls_per_turn_max": per_turn[-1] if per_turn else 0,
        },
    }


if __name__ == "__main__":
    from scripts.usage_breakdown_cli import main

    main()
