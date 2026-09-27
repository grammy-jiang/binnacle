"""Isolation for the weekly quality run (scripts/weekly_quality.py).

Every job runs in its own transient user scope, limited to one CPU:

    systemd-run --user --scope --collect --unit=<name> -p CPUQuota=100%
        -p CPUWeight=idle -p MemoryMax=2G -p TasksMax=1024
        -p RuntimeMaxSec=<limit> -- nice -n 19 ionice -c3 timeout -k 30 <T> <command>

What this host enforces (measured 2026-09-28): the user manager delegates
only the cpu and pids controllers, so CPUQuota, CPUWeight, TasksMax and
RuntimeMaxSec hold, while MemoryMax is accepted and ignored. CPUWeight=idle
(cgroup ``cpu.idle`` 1) is what protects production: the scope sits in the
user manager's app.slice beside binnacle-mcp, binnacle-jobs and
binnacle-tunnel and gets CPU only when they do not want it. ``nice``
ranks processes inside one cgroup only, so nice 19 alone did not: a flake
lane at nice 19 raised a neighbouring nice-0 server's read_file p50 from
20 to 32 ms. The other projects run outside the user manager (a login
session scope); for them the one-CPU cap and the load gate are the bound. The runner therefore sums
the scope's resident memory at every check and stops the scope above
2 GiB. The NVMe queue has no I/O scheduler ("none"), so ionice changes
nothing there; it stays for the SD card and a future scheduler.
RuntimeMaxSec bounds a scope even when the runner itself dies.

A job starts only at a quiet moment: no production tool call for
``quiet_s``, a low 1-minute load and enough free memory. While it runs, the
runner stops its scope, by its exact unit name, when a production tool
call arrives (the server got busy), when the host runs short of memory or
when the scope passes its memory cap. The job is then "aborted", never
paused: a paused test run or benchmark would give false results.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from scripts.smoke_checks import last_line
from scripts.weekly_host import TOOL_CALL, Host

KILL_GRACE_S = 30  # timeout -k: SIGKILL this long after SIGTERM
#: cpu.max and cpu.idle inside a scope: CPUQuota=100% and CPUWeight=idle.
EXPECTED_CPU = "100000 100000\n1"
PROBE_SCRIPT = (
    'g="/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup)"; cat "$g/cpu.max" "$g/cpu.idle"'
)


@dataclass(frozen=True)
class Limits:
    quiet_s: float = 300.0  # no production tool call this long before a start
    load_max: float = 2.0  # 1-minute load at a start (4 cores)
    mem_min_kb: int = 3 * 1024 * 1024  # MemAvailable at a start
    mem_floor_kb: int = 1024 * 1024  # abort below this while a job runs
    rss_max_kb: int = 2 * 1024 * 1024  # the scope's memory cap
    # Busy checks while a job runs. Until one sees a production call, the
    # job still slows production a little (measured 2026-09-28: read_file
    # p50 18 -> 24 ms beside a flake lane), so the window is short.
    check_s: float = 10.0
    step_s: float = 2.0  # process polls between the checks
    gate_poll_s: float = 30.0


@dataclass
class Job:
    name: str  # unique within a run; part of the scope's unit name
    argv: Sequence[str]
    cwd: Path
    log: Path
    timeout_s: int
    env: Mapping[str, str]


@dataclass
class Outcome:
    status: str  # ok | failed | timeout | aborted | error
    rc: int | None
    seconds: float
    detail: str = ""


@dataclass
class Samples:
    """What the host looked like while jobs ran (the impact report)."""

    load: list[float] = field(default_factory=list)
    mem_kb: list[int] = field(default_factory=list)
    busy_aborts: int = 0

    def add(self, load: float, mem_kb: int) -> None:
        self.load.append(load)
        self.mem_kb.append(mem_kb)

    def summary(self) -> str:
        if not self.load:
            return "no samples"
        return (
            f"load1 median {statistics.median(self.load):.2f} max {max(self.load):.2f}; "
            f"MemAvailable min {min(self.mem_kb) // 1024} MiB; "
            f"{self.busy_aborts} job(s) stopped for production calls"
        )


def unit_name(run_id: str, job: str) -> str:
    return f"binnacle-weekly-{run_id}-{job}"


def scope_argv(unit: str, timeout_s: int, argv: Sequence[str]) -> list[str]:
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        f"--unit={unit}",
        "-p",
        "CPUQuota=100%",
        "-p",
        "CPUWeight=idle",
        "-p",
        "MemoryMax=2G",
        "-p",
        "TasksMax=1024",
        "-p",
        f"RuntimeMaxSec={timeout_s + KILL_GRACE_S + 60}",
        "--",
        "nice",
        "-n",
        "19",
        "ionice",
        "-c3",
        "timeout",
        "-k",
        str(KILL_GRACE_S),
        str(timeout_s),
        *argv,
    ]


def _calls(host: Host, since: float) -> int:
    return sum(TOOL_CALL in line for line in host.journal(since, None))


def gate_reason(host: Host, limits: Limits) -> str:
    """'' when a job may start now, else why not."""
    calls = _calls(host, host.now() - limits.quiet_s)
    if calls:
        return f"{calls} production tool call(s) in the last {limits.quiet_s:g} s"
    load = host.load1()
    if load >= limits.load_max:
        return f"load {load:.2f} >= {limits.load_max:g}"
    mem = host.mem_available_kb()
    if mem < limits.mem_min_kb:
        return f"MemAvailable {mem // 1024} MiB < {limits.mem_min_kb // 1024} MiB"
    return ""


def wait_for_gate(host: Host, limits: Limits, deadline: float) -> str:
    """Wait for a quiet moment: '' once it comes, else the last reason."""
    while True:
        reason = gate_reason(host, limits)
        if not reason:
            return ""
        if host.now() + limits.gate_poll_s > deadline:
            return reason
        host.sleep(limits.gate_poll_s)


def busy_reason(
    host: Host, limits: Limits, unit: str, since: float, samples: Samples
) -> str:
    """'' while the job may go on, else why it must stop now."""
    calls = _calls(host, since)
    mem = host.mem_available_kb()
    samples.add(host.load1(), mem)
    if calls:
        samples.busy_aborts += 1
        return f"server busy: {calls} production tool call(s)"
    if mem < limits.mem_floor_kb:
        return f"host memory low: MemAvailable {mem // 1024} MiB"
    rss = host.scope_rss_kb(unit)
    if rss is not None and rss > limits.rss_max_kb:
        return f"scope memory {rss // 1024} MiB > {limits.rss_max_kb // 1024} MiB"
    return ""


def stop_scope(host: Host, unit: str) -> None:
    host.run(["systemctl", "--user", "stop", f"{unit}.scope"], 120)


def _status(rc: int) -> str:
    if rc == 0:
        return "ok"
    if rc in (124, 137):  # timeout(1): TERM at the limit, KILL after the grace
        return "timeout"
    return "failed"


def run_job(
    host: Host, limits: Limits, job: Job, unit: str, samples: Samples
) -> Outcome:
    """Run one job in its scope and watch it until it ends or must stop."""
    started = host.now()
    try:
        proc = host.spawn(
            scope_argv(unit, job.timeout_s, job.argv), job.cwd, job.log, job.env
        )
    except OSError as exc:
        return Outcome("error", None, 0.0, f"could not start: {exc}")
    checked = started
    hard_deadline = started + job.timeout_s + KILL_GRACE_S + 60
    while (rc := proc.poll()) is None:
        host.sleep(limits.step_s)
        now = host.now()
        if now - checked < limits.check_s:
            continue
        reason = busy_reason(host, limits, unit, checked - 1, samples)
        checked = now
        if not reason and now > hard_deadline:
            reason = "past its deadline"
        if reason:
            stop_scope(host, unit)
            try:
                proc.wait(timeout=60)
            except Exception as exc:  # noqa: BLE001 - the scope stop killed it
                reason += f" (the stopped job did not report its exit: {exc})"
            return Outcome("aborted", None, host.now() - started, reason)
    seconds = host.now() - started
    stop_scope(host, unit)  # anything the job left behind dies with its scope
    status = _status(rc)
    detail = f"exit {rc}" if status == "failed" else ""
    return Outcome(status, rc, seconds, detail)


def probe_scope(host: Host, run_id: str, log: Path) -> str:
    """'' when this host can create a limited user scope and both CPU
    settings are in force inside it, else the problem (then nothing may run)."""
    unit = unit_name(run_id, "probe")
    argv = scope_argv(
        unit,
        30,
        [
            "/bin/sh",
            "-c",
            PROBE_SCRIPT,
        ],
    )
    rc, out = host.run(argv, 90)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(out, encoding="utf-8")
    if rc != 0:
        return f"systemd-run --user --scope failed (exit {rc}): {last_line(out)}"
    if out.strip() != EXPECTED_CPU:
        shown = " ".join(out.split())
        return f"the CPU settings are not in force (cpu.max, cpu.idle: {shown!r})"
    return ""


@dataclass
class Runner:
    """Runs a run's jobs: each waits for the gate, fits the run's budget, and
    gets one more try when production calls stopped it."""

    host: Host
    limits: Limits
    run_id: str
    run_dir: Path
    env: Mapping[str, str]
    deadline: float  # the end of the whole run's budget
    gate_wait_s: float = 1200.0
    samples: Samples = field(default_factory=Samples)
    timeline: list[str] = field(default_factory=list)

    def execute(
        self,
        name: str,
        argv: Sequence[str],
        timeout_s: int,
        cwd: Path,
        min_s: int = 120,
    ) -> Outcome:
        for attempt in range(2):
            if self.deadline - self.host.now() < min_s:
                return self._note(
                    name, Outcome("skipped", None, 0.0, "no time left in the budget")
                )
            latest_start = min(
                self.host.now() + self.gate_wait_s, self.deadline - min_s
            )
            reason = wait_for_gate(self.host, self.limits, latest_start)
            if reason:
                return self._note(
                    name, Outcome("skipped", None, 0.0, f"no quiet moment: {reason}")
                )
            timeout = int(min(timeout_s, self.deadline - self.host.now()))
            unit = unit_name(self.run_id, name if attempt == 0 else f"{name}-retry")
            job = Job(name, argv, cwd, self.run_dir / f"{name}.log", timeout, self.env)
            outcome = self._note(
                name, run_job(self.host, self.limits, job, unit, self.samples)
            )
            if not (
                outcome.status == "aborted" and outcome.detail.startswith("server busy")
            ):
                return outcome
        return outcome

    def _note(self, name: str, outcome: Outcome) -> Outcome:
        detail = f" ({outcome.detail})" if outcome.detail else ""
        self.timeline.append(
            f"{name}: {outcome.status} in {outcome.seconds:.0f} s{detail}"
        )
        return outcome
