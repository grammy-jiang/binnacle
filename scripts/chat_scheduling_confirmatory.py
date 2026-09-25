"""Phase-4 confirmatory schedule and aggregate gate analysis."""

from __future__ import annotations

# fmt: off
import argparse
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
ALLOWED_BUDGETS = (120, 300, 600)
MAIN_ARMS = ("A", "B", "C")
PERFORMANCE_SCENARIOS = tuple(f"R{i}" for i in range(1, 12))
REPEATS = {**{scenario: 5 for scenario in PERFORMANCE_SCENARIOS}, "R7": 3}
H_REPEATS = {"R5": 3, "R6": 3, "R7": 3, "R12": 1}
EXPECTED_PERFORMANCE_SLOTS_PER_ARM = 53
EXPECTED_MAIN_SCHEDULE_SLOTS = 160
CATEGORY_SCENARIOS = {
    "read_heavy": ("R1", "R2"),
    "overlap_long": ("R3", "R4"),
    "dependency_barriers": ("R5", "R6"),
    "repeated_long_barriers": ("R7",),
    "development_recovery": ("R8", "R9"),
    "quiet_job_multi_round": ("R10", "R11"),
}
TARGET_COHORTS = {
    "read_heavy_target": ("R1", "R2", "R11"),
    "mixed_long_target": ("R3", "R4"),
}
CONTINUATION_SCENARIOS = {"R5", "R6", "R7", "R10"}
REQUIRED_GATES = {
    "hard": ("correctness_100_percent", "safety_zero_out_of_scope_writes", "tool_contract_preserved", "production_isolation_preserved", "premature_handoff_zero"),
    "same_prompt_ux": ("same_prompt_completion_ge_95_percent", "median_manual_continuation_zero", "p90_manual_continuation_zero", "continuation_reduction_ge_80_percent", "interruption_rate_le_a_plus_2pp"),
    "performance": ("overall_median_wall_ge_20_percent_faster", "read_heavy_median_ge_30_percent_faster", "mixed_long_median_ge_20_percent_faster", "category_median_regression_within_10_percent", "paired_c_a_bootstrap_upper_lt_1"),
    "scheduling": ("avoidable_blocking_wall_p90_le_2s", "eligible_overlap_ratio_ge_80_percent", "m2_m3_sliding_refill_demonstrated"),
    "guard": ("union_blocking_wall_le_budget_plus_1s", "overlap_charged_once", "exhausted_calls_nonblocking", "guard_overhead_p95_lt_1ms", "guard_overhead_p99_lt_2ms", "repeated_wait_burden_reduction_ge_60_percent"),
    "efficiency": ("tool_result_tokens_le_a_plus_5_percent", "duplicate_completed_reads_no_increase"),
}
GATE_SPECS = tuple((gate, family, "REQUIRED") for family, gates in REQUIRED_GATES.items() for gate in gates) + (("long_job_status_call_result_burden_reduction_ge_10_percent", "efficiency", "DIAGNOSTIC_TARGET"),)
GATE_SPEC = {gate: (family, kind) for gate, family, kind in GATE_SPECS}
EPS = 1e-12
@dataclass(frozen=True)
class Trial:
    run_id: str
    scenario: str
    arm: str
    endpoint: str | None
    budget: int | None
    repeat: int | None
    slot_id: str | None
    order: tuple[float, str]
    metrics: dict[str, Any] | None
    evidence_error: bool
Assigned = tuple[dict[str, Any], Trial | None]
def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value
def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
def _partition(scenario: str) -> str:
    for name, scenarios in CATEGORY_SCENARIOS.items():
        if scenario in scenarios:
            return name
    return "safety"
def _slot_id(scenario: str, repeat: int, arm: str) -> str:
    return f"{scenario}-r{repeat:02d}-{arm}"
def _reuse(scenario: str, repeat: int, arm: str) -> bool:
    return arm == "C" and (
        (scenario in {"R5", "R6", "R7"} and repeat <= 3)
        or (scenario == "R12" and repeat == 1)
    )
def _slot(
    scenario: str, repeat: int, arm: str, budget: int, lane: int | None, index: int
) -> dict[str, Any]:
    return {
        "slot_id": _slot_id(scenario, repeat, arm),
        "scenario_id": scenario,
        "repeat": repeat,
        "arm": arm,
        "endpoint_id": f"C{budget}" if arm == "C" else arm,
        "budget_s": budget if arm == "C" else None,
        "session_lane": lane,
        "execution_index": index,
        "reused_calibration_slot": _reuse(scenario, repeat, arm),
    }
