# Phase 3 corpus audit: phase1-step7

## Frozen inputs

- Source report:
  `benchmarks/chat-mode-scheduling-v2/phase1-step7-multiround-planning-ab-2026-09-23.json`
  - SHA-256:
    `8703003bf2bd1c57f098d869e41dd9ed8eaa9bc574cc691af582bd0b6e50909f`
- Shard:
  `benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step7.json`
  - SHA-256:
    `98fbab4cc39735db0e2fa9b1079c5a7a74841e53748edcaff7da4501e338fed3`

The audit was independently re-derived from the immutable Phase-1 source report
and each submitted run's raw `trial.json` and `trace.json` state. It did not
use the corpus extractor implementation. A positive status wait is a
`job_status` trace call whose requested `wait_seconds` is greater than zero;
its physical duration is the returned `waited_s`. Blocking wall is the union of
that call's observed blocking intervals per turn, not the requested wait.
Observed required completions are positive status calls that returned
`state=exited`. Terminal state is read from the run's `trial.json`.

## Canonical submitted slot count

| Scenario / arm | Expected from source | Shard rows | Verdict |
| --- | ---: | ---: | --- |
| R11 / A | 3 | 3 | PASS |
| R11 / B | 3 | 3 | PASS |
| R11 / total | 6 | 6 | PASS |

The shard also records `row_count=6` and `trial_count=6`.

## Positive job-status waits and actual waited seconds

No submitted R11 trace contains a positive `job_status` call.

| Trial | Expected from raw trace | Shard `waits` | Verdict |
| --- | --- | --- | --- |
| `r11-20260923T191434-97685ba785` | `[]` | `[]` | PASS |
| `r11-20260923T191622-5b9eb4d61a` | `[]` | `[]` | PASS |
| `r11-20260923T191936-3f54037f48` | `[]` | `[]` | PASS |
| `r11-20260923T192137-e0ef7c549e` | `[]` | `[]` | PASS |
| `r11-20260923T192313-5af845ba2a` | `[]` | `[]` | PASS |
| `r11-20260923T192438-53a7f2844c` | `[]` | `[]` | PASS |

Because there are no positive waits, there are no actual `waited_s` values to
preserve for this source.

## Union blocking wall per turn

Every submitted trace has no positive status blocking interval. Therefore each
turn's union is zero and the per-trial union is `0.0 s`.

| Trial | Expected union wall | Shard `observed_blocking_wall_s` | Verdict |
| --- | ---: | ---: | --- |
| `r11-20260923T191434-97685ba785` | 0.0 s | 0 | PASS |
| `r11-20260923T191622-5b9eb4d61a` | 0.0 s | 0 | PASS |
| `r11-20260923T191936-3f54037f48` | 0.0 s | 0 | PASS |
| `r11-20260923T192137-e0ef7c549e` | 0.0 s | 0 | PASS |
| `r11-20260923T192313-5af845ba2a` | 0.0 s | 0 | PASS |
| `r11-20260923T192438-53a7f2844c` | 0.0 s | 0 | PASS |

## Observed required completions

With no positive status calls, no submitted trial contains a completion-bearing
status return.

| Trial | Expected completions | Shard completions | Verdict |
| --- | ---: | ---: | --- |
| `r11-20260923T191434-97685ba785` | 0 | 0 | PASS |
| `r11-20260923T191622-5b9eb4d61a` | 0 | 0 | PASS |
| `r11-20260923T191936-3f54037f48` | 0 | 0 | PASS |
| `r11-20260923T192137-e0ef7c549e` | 0 | 0 | PASS |
| `r11-20260923T192313-5af845ba2a` | 0 | 0 | PASS |
| `r11-20260923T192438-53a7f2844c` | 0 | 0 | PASS |

## Terminal states

| Trial | Expected from `trial.json` | Shard terminal state | Verdict |
| --- | --- | --- | --- |
| `r11-20260923T191434-97685ba785` | `completed` | `completed` | PASS |
| `r11-20260923T191622-5b9eb4d61a` | `failed` | `failed` | PASS |
| `r11-20260923T191936-3f54037f48` | `completed` | `completed` | PASS |
| `r11-20260923T192137-e0ef7c549e` | `completed` | `completed` | PASS |
| `r11-20260923T192313-5af845ba2a` | `completed` | `completed` | PASS |
| `r11-20260923T192438-53a7f2844c` | `completed` | `completed` | PASS |

## Commands used

Hash verification:

```bash
sha256sum \
  benchmarks/chat-mode-scheduling-v2/phase1-step7-multiround-planning-ab-2026-09-23.json \
  benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step7.json
```

