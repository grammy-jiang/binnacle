"""Portable fake tree observation and fail-closed evidence comparison."""

import copy
import platform
import subprocess

import pytest

from tests.fixtures.lsp import raw_benchmark as bench
from tests.fixtures.lsp import resource_sampling as resources
from tests.fixtures.lsp.benchmark_compare import compare


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    """Real fake-wire timings plus explicitly synthetic comparator resource input."""
    directory = tmp_path_factory.mktemp("comparator")
    result = bench.run(directory / "wire.json", fault="child")
    assert result["valid"]
    result["identity"]["sampling"]["enabled"] = True
    pid = result["execution"]["pid"]
    sampler = resources.Sampler(pid, set(), 0.02)
    result["resources"] = sampler.result
    result["resources"]["status"] = "valid"
    result["resources"]["samples"] = [
        {
            "phase": phase,
            "parent_rss_kib": 100,
            "tree_rss_kib": 150,
            "parent_cpu_s": 1,
            "tree_cpu_s": 2 + index / 100,
            "child_count": 1,
            "members": [pid, pid + 1],
            "observed_at_s": index + 1,
        }
        for index, phase in enumerate(p for p in resources.PHASES for _ in range(2))
    ]
    return result


def test_compatible_comparator(measured):
    result = compare(measured, copy.deepcopy(measured))
    assert result["compatible"]
    assert set(result["warm_ms"]) == {"p50", "p95", "p99"}
    assert set(result["resources"]["before"]) == set(resources.PHASES)


def test_native_child_tree_and_compatible_repeat(tmp_path):
    if platform.system() not in ("Linux", "Darwin"):
        pytest.skip("resource observation supports Linux/Darwin only")
    try:
        resources.process_table()
    except (PermissionError, FileNotFoundError) as error:
        pytest.skip(
            f"native ps unavailable: {type(error).__name__}; no resource evidence"
        )
    first = bench.run(tmp_path / "tree.json", sample_resources=True, fault="child")
    other = bench.run(tmp_path / "repeat.json", sample_resources=True, fault="child")
    assert first["valid"] and other["valid"]
    assert compare(first, other)["compatible"]
    for sample in first["resources"]["samples"]:
        assert sample["child_count"] == 1
        assert sample["tree_rss_kib"] > sample["parent_rss_kib"] > 0
        assert sample["tree_cpu_s"] >= sample["parent_cpu_s"]
    assert not first["resources"]["warm_memory_validated"]
    assert first["resources"]["settled"] == "unobserved"


@pytest.mark.parametrize(
    "field",
    [
        "manifest_sha256",
        "provider",
        "harness",
        "os",
        "python",
        "repo_revision",
        "case",
        "profile",
        "method",
        "semantics",
        "workspace_sha256",
        "gold_sha256",
        "setup",
        "measurement",
        "sampling",
    ],
)
def test_missing_or_incompatible_identity(measured, field):
    missing = copy.deepcopy(measured)
    del missing["identity"][field]
    assert not compare(missing, missing)["compatible"]
    changed = copy.deepcopy(measured)
    changed["identity"][field] = "different"
    assert not compare(measured, changed)["compatible"]


