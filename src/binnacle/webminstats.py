"""Read Webmin ``system-status`` historical resource samples.

Webmin owns collection/storage.  Binnacle only reads a fixed whitelist of history
files when ``binnacle stats --system-resources`` is explicitly requested.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HISTORY_DIR = Path("/var/webmin/modules/system-status/history")
METRICS = (
    "load",
    "load5",
    "load15",
    "cpuuser",
    "cpukernel",
    "cpuidle",
    "cpuio",
    "memused",
    "swapused",
    "procs",
    "diskused",
    "bin",
    "bout",
    "drivetemp",
)


@dataclass(frozen=True)
class Point:
    ts: int
    value: float


@dataclass
class WebminResourceStats:
    start_ts: int
    end_ts: int
    interval_s: float
    series: dict[str, list[Point]]

    @property
    def samples(self) -> int:
        return len(self.series.get("cpuidle", []))


def _read_all_metric_texts() -> dict[str, str]:
    """Read the fixed metric set, with at most one sudo invocation."""
    try:
        return {
            name: (HISTORY_DIR / name).read_text(errors="replace")
            if (HISTORY_DIR / name).exists()
            else ""
            for name in METRICS
        }
    except PermissionError:
        # Webmin's parent directories are root-only on the Pi.  The helper code
        # accepts only the fixed root + fixed METRICS argv supplied here; no CLI
        # argument or user path is evaluated as Python or shell source.
        code = (
            "import json,pathlib,sys; "
            "root=pathlib.Path(sys.argv[1]); names=sys.argv[2:]; "
            "print(json.dumps({n:(root/n).read_text(errors='replace') "
            "if (root/n).exists() else '' for n in names}))"
        )
        proc = subprocess.run(
            ["sudo", "-n", "python3", "-c", code, str(HISTORY_DIR), *METRICS],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "Webmin history is not readable. Configure read access to "
                f"{HISTORY_DIR} or passwordless read-only sudo access."
            ) from None
        try:
            value = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Webmin history reader returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise TypeError("Webmin history reader returned an invalid payload")
        return {name: str(value.get(name, "")) for name in METRICS}


def _parse_metric_text(text: str) -> list[Point]:
    out: list[Point] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            out.append(Point(int(float(parts[0])), float(parts[1])))
        except ValueError:
            continue
    return out


def _resolve_time(spec: str | None, *, default_now: bool = False) -> int:
    if spec is None:
        if default_now:
            return int(time.time())
        raise ValueError("time spec required")
    proc = subprocess.run(
        ["date", "--date", spec, "+%s"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(f"Cannot parse time specification {spec!r}") from None
    return int(proc.stdout.strip())


def load(since: str, until: str | None = None) -> WebminResourceStats:
    start_ts = _resolve_time(since)
    end_ts = _resolve_time(until, default_now=True)
    if end_ts < start_ts:
        raise ValueError("until must not be earlier than since")

    series: dict[str, list[Point]] = {}
    all_gaps: list[int] = []
    texts = _read_all_metric_texts()
    for name in METRICS:
        values = [
            p
            for p in _parse_metric_text(texts.get(name, ""))
            if start_ts <= p.ts <= end_ts
        ]
        series[name] = values
        all_gaps.extend(values[i].ts - values[i - 1].ts for i in range(1, len(values)))
    interval = statistics.median(all_gaps) if all_gaps else 0.0
    return WebminResourceStats(start_ts, end_ts, float(interval), series)


def _values(stats: WebminResourceStats, name: str) -> list[float]:
    return [p.value for p in stats.series.get(name, [])]


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def _dist(values: list[float]) -> tuple[float, float, float, float, float] | None:
    if not values:
        return None
    return (
        statistics.median(values),
        _pct(values, 0.90),
        _pct(values, 0.95),
        max(values),
        min(values),
    )


def _peak_points(
    points: list[Point], transform=lambda x: x, count: int = 3
) -> list[tuple[int, float]]:
    return sorted(
        ((p.ts, float(transform(p.value))) for p in points),
        key=lambda item: item[1],
        reverse=True,
    )[:count]


def _render_dist(label: str, values: list[float], unit: str = "") -> str | None:
    d = _dist(values)
    if d is None:
        return None
    p50, p90, p95, maximum, minimum = d
    return (
        f"  {label:18s} p50={p50:7.1f}{unit}  p90={p90:7.1f}{unit}  "
        f"p95={p95:7.1f}{unit}  max={maximum:8.1f}{unit}  min={minimum:7.1f}{unit}"
    )


def render(stats: WebminResourceStats) -> str:
    out = ["system resources (Webmin system-status):"]
    available = [p.ts for values in stats.series.values() for p in values]
    if not available:
        out.append("  no Webmin samples in requested window")
        return "\n".join(out)

    first, last = min(available), max(available)
    out.append(
        f"  samples={stats.samples} interval≈{stats.interval_s:.0f}s "
        f"first={datetime.fromtimestamp(first, timezone.utc).astimezone().isoformat(timespec='seconds')} "
        f"last={datetime.fromtimestamp(last, timezone.utc).astimezone().isoformat(timespec='seconds')}"
    )

    idle = _values(stats, "cpuidle")
    busy = [100.0 - x for x in idle]
    rows = [
        _render_dist("CPU busy", busy, "%"),
        _render_dist("CPU IOwait", _values(stats, "cpuio"), "%"),
        _render_dist("load1", _values(stats, "load")),
        _render_dist("load5", _values(stats, "load5")),
        _render_dist("load15", _values(stats, "load15")),
        _render_dist(
            "memory used",
            [x / 1024**3 for x in _values(stats, "memused")],
            " GiB",
        ),
        _render_dist(
            "swap used",
            [x / 1024**3 for x in _values(stats, "swapused")],
            " GiB",
        ),
        _render_dist("processes", _values(stats, "procs")),
        _render_dist("NVMe temp", _values(stats, "drivetemp"), " C"),
    ]
    out.extend(row for row in rows if row is not None)

    cores = os.cpu_count() or 1
    if busy:
        for threshold in (50, 75, 90):
            n = sum(x >= threshold for x in busy)
            out.append(
                f"  CPU >= {threshold:2d}%: {n}/{len(busy)} "
                f"({100 * n / len(busy):.2f}%)"
            )
    load1 = _values(stats, "load")
    if load1:
        n = sum(x >= cores for x in load1)
        out.append(
            f"  load1 >= {cores} cores: {n}/{len(load1)} ({100 * n / len(load1):.2f}%)"
        )

    out.append("  peak timestamps:")
    for label, points, transform, unit in (
        ("CPU busy", stats.series.get("cpuidle", []), lambda x: 100 - x, "%"),
        ("load1", stats.series.get("load", []), lambda x: x, ""),
        ("memory used", stats.series.get("memused", []), lambda x: x / 1024**3, " GiB"),
        ("NVMe temp", stats.series.get("drivetemp", []), lambda x: x, " C"),
    ):
        peaks = _peak_points(points, transform, 3)
        if peaks:
            text = ", ".join(
                f"{datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec='minutes')}={value:.1f}{unit}"
                for ts, value in peaks
            )
            out.append(f"    {label:12s} {text}")
    return "\n".join(out)