Independent invariant derivation and shard comparison:

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path.cwd()
report_path = (
    root
    / "benchmarks/chat-mode-scheduling-v2/"
    "phase1-step7-multiround-planning-ab-2026-09-23.json"
)
shard_path = (
    root
    / "benchmarks/chat-mode-scheduling-v2/"
    "phase3-corpus-shards/phase1-step7.json"
)
report = json.loads(report_path.read_text())
shard = json.loads(shard_path.read_text())
rows = {r["trial_id"]: r for r in shard["rows"]}


def merge_wall(intervals):
    if not intervals:
        return 0.0
    intervals = sorted(intervals)
    total = 0.0
    start, end = intervals[0]
    for next_start, next_end in intervals[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + (end - start)


arm_scenario = {}
all_pass = True
row_check_total = 0
row_check_passes = 0
for slot in report["canonical_slots"]:
    if not slot["submitted"]:
        continue
    key = (slot["scenario_id"], slot["arm"])
    arm_scenario[key] = arm_scenario.get(key, 0) + 1
    state = Path(slot["state_dir"])
    trial = json.loads((state / "trial.json").read_text())
    trace = json.loads((state / "trace.json").read_text())
    calls = trace.get("calls", [])
    positives = []
    by_turn = {}
    completions = 0
    for call in calls:
        if call.get("tool") != "job_status":
            continue
        requested = call.get("args", {}).get("wait_seconds", 0) or 0
        if requested <= 0:
            continue
        result = call.get("result") or {}
        positives.append(
            {
                "turn": call.get("turn"),
                "job_id": call.get("args", {}).get("job_id"),
                "waited_s": result.get("waited_s"),
                "state": result.get("state"),
            }
        )
        block_start = call.get("blocking_start_s")
        block_end = call.get("blocking_end_s")
        if block_start is not None and block_end is not None:
            by_turn.setdefault(call.get("turn") or "unknown", []).append(
                (float(block_start), float(block_end))
            )
        if result.get("state") == "exited":
            completions += 1
    blocking = {
        turn: round(merge_wall(intervals), 6)
        for turn, intervals in by_turn.items()
    }
    if not blocking:
        blocking = {"<none>": 0.0}
    shard_row = rows[slot["run_id"]]
    expected_terminal = trial["status"]
    checks = {
        "waits": positives == shard_row["waits"],
        "blocking_wall": (
            abs(
                sum(blocking.values())
                - float(shard_row["observed_blocking_wall_s"])
            )
            < 1e-9
        ),
        "required_completions": (
            completions == shard_row["observed_required_completions"]
        ),
        "terminal_state": expected_terminal == shard_row["terminal_state"],
    }
    all_pass &= all(checks.values())
    row_check_total += len(checks)
    row_check_passes += sum(checks.values())
    print(
        json.dumps(
            {
                "trial_id": slot["run_id"],
                "scenario": slot["scenario_id"],
                "arm": slot["arm"],
                "positive_waits": positives,
                "union_blocking_wall_by_turn_s": blocking,
                "observed_required_completions": completions,
                "terminal_state": expected_terminal,
                "shard": {
                    "waits": shard_row["waits"],
                    "observed_blocking_wall_s": (
                        shard_row["observed_blocking_wall_s"]
                    ),
                    "observed_required_completions": (
                        shard_row["observed_required_completions"]
                    ),
                    "terminal_state": shard_row["terminal_state"],
                },
                "checks": checks,
            },
            sort_keys=True,
        )
    )

source_counts = {
    f"{key[0]}/{key[1]}": value
    for key, value in sorted(arm_scenario.items())
}
shard_counts = {}
for row in shard["rows"]:
    key = f"{row['scenario']}/{row['arm']}"
    shard_counts[key] = shard_counts.get(key, 0) + 1

population_checks = {
    "R11/A": source_counts.get("R11/A") == shard_counts.get("R11/A"),
    "R11/B": source_counts.get("R11/B") == shard_counts.get("R11/B"),
    "R11/total": (
        sum(source_counts.values())
        == len(shard["rows"])
        == shard["row_count"]
        == shard["trial_count"]
    ),
}
print("source_counts=" + json.dumps(source_counts, sort_keys=True))
print("shard_counts=" + json.dumps(shard_counts, sort_keys=True))
print(
    f"row_invariant_checks={row_check_total} "
    f"passed={row_check_passes} "
    f"failed={row_check_total - row_check_passes}"
)
population_passes = sum(population_checks.values())
print(
    f"population_checks={len(population_checks)} "
    f"passed={population_passes} "
    f"failed={len(population_checks) - population_passes}"
)
counts_pass = all(population_checks.values())
print("overall=" + ("PASS" if all_pass and counts_pass else "FAIL"))
PY
```

## Overall verdict

All 24 row-level invariant comparisons and all three submitted-population
comparisons pass.

AUDIT phase1-step7: PASS