@pytest.mark.parametrize(
    "fault",
    [
        "wrong-gold",
        "missing-gold",
        "skipped",
        "partial",
        "invalid",
        "missing-phase",
        "wrong-percentile",
        "wrong-sample",
        "missing-sample",
        "wrong-count",
        "negative-rss",
        "tree-below-parent",
        "nan-cpu",
        "orphan",
        "command",
        "workspace",
        "cleanup",
        "missing-first",
        "missing-cold",
        "index-claim",
        "memory-claim",
        "missing-child",
    ],
)
def test_invalid_evidence_rejected(measured, fault):
    changed = copy.deepcopy(measured)
    if fault == "wrong-gold":
        changed["identity"]["gold_sha256"] = "0" * 64
    elif fault == "missing-gold":
        del changed["gold_verified"]
    elif fault in ("skipped", "partial", "invalid"):
        changed["resources"]["status"] = fault
    elif fault == "missing-phase":
        changed["resources"]["samples"].pop()
    elif fault == "wrong-percentile":
        changed["warm_ms"]["p99"] += 1
    elif fault == "wrong-sample":
        changed["samples"][0]["correct"] = False
    elif fault == "missing-sample":
        changed["samples"].pop()
    elif fault == "wrong-count":
        changed["correct_samples"] = 0
    elif fault == "negative-rss":
        changed["resources"]["samples"][0]["parent_rss_kib"] = -1
    elif fault == "tree-below-parent":
        changed["resources"]["samples"][0]["tree_rss_kib"] = 1
    elif fault == "nan-cpu":
        changed["resources"]["samples"][0]["tree_cpu_s"] = float("nan")
    elif fault == "orphan":
        changed["resources"]["samples"][1]["members"][-1] += 1
    elif fault == "command":
        changed["execution"]["argv"][2] = "/tmp/not-the-fake.py"
    elif fault == "workspace":
        changed["execution"]["cwd"] = "/tmp/different"
    elif fault == "cleanup":
        changed["cleanup_verified"] = False
    elif fault == "missing-first":
        del changed["first_request"]
    elif fault == "missing-cold":
        del changed["cold_initialize_ms"]
    elif fault == "index-claim":
        changed["settling"]["indexed"] = True
    elif fault == "memory-claim":
        changed["resources"]["warm_memory_validated"] = True
    elif fault == "missing-child":
        changed["resources"]["samples"][0]["child_count"] = 0
    assert not compare(measured, changed)["compatible"]
    assert not compare(changed, changed)["compatible"]


def rows():
    return {
        10: {
            "pid": 10,
            "ppid": 1,
            "pgid": 10,
            "rss_kib": 100,
            "cpu_s": 1,
            "start": "a",
        },
        11: {
            "pid": 11,
            "ppid": 10,
            "pgid": 10,
            "rss_kib": 50,
            "cpu_s": 2,
            "start": "b",
        },
        12: {
            "pid": 12,
            "ppid": 11,
            "pgid": 10,
            "rss_kib": 25,
            "cpu_s": 3,
            "start": "c",
        },
    }


def test_nested_tree_totals():
    sample, known = resources.tree_snapshot(rows(), 10, {}, {11})
    assert sample["tree_rss_kib"] == 175
    assert sample["tree_cpu_s"] == 6
    assert sample["child_count"] == 2
    assert known == {10: "a", 11: "b", 12: "c"}


@pytest.mark.parametrize(
    "fault", ["missing-parent", "missing-child", "orphan", "escape", "pid-reuse"]
)
def test_partial_or_escaped_tree_is_invalid(fault):
    table = rows()
    known = {10: "a", 11: "b", 12: "c"}
    if fault == "missing-parent":
        del table[10]
    elif fault == "missing-child":
        del table[12]
    elif fault == "orphan":
        table[11]["ppid"] = 1
    elif fault == "escape":
        table[11]["pgid"] = 11
    else:
        table[12]["start"] = "new"
    with pytest.raises(ValueError):
        resources.tree_snapshot(table, 10, known, {11})


def test_real_escaped_child_invalidates_run(tmp_path):
    try:
        resources.process_table()
    except (PermissionError, FileNotFoundError, NotImplementedError) as error:
        pytest.skip(
            f"native ps unavailable: {type(error).__name__}; no escape evidence"
        )
    result = bench.run(
        tmp_path / "escape.json", fault="escaped-child", sample_resources=True
    )
    assert not result["valid"]
    assert result["resources"]["status"] == "invalid"
    assert result["cleanup_verified"]
    assert not compare(result, result)["compatible"]


def test_skipped_sampling_refuses_comparison(tmp_path):
    result = bench.run(tmp_path / "skipped.json")
    assert result["valid"]
    assert not compare(result, result)["compatible"]


