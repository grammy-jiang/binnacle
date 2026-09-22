#!/usr/bin/env python3
"""Classify one ChatGPT async-probe trial from binnacle journal text."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

TOOL_CALL = re.compile(
    r"^(?P<ts>\S+).*event=tool_call call=(?P<call>\S+) "
    r"tool=async_probe_(?P<tool>\w+).* turn=(?P<turn>\S+).*"
    r'args=.*"probe_id":"(?P<probe>[^"]+)"'
)
PROBE_EVENT = re.compile(
    r"^(?P<ts>\S+).*event=async_probe phase=(?P<phase>\w+) "
    r"tool=(?P<tool>\w+) probe_id=(?P<probe>\S+) "
    r"label=(?P<label>\S+) token=(?P<token>\S+) call=(?P<call>\S+) "
    r"monotonic_ns=(?P<ns>\d+)"
)


@dataclass(frozen=True)
class Event:
    phase: str
    tool: str
    label: str
    token: str
    call: str
    ns: int
    ts: str


def base_turn(value: str) -> str:
    return value.split("/", 1)[0]


def analyze(text: str, probe_id: str) -> dict:
    turns: dict[str, str] = {}
    events: list[Event] = []
    for line in text.splitlines():
        if (m := TOOL_CALL.search(line)) and m.group("probe") == probe_id:
            turns[m.group("call")] = base_turn(m.group("turn"))
        if (m := PROBE_EVENT.search(line)) and m.group("probe") == probe_id:
            events.append(
                Event(
                    m.group("phase"),
                    m.group("tool"),
                    m.group("label"),
                    m.group("token"),
                    m.group("call"),
                    int(m.group("ns")),
                    m.group("ts"),
                )
            )

    starts = [e for e in events if e.phase == "start"]
    ends = [e for e in events if e.phase == "end"]
    wait_starts = [e for e in starts if e.tool == "wait"]
    wait_ends = [e for e in ends if e.tool == "wait"]
    seed_ends = [e for e in ends if e.tool == "seed"]
    echo_starts = [e for e in starts if e.tool == "echo"]

    all_turns = sorted({turns[e.call] for e in events if e.call in turns})
    result = {
        "probe_id": probe_id,
        "events": events,
        "turns": all_turns,
        "same_turn": len(all_turns) == 1 and bool(all_turns),
        "classification": "inconclusive",
        "reason": "insufficient events",
    }

    if len(wait_starts) >= 2 and len(wait_ends) >= 2 and not seed_ends:
        latest_start = max(e.ns for e in wait_starts)
        earliest_end = min(e.ns for e in wait_ends)
        result["classification"] = (
            "parallel_dispatch" if latest_start < earliest_end else "sequential"
        )
        result["reason"] = (
            "multiple waits overlap"
            if latest_start < earliest_end
            else "waits do not overlap"
        )
        return result

    if wait_starts and wait_ends and seed_ends and echo_starts:
        long_start = min(wait_starts, key=lambda e: e.ns)
        long_end = max(wait_ends, key=lambda e: e.ns)
        seed = min(seed_ends, key=lambda e: e.ns)
        echo = min(echo_starts, key=lambda e: e.ns)
        token_match = seed.token == echo.token and len(seed.token) == 32
        overlap = long_start.ns < seed.ns < long_end.ns
        true_async = overlap and seed.ns < echo.ns < long_end.ns and token_match
        result.update(
            seed_token_matches_echo=token_match,
            seed_finished_while_wait_running=overlap,
            echo_started_before_wait_end=echo.ns < long_end.ns,
        )
        if true_async:
            result["classification"] = "true_async"
            result["reason"] = "dependent echo started before outstanding wait ended"
        elif overlap and token_match:
            result["classification"] = "parallel_batch_barrier"
            result["reason"] = (
                "seed finished while wait was outstanding, but dependent echo "
                "started only after the wait ended"
            )
        else:
            result["classification"] = "sequential_or_invalid"
            result["reason"] = "required overlap/token dependency was not established"
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("probe_id")
    p.add_argument("journal", nargs="?", help="journal text file; stdin when omitted")
    args = p.parse_args()
    text_data = Path(args.journal).read_text() if args.journal else sys.stdin.read()
    result = analyze(text_data, args.probe_id)
    print(f"probe_id={result['probe_id']}")
    print(f"classification={result['classification']}")
    print(f"same_turn={str(result['same_turn']).lower()}")
    print(f"turns={','.join(result['turns']) or '-'}")
    for key in (
        "seed_token_matches_echo",
        "seed_finished_while_wait_running",
        "echo_started_before_wait_end",
    ):
        if key in result:
            print(f"{key}={str(result[key]).lower()}")
    print(f"reason={result['reason']}")
    for e in sorted(result["events"], key=lambda x: x.ns):
        print(
            f"{e.ts} {e.phase:5s} {e.tool:4s} "
            f"label={e.label} token={e.token} call={e.call}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
