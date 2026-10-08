"""Reconstruct the watchdog's story from its journal.

Every line the watchdog writes is `event=<name> key=value ...`; this
module fetches them from journald, parses them, and renders a timeline of
what changed and what was done, plus a summary. It is the review tool the
richer logging exists for (2026-09-13): a window of the journal, however
short, carries the last snapshot, the transitions since, every decision
and every action, so an incident can be replayed without the host.
"""

import json
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

#: Events that make the timeline; the rest are steady-state chatter.
TIMELINE = {
    "watchdog_start",
    "watchdog_cycle_hung",
    "watchdog_cycle_error",
    "inventory",
    "inventory_host",
    "transition",
    "uplink_demoted",
    "uplink_reset",
    "uplink_usb_reset",
    "uplink_driver_reload",
    "uplink_restored",
    "uplink_radio_on",
    "service_restart",
    "system_service_restart",
    "uplink_issue",
    "uplink_issue_cleared",
    "paused",
    "reset_skipped",
    "demote_skipped",
    # fifth review (2026-09-14 night)
    "fast_failover",
    "fast_failover_blocked",
    "uplink_issue_flapping",
    "tunnel_not_ready",
    "service_restart_deferred",
    "action_skipped",
    "fast_path_stalled",
    "fast_path_restarted",
    "fast_path_hung",
}
VERBOSE = {
    "decision",
    "uplink_probe_error",
    "uplink_probe_unavailable",
    "snapshot",
    "snapshot_state",
    "fast_failure",
    "fast_recovered",
    "tunnel_kept",
}

#: Tunnel log messages: the poller backing off, and coming back.
_POLL_DOWN = ("poll failed; backing off", "poll timed out; backing off")
_POLL_UP = ("poller recovered; polling operational",)

_LINE = re.compile(
    r"^(?P<ts>\S+)?\s*(?P<level>INFO|WARNING|ERROR|CRITICAL|DEBUG)?:?\s*event=(?P<name>\w+)(?P<rest>.*)$"
)
_FIELD = re.compile(r"(\w+)=(.*?)(?=\s+\w+=|$)")


@dataclass(slots=True)
class Event:
    ts: str
    level: str
    name: str
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def when(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self.ts)
        except ValueError:
            return None


def fetch_journal(unit: str, since: str, until: str | None = None) -> list[str]:
    args = [
        "journalctl",
        "--user",
        "-u",
        unit,
        "--no-pager",
        "-o",
        "short-iso",
        f"--since={since}",
    ]
    if until:
        args.append(f"--until={until}")
    proc = subprocess.run(
        args, capture_output=True, text=True, check=False, timeout=120
    )
    return proc.stdout.splitlines()


def parse(lines: list[str]) -> list[Event]:
    """`short-iso` journal lines (or bare `event=` lines) to events."""
    out: list[Event] = []
    for raw in lines:
        line = raw.strip()
        if "event=" not in line:
            continue
        # short-iso: "<ts> <host> <unit>[pid]: LEVEL: event=..." -- keep the
        # timestamp and everything from the level on.
        ts = line.split(" ", 1)[0] if line[:4].isdigit() else ""
        body = line[line.index("event=") :]
        head = line[: line.index("event=")]
        level = "INFO"
        m = re.search(r"(INFO|WARNING|ERROR|CRITICAL|DEBUG)", head)
        if m:
            level = m.group(1)
        name_match = re.match(r"event=(\w+)", body)
        if not name_match:
            continue
        rest = body[name_match.end() :]
        fields = {k: v.strip() for k, v in _FIELD.findall(rest)}
        out.append(Event(ts=ts, level=level, name=name_match.group(1), fields=fields))
    return out