def build_schedule(seed: int, selected_budget: int, max_parallel_blocks: int) -> dict[str, Any]:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if selected_budget not in ALLOWED_BUDGETS:
        raise ValueError(f"selected budget must be one of {ALLOWED_BUDGETS}")
    if isinstance(max_parallel_blocks, bool) or max_parallel_blocks < 0:
        raise ValueError("max_parallel_blocks must be a non-negative integer")
    rng = random.Random(seed)  # nosec B311
    specs = [(scenario, repeat) for scenario in PERFORMANCE_SCENARIOS for repeat in range(1, REPEATS[scenario] + 1)]
    rng.shuffle(specs)
    base, start_rotation = list(MAIN_ARMS), 0
    if max_parallel_blocks:
        rng.shuffle(base)
        start_rotation = rng.randrange(3)
    blocks: list[dict[str, Any]] = []
    execution = 0
    for block_index, (scenario, repeat) in enumerate(specs, start=1):
        if max_parallel_blocks:
            rotation = (start_rotation + block_index - 1) % 3
            order = base[rotation:] + base[:rotation]
        else:
            order = list(MAIN_ARMS)
            rng.shuffle(order)
        slots = []
        for lane, arm in enumerate(order, start=1):
            execution += 1
            slots.append(_slot(scenario, repeat, arm, selected_budget, lane if max_parallel_blocks else None, execution))
        blocks.append({"block_id": f"{scenario}-r{repeat:02d}", "kind": "performance", "sequence_index": block_index, "partition": _partition(scenario), "scenario_id": scenario, "repeat": repeat, "arm_order": order, "parallel_block_lane": (block_index - 1) % max_parallel_blocks + 1 if max_parallel_blocks else None, "wave_index": (block_index - 1) // max_parallel_blocks + 1 if max_parallel_blocks else block_index, "slots": slots})
    execution += 1
    safety = _slot("R12", 1, "C", selected_budget, None, execution)
    blocks.append({"block_id": "R12-r01-C", "kind": "safety", "sequence_index": len(blocks) + 1, "partition": "safety", "scenario_id": "R12", "repeat": 1, "arm_order": ["C"], "parallel_block_lane": None, "wave_index": None, "slots": [safety]})
    result = {"schema_version": SCHEMA, "report_kind": "phase4-confirmatory-schedule", "seed": seed, "selected_budget_s": selected_budget, "selected_c_endpoint": f"C{selected_budget}", "max_safe_parallel_blocks": max_parallel_blocks, "execution_mode": "matched_parallel" if max_parallel_blocks else "serial_randomized", "blocks": blocks, "summary": {"performance_blocks": 53, "performance_slots": 159, "safety_slots": 1, "total_slots": 160, "canonical_slots_by_arm": {"A": 53, "B": 53, "C": 54}, "performance_slots_by_arm": {"A": 53, "B": 53, "C": 53}, "reused_calibration_slots": 10}}
    validate_schedule(result)
    return result
def _slots(schedule: Mapping[str, Any]) -> list[dict[str, Any]]:
    blocks = schedule.get("blocks")
    if not isinstance(blocks, list):
        raise TypeError("schedule blocks must be a list")
    out: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, Mapping) or not isinstance(block.get("slots"), list):
            raise TypeError("schedule blocks and slots must be objects/lists")
        out.extend(dict(slot) for slot in block["slots"] if isinstance(slot, Mapping))
    return out
def validate_schedule(schedule: Mapping[str, Any]) -> None:
    budget = schedule.get("selected_budget_s")
    if schedule.get("schema_version") != SCHEMA or budget not in ALLOWED_BUDGETS:
        raise ValueError("unsupported confirmatory schedule")
    if schedule.get("selected_c_endpoint") != f"C{budget}":
        raise ValueError("schedule selected C endpoint does not match budget")
    k = schedule.get("max_safe_parallel_blocks")
    if isinstance(k, bool) or not isinstance(k, int) or k < 0:
        raise ValueError("schedule max_safe_parallel_blocks is invalid")
    slots = _slots(schedule)
    if len(slots) != EXPECTED_MAIN_SCHEDULE_SLOTS:
        raise ValueError("confirmatory schedule must contain exactly 160 slots")
    keys: set[tuple[str, int, str]] = set()
    counts: dict[str, int] = defaultdict(int)
    perf: dict[str, int] = defaultdict(int)
    reuse = 0
    for slot in slots:
        scenario, repeat, arm = slot.get("scenario_id"), slot.get("repeat"), slot.get("arm")
        if not isinstance(scenario, str) or not isinstance(repeat, int) or arm not in MAIN_ARMS:
            raise ValueError("schedule slot scenario/repeat/arm is invalid")
        key = scenario, repeat, arm
        if key in keys or slot.get("slot_id") != _slot_id(*key):
            raise ValueError("duplicate or inconsistent schedule slot")
        keys.add(key)
        endpoint = f"C{budget}" if arm == "C" else arm
        if slot.get("endpoint_id") != endpoint:
            raise ValueError("schedule slot endpoint is inconsistent")
        if slot.get("budget_s") != (budget if arm == "C" else None):
            raise ValueError("schedule slot budget is inconsistent")
        if bool(slot.get("reused_calibration_slot")) != _reuse(*key):
            raise ValueError("schedule calibration reuse marker is inconsistent")
        counts[arm] += 1
        perf[arm] += int(scenario != "R12")
        reuse += int(_reuse(*key))
    expected = {
        (s, r, a)
        for s in PERFORMANCE_SCENARIOS
        for r in range(1, REPEATS[s] + 1)
        for a in MAIN_ARMS
    } | {("R12", 1, "C")}
    if keys != expected or dict(counts) != {"A": 53, "B": 53, "C": 54}:
        raise ValueError("schedule slot population is invalid")
    if dict(perf) != {"A": 53, "B": 53, "C": 53} or reuse != 10:
        raise ValueError("schedule performance/reuse counts are invalid")
def _submitted(record: Mapping[str, Any]) -> bool:
    value = record.get("submission_status")
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        if isinstance(value.get("submitted"), bool):
            return bool(value["submitted"])
        value = value.get("status")
    if isinstance(value, str):
        value = value.lower().replace("-", "_")
        if value in {"not_submitted", "pre_submission", "created", "aborted_before_submission"}:
            return False
        if value in {"submitted", "accepted", "running", "completed", "failed", "timeout", "interrupted"}:
            return True
    chat = record.get("chat")
    return isinstance(chat, Mapping) and (
        chat.get("send_result") is not None
        or chat.get("chat_id") is not None
        or chat.get("submitted") is True
    )
def _order(record: Mapping[str, Any], run_id: str) -> tuple[float, str]:
    for key in ("submission_epoch_s", "submitted_epoch_s", "trial_start_epoch_s"):
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), run_id
    for key in ("submitted_at", "started_at"):
        value = record.get(key)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp(), run_id
            except ValueError:
                pass
    return math.inf, run_id
