"""Read the installed Darwin LaunchDaemons' bounded log files for usage stats.

This is deliberately NOT the generation-bound private service log contract:
production launchd owns stdout/stderr paths, while that contract governs
explicitly leased test services. Refuse unknown service labels and unsafe files;
never silently present an incomplete capped read as complete.
"""

from __future__ import annotations

import bz2
import gzip
import os
import re
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from binnacle.platform.contracts.service_log_contracts import ServiceLogError

MAX_QUERY_BYTES = 256 << 20
_ISO = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)\s")
_RICH = re.compile(r"^\[(\d\d/\d\d/\d\d \d\d:\d\d:\d\d)\]")
_OFFSET = re.compile(
    r"^\s*(-?\d+)\s*(seconds?|minutes?|hours?|days?|weeks?)\s*(ago)?\s*$", re.IGNORECASE
)
_ARCHIVE = re.compile(r"^(?P<base>[\w.-]+\.log)(?:\.(?P<num>\d+)(?:\.(?:gz|bz2))?)?$")

_LOGS = {
    "binnacle-mcp": ("mcp.stderr.log", "mcp.stdout.log"),
    "binnacle-jobs": ("com.binnacle.jobs.err.log", "com.binnacle.jobs.out.log"),
    "binnacle-tunnel": ("tunnel.stderr.log", "tunnel.stdout.log"),
}
_ALIASES = {
    **{name: name for name in _LOGS},
    **{name + ".service": name for name in _LOGS},
    "com.binnacle.mcp": "binnacle-mcp",
    "com.binnacle.jobs": "binnacle-jobs",
    "com.binnacle.tunnel": "binnacle-tunnel",
}
_MULTIPLIER = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}


def _instant(value: str, now: datetime) -> float:
    """A documented, deliberately small subset of journalctl's time grammar."""
    raw = value.strip()
    if raw == "now":
        return now.timestamp()
    if raw in {"today", "yesterday"}:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return (midnight - timedelta(days=int(raw == "yesterday"))).timestamp()
    if raw.startswith("@"):
        try:
            return float(raw[1:])
        except ValueError:
            pass
    match = _OFFSET.fullmatch(raw)
    if match and (match.group(1).startswith("-") or match.group(3)):
        amount = abs(int(match.group(1)))
        unit = match.group(2).lower().rstrip("s")
        return now.timestamp() - amount * _MULTIPLIER[unit]
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        raise ServiceLogError(f"unsupported macOS log time window: {value!r}") from None


def _stamp(line: str) -> float | None:
    iso = _ISO.match(line)
    if iso:
        try:
            return datetime.fromisoformat(iso.group(1)).timestamp()
        except ValueError:
            return None
    rich = _RICH.match(line)
    if rich:
        try:
            return (
                datetime.strptime(rich.group(1), "%m/%d/%y %H:%M:%S")
                .astimezone()
                .timestamp()
            )
        except ValueError:
            return None
    return None


def _safe_fd(path: Path) -> BinaryIO:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ServiceLogError("unsafe macOS service log file")
            return os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise
    except OSError as exc:
        raise ServiceLogError(
            f"cannot safely open macOS service log: {type(exc).__name__}"
        ) from exc


@dataclass(frozen=True, slots=True)
class DarwinDaemonLogStatsSource:
    root: Path | None = None
    max_bytes: int = MAX_QUERY_BYTES

    def _paths(self, service: str) -> list[Path]:
        if self.root is None:
            root = Path.home() / "Library" / "Logs" / "binnacle"
        else:
            root = self.root
        try:
            info = root.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise ServiceLogError("unsafe macOS service log directory")
            children = list(root.iterdir())
        except OSError as exc:
            raise ServiceLogError("macOS service log directory unavailable") from exc
        known = _LOGS[service]
        # During a verified finalization both .log.N and .log.N.bz2 may
        # coexist between atomic publication and unlink. Treat them as ONE
        # logical generation: raw wins while present (it may have grown);
        # only after the raw source disappears can the compressed copy win.
        # Do not let a stale pending snapshot replace live evidence.
        generations: dict[tuple[str, str | None], Path] = {}
        for child in children:
            match = _ARCHIVE.fullmatch(child.name)
            if match is None or match.group("base") not in known:
                continue
            key = match.group("base"), match.group("num")
            current = generations.get(key)

            # Raw wins if the archive is still writable; bz2 wins over gz.
            def rank(item: Path) -> int:
                return {".bz2": 1, ".gz": 2}.get(item.suffix, 0)

            if current is None or rank(child) < rank(current):
                generations[key] = child
        selected = list(generations.values())
        if not any(p.name == known[0] for p in selected):
            raise ServiceLogError(f"macOS service log missing: {known[0]}")
        # Oldest archives before active files, across both streams; final merge
        # is by parsed timestamp because stdout/stderr do not share ordering.
        return sorted(selected, key=lambda x: (x.name.endswith(".log"), x.name))

    def read_spec(
        self, services: str | Sequence[str], since: str, until: str | None = None
    ) -> str:
        names = (services,) if isinstance(services, str) else tuple(services)
        if not names:
            raise ServiceLogError("macOS service logs require at least one unit")
        try:
            canonical = tuple(dict.fromkeys(_ALIASES[name] for name in names))
        except KeyError:
            raise ServiceLogError("unrecognised macOS service log unit") from None
        now = datetime.now().astimezone()
        low = _instant(since, now)
        high = _instant(until, now) if until is not None else now.timestamp()
        if high < low:
            raise ServiceLogError("macOS service log window has until before since")
        if self.max_bytes <= 0:
            raise ServiceLogError("invalid macOS service log budget")
        output: list[tuple[float, int, str]] = []
        bytes_read = 0
        sequence = 0
        unstamped = 0
        for service in canonical:
            for path in self._paths(service):
                with _safe_fd(path) as raw:
                    source: BinaryIO | gzip.GzipFile | bz2.BZ2File
                    if path.name.endswith(".gz"):
                        source = gzip.GzipFile(fileobj=raw)
                    elif path.name.endswith(".bz2"):
                        source = bz2.BZ2File(raw)
                    else:
                        source = raw
                    previous: float | None = None
                    # Reading line-by-line bounds memory even when a log has a
                    # single maliciously long line; a positive budget is strict.
                    while True:
                        chunk = source.readline(
                            min(self.max_bytes - bytes_read + 1, 1 << 20)
                        )
                        if not chunk:
                            break
                        bytes_read += len(chunk)
                        if bytes_read > self.max_bytes:
                            raise ServiceLogError(
                                "macOS service log query budget exceeded"
                            )
                        line = chunk.decode("utf-8", "replace")
                        marked = _stamp(line)
                        if marked is not None:
                            previous = marked
                        elif previous is None and "event=" in line:
                            unstamped += 1
                        if previous is not None and low <= previous <= high:
                            # Discard a tail from an overlong physical line
                            # only by failing the whole query at the byte cap.
                            output.append((previous, sequence, line))
                        sequence += 1
                    if source is not raw:
                        source.close()
        if unstamped:
            print(
                f"warning: {unstamped} legacy macOS log lines have no reliable "
                "timestamp and were excluded from this time-window analysis",
                file=sys.stderr,
            )
        output.sort(key=lambda item: (item[0], item[1]))
        return "".join(line for _, _, line in output)
