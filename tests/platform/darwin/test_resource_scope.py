"""A5 honest Darwin metrics: typed unavailable totals, measured narrow scopes.

The real direct-child test spawns one child and is itself the sole reaper,
handing its final ``wait4`` rusage to the accounting, exactly as the owning
reaper must. Assertions are portable; ru_maxrss units are normalized per OS.
"""

from __future__ import annotations

import ast
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.platform.contracts.capability_contracts import CapabilityState
from binnacle.platform.contracts.metric_log_contracts import MetricValue, ScopedMetrics
from binnacle.platform.contracts.resource_contracts import (
    NoResourceAccounting,
    ResourceAccounting,
)
from binnacle.platform.darwin import resource_accounting
from binnacle.platform.darwin.resource_accounting import DarwinResourceAccounting

# CAPABILITY-DECISION 1.1.0 scope_decision.unavailable_in_this_revision (A5 rows).
UNAVAILABLE_N6 = {
    "N6.private_libproc_samples", "N6.cpu.stat.usage_usec", "N6.cpu.stat.user_usec",
    "N6.cpu.stat.system_usec", "N6.memory.current", "N6.memory.peak", "N6.pids.current",
    "N6.io.stat.rbytes", "N6.io.stat.wbytes", "N6.memory.events.oom",
    "N6.scope.wait_empty", "N6.resource_history.final", "N6.memory.stat",
    "N6.memory.swap.current", "N6.memory.swap.peak", "N6.memory.swap.events",
    "N6.pids.peak", "N6.processes", "N6.io.stat.rios/wios", "N6.memory.events.oom_kill",
}  # fmt: skip
DIRECT_KEYS = (
    "direct_child.cpu.user_usec",
    "direct_child.cpu.system_usec",
    "direct_child.memory.maxrss_bytes",
)
SELF_KEYS = ("self.cpu.user_usec", "self.cpu.system_usec", "self.memory.maxrss_bytes")
CHILD = (
    "import time\n"
    "block = bytearray(48 << 20)\n"  # resident: pages are touched below
    "block[:: 4096] = b'x' * len(block[:: 4096])\n"
    "end = time.process_time() + 0.25\n"
    "while time.process_time() < end:\n"
    "    pass\n"
)


def rusage(utime=0.5, stime=0.25, maxrss=1000):
    return SimpleNamespace(ru_utime=utime, ru_stime=stime, ru_maxrss=maxrss)


def assert_never_invented(values: Mapping[str, MetricValue]) -> None:
    for key, metric in values.items():
        assert metric.unit and metric.scope in ("self", "direct_child", "job"), key
        if metric.capability.state in (
            CapabilityState.UNKNOWN,
            CapabilityState.UNAVAILABLE,
        ):
            assert metric.value is None, key  # never zero
            assert metric.sampled_at_epoch is None and metric.final is False, key
        else:
            assert metric.capability.state is CapabilityState.LIMITED, key
            assert isinstance(metric.value, int) and metric.value >= 0, key
        assert metric.capability.state is not CapabilityState.AVAILABLE, key


@pytest.mark.parametrize("identity", [None, "", "/legacy/job-012345abcdef"])
def test_legacy_facade_matches_no_accounting_and_invents_no_cgroup(identity):
    darwin: ResourceAccounting = DarwinResourceAccounting()
    legacy: ResourceAccounting = NoResourceAccounting()
    argv = ["bash", "-c", "two words"]
    for port in (darwin, legacy):
        assert port.prepare() is None and port.prepare(log_ready=True) is None
        assert port.create("012345abcdef") is None
        assert port.wrap_argv(argv, identity) is argv
        assert port.snapshot(identity) == {}
        assert port.wait_empty("/legacy/job-012345abcdef") is False
        assert port.cleanup(identity) is (identity is None)
    assert argv == ["bash", "-c", "two words"]


@pytest.mark.parametrize("job_id", [None, "012345abcdef"])
def test_every_job_wide_total_is_typed_unavailable_never_zero(job_id):
    scoped: ScopedMetrics = DarwinResourceAccounting()
    values = scoped.snapshot_scoped(job_id)
    job = {key: metric for key, metric in values.items() if metric.scope == "job"}
    assert {m.capability.evidence_id for m in job.values()} == UNAVAILABLE_N6
    for key, metric in job.items():
        assert key.startswith("job.")
        assert metric.capability.state is CapabilityState.UNAVAILABLE
        assert metric.capability.reason_code == "darwin_job_scope_unavailable"
        assert "no complete Darwin job-membership" in metric.capability.scope
        assert metric.value is None
    assert values["job.scope.empty"].value is None  # no empty-scope proof
    assert values["job.memory.peak_bytes"].value is None  # no aggregate peak
    assert_never_invented(values)


def test_self_scope_is_measured_and_labelled_self_only():
    values = DarwinResourceAccounting().snapshot_scoped()
    for key in SELF_KEYS:
        metric = values[key]
        assert metric.capability.state is CapabilityState.LIMITED
        assert metric.capability.reason_code == "measured_self_getrusage"
        assert metric.scope == "self" and metric.final is False
        assert metric.sampled_at_epoch is not None
    assert values["self.memory.maxrss_bytes"].value > 1 << 20  # bytes, not KiB
    assert not any(key.startswith("direct_child.") for key in values)
    assert_never_invented(values)