def _short(ev: Event) -> str:
    f = ev.fields
    name = ev.name
    if name == "transition":
        return f"{f.get('dev')}: {f.get('from')} -> {f.get('to')} (after {f.get('after_s')} s) {f.get('detail', '')}"
    if name in ("uplink_demoted", "uplink_restored"):
        return f"{f.get('dev')}: {'demoted' if name == 'uplink_demoted' else 'restored'} metric {f.get('metric')} kind={f.get('kind')}: {f.get('reason', '')}"
    if name == "uplink_reset":
        return f"{f.get('dev')}: re-activation ok={f.get('ok')} tag={f.get('tag')} profile={f.get('profile')}: {f.get('reason', '')}"
    if name == "uplink_usb_reset":
        return f"{f.get('dev')}: USB reset attempt {f.get('attempt')} method={f.get('method')} ok={f.get('ok')} tag={f.get('tag')} next_in={f.get('next_in_s')} s: {f.get('detail', '')}"
    if name == "uplink_driver_reload":
        return f"{f.get('dev')}: driver reload attempt {f.get('attempt')} ok={f.get('ok')}: {f.get('detail', '')}"
    if name in ("service_restart", "system_service_restart"):
        ready = f" ready in {f['ready_ms']} ms" if f.get("ready_ms", "-") != "-" else ""
        return f"restart {f.get('unit')} ok={f.get('ok')}{ready}: {f.get('reason', '')}"
    if name == "fast_failover":
        return f"{f.get('dev')}: fast failover after {f.get('failures')} misses ({f.get('window_s')} s) -> {f.get('target')} (metric {f.get('metric')})"
    if name == "fast_failover_blocked":
        return f"{f.get('dev')}: fast failover blocked: {f.get('reason', '')}"
    if name == "uplink_issue_flapping":
        return f"{f.get('dev')}: issue flapping, {f.get('changes')} changes in {f.get('window_s')} s; now {f.get('current', '?')}"
    if name == "tunnel_not_ready":
        return f"{f.get('unit')}: not ready {f.get('waited_s')} s after its restart: {f.get('reason', '')}"
    if name == "service_restart_deferred":
        return f"restart of {f.get('unit')} deferred (connection on {f.get('via')}): {f.get('reason', '')}"
    if name == "action_skipped":
        return f"{f.get('dev')}: {f.get('kind')} skipped: {f.get('reason', '')}"
    if name in ("fast_path_stalled", "fast_path_hung"):
        return f"fast path {name.split('_')[-1]}: heartbeat {f.get('age_s')} s old"
    if name == "fast_path_restarted":
        return f"fast path thread restarted: {f.get('reason', '')}"
    if name == "uplink_issue":
        return f"{f.get('dev')}: issue: {f.get('issue', '')}"
    if name == "uplink_issue_cleared":
        return f"{f.get('dev')}: issue cleared"
    if name == "watchdog_start":
        return f"watchdog started (cycle {f.get('cycle')}, demoted={f.get('demoted')}, versions={f.get('versions', '')})"
    if name == "inventory":
        return f"{f.get('dev')}: {f.get('kind')} driver={f.get('driver')} module={f.get('module')} params={f.get('params', '-')} profiles={f.get('profiles')}"
    if name == "inventory_host":
        return "host: " + " ".join(f"{k}={v}" for k, v in f.items() if k != "cycle")
    if name == "decision":
        return f"{f.get('dev')}: {f.get('rung')} declined: {f.get('note', '')}"
    if name == "paused":
        return f"paused: skipped {f.get('skipped') or f.get('skipped_services') or f.get('skipped_system')} until {f.get('until', '?')}"
    return " ".join(f"{k}={v}" for k, v in f.items() if k != "cycle")


def _rfc3339(stamp: str) -> datetime | None:
    """A Go RFC 3339 stamp (nanoseconds) as an aware datetime."""
    head, sep, rest = stamp.partition(".")
    if sep:
        digits = ""
        i = 0
        while i < len(rest) and rest[i].isdigit():
            digits += rest[i]
            i += 1
        stamp = f"{head}.{(digits + '000000')[:6]}{rest[i:]}"
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def window_of(events: list[Event]) -> tuple[datetime, datetime] | None:
    """The first and last timestamp among the events."""
    stamps = [w for w in (e.when for e in events) if w is not None]
    if not stamps:
        return None
    return min(stamps), max(stamps)


def tunnel_polls(
    log_file: Path, since: datetime, until: datetime
) -> list[tuple[datetime, str]]:
    """What the tunnel logged about its polling between `since` and
    `until`: ("down" for a failed or timed-out poll, "up" for a recovery),
    in order. This is what ChatGPT saw."""
    out: list[tuple[datetime, str]] = []
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        if not any(m in line for m in _POLL_DOWN) and not any(
            m in line for m in _POLL_UP
        ):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        when = _rfc3339(rec.get("time", ""))
        if when is None:
            continue
        if when.tzinfo is None or since.tzinfo is None:
            when = when.replace(tzinfo=None)
            lo, hi = since.replace(tzinfo=None), until.replace(tzinfo=None)
        else:
            lo, hi = since, until
        if lo <= when <= hi:
            msg = rec.get("msg", "")
            out.append((when, "down" if msg in _POLL_DOWN else "up"))
    return out


def _chatgpt_lines(events: list[Event], polls: list[tuple[datetime, str]]) -> list[str]:
    """The tunnel's failed polls in the window, in total and per failover
    (from each demotion until the device's restore, or ten minutes)."""
    down = [w for w, kind in polls if kind == "down"]
    ups = sum(1 for _, kind in polls if kind == "up")
    lines = [
        f"  ChatGPT (tunnel log): {len(down)} polls failed or timed out, {ups} recoveries"
    ]
    failovers = [
        e
        for e in events
        if e.name == "uplink_demoted"
        and e.fields.get("kind") == "wedged"
        and e.when is not None
    ]
    per: list[str] = []
    for failover in failovers:
        start = failover.when
        if start is None:
            continue
        dev = failover.fields.get("dev", "?")
        end = start + timedelta(minutes=10)
        for e in events:
            if (
                e.name == "uplink_restored"
                and e.fields.get("dev") == dev
                and e.when is not None
                and e.when > start
            ):
                end = min(end, e.when)
                break
        n = sum(1 for w in down if start - timedelta(seconds=60) <= w <= end)
        per.append(f"{start.strftime('%H:%M:%S')} {dev} {n}")
    if per:
        lines.append(
            "  failed polls per failover (from a minute before to the restore): "
            + ", ".join(per)
        )
    return lines


