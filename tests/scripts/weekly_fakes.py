"""A fake host for the weekly quality run's tests: a clock, a production
journal, load and memory, scopes and processes. Nothing real is started."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from scripts.weekly_host import Host

T0 = 1_790_500_000.0


@dataclass
class FakeProc:
    host: FakeHost
    ends_at: float
    rc: int
    unit: str = ""
    pid: int = 4242
    killed: bool = False

    def poll(self) -> int | None:
        if self.killed:
            return -15
        return self.rc if self.host.t >= self.ends_at else None

    def wait(self, timeout: float | None = None) -> int:
        return -15 if self.killed else self.rc


@dataclass
class FakeHost:
    """``calls_at``: production tool_call times; ``plans``: per spawned job,
    (seconds it runs, exit code, a side effect run at spawn time)."""

    t: float = T0
    calls_at: list[float] = field(default_factory=list)
    load: float = 0.5
    mem_kb: int = 8 * 1024 * 1024
    rss_kb: int | None = 100 * 1024
    plans: list[tuple[float, int, Callable[[Sequence[str]], None] | None]] = field(
        default_factory=list
    )
    run_results: dict[str, tuple[int, str]] = field(default_factory=dict)
    ran: list[list[str]] = field(default_factory=list)
    spawned: list[list[str]] = field(default_factory=list)
    procs: list[FakeProc] = field(default_factory=list)

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def journal(self, since: float, until: float | None) -> list[str]:
        end = self.t if until is None else until
        return [
            f"x INFO: event=tool_call call=c{i} tool=read_file client=openai-mcp args={{}}"
            for i, at in enumerate(self.calls_at)
            if since <= at <= end
        ]

    def run(self, argv: Sequence[str], timeout: float) -> tuple[int, str]:
        self.ran.append(list(argv))
        joined = " ".join(argv)
        if argv[:3] == ["systemctl", "--user", "stop"]:
            unit = argv[3].removesuffix(".scope")
            for proc in self.procs:
                if proc.poll() is None and proc.unit == unit:
                    proc.killed = True
            return 0, ""
        for key, result in self.run_results.items():
            if key in joined:
                return result
        return 0, ""

    def spawn(
        self, argv: Sequence[str], cwd: Path, log: Path, env: Mapping[str, str]
    ) -> FakeProc:
        self.spawned.append(list(argv))
        seconds, rc, effect = self.plans.pop(0) if self.plans else (10.0, 0, None)
        if effect:
            effect(argv)
        unit = next(a.removeprefix("--unit=") for a in argv if a.startswith("--unit="))
        proc = FakeProc(self, self.t + seconds, rc, unit)
        self.procs.append(proc)
        return proc

    def as_host(self) -> Host:
        return Host(
            run=self.run,
            spawn=self.spawn,
            journal=self.journal,
            now=self.now,
            sleep=self.sleep,
            load1=lambda: self.load,
            mem_available_kb=lambda: self.mem_kb,
            scope_rss_kb=lambda unit: self.rss_kb,
        )


def stops(host: FakeHost) -> list[str]:
    """The scope units the runner stopped, in order."""
    return [argv[3] for argv in host.ran if argv[:3] == ["systemctl", "--user", "stop"]]


def inner(argv: Sequence[str]) -> list[str]:
    """The job's own command inside a scope_argv command line."""
    rest = list(argv[argv.index("--") + 1 :])
    return rest[rest.index("timeout") + 4 :]