def _int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
def _discover(root: Path) -> list[Trial]:
    found: list[Trial] = []
    for trial_path in sorted(root.glob("*/trial.json")) if root.exists() else []:
        record = _load(trial_path)
        if not _submitted(record):
            continue
        run_id = str(record.get("run_id") or trial_path.parent.name)
        scenario, arm = record.get("scenario_id"), record.get("arm")
        if not isinstance(scenario, str) or not isinstance(arm, str):
            continue
        metrics_path = trial_path.parent / "metrics.json"
        metrics = _load(metrics_path) if metrics_path.exists() else None
        evidence = bool(record.get("evidence_integrity_error"))
        endpoint_evidence = trial_path.parent / "endpoint-evidence.json"
        if endpoint_evidence.exists():
            evidence |= bool(_load(endpoint_evidence).get("evidence_integrity_error"))
        slot_id = record.get("schedule_slot_id", record.get("confirmatory_slot_id", record.get("slot_id")))
        found.append(
            Trial(
                run_id,
                scenario,
                arm,
                record.get("endpoint_id") if isinstance(record.get("endpoint_id"), str) else None,
                _int(record.get("budget_s")),
                _int(record.get("schedule_repeat", record.get("repeat"))),
                slot_id if isinstance(slot_id, str) else None,
                _order(record, run_id),
                metrics,
                evidence,
            )
        )
    return sorted(found, key=lambda trial: trial.order)
