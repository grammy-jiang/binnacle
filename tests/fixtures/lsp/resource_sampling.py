"""Bounded opt-in Linux/Darwin ps observation of cooperative FAKE processes.

RSS is KiB (shared pages may be double counted), CPU is cumulative ps TIME
seconds, not instantaneous utilization. Snapshots cannot see between-sample
children or prove confinement. No full process table or command line is saved.
"""

from __future__ import annotations

import math
import os
import platform
import subprocess
import time
from typing import Any

METHOD = "ps-pid-ppid-pgid-rss-time-lstart/1"
PHASES = ("cold", "settling", "warm")


def cpu_seconds(value: str) -> float:
    days, separator, rest = value.partition("-")
    total = int(days) * 86400 if separator else 0
    fields = (rest if separator else days).split(":")
    if not 2 <= len(fields) <= 3:
        raise ValueError("invalid ps time")
    for exponent, part in enumerate(reversed(fields)):
        total += float(part) * 60**exponent
    if not math.isfinite(total) or total < 0:
        raise ValueError("invalid CPU time")
    return total


def process_table() -> dict[int, dict]:
    if platform.system() not in ("Linux", "Darwin"):
        raise NotImplementedError("Linux/Darwin ps only")
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,pgid=,rss=,time=,lstart="],
        capture_output=True,
        text=True,
        timeout=1,
        check=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    rows = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 5)
        if len(fields) != 6:
            raise ValueError("partial ps row")
        pid, ppid, pgid, rss = map(int, fields[:4])
        if pid in rows or rss < 0:
            raise ValueError("invalid ps row")
        rows[pid] = {
            "pid": pid,
            "ppid": ppid,
            "pgid": pgid,
            "rss_kib": rss,
            "cpu_s": cpu_seconds(fields[4]),
            "start": fields[5],
        }
    return rows


def tree_snapshot(
    rows: dict[int, dict], root: int, known: dict[int, str], expected: set[int]
) -> tuple[dict, dict[int, str]]:
    if root not in rows:
        raise ValueError("missing root process")
    members = {root}
    while True:
        expanded = members | {
            pid for pid, row in rows.items() if row["ppid"] in members
        }
        if expanded == members:
            break
        members = expanded
    if not (set(known) | expected).issubset(members):
        raise ValueError("missing or orphan descendant")
    group = rows[root]["pgid"]
    if any(rows[pid]["pgid"] != group for pid in members):
        raise ValueError("escaped descendant")
    if any(rows[pid]["start"] != start for pid, start in known.items()):
        raise ValueError("process identity changed")
    parent = rows[root]
    return {
        "parent_rss_kib": parent["rss_kib"],
        "tree_rss_kib": sum(rows[pid]["rss_kib"] for pid in members),
        "parent_cpu_s": parent["cpu_s"],
        "tree_cpu_s": sum(rows[pid]["cpu_s"] for pid in members),
        "child_count": len(members) - 1,
        "members": sorted(members),
    }, {pid: rows[pid]["start"] for pid in members}


class Sampler:
    """Six snapshots maximum; delay and ps timeout are bounded, no worker thread."""

    def __init__(self, root: int, expected: set[int], interval: float):
        if not 0.01 <= interval <= 0.2:
            raise ValueError("sample interval must be 0.01..0.2 seconds")
        self.root, self.expected, self.interval = root, expected, interval
        self.known: dict[int, str] = {}
        self.result: dict[str, Any] = {
            "status": "pending",
            "method": METHOD,
            "interval_s": interval,
            "samples": [],
            "cpu_semantics": "cumulative ps TIME seconds; rounded by OS",
            "rss_semantics": "sum of observed RSS KiB; shared pages may double count",
            "settled": "unobserved",
            "warm_memory_validated": False,
        }

    def capture(self, phase: str) -> None:
        if phase not in PHASES or len(self.result["samples"]) >= 6:
            raise ValueError("sampling bound")
        if self.result["status"] not in ("pending", "valid"):
            return
        try:
            time.sleep(self.interval)
            sample, self.known = tree_snapshot(
                process_table(),
                self.root,
                self.known,
                self.expected,
            )
            previous = self.result["samples"][-1] if self.result["samples"] else None
            if previous and (
                sample["members"] != previous["members"]
                or sample["tree_cpu_s"] < previous["tree_cpu_s"]
            ):
                raise ValueError("partial/changing observation")
            sample.update(phase=phase, observed_at_s=time.monotonic())
            self.result["samples"].append(sample)
        except (NotImplementedError, PermissionError, FileNotFoundError) as error:
            self.result["status"] = "unsupported"
            self.result["reason"] = type(error).__name__
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.result["status"] = "invalid"
            self.result["reason"] = type(error).__name__

    def finish(self) -> dict:
        if self.result["status"] == "pending":
            self.result["status"] = (
                "valid"
                if all(
                    sum(s["phase"] == phase for s in self.result["samples"]) == 2
                    for phase in PHASES
                )
                else "partial"
            )
        return self.result