def render(
    events: list[Event],
    verbose: bool = False,
    polls: list[tuple[datetime, str]] | None = None,
) -> str:
    """A timeline of what changed and what was done, then a summary; with
    `polls` (see `tunnel_polls`) also what ChatGPT saw."""
    lines: list[str] = []
    wanted = TIMELINE | (VERBOSE if verbose else set())
    for ev in events:
        if ev.name not in wanted:
            continue
        stamp = ev.ts[:19] if ev.ts else "?"
        mark = {"WARNING": "!", "ERROR": "X", "CRITICAL": "X"}.get(ev.level, " ")
        lines.append(f"{stamp} {mark} {ev.name:<24} {_short(ev)}")
    if not lines:
        lines.append("(no watchdog events in this window)")

    # -- summary
    cycles = [e for e in events if e.name == "cycle"]
    durations = [float(e.fields.get("duration_ms", 0) or 0) for e in cycles]
    actions: Counter[str] = Counter()
    for e in events:
        if e.name in (
            "uplink_demoted",
            "uplink_reset",
            "uplink_usb_reset",
            "uplink_driver_reload",
            "uplink_restored",
            "service_restart",
            "system_service_restart",
            "uplink_radio_on",
        ):
            actions[e.name.replace("uplink_", "")] += 1
    # time per grade per device, from transitions (the first known grade
    # is taken from the first transition's `from`, the last runs to the
    # last event's time)
    per_grade: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    current: dict[str, tuple[str, datetime]] = {}
    last_when = None
    for e in events:
        w = e.when
        if w is None:
            continue
        last_when = w
        if e.name == "transition":
            dev = e.fields.get("dev", "?")
            before = current.get(dev)
            if before is not None:
                per_grade[dev][before[0]] += (w - before[1]).total_seconds()
            elif e.fields.get("from", "-") != "-":
                per_grade[dev][e.fields["from"]] += float(
                    e.fields.get("after_s", 0) or 0
                )
            current[dev] = (e.fields.get("to", "?"), w)
    if last_when is not None:
        for dev, (grade, since) in current.items():
            per_grade[dev][grade] += (last_when - since).total_seconds()
    failovers = [
        e
        for e in events
        if e.name == "uplink_demoted" and e.fields.get("kind") == "wedged"
    ]
    fast = sum(1 for e in failovers if e.fields.get("trigger") == "fast")
    blocked = sum(1 for e in events if e.name == "fast_failover_blocked")
    restores = [e for e in events if e.name == "uplink_restored"]
    tunnel_restarts: Counter[str] = Counter()
    for e in events:
        if e.name == "service_restart" and "tunnel" in e.fields.get("unit", ""):
            reason = e.fields.get("reason", "")
            tunnel_restarts[reason.split(":", 1)[0] if ":" in reason else "other"] += 1
    flapping = sum(1 for e in events if e.name == "uplink_issue_flapping")

    lines.append("")
    lines.append("summary")
    lines.append(
        f"  cycles: {len(cycles)}"
        + (
            f", mean {sum(durations) / len(durations):.0f} ms, max {max(durations):.0f} ms"
            if durations
            else ""
        )
    )
    lines.append(
        "  actions: "
        + (", ".join(f"{k} {v}" for k, v in sorted(actions.items())) or "none")
    )
    lines.append(
        f"  failovers (wedge/dead end demotions): {len(failovers)}"
        + (f" ({fast} by the fast path)" if fast else "")
        + f", restores: {len(restores)}"
        + (f", fast failovers blocked: {blocked}" if blocked else "")
    )
    if tunnel_restarts:
        lines.append(
            "  tunnel restarts: "
            + ", ".join(f"{k} {v}" for k, v in sorted(tunnel_restarts.items()))
        )
    if flapping:
        lines.append(f"  issue flapping summaries: {flapping}")
    if polls is not None:
        lines.extend(_chatgpt_lines(events, polls))
    for dev in sorted(per_grade):
        total = sum(per_grade[dev].values()) or 1.0
        parts = ", ".join(
            f"{g} {secs / 60:.0f} min ({100 * secs / total:.0f}%)"
            for g, secs in sorted(per_grade[dev].items(), key=lambda kv: -kv[1])
        )
        lines.append(f"  {dev}: {parts}")
    issues = [e for e in events if e.name == "uplink_issue"]
    if issues:
        lines.append(
            f"  issues raised: {len(issues)}; last: {issues[-1].fields.get('dev')}: {issues[-1].fields.get('issue', '')}"
        )
    hung = [
        e for e in events if e.name in ("watchdog_cycle_hung", "watchdog_cycle_error")
    ]
    if hung:
        lines.append(f"  watchdog trouble: {len(hung)} hung/error cycles")
    return "\n".join(lines)
