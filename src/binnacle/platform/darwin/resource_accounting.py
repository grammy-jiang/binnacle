"""Honest Darwin resource accounting: measured scopes only, never invented totals.

Darwin has no cgroup-equivalent job scope here, so the legacy
``ResourceAccounting`` facade is inert: no identity, empty legacy snapshot,
``wait_empty`` False and cleanup only of the absent identity. ``B0`` must not
render that empty map as measured zero totals. ``snapshot_scoped`` instead names
every job-wide counter with an explicit ``UNAVAILABLE`` value of ``None``.

Measured values have narrow scopes. ``self`` is this process's own
``getrusage``. ``direct_child`` is the final ``wait4`` rusage that the single
owning reaper hands to ``record_direct_child_exit``; this module never waits for,
polls or signals a process. That rusage covers the direct child plus only those
descendants it reaped itself; escaped or orphaned descendants are excluded, so it
is never a job total. A missing, evicted or pre-restart observation is
``UNKNOWN`` with ``None``. Private libproc sampling stays disabled.
"""

from __future__ import annotations

import math
import resource
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from binnacle.platform.contracts.capability_contracts import (
    Capability,
    CapabilityState,
)
from binnacle.platform.contracts.metric_log_contracts import MetricValue

MAX_RECORDED_JOBS = 4096
DIRECT_CHILD_SCOPE = (
    "direct_child:final wait4 rusage from the sole owning reaper; includes only "
    "descendants the child reaped itself; never a job total"
)
SELF_SCOPE = "self:getrusage(RUSAGE_SELF) of this process only"
JOB_SCOPE = "job:no complete Darwin job-membership primitive"
# ru_maxrss is bytes on Darwin and KiB on Linux.
_MAXRSS_UNIT_BYTES = 1 if sys.platform == "darwin" else 1024
# (N6 evidence id, metric key, unit): every job-wide total is unavailable.
UNAVAILABLE_JOB_METRICS: tuple[tuple[str, str, str], ...] = (
    ("N6.cpu.stat.usage_usec", "job.cpu.usage_usec", "usec"),
    ("N6.cpu.stat.user_usec", "job.cpu.user_usec", "usec"),
    ("N6.cpu.stat.system_usec", "job.cpu.system_usec", "usec"),
    ("N6.memory.current", "job.memory.current_bytes", "bytes"),
    ("N6.memory.peak", "job.memory.peak_bytes", "bytes"),
    ("N6.memory.stat", "job.memory.stat", "bytes"),
    ("N6.memory.swap.current", "job.memory.swap_current_bytes", "bytes"),
    ("N6.memory.swap.peak", "job.memory.swap_peak_bytes", "bytes"),
    ("N6.memory.swap.events", "job.memory.swap_events", "count"),
    ("N6.memory.events.oom", "job.memory.oom_events", "count"),
    ("N6.memory.events.oom_kill", "job.memory.oom_kill_events", "count"),
    ("N6.pids.current", "job.pids.current", "count"),
    ("N6.pids.peak", "job.pids.peak", "count"),
    ("N6.processes", "job.processes", "count"),
    ("N6.io.stat.rbytes", "job.io.read_bytes", "bytes"),
    ("N6.io.stat.wbytes", "job.io.write_bytes", "bytes"),
    ("N6.io.stat.rios/wios", "job.io.read_ops", "count"),
    ("N6.io.stat.rios/wios", "job.io.write_ops", "count"),
    ("N6.scope.wait_empty", "job.scope.empty", "bool"),
    ("N6.resource_history.final", "job.resource_history.final", "bool"),
    ("N6.private_libproc_samples", "job.libproc_sample", "sample"),
)
_DIRECT_CHILD_KEYS = (
    ("direct_child.cpu.user_usec", "usec"),
    ("direct_child.cpu.system_usec", "usec"),
    ("direct_child.memory.maxrss_bytes", "bytes"),
)


@dataclass(frozen=True)
class DirectChildExit:
    """One final direct-child rusage observation, already normalized."""

    user_usec: int
    system_usec: int
    maxrss_bytes: int
    observed_at: float


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("rusage value must be a number")
    if not math.isfinite(value) or value < 0:
        raise ValueError("rusage value must be a finite non-negative number")
    return float(value)


def _usec(seconds: object) -> int:
    return round(_finite(seconds) * 1_000_000)


