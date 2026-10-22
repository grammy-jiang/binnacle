"""Bounded, injectable experiment runner. Only sanitized aggregate data escapes."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass

from .metrics import Resources, correct, percentiles


@dataclass(frozen=True)
class Options:
    repeats: int = 30
    warmup: int = 3
    concurrency: int = 1
    instances: int = 1
    deadline_s: float = 15
    total_s: float = 120
    sample_interval_s: float = 0.1
    p95_budget_ms: float = 100
    rss_budget_mib: float = 512

    def __post_init__(self):
        for name, low, high in (
            ("repeats", 1, 1000),
            ("warmup", 1, 20),
            ("concurrency", 1, 4),
            ("instances", 1, 3),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError("invalid_experiment_bound")
        for name, low, high in (
            ("deadline_s", 0.01, 120),
            ("total_s", 1, 600),
            ("sample_interval_s", 0.05, 1),
            ("p95_budget_ms", 0.01, 60000),
            ("rss_budget_mib", 1, 32768),
        ):
            value = getattr(self, name)
            if type(value) not in (float, int) or not low <= value <= high:
                raise ValueError("invalid_experiment_budget")


async def experiment(
    backend, corpus, options: Options, *, resources=None, clock=time.perf_counter
) -> dict:
    resources = resources if resources is not None else Resources()
    rows = {}
    stop = asyncio.Event()
    start = clock()
    cpu_start = time.process_time()
    result = {
        "status": "running",
        "options": asdict(options),
        "corpus": corpus.identity(),
        "sample_grade": "smoke"
        if options.repeats < 30
        else "exploratory"
        if options.repeats < 100
        else "repeat_candidate",
        "release_decision": "NOT_EVALUATED_READ_NO_GO",
        "operations": [],
        "startup_to_first_result_ms": None,
    }

    async def sample():
        while not stop.is_set():
            resources.capture(backend.processes(), backend.residents)
            try:
                await asyncio.wait_for(stop.wait(), options.sample_interval_s)
            except asyncio.TimeoutError:
                pass

    async def request(index, case, row, phase):
        began = clock()
        elapsed = None
        outcome = "error"
        count = size = 0
        try:
            response = await asyncio.wait_for(
                backend.query(index, case), options.deadline_s
            )
            elapsed = (clock() - began) * 1000
            outcome = (
                "correct"
                if correct(case, response, backend.roots[index])
                else "incorrect"
            )
            # Sizes only; never store strings, wire results, exception messages.
            import json

            size = len(json.dumps(response, ensure_ascii=True).encode())
            count = (
                len(response)
                if isinstance(response, list)
                else int(response is not None)
            )
        except asyncio.TimeoutError:
            outcome = "timeout"
        except Exception:  # noqa: BLE001 - sanitize provider faults
            outcome = "error"
        if elapsed is None:
            elapsed = (clock() - began) * 1000
        bucket = row[phase]
        bucket[outcome] += 1
        if phase == "warm":
            bucket["latencies"].append(elapsed)
            bucket["correct_latencies"].extend(
                [elapsed] if outcome == "correct" else []
            )
            bucket["result_counts"].append(count)
            bucket["result_bytes"].append(size)

    async def workload():
        await asyncio.wait_for(
            backend.start(corpus.cases), options.deadline_s * options.instances
        )
        result["startup_to_first_result_ms"] = (clock() - start) * 1000
        resources.capture(backend.processes(), backend.residents)
        for number, case in enumerate(corpus.cases):
            row = {
                "case": number,
                "operation": case.operation,
                "supported_instances": sum(
                    backend.supports(i, case.operation)
                    for i in range(options.instances)
                ),
            }
            rows[number] = row
            for phase in ("settling", "warm"):
                row[phase] = dict.fromkeys(
                    ("correct", "incorrect", "error", "timeout"), 0
                )
            row["warm"].update(
                latencies=[], correct_latencies=[], result_counts=[], result_bytes=[]
            )
            supported = [
                i
                for i in range(options.instances)
                if backend.supports(i, case.operation)
            ]
            if not supported:
                continue
            for index in supported:
                for _ in range(options.warmup):
                    await request(index, case, row, "settling")
            # Exactly repeats per supported instance, with at most concurrency
            # tasks allocated at once. No unbounded gather or task queue.
            jobs = [i for _ in range(options.repeats) for i in supported]
            for offset in range(0, len(jobs), options.concurrency):
                await asyncio.gather(
                    *(
                        request(i, case, row, "warm")
                        for i in jobs[offset : offset + options.concurrency]
                    )
                )
            resources.capture(backend.processes(), backend.residents)

    sampler = asyncio.create_task(sample())
    try:
        await asyncio.wait_for(workload(), options.total_s)
        result["status"] = "completed"
    except asyncio.TimeoutError:
        result["status"] = "deadline_exceeded"
    except Exception:  # noqa: BLE001 - no source/path-bearing errors
        result["status"] = "startup_or_workload_error"
    finally:
        began = clock()
        try:
            # P2.6 and P2.4 own their finite close deadlines. Do not cancel
            # their cleanup merely because the workload exhausted its budget.
            result["cleanup_verified"] = await backend.close()
        except Exception:  # noqa: BLE001
            result["cleanup_verified"] = False
        result["teardown_ms"] = (clock() - began) * 1000
        stop.set()
        await sampler
    for row in rows.values():
        warm = row["warm"]
        latencies = warm.pop("latencies")
        valid = warm.pop("correct_latencies")
        counts, sizes = warm.pop("result_counts"), warm.pop("result_bytes")
        n = len(latencies)
        warm.update(
            samples=n,
            response_ms=percentiles(latencies),
            correct_response_ms=percentiles(valid),
            result_count=percentiles(counts),
            result_bytes=percentiles(sizes),
            error_rate=warm["error"] / n if n else None,
            timeout_rate=warm["timeout"] / n if n else None,
            correctness_rate=warm["correct"] / n if n else None,
        )
        expected = options.repeats * row["supported_instances"]
        eligible = (
            n == expected
            and n > 0
            and warm["correct"] == n
            and row["settling"]["correct"]
            == options.warmup * row["supported_instances"]
        )
        row["budget_label"] = (
            "unsupported"
            if not expected
            else "invalid_correctness_or_incomplete"
            if not eligible
            else "within_provisional_budget"
            if warm["response_ms"]["p95"] <= options.p95_budget_ms
            else "exceeds_provisional_budget"
        )
        result["operations"].append(row)
    result["resources"] = resources.result()
    rss = result["resources"]["tree_rss_peak_bytes"]
    result["resource_budget_label"] = (
        "unobserved"
        if rss is None
        else "within_provisional_budget"
        if rss <= options.rss_budget_mib * 1048576
        else "exceeds_provisional_budget"
    )
    result["provider_readiness"] = list(getattr(backend, "readiness", ()))
    result["initialize_response_ms"] = percentiles(backend.initialization)
    result["initialize_samples"] = len(backend.initialization)
    # P2.6 may transparently recycle a dead resident. Such a run cannot
    # establish warm latency for one unchanged provider lifetime.
    result["resident_reuse_verified"] = len(backend.initialization) == options.instances
    result["elapsed_ms"] = (clock() - start) * 1000
    result["harness_cpu_seconds"] = time.process_time() - cpu_start
    result["valid"] = (
        result["status"] == "completed"
        and result["cleanup_verified"]
        and result["resident_reuse_verified"]
        and bool(rows)
        and any(row["supported_instances"] for row in rows.values())
        and all(
            row["budget_label"]
            in (
                "within_provisional_budget",
                "exceeds_provisional_budget",
                "unsupported",
            )
            for row in rows.values()
        )
    )
    return result