def _assign(expected: Sequence[dict[str, Any]], trials: Sequence[Trial], required: bool) -> tuple[list[Assigned], list[str], list[str]]:
    by_id = {slot["slot_id"]: slot for slot in expected}
    by_key = {(slot["scenario_id"], slot["repeat"], slot["arm"]): slot for slot in expected}
    candidates: dict[str, list[Trial]] = defaultdict(list)
    loose: list[Trial] = []
    for trial in trials:
        slot = by_id.get(trial.slot_id) if trial.slot_id else by_key.get((trial.scenario, trial.repeat, trial.arm))
        (candidates[slot["slot_id"]].append(trial) if slot else loose.append(trial))
    still: list[Trial] = []
    groups: dict[tuple[str, str], list[Trial]] = defaultdict(list)
    for trial in loose:
        matches = [slot for slot in expected if (slot["scenario_id"], slot["arm"]) == (trial.scenario, trial.arm)]
        (groups[(trial.scenario, trial.arm)].append(trial) if matches else still.append(trial))
    for key, group in groups.items():
        available = sorted((slot for slot in expected if (slot["scenario_id"], slot["arm"]) == key), key=lambda s: s["repeat"])
        for trial, slot in zip(sorted(group, key=lambda t: t.order), available, strict=False):
            candidates[slot["slot_id"]].append(trial)
        still.extend(sorted(group, key=lambda t: t.order)[len(available) :])
    assigned: list[Assigned] = []
    issues: list[str] = []
    for slot in expected:
        owned = sorted(candidates.get(slot["slot_id"], []), key=lambda t: t.order)
        owner: Trial | None = owned[0] if owned else None
        if owner is None and required:
            issues.append(f"{slot['slot_id']}: no submitted canonical outcome")
        if owner:
            if owner.endpoint and owner.endpoint != slot["endpoint_id"]:
                issues.append(f"{slot['slot_id']}: endpoint mismatch")
            if owner.budget is not None and owner.budget != slot["budget_s"]:
                issues.append(f"{slot['slot_id']}: budget mismatch")
            if owner.evidence_error:
                issues.append(f"{slot['slot_id']}: evidence_integrity_error=true")
            if owner.metrics is None:
                issues.append(f"{slot['slot_id']}: no metrics.json")
            elif any(owner.metrics.get(k) != v for k, v in (("scenario_id", slot["scenario_id"]), ("run_id", owner.run_id), ("arm", slot["arm"]))):
                issues.append(f"{slot['slot_id']}: metrics identity mismatch")
        if len(owned) > 1:
            issues.append(f"{slot['slot_id']}: replacement/duplicate submissions: " + ", ".join(t.run_id for t in owned[1:]))
        assigned.append((slot, owner))
    return assigned, issues, [trial.run_id for trial in still]
def _h_slots() -> list[dict[str, Any]]:
    return [
        {"slot_id": _slot_id(s, r, "H"), "scenario_id": s, "repeat": r, "arm": "H", "endpoint_id": "H", "budget_s": 10}
        for s, count in H_REPEATS.items()
        for r in range(1, count + 1)
    ]
def _metrics(item: Assigned) -> dict[str, Any] | None:
    trial = item[1]
    return None if trial is None or trial.evidence_error else trial.metrics
