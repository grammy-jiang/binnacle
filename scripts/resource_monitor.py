#!/usr/bin/env python3
"""Low-overhead PSI-triggered burst capture.

Steady state is fully event-driven: PSI file descriptors sleep in ``poll()``
until the kernel signals a pressure threshold.  Per-job resource attribution is
owned by the Binnacle job lifecycle itself, so this monitor never scans durable
jobs or ``/proc`` on a timer.  Bursts are bounded and cooldown-limited.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import select
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger("binnacle.resource_monitor")
STATE_ROOT = Path(
    os.environ.get(
        "BINNACLE_RESOURCE_STATE", "~/.local/state/binnacle/resource-monitor"
    )
).expanduser()
BURST_ROOT = STATE_ROOT / "bursts"
BURST_S = int(os.environ.get("BINNACLE_RESOURCE_BURST_S", "300"))
RETENTION_DAYS = int(os.environ.get("BINNACLE_RESOURCE_BURST_RETENTION_DAYS", "90"))


@dataclass(frozen=True)
class Trigger:
    name: str
    path: str
    mode: str
    stall_us: int
    max_bursts_per_day: int
    min_interval_s: int
    window_us: int = 10_000_000

    @property
    def expression(self) -> str:
        return f"{self.mode} {self.stall_us} {self.window_us}"


TRIGGERS = (
    Trigger(
        "cpu",
        "/proc/pressure/cpu",
        "some",
        int(os.environ.get("BINNACLE_PSI_CPU_STALL_US", "2500000")),
        int(os.environ.get("BINNACLE_RESOURCE_CPU_MAX_BURSTS_PER_DAY", "8")),
        int(os.environ.get("BINNACLE_RESOURCE_CPU_MIN_INTERVAL_S", "1800")),
    ),
    Trigger(
        "memory",
        "/proc/pressure/memory",
        "some",
        int(os.environ.get("BINNACLE_PSI_MEMORY_STALL_US", "500000")),
        int(os.environ.get("BINNACLE_RESOURCE_MEMORY_MAX_BURSTS_PER_DAY", "4")),
        int(os.environ.get("BINNACLE_RESOURCE_MEMORY_MIN_INTERVAL_S", "1800")),
    ),
    Trigger(
        "io",
        "/proc/pressure/io",
        "some",
        int(os.environ.get("BINNACLE_PSI_IO_STALL_US", "1000000")),
        int(os.environ.get("BINNACLE_RESOURCE_IO_MAX_BURSTS_PER_DAY", "6")),
        int(os.environ.get("BINNACLE_RESOURCE_IO_MIN_INTERVAL_S", "2700")),
    ),
)


def _system_snapshot() -> dict[str, object]:
    out: dict[str, object] = {"time": time.time()}
    for name in ("cpu", "memory", "io"):
        try:
            out[f"psi_{name}"] = Path(f"/proc/pressure/{name}").read_text().strip()
        except OSError:
            pass
    for src, key in (("/proc/loadavg", "loadavg"), ("/proc/meminfo", "meminfo")):
        try:
            out[key] = Path(src).read_text().strip()
        except OSError:
            pass
    try:
        proc = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        out["throttled"] = proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return out


def _prune_bursts(now: float) -> None:
    cutoff = now - RETENTION_DAYS * 86400
    try:
        dirs = [p for p in BURST_ROOT.iterdir() if p.is_dir()]
    except OSError:
        return
    for path in dirs:
        try:
            if path.stat().st_mtime < cutoff:
                shutil.rmtree(path)
        except OSError:
            pass


def _daily_count(now: float, resource: str) -> int:
    prefix = datetime.fromtimestamp(now).astimezone().strftime("%Y%m%d")
    suffix = f"-psi-{resource}"
    try:
        return sum(
            1
            for p in BURST_ROOT.iterdir()
            if p.is_dir() and p.name.startswith(prefix) and p.name.endswith(suffix)
        )
    except OSError:
        return 0


def _sadc_path() -> str | None:
    for candidate in (shutil.which("sadc"), "/usr/libexec/sysstat/sadc"):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def run_burst(trigger: str, seconds: int = BURST_S) -> Path:
    now = time.time()
    BURST_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(now).astimezone().strftime("%Y%m%dT%H%M%S%z")
    directory = BURST_ROOT / f"{stamp}-{trigger}"
    directory.mkdir(mode=0o700)
    meta = {
        "trigger": trigger,
        "started_at": now,
        "seconds": seconds,
        "pidstat": "active tasks only; CPU/memory/disk at 1 second",
        "sysstat": "DISK,POWER at 1 second",
        "start": _system_snapshot(),
    }
    (directory / "meta.json").write_text(json.dumps(meta, indent=2))
    LOG.info(
        "event=resource_burst_start trigger=%s seconds=%d dir=%s",
        trigger,
        seconds,
        directory,
    )

    pidstat = shutil.which("pidstat")
    sadc = _sadc_path()
    processes: list[subprocess.Popen] = []
    gzip_proc: subprocess.Popen | None = None
    raw_pipe = None
    if pidstat:
        raw_pipe = subprocess.Popen(
            [pidstat, "-urd", "1", str(seconds)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        stdout_pipe = raw_pipe.stdout
        if stdout_pipe is None:
            raise RuntimeError("pidstat stdout pipe unavailable")
        with open(directory / "pidstat.txt.gz", "wb") as compressed:
            gzip_proc = subprocess.Popen(
                ["gzip", "-1"], stdin=stdout_pipe, stdout=compressed
            )
        stdout_pipe.close()
        processes.append(raw_pipe)
    if sadc:
        processes.append(
            subprocess.Popen(
                [
                    sadc,
                    "-S",
                    "DISK,POWER",
                    "1",
                    str(seconds),
                    str(directory / "sysstat.sa"),
                ]
            )
        )
    for proc in processes:
        proc.wait()
    if gzip_proc is not None:
        gzip_proc.wait()

    ended_at = time.time()
    meta["ended_at"] = ended_at
    meta["end"] = _system_snapshot()
    meta["returncodes"] = [proc.returncode for proc in processes]
    if gzip_proc is not None:
        meta["gzip_returncode"] = gzip_proc.returncode
    (directory / "meta.json").write_text(json.dumps(meta, indent=2))
    _prune_bursts(time.time())
    LOG.info(
        "event=resource_burst_end trigger=%s duration_s=%.1f dir=%s",
        trigger,
        ended_at - now,
        directory,
    )
    return directory


class Monitor:
    def __init__(self, *, burst_seconds: int = BURST_S) -> None:
        self.burst_seconds = burst_seconds
        self.poller = select.poll()
        self.fds: dict[int, Trigger] = {}
        self.active = threading.Event()
        self.last_burst: dict[str, float] = {}
        self._suppression_notices: set[str] = set()
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            legacy_last_burst = float((STATE_ROOT / "last-burst").read_text())
        except (OSError, ValueError):
            legacy_last_burst = 0.0
        for spec in TRIGGERS:
            try:
                last = float((STATE_ROOT / f"last-burst-{spec.name}").read_text())
            except (OSError, ValueError):
                last = legacy_last_burst
            self.last_burst[spec.name] = last

    def open_triggers(self) -> None:
        for spec in TRIGGERS:
            fd = os.open(spec.path, os.O_RDWR | os.O_NONBLOCK)
            os.write(fd, (spec.expression + "\n").encode())
            self.poller.register(fd, select.POLLPRI | select.POLLERR)
            self.fds[fd] = spec
            LOG.info(
                "event=psi_trigger_registered resource=%s expression=%s",
                spec.name,
                spec.expression,
            )

    def close(self) -> None:
        for fd in list(self.fds):
            try:
                self.poller.unregister(fd)
            except OSError:
                pass
            os.close(fd)
        self.fds.clear()

    def _suppress_once(self, spec: Trigger, reason: str, now: float) -> None:
        day = datetime.fromtimestamp(now).astimezone().strftime("%Y%m%d")
        key = f"{day}:{spec.name}:{reason}"
        if key in self._suppression_notices:
            return
        LOG.info(
            "event=resource_burst_suppressed reason=%s resource=%s",
            reason,
            spec.name,
        )
        self._suppression_notices.add(key)

    def _start_burst(self, spec: Trigger) -> None:
        now = time.time()
        if self.active.is_set():
            return
        if now - self.last_burst.get(spec.name, 0.0) < spec.min_interval_s:
            self._suppress_once(spec, "min_interval", now)
            return
        if _daily_count(now, spec.name) >= spec.max_bursts_per_day:
            self._suppress_once(spec, "daily_cap", now)
            return
        self.last_burst[spec.name] = now
        (STATE_ROOT / f"last-burst-{spec.name}").write_text(str(now))
        # Keep the legacy global timestamp fresh so a rollback to the old monitor
        # still observes a conservative cooldown rather than bursting immediately.
        (STATE_ROOT / "last-burst").write_text(str(now))
        self.active.set()

        def worker() -> None:
            try:
                run_burst(f"psi-{spec.name}", self.burst_seconds)
            except Exception:
                LOG.exception("event=resource_burst_error resource=%s", spec.name)
            finally:
                self.active.clear()

        threading.Thread(target=worker, name="resource-burst", daemon=True).start()

    def run(self) -> None:
        self.open_triggers()
        try:
            while True:
                # No timeout by design.  The monitor consumes no periodic wakeups
                # in steady state; the kernel wakes us only for a registered PSI
                # threshold event.
                for fd, _event in self.poller.poll():
                    spec = self.fds.get(fd)
                    if spec is None:
                        continue
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        os.read(fd, 4096)
                    except OSError:
                        pass
                    self._start_burst(spec)
        finally:
            self.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--burst-now", type=int, metavar="SECONDS")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if args.burst_now is not None:
        print(run_burst("manual", max(2, args.burst_now)))
        return
    Monitor().run()


if __name__ == "__main__":
    main()