@pytest.mark.parametrize(
    "exception,status",
    [
        (NotImplementedError, "unsupported"),
        (OSError, "invalid"),
        (ValueError, "invalid"),
    ],
)
def test_unavailable_observation_is_not_zero(monkeypatch, exception, status):
    def unavailable():
        raise exception("test")

    monkeypatch.setattr(resources, "process_table", unavailable)
    sampler = resources.Sampler(10, set(), 0.01)
    sampler.capture("cold")
    assert sampler.finish()["status"] == status
    assert sampler.result["samples"] == []


def test_missing_process_and_partial_sampling(monkeypatch):
    monkeypatch.setattr(resources, "process_table", dict)
    sampler = resources.Sampler(10, set(), 0.01)
    sampler.capture("cold")
    assert sampler.finish()["status"] == "invalid"
    assert resources.Sampler(10, set(), 0.01).finish()["status"] == "partial"
    with pytest.raises(ValueError):
        resources.Sampler(10, set(), 1)


@pytest.mark.parametrize(
    "value,expected", [("00:01.20", 1.2), ("01:02:03", 3723), ("1-00:00:01", 86401)]
)
def test_portable_cpu_time(value, expected):
    assert resources.cpu_seconds(value) == expected


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_ps_rows_are_parsed_without_recording_commands(monkeypatch, system):
    def ps(argv, **kwargs):
        assert argv == ["/bin/ps", "-axo", "pid=,ppid=,pgid=,rss=,time=,lstart="]
        assert kwargs["timeout"] == 1 and kwargs["env"]["LC_ALL"] == "C"
        return subprocess.CompletedProcess(
            argv, 0, " 10 1 10 200 00:01.20 Wed Oct 21 10:00:00 2026\n"
        )

    monkeypatch.setattr(resources.subprocess, "run", ps)
    monkeypatch.setattr(resources.platform, "system", lambda: system)
    table = resources.process_table()
    assert table[10]["rss_kib"] == 200 and table[10]["cpu_s"] == 1.2


def test_runner_with_explicit_synthetic_resource_observations(tmp_path, monkeypatch):
    """Exercise phase wiring with synthetic counters, not native resource evidence."""
    original = resources.Sampler.__init__

    def initialize(self, root, expected, interval):
        original(self, root, expected, interval)
        table = {
            pid: {
                "pid": pid,
                "ppid": root if pid != root else 1,
                "pgid": root,
                "rss_kib": 100,
                "cpu_s": 1,
                "start": "fixed",
            }
            for pid in {root, *expected}
        }
        monkeypatch.setattr(resources, "process_table", lambda: table)

    monkeypatch.setattr(resources.Sampler, "__init__", initialize)
    result = bench.run(
        tmp_path / "synthetic.json", fault="child", sample_resources=True
    )
    assert result["valid"]
    assert compare(result, result)["compatible"]
    assert [s["phase"] for s in result["resources"]["samples"]] == [
        "cold",
        "cold",
        "settling",
        "settling",
        "warm",
        "warm",
    ]


def test_runner_cannot_accept_denied_observation(tmp_path, monkeypatch):
    def denied():
        raise PermissionError("synthetic denial")

    monkeypatch.setattr(resources, "process_table", denied)
    result = bench.run(tmp_path / "denied.json", sample_resources=True)
    assert not result["valid"]
    assert result["resources"]["status"] == "unsupported"
    assert result["resources"]["reason"] == "PermissionError"
    assert result["resources"]["samples"] == []
    assert not compare(result, result)["compatible"]


def test_sampler_rejects_changing_membership(monkeypatch):
    table = rows()
    monkeypatch.setattr(resources, "process_table", lambda: table)
    sampler = resources.Sampler(10, {11}, 0.01)
    sampler.capture("cold")
    table[13] = {**table[12], "pid": 13}
    sampler.capture("cold")
    assert sampler.finish()["status"] == "invalid"