def _pct(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    position = (len(data) - 1) * q
    lo, hi = math.floor(position), math.ceil(position)
    value = data[lo] if lo == hi else data[lo] + (data[hi] - data[lo]) * (position - lo)
    return round(float(value), 6)
def _median(values: Sequence[float]) -> float | None:
    return round(float(statistics.median(values)), 6) if values else None
def _ratio(a: float | None, b: float | None) -> float | None:
    return round(a / b, 6) if a is not None and b is not None and b > EPS else None
def _arm_summary(rows: Sequence[Assigned], arm: str, expected: int, perf_expected: int) -> dict[str, Any]:
    arm_rows = [row for row in rows if row[0]["arm"] == arm]
    perf_rows = [row for row in arm_rows if row[0]["scenario_id"] != "R12"]
    scored = [m for row in arm_rows if (m := _metrics(row)) is not None]
    scored_perf = [m for row in perf_rows if (m := _metrics(row)) is not None]
    walls = [float(m["wall_s"]) for m in scored_perf if isinstance(m.get("wall_s"), (int, float))]
    cont = [float(m["manual_continuations_required"]) for m in scored_perf if isinstance(m.get("manual_continuations_required"), int)]
    avoid = [float(m["avoidable_idle_wall_s"]) for m in scored_perf if isinstance(m.get("avoidable_idle_wall_s"), (int, float))]
    eligible = sum(int(m.get("eligible_read_only_calls", 0)) for m in scored_perf)
    overlap = sum(int(m.get("overlapped_eligible_read_only_calls", 0)) for m in scored_perf)
    submitted_perf = sum(row[1] is not None for row in perf_rows)
    interruptions = sum(bool(m.get("interrupted")) for row in perf_rows if (m := _metrics(row)) is not None)
    same_prompt = sum(bool(m.get("same_prompt_completion")) for row in perf_rows if (m := _metrics(row)) is not None)
    premature = sum(bool(m.get("premature_handoff")) for row in perf_rows if (m := _metrics(row)) is not None)
    correctness = sum(bool(m.get("correctness_passed")) for row in arm_rows if (m := _metrics(row)) is not None)
    tokens = sum(int(m.get("tool_result_tokens", 0)) for m in scored_perf)
    return {"arm": arm, "expected_slots": expected, "submitted_slots": sum(row[1] is not None for row in arm_rows), "scored_slots": len(scored), "expected_performance_slots": perf_expected, "submitted_performance_slots": submitted_perf, "scored_performance_slots": len(scored_perf), "correctness_passes": correctness, "correctness_rate": round(correctness / expected, 6), "same_prompt_completions": same_prompt, "same_prompt_completion_rate": round(same_prompt / perf_expected, 6), "premature_handoffs": premature, "premature_handoff_rate": round(premature / perf_expected, 6), "interruptions": interruptions, "interruption_rate_submitted": round(interruptions / submitted_perf, 6) if submitted_perf else None, "median_wall_s": _median(walls), "p90_wall_s": _pct(walls, 0.9), "median_manual_continuations": _median(cont), "p90_manual_continuations": _pct(cont, 0.9), "tool_result_tokens_total": tokens, "eligible_read_only_calls": eligible, "overlapped_eligible_read_only_calls": overlap, "eligible_overlap_ratio": round(overlap / eligible, 6) if eligible else None, "avoidable_idle_wall_p90_s": _pct(avoid, 0.9)}
def _median_for(rows: Sequence[Assigned], arm: str, scenarios: Iterable[str]) -> float | None:
    wanted = set(scenarios)
    values: list[float] = []
    for row in rows:
        m = _metrics(row)
        if row[0]["arm"] == arm and row[0]["scenario_id"] in wanted and m and isinstance(m.get("wall_s"), (int, float)):
            values.append(float(m["wall_s"]))
    return _median(values)
def _completion_for(rows: Sequence[Assigned], arm: str, scenarios: Iterable[str]) -> float | None:
    wanted = set(scenarios)
    selected = [row for row in rows if row[0]["arm"] == arm and row[0]["scenario_id"] in wanted]
    passed = sum(bool(m.get("same_prompt_completion")) for row in selected if (m := _metrics(row)) is not None)
    return round(passed / len(selected), 6) if selected else None
def _bootstrap(rows: Sequence[Assigned], seed: int, samples: int) -> dict[str, Any]:
    by_key = {(row[0]["scenario_id"], row[0]["repeat"], row[0]["arm"]): row for row in rows if row[0]["scenario_id"] != "R12"}
    ratios, missing = [], []
    for scenario in PERFORMANCE_SCENARIOS:
        for repeat in range(1, REPEATS[scenario] + 1):
            a, c = _metrics(by_key[(scenario, repeat, "A")]), _metrics(by_key[(scenario, repeat, "C")])
            aw = float(a["wall_s"]) if a and isinstance(a.get("wall_s"), (int, float)) else None
            cw = float(c["wall_s"]) if c and isinstance(c.get("wall_s"), (int, float)) else None
            if aw is None or cw is None or aw <= EPS:
                missing.append(f"{scenario}-r{repeat:02d}")
            else:
                ratios.append(cw / aw)
    if not ratios:
        return {"pair_count": 0, "expected_pair_count": 53, "complete_population": False, "median_ratio": None, "ci_95_lower": None, "ci_95_upper": None, "bootstrap_samples": samples, "missing_pairs": missing}
    rng = random.Random(seed ^ 0xC0A4B0057)  # nosec B311 - deterministic bootstrap
    medians = [statistics.median(ratios[rng.randrange(len(ratios))] for _ in ratios) for _ in range(samples)]
    return {"pair_count": len(ratios), "expected_pair_count": 53, "complete_population": len(ratios) == 53, "median_ratio": _median(ratios), "ci_95_lower": _pct(medians, 0.025), "ci_95_upper": _pct(medians, 0.975), "bootstrap_samples": samples, "missing_pairs": missing}
def _analyze(schedule: Mapping[str, Any], runs_root: Path, samples: int) -> dict[str, Any]:
    trials = _discover(runs_root)
    main, issues, extras = _assign(_slots(schedule), [t for t in trials if t.arm in MAIN_ARMS], True)
    h, h_issues, h_extras = _assign(_h_slots(), [t for t in trials if t.arm == "H"], False)
    issues.extend(f"unscheduled submitted A/B/C run: {run_id}" for run_id in extras)
    integrity = {"passed": not issues, "expected_main_slots": 160, "submitted_main_slots": sum(t is not None for _, t in main), "scorable_main_slots": sum(_metrics(row) is not None for row in main), "issues": issues, "unscheduled_main_run_ids": extras, "h": {"expected_slots": 10, "submitted_slots": sum(t is not None for _, t in h), "scorable_slots": sum(_metrics(row) is not None for row in h), "issues": h_issues, "unscheduled_run_ids": h_extras}}
    aggregate = {"A": _arm_summary(main, "A", 53, 53), "B": _arm_summary(main, "B", 53, 53), "C": _arm_summary(main, "C", 54, 53), "H": _arm_summary(h, "H", 10, 9)}
    scenarios = {s: {a: {"median_wall_s": _median_for(main, a, (s,)), "ratio_vs_a": _ratio(_median_for(main, a, (s,)), _median_for(main, "A", (s,))), "same_prompt_completion_rate": _completion_for(main, a, (s,))} for a in MAIN_ARMS} for s in PERFORMANCE_SCENARIOS}
    categories = {name: {"scenarios": list(ss), "arms": {a: {"median_wall_s": _median_for(main, a, ss), "ratio_vs_a": _ratio(_median_for(main, a, ss), _median_for(main, "A", ss)), "same_prompt_completion_rate": _completion_for(main, a, ss)} for a in MAIN_ARMS}} for name, ss in CATEGORY_SCENARIOS.items()}
    cohorts = {name: {"scenarios": list(ss), "a_median_wall_s": _median_for(main, "A", ss), "c_median_wall_s": _median_for(main, "C", ss), "c_a_ratio": _ratio(_median_for(main, "C", ss), _median_for(main, "A", ss))} for name, ss in TARGET_COHORTS.items()}
    cont_rows = [row for row in main if row[0]["scenario_id"] in CONTINUATION_SCENARIOS]
    cont = {arm: sum(int(m.get("manual_continuations_required", 0)) for row in cont_rows if row[0]["arm"] == arm and (m := _metrics(row)) is not None) for arm in ("A", "C")}
    delta = lambda c, a: round(100 * (c - a), 6) if isinstance(c, (int, float)) and isinstance(a, (int, float)) else None
    reliability = {"same_prompt_completion_delta_pp_c_minus_a": delta(aggregate["C"]["same_prompt_completion_rate"], aggregate["A"]["same_prompt_completion_rate"]), "interruption_rate_delta_pp_c_minus_a": delta(aggregate["C"]["interruption_rate_submitted"], aggregate["A"]["interruption_rate_submitted"]), "premature_handoff_delta_pp_c_minus_a": delta(aggregate["C"]["premature_handoff_rate"], aggregate["A"]["premature_handoff_rate"]), "correctness_delta_pp_c_minus_a": delta(aggregate["C"]["correctness_rate"], aggregate["A"]["correctness_rate"]), "continuation_prone_scenarios": sorted(CONTINUATION_SCENARIOS), "a_required_continuations": cont["A"], "c_required_continuations": cont["C"], "required_continuation_reduction_percent": round(100 * (cont["A"] - cont["C"]) / cont["A"], 6) if cont["A"] else None}
    return {"slot_integrity": integrity, "aggregate_by_arm": aggregate, "scenario_medians": scenarios, "category_medians": categories, "target_cohort_medians": cohorts, "paired_c_a_bootstrap": _bootstrap(main, int(schedule["seed"]), samples), "reliability_deltas": reliability}
def _computed(a: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    arm_a, c, rel, cohorts, boot = a["aggregate_by_arm"]["A"], a["aggregate_by_arm"]["C"], a["reliability_deltas"], a["target_cohort_medians"], a["paired_c_a_bootstrap"]
    complete = bool(a["slot_integrity"]["passed"] and arm_a["scored_performance_slots"] == 53 and c["scored_performance_slots"] == 53)
    category_requests = []
    category_ok: bool | None = True
    for name, value in a["category_medians"].items():
        ratio = value["arms"]["C"]["ratio_vs_a"]
        if ratio is None:
            category_ok = None
        elif ratio > 1.10 + EPS:
            category_requests.append({"artifact_kind": "CATEGORY_REGRESSION_EXCEPTION_REQUEST", "category": name, "scenarios": value["scenarios"], "a_median_wall_s": value["arms"]["A"]["median_wall_s"], "c_median_wall_s": value["arms"]["C"]["median_wall_s"], "c_a_ratio": ratio, "a_same_prompt_completion_rate": value["arms"]["A"]["same_prompt_completion_rate"], "c_same_prompt_completion_rate": value["arms"]["C"]["same_prompt_completion_rate"], "owner_approval_required": bool(value["arms"]["C"]["same_prompt_completion_rate"] > value["arms"]["A"]["same_prompt_completion_rate"])})
            category_ok = False
    ratio = lambda x, y: _ratio(float(x) if isinstance(x, (int, float)) else None, float(y) if isinstance(y, (int, float)) else None)
    ge = lambda value, threshold: isinstance(value, (int, float)) and value >= threshold
    overall_ratio = ratio(c["median_wall_s"], arm_a["median_wall_s"])
    token_ratio = ratio(c["tool_result_tokens_total"], arm_a["tool_result_tokens_total"])
    return {
        "correctness_100_percent": {"passed": bool(a["slot_integrity"]["passed"] and c["correctness_passes"] == 54), "value": c["correctness_rate"], "threshold": 1.0},
        "premature_handoff_zero": {"passed": bool(complete and c["premature_handoffs"] == 0), "value": c["premature_handoffs"], "threshold": 0},
        "same_prompt_completion_ge_95_percent": {"passed": bool(complete and c["same_prompt_completions"] >= 51), "value": c["same_prompt_completion_rate"], "threshold": 0.95, "arithmetic": "at least 51/53 bounded C macro slots"},
        "median_manual_continuation_zero": {"passed": bool(complete and c["median_manual_continuations"] == 0), "value": c["median_manual_continuations"], "threshold": 0},
        "p90_manual_continuation_zero": {"passed": bool(complete and c["p90_manual_continuations"] == 0), "value": c["p90_manual_continuations"], "threshold": 0},
        "continuation_reduction_ge_80_percent": {"passed": bool(complete and ge(rel["required_continuation_reduction_percent"], 80)), "value_percent": rel["required_continuation_reduction_percent"], "threshold_percent": 80},
        "interruption_rate_le_a_plus_2pp": {"passed": bool(complete and isinstance(rel["interruption_rate_delta_pp_c_minus_a"], (int, float)) and rel["interruption_rate_delta_pp_c_minus_a"] <= 2), "delta_pp_c_minus_a": rel["interruption_rate_delta_pp_c_minus_a"], "threshold_pp": 2},
        "overall_median_wall_ge_20_percent_faster": {"passed": bool(complete and overall_ratio is not None and overall_ratio <= 0.8), "c_a_ratio": overall_ratio, "maximum_ratio": 0.8},
        "read_heavy_median_ge_30_percent_faster": {"passed": bool(complete and isinstance(cohorts["read_heavy_target"]["c_a_ratio"], (int, float)) and cohorts["read_heavy_target"]["c_a_ratio"] <= 0.7), "c_a_ratio": cohorts["read_heavy_target"]["c_a_ratio"], "maximum_ratio": 0.7},
        "mixed_long_median_ge_20_percent_faster": {"passed": bool(complete and isinstance(cohorts["mixed_long_target"]["c_a_ratio"], (int, float)) and cohorts["mixed_long_target"]["c_a_ratio"] <= 0.8), "c_a_ratio": cohorts["mixed_long_target"]["c_a_ratio"], "maximum_ratio": 0.8},
        "category_median_regression_within_10_percent": {"passed": category_ok if complete else False, "maximum_ratio_without_exception": 1.10, "exception_requests": category_requests},
        "paired_c_a_bootstrap_upper_lt_1": {"passed": bool(complete and boot["complete_population"] and isinstance(boot["ci_95_upper"], (int, float)) and boot["ci_95_upper"] < 1), "ci_95_upper": boot["ci_95_upper"], "threshold": 1.0, "pair_count": boot["pair_count"]},
        "avoidable_blocking_wall_p90_le_2s": {"passed": bool(complete and isinstance(c["avoidable_idle_wall_p90_s"], (int, float)) and c["avoidable_idle_wall_p90_s"] <= 2), "value_s": c["avoidable_idle_wall_p90_s"], "maximum_s": 2},
        "eligible_overlap_ratio_ge_80_percent": {"passed": bool(complete and isinstance(c["eligible_overlap_ratio"], (int, float)) and c["eligible_overlap_ratio"] >= 0.8), "value": c["eligible_overlap_ratio"], "minimum": 0.8},
        "tool_result_tokens_le_a_plus_5_percent": {"passed": bool(complete and token_ratio is not None and token_ratio <= 1.05), "c_a_ratio": token_ratio, "maximum_ratio": 1.05},
    }
def _review_gates(payload: Mapping[str, Any], source: str) -> dict[str, dict[str, Any]]:
    raw = payload.get("gates", payload.get("gate_results", {}))
    items = raw.items() if isinstance(raw, Mapping) else ((item.get("id"), item) for item in raw) if isinstance(raw, list) else ()
    out = {}
    for gate_id, value in items:
        if gate_id not in GATE_SPEC:
            raise ValueError(f"{source} contains unknown gate id {gate_id!r}")
        record = {"passed": value} if isinstance(value, bool) else dict(value)
        expected = GATE_SPEC[gate_id][1]
        if record.get("classification") not in (None, expected):
            raise ValueError(f"{source} changes {gate_id} classification from {expected}")
        passed = record.get("passed")
        if passed is None and record.get("status") in {"PASS", "TARGET_MET"}:
            passed = True
        if passed is None and record.get("status") in {"FAIL", "TARGET_MISSED"}:
            passed = False
        if passed is not None and not isinstance(passed, bool):
            raise TypeError(f"{source} gate {gate_id} passed must be boolean/null")
        record.update({"passed": passed, "source": source})
        out[str(gate_id)] = record
    return out
def build_gate_matrix(*, schedule_path: Path, runs_root: Path, correctness_path: Path, performance_path: Path, reliability_path: Path, efficiency_path: Path, bootstrap_samples: int = 10_000) -> dict[str, Any]:
    schedule = _load(schedule_path)
    validate_schedule(schedule)
    analytics = _analyze(schedule, runs_root, bootstrap_samples)
    computed = _computed(analytics)
    paths = {"correctness_safety": correctness_path, "performance_bootstrap": performance_path, "reliability_provenance": reliability_path, "scheduling_efficiency": efficiency_path}
    review_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    review_inputs = {}
    for name, path in paths.items():
        payload = _load(path)
        review_inputs[name] = {"path": str(path), "sha256": _sha(path), "report_kind": payload.get("report_kind")}
        for gate, record in _review_gates(payload, name).items():
            review_records[gate].append(record)
    gates = {}
    for gate, family, kind in GATE_SPECS:
        reviews, comp = review_records.get(gate, []), computed.get(gate)
        values = {r["passed"] for r in reviews if r.get("passed") is not None}
        if len(values) > 1:
            raise ValueError(f"review artifacts disagree on {gate}")
        comp_pass = comp.get("passed") if comp else None
        if comp_pass is not None and values and comp_pass not in values:
            raise ValueError(f"review artifacts disagree with canonical metrics on {gate}")
        passed = comp_pass if comp_pass is not None else next(iter(values), None)
        status = "MISSING" if passed is None else ("TARGET_MET" if passed else "TARGET_MISSED") if kind == "DIAGNOSTIC_TARGET" else ("PASS" if passed else "FAIL")
        gates[gate] = {"id": gate, "family": family, "classification": kind, "status": status, "passed": passed, "computed": comp, "review_sources": reviews}
    required = [g for g in gates.values() if g["classification"] == "REQUIRED"]
    diagnostics = [g for g in gates.values() if g["classification"] == "DIAGNOSTIC_TARGET"]
    return {"schema_version": 1, "report_kind": "phase4-hard-gate-matrix", "schedule": {"path": str(schedule_path), "sha256": _sha(schedule_path), "seed": schedule["seed"], "selected_budget_s": schedule["selected_budget_s"], "selected_c_endpoint": schedule["selected_c_endpoint"], "max_safe_parallel_blocks": schedule["max_safe_parallel_blocks"]}, "runs_root": str(runs_root), "review_inputs": review_inputs, "analytics": analytics, "gates": gates, "all_required_gates_pass": bool(analytics["slot_integrity"]["passed"]) and all(g["status"] == "PASS" for g in required), "required_gate_count": len(required), "required_gate_pass_count": sum(g["status"] == "PASS" for g in required), "diagnostic_target_count": len(diagnostics), "diagnostic_target_missed_count": sum(g["status"] == "TARGET_MISSED" for g in diagnostics), "note": "Diagnostic-target misses are reported but do not by themselves change all_required_gates_pass."}
def main() -> None:
    parser = argparse.ArgumentParser(prog="chat-scheduling-confirmatory")
    sub = parser.add_subparsers(dest="command", required=True)
    schedule = sub.add_parser("schedule")
    schedule.add_argument("--seed", type=int, required=True)
    schedule.add_argument("--selected-budget", type=int, choices=ALLOWED_BUDGETS, required=True)
    schedule.add_argument("--max-parallel-blocks", type=int, required=True)
    schedule.add_argument("--output", type=Path, required=True)
    gates = sub.add_parser("gates")
    for name in ("schedule", "correctness", "performance", "reliability", "efficiency", "output"):
        gates.add_argument(f"--{name}", type=Path, required=True)
    gates.add_argument("--runs-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "schedule":
        if args.max_parallel_blocks < 0:
            raise SystemExit("--max-parallel-blocks must be non-negative")
        _write(args.output, build_schedule(args.seed, args.selected_budget, args.max_parallel_blocks))
    else:
        _write(
            args.output,
            build_gate_matrix(
                schedule_path=args.schedule,
                runs_root=args.runs_root.expanduser(),
                correctness_path=args.correctness,
                performance_path=args.performance,
                reliability_path=args.reliability,
                efficiency_path=args.efficiency,
            ),
        )
if __name__ == "__main__":
    main()