def _maxrss_bytes(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("rusage maxrss must be an integer")
    if value < 0:
        raise ValueError("rusage maxrss must be non-negative")
    return value * _MAXRSS_UNIT_BYTES


def _value(
    state: CapabilityState,
    reason: str,
    *,
    unit: str,
    scope: Literal["self", "direct_child", "job"],
    scope_text: str,
    value: int | None = None,
    sampled_at: float | None = None,
    final: bool = False,
    evidence_id: str | None = None,
) -> MetricValue:
    if state in (CapabilityState.UNKNOWN, CapabilityState.UNAVAILABLE):
        value, sampled_at, final = None, None, False
    capability = Capability(state, reason, scope_text, evidence_id)
    return MetricValue(capability, value, unit, scope, sampled_at, final)


class DarwinResourceAccounting:
    """Compatibility-inert ResourceAccounting plus typed scoped metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._exits: OrderedDict[str, DirectChildExit] = OrderedDict()

    # Legacy ResourceAccounting compatibility: no cgroup is ever invented.
    def prepare(self, *, log_ready: bool = False) -> str | None:
        return None

    def create(self, job_id: str) -> str | None:
        return None

    def wrap_argv(self, argv: list[str], identity: str | None) -> list[str]:
        return argv

    def snapshot(self, identity: str | None) -> dict[str, object]:
        return {}

    def wait_empty(self, identity: str) -> bool:
        return False

    def cleanup(self, identity: str | None) -> bool:
        return identity is None

    def record_direct_child_exit(
        self, job_id: str, rusage: object, *, observed_at: float | None = None
    ) -> None:
        """Accept the sole reaper's final ``wait4`` rusage for one job's child.

        A second observation for the same job is refused: there is exactly one
        owning reaper, and a competing collector would be a contract breach.
        """

        if not isinstance(job_id, str) or not job_id:
            raise ValueError("job_id must be a non-empty string")
        observation = DirectChildExit(
            _usec(getattr(rusage, "ru_utime", None)),
            _usec(getattr(rusage, "ru_stime", None)),
            _maxrss_bytes(getattr(rusage, "ru_maxrss", None)),
            time.time() if observed_at is None else _finite(observed_at),
        )
        with self._lock:
            if job_id in self._exits:
                raise ValueError("direct-child exit already recorded for this job")
            self._exits[job_id] = observation
            while len(self._exits) > MAX_RECORDED_JOBS:
                self._exits.popitem(last=False)

    def discard_job(self, job_id: str) -> bool:
        """Drop a job's in-memory observation; True only if one was removed."""

        with self._lock:
            return self._exits.pop(job_id, None) is not None

    def snapshot_scoped(self, job_id: str | None = None) -> Mapping[str, MetricValue]:
        values = {
            key: _value(
                CapabilityState.UNAVAILABLE,
                "darwin_job_scope_unavailable",
                unit=unit,
                scope="job",
                scope_text=JOB_SCOPE,
                evidence_id=evidence,
            )
            for evidence, key, unit in UNAVAILABLE_JOB_METRICS
        }
        if job_id is None:
            values.update(self._self_values())
        else:
            values.update(self._direct_child_values(job_id))
        return values

    def _self_values(self) -> dict[str, MetricValue]:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        now = time.time()
        measured = (
            ("self.cpu.user_usec", _usec(usage.ru_utime), "usec"),
            ("self.cpu.system_usec", _usec(usage.ru_stime), "usec"),
            ("self.memory.maxrss_bytes", _maxrss_bytes(usage.ru_maxrss), "bytes"),
        )
        return {
            key: _value(
                CapabilityState.LIMITED,
                "measured_self_getrusage",
                unit=unit,
                scope="self",
                scope_text=SELF_SCOPE,
                value=amount,
                sampled_at=now,
            )
            for key, amount, unit in measured
        }

    def _direct_child_values(self, job_id: str) -> dict[str, MetricValue]:
        with self._lock:
            exit_ = self._exits.get(job_id)
        if exit_ is None:
            # Never recorded, still running, evicted or lost across a restart:
            # indistinguishable here, so the value is unknown, never zero.
            return {
                key: _value(
                    CapabilityState.UNKNOWN,
                    "direct_child_observation_missing",
                    unit=unit,
                    scope="direct_child",
                    scope_text=DIRECT_CHILD_SCOPE,
                )
                for key, unit in _DIRECT_CHILD_KEYS
            }
        amounts = (exit_.user_usec, exit_.system_usec, exit_.maxrss_bytes)
        return {
            key: _value(
                CapabilityState.LIMITED,
                "measured_direct_child_wait4",
                unit=unit,
                scope="direct_child",
                scope_text=DIRECT_CHILD_SCOPE,
                value=amount,
                sampled_at=exit_.observed_at,
                final=True,
                evidence_id="N6.direct_child_wait4",
            )
            for (key, unit), amount in zip(_DIRECT_CHILD_KEYS, amounts, strict=True)
        }
