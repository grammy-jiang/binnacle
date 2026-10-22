"""Sanitized gold assertions, nearest-rank percentiles and observed resources."""

from __future__ import annotations

import math
from pathlib import Path
from urllib.parse import unquote, urlparse

from .corpus import Case


def percentiles(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        f"p{p}": ordered[max(0, math.ceil(len(ordered) * p / 100) - 1)]
        if ordered
        else None
        for p in (50, 95, 99)
    }


def correct(case: Case, response, root: Path) -> bool:
    """Exact location sets; never save source, URIs, names or provider messages."""

    def location(item):
        uri = urlparse(item["uri"])
        if uri.scheme != "file" or uri.netloc not in ("", "localhost"):
            raise ValueError("nonlocal_location")
        path = Path(unquote(uri.path)).resolve().relative_to(root.resolve()).as_posix()
        span = item["range"]
        return (
            path,
            span["start"]["line"],
            span["start"]["character"],
            span["end"]["line"],
            span["end"]["character"],
        )

    try:
        if case.operation == "hover":
            contents = response["contents"]
            texts = contents if isinstance(contents, list) else [contents]
            text = "\n".join(x if isinstance(x, str) else x["value"] for x in texts)
            return all(name in text for name in case.names)
        if case.operation in ("document_symbols", "workspace_symbols"):
            symbols = []

            def visit(items):
                for item in items:
                    symbols.append(item)
                    visit(item.get("children", []))

            visit(response)
            selected = [item for item in symbols if item["name"] in case.names]
            positions = [
                location(
                    item["location"]
                    if "location" in item
                    else {
                        "uri": (root / case.file).as_uri(),
                        "range": item["selectionRange"],
                    }
                )
                for item in selected
            ]
            return {item["name"] for item in selected} == set(case.names) and set(
                positions
            ) == set(case.locations)
        positions = [location(item) for item in response]
        return len(positions) == len(case.locations) and set(positions) == set(
            case.locations
        )
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        return False


class Resources:
    """Sample owned roots only. CPU totals retain observed exited processes.

    RSS sums can double count shared pages. Peaks are sampled lower bounds.
    Process birth identities prevent PID reuse from becoming a false CPU delta.
    """

    def __init__(self):
        self.samples = 0
        self.errors = 0
        self.rss_peak = 0
        self.process_peak = 0
        self.cpu: dict[tuple[int, float], float] = {}
        self.resident_peak = 0
        self.resident_rss_peak = 0

    def capture(self, roots: list[int], residents: int = 0) -> None:
        import psutil

        rss = 0
        seen = set()
        for pid in roots:
            try:
                parent = psutil.Process(pid)
                for process in [parent, *parent.children(recursive=True)]:
                    identity = (process.pid, process.create_time())
                    if identity in seen:
                        continue
                    seen.add(identity)
                    rss += process.memory_info().rss
                    cpu = process.cpu_times()
                    self.cpu[identity] = max(
                        self.cpu.get(identity, 0), cpu.user + cpu.system
                    )
            except psutil.Error:
                self.errors += 1
        if seen:
            self.samples += 1
        self.rss_peak = max(self.rss_peak, rss)
        self.process_peak = max(self.process_peak, len(seen))
        self.resident_peak = max(self.resident_peak, residents)
        if residents:
            self.resident_rss_peak = max(self.resident_rss_peak, rss)

    def result(self) -> dict:
        return {
            "status": "unavailable"
            if not self.samples
            else "partial"
            if self.errors
            else "observed",
            "samples": self.samples,
            "sampling_errors": self.errors,
            "tree_rss_peak_bytes": self.rss_peak if self.samples else None,
            "resident_tree_rss_peak_bytes": self.resident_rss_peak
            if self.samples
            else None,
            "observed_cpu_seconds": sum(self.cpu.values()) if self.samples else None,
            "process_count_peak": self.process_peak,
            "resident_instances_peak": self.resident_peak,
            "semantics": "sampled RSS sum; shared pages may double count; CPU since observed process birth; missed short-lived/escaped children possible; no confinement proof",
        }