def test_missing_record_is_unknown_not_zero():
    values = DarwinResourceAccounting().snapshot_scoped("012345abcdef")
    for key in DIRECT_KEYS:
        metric = values[key]
        assert metric.capability.state is CapabilityState.UNKNOWN
        assert metric.capability.reason_code == "direct_child_observation_missing"
        assert metric.value is None and metric.scope == "direct_child"
    assert not any(key.startswith("self.") for key in values)
    assert_never_invented(values)


def test_restarted_accounting_loses_samples_as_unknown():
    before = DarwinResourceAccounting()
    before.record_direct_child_exit("job-1", rusage(), observed_at=1234.5)
    assert before.snapshot_scoped("job-1")[DIRECT_KEYS[0]].value == 500_000
    restarted = DarwinResourceAccounting()  # a new owner generation
    metric = restarted.snapshot_scoped("job-1")[DIRECT_KEYS[0]]
    assert metric.capability.state is CapabilityState.UNKNOWN and metric.value is None


def test_measured_zero_is_kept_only_for_an_observed_value():
    accounting = DarwinResourceAccounting()
    accounting.record_direct_child_exit("job-0", rusage(0.0, 0.0, 0), observed_at=1.0)
    values = accounting.snapshot_scoped("job-0")
    for key in DIRECT_KEYS:
        assert values[key].capability.state is CapabilityState.LIMITED
        assert values[key].value == 0 and values[key].final is True
    assert_never_invented(values)


def test_real_direct_child_wait4_counters_from_the_single_reaper():
    accounting = DarwinResourceAccounting()
    pid = os.posix_spawn(
        sys.executable, [sys.executable, "-c", CHILD], dict(os.environ)
    )
    reaped, status, usage = os.wait4(pid, 0)  # this test is the sole reaper
    assert reaped == pid and os.waitstatus_to_exitcode(status) == 0
    accounting.record_direct_child_exit("job-real", usage, observed_at=42.0)
    values = accounting.snapshot_scoped("job-real")
    user = values["direct_child.cpu.user_usec"]
    assert user.capability.state is CapabilityState.LIMITED
    assert user.capability.reason_code == "measured_direct_child_wait4"
    assert user.capability.evidence_id == "N6.direct_child_wait4"
    assert "never a job total" in user.capability.scope
    assert user.final is True and user.sampled_at_epoch == 42.0
    total_cpu = user.value + values["direct_child.cpu.system_usec"].value
    assert total_cpu >= 200_000
    assert values["direct_child.memory.maxrss_bytes"].value >= 48 << 20
    assert values["job.cpu.usage_usec"].value is None  # still not a job total
    assert_never_invented(values)
    with pytest.raises(ValueError, match="already recorded"):
        accounting.record_direct_child_exit("job-real", usage)  # no second collector


def test_invalid_observations_are_refused_without_recording():
    accounting = DarwinResourceAccounting()
    bad = [
        (rusage(utime=-1.0), ValueError),
        (rusage(stime=float("nan")), ValueError),
        (rusage(maxrss=-5), ValueError),
        (rusage(utime="1"), TypeError),
        (rusage(maxrss=True), TypeError),
        (object(), TypeError),
    ]
    for observation, error in bad:
        with pytest.raises(error):
            accounting.record_direct_child_exit("job-x", observation)
    with pytest.raises(ValueError, match="job_id"):
        accounting.record_direct_child_exit("", rusage())
    with pytest.raises(ValueError):
        accounting.record_direct_child_exit("job-x", rusage(), observed_at=float("inf"))
    metric = accounting.snapshot_scoped("job-x")[DIRECT_KEYS[0]]
    assert metric.capability.state is CapabilityState.UNKNOWN


def test_positive_cleanup_and_bounded_retention(monkeypatch):
    monkeypatch.setattr(resource_accounting, "MAX_RECORDED_JOBS", 2)
    accounting = DarwinResourceAccounting()
    for job in ("a", "b", "c"):
        accounting.record_direct_child_exit(job, rusage(), observed_at=1.0)
    evicted = accounting.snapshot_scoped("a")[DIRECT_KEYS[0]]
    assert evicted.capability.state is CapabilityState.UNKNOWN  # evicted, not zero
    assert accounting.discard_job("b") is True
    assert accounting.discard_job("b") is False
    assert accounting.snapshot_scoped("b")[DIRECT_KEYS[0]].value is None
    assert accounting.snapshot_scoped("c")[DIRECT_KEYS[0]].value == 500_000


def test_module_never_waits_signals_or_samples_private_libproc():
    source = Path(resource_accounting.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "wait", "wait3", "wait4", "waitpid", "waitid", "kill", "killpg",
        "posix_spawn", "fork", "CDLL", "cdll", "proc_pidinfo", "proc_pid_rusage",
    }  # fmt: skip
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert not called & forbidden
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imported & {"ctypes", "subprocess", "signal", "cffi"}
