"""Fail-closed comparator for fake-only benchmark artifacts, not provider rankings.

Usage: python -m tests.fixtures.lsp.benchmark_compare FIRST.json SECOND.json
No budget, statistical significance, indexing or long-residency claims.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from tests.fixtures.lsp import raw_benchmark as bench
from tests.fixtures.lsp.resource_sampling import METHOD, PHASES


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def hash_string(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def validate_identity(identity: dict, manifest: dict) -> None:
    require(
        set(identity)
        == {
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
        },
        "missing identity",
    )
    require(identity["manifest_sha256"] == bench.MANIFEST_SHA256, "manifest mismatch")
    for field in ("case", "profile", "method", "semantics", "setup"):
        require(identity[field] == manifest[field], "workload mismatch")
    for field in ("workspace", "gold"):
        require(
            identity[field + "_sha256"]
            == bench.digest(bench.canonical(manifest[field])),
            "workspace/gold mismatch",
        )
    provider = identity["provider"]
    require(
        provider["name"] == "binnacle-fake-lsp" and provider["version"] == "0",
        "not fake",
    )
    require(set(provider["sources"]) == set(bench.PROVIDER_FILES), "incomplete package")
    require(
        all(hash_string(v) for v in provider["sources"].values()),
        "bad source fingerprint",
    )
    require(
        provider["package_sha256"]
        == bench.digest(bench.canonical(provider["sources"])),
        "package fingerprint mismatch",
    )
    require(
        set(identity["harness"])
        == {
            "raw_benchmark.py",
            "lsp_peer.py",
            "process_observer.py",
            "resource_sampling.py",
            "benchmark_compare.py",
        }
        and all(hash_string(v) for v in identity["harness"].values()),
        "incomplete harness",
    )
    require(
        set(identity["os"]) == {"system", "release", "machine"}
        and all(identity["os"].values()),
        "missing OS",
    )
    require(
        set(identity["python"]) == {"version", "executable", "sha256"}
        and all(identity["python"].values())
        and hash_string(identity["python"]["sha256"]),
        "missing Python",
    )
    require(
        isinstance(identity["repo_revision"], str)
        and len(identity["repo_revision"]) == 40,
        "missing revision",
    )
    setup = identity["measurement"]
    require(
        set(setup)
        == {
            "warm_requests",
            "deadline_s",
            "fault",
            "percentiles",
            "transport",
            "clock",
            "timing",
        },
        "missing measurement setup",
    )
    require(
        type(setup["warm_requests"]) is int and 30 <= setup["warm_requests"] <= 1000,
        "insufficient requests",
    )
    require(
        number(setup["deadline_s"]) and 0.01 <= setup["deadline_s"] <= 3,
        "invalid deadline",
    )
    require(
        setup["fault"] in ("none", "child")
        and setup["percentiles"] == "nearest-rank"
        and setup["transport"] == "raw-stdio"
        and setup["clock"] == "perf_counter_ns"
        and bool(setup["timing"]),
        "invalid measurement method",
    )
    sampling = identity["sampling"]
    require(
        set(sampling)
        == {"enabled", "method", "interval_s", "snapshots_per_phase", "cold_timing"},
        "missing sampling setup",
    )
    require(
        sampling["enabled"] is True
        and sampling["method"] == METHOD
        and sampling["snapshots_per_phase"] == 2
        and bool(sampling["cold_timing"])
        and number(sampling["interval_s"])
        and 0.01 <= sampling["interval_s"] <= 0.2,
        "skipped/invalid sampling setup",
    )


def validate_resources(resources: dict, identity: dict, pid: int) -> dict:
    require(
        resources["status"] == "valid" and resources["method"] == METHOD,
        "partial/invalid resource observations",
    )
    require(
        resources["interval_s"] == identity["sampling"]["interval_s"],
        "sampling mismatch",
    )
    require(
        resources["settled"] == "unobserved"
        and resources["warm_memory_validated"] is False,
        "unsupported settling/memory claim",
    )
    require(
        resources["cpu_semantics"] == "cumulative ps TIME seconds; rounded by OS"
        and resources["rss_semantics"]
        == "sum of observed RSS KiB; shared pages may double count"
        and "reason" not in resources,
        "missing resource semantics or observation failure",
    )
    samples = resources["samples"]
    require(
        len(samples) == 6
        and [s["phase"] for s in samples] == [p for p in PHASES for _ in range(2)],
        "incomplete phases",
    )
    previous = None
    for sample in samples:
        for field in (
            "parent_rss_kib",
            "tree_rss_kib",
            "parent_cpu_s",
            "tree_cpu_s",
            "observed_at_s",
        ):
            require(number(sample[field]), "invalid resource number")
        require(
            sample["tree_rss_kib"] >= sample["parent_rss_kib"] > 0
            and sample["tree_cpu_s"] >= sample["parent_cpu_s"],
            "invalid tree totals",
        )
        count = 1 if identity["measurement"]["fault"] == "child" else 0
        require(
            type(sample["child_count"]) is int and sample["child_count"] == count,
            "missing/unexpected child",
        )
        members = sample["members"]
        require(
            len(members) == count + 1
            and len(set(members)) == len(members)
            and pid in members
            and all(type(p) is int and p > 0 for p in members),
            "invalid members",
        )
        if previous:
            require(
                members == previous["members"]
                and sample["observed_at_s"] > previous["observed_at_s"]
                and sample["tree_cpu_s"] >= previous["tree_cpu_s"],
                "partial/changing tree",
            )
        previous = sample
    return {
        phase: {
            "peak_tree_rss_kib": max(
                s["tree_rss_kib"] for s in samples if s["phase"] == phase
            ),
            "peak_parent_rss_kib": max(
                s["parent_rss_kib"] for s in samples if s["phase"] == phase
            ),
            "child_count": next(
                s["child_count"] for s in samples if s["phase"] == phase
            ),
            "observed_cpu_s": samples[index * 2 + 1]["tree_cpu_s"]
            - samples[index * 2]["tree_cpu_s"],
            "observation_span_s": samples[index * 2 + 1]["observed_at_s"]
            - samples[index * 2]["observed_at_s"],
        }
        for index, phase in enumerate(PHASES)
    }


def validate(artifact: dict) -> dict:
    require(
        artifact["schema"] == "binnacle-fake-raw-benchmark/1"
        and artifact["evidence"] == "fake-only"
        and artifact["valid"] is True
        and artifact["gold_verified"] is True
        and artifact["cleanup_verified"] is True
        and "failure" not in artifact,
        "invalid benchmark evidence",
    )
    manifest = bench.load_manifest(bench.MANIFEST)
    identity = artifact["identity"]
    validate_identity(identity, manifest)
    execution = artifact["execution"]
    argv = execution["argv"]
    require(
        len(argv) == 9
        and argv[:2] == [identity["python"]["executable"], "-u"]
        and Path(argv[2]).name == "fake_stdio_server.py"
        and argv[3:5] == ["--fault", identity["measurement"]["fault"]]
        and argv[5] == "--trace"
        and argv[7] == "--control-fd"
        and argv[8].isdigit(),
        "command mismatch",
    )
    require(
        Path(argv[6]).parent == Path(execution["cwd"])
        and execution["rootUri"] == Path(execution["cwd"]).as_uri(),
        "workspace setup mismatch",
    )
    require(number(artifact["cold_initialize_ms"]), "missing cold measurement")
    require(
        artifact["settling"] == {"status": "unobserved", "indexed": None},
        "unsupported indexing claim",
    )
    samples = artifact["samples"]
    require(
        len(samples)
        == identity["measurement"]["warm_requests"]
        == artifact["correct_samples"],
        "missing samples",
    )
    for sample in [artifact["first_request"], *samples]:
        require(
            sample["correct"] is True
            and number(sample["latency_ms"])
            and sample["result_count"] == 1
            and sample["result_bytes"] == len(bench.canonical(manifest["gold"])),
            "invalid gold sample",
        )
    require(
        artifact["warm_ms"] == bench.percentiles([s["latency_ms"] for s in samples]),
        "incorrect percentiles",
    )
    return validate_resources(artifact["resources"], identity, execution["pid"])


def compare(first: dict, second: dict) -> dict:
    try:
        left, right = validate(first), validate(second)
        require(first["identity"] == second["identity"], "incompatible run identity")
        require(
            first["execution"]["argv"][:5] == second["execution"]["argv"][:5],
            "incompatible command",
        )
        return {
            "compatible": True,
            "evidence": "fake-only",
            "warm_ms": {
                p: {
                    "before": first["warm_ms"][p],
                    "after": second["warm_ms"][p],
                    "delta": second["warm_ms"][p] - first["warm_ms"][p],
                }
                for p in ("p50", "p95", "p99")
            },
            "resources": {"before": left, "after": right},
        }
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OSError):
        return {
            "compatible": False,
            "reason": "invalid, incomplete or incompatible evidence",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    result = compare(
        json.loads(args.first.read_text()), json.loads(args.second.read_text())
    )
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["compatible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
