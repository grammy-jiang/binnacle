# Phase 3 corpus audit: phase1-step3

This audit independently re-derived the Step-3 corpus invariants from the
canonical Phase-1 report and its immutable raw trial/trace state. No extractor
implementation path was used.

## Inputs

- Source:
  `benchmarks/chat-mode-scheduling-v2/phase1-step3-read-heavy-ab-2026-09-23.json`
  SHA-256:
  `bfb2a31f79a20ac6a292d1ec095a05d7dd462bdf26d22b1922bc2389cb253190`
- Shard:
  `benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step3.json`
  SHA-256:
  `6c1a6bf8df81bd3a68e697d3cfae9927fba4fec3c569ce27b71eefe134aed118`
- Raw state basis: the 12 `state_dir` entries named by the canonical source
  report, using each run's `trial.json` and `trace.json`.
- Merged corpus SHA: not applicable at this per-source audit point. This audit
  starts from the exact source-shard commit before the Step-3.5M aggregate merge.

## Canonical submitted slots

The source report contains 12 canonical submitted slots. The independently
counted source and shard populations match by scenario and arm.

| Scenario | Arm | Expected source slots | Shard rows | Verdict |
| --- | --- | ---: | ---: | --- |
| R1 | A | 3 | 3 | PASS |
| R1 | B | 3 | 3 | PASS |
| R2 | A | 3 | 3 | PASS |
| R2 | B | 3 | 3 | PASS |
| Total | all | 12 | 12 | PASS |

## Positive job_status waits and actual waited_s

Every canonical raw `trace.json` was read through
`/tmp/p36-manager/statecat.sh`. None contains a physical
`job_status` tool call. Therefore the independently observed positive-wait
set, including actual `waited_s` values, is the empty list `[]`.

The shard also has `waits: []` for all 12 rows.

| Invariant | Expected from raw state | Shard value | Verdict |
| --- | --- | --- | --- |
| Physical `job_status` calls | 0 | 0 represented waits | PASS |
| Positive `job_status` waits | 0 | 0 | PASS |
| Actual `waited_s` values | `[]` | `[]` | PASS |

## Union blocking wall per turn

All physical tool records in the 11 non-empty traces have
`blocking_start_s: null` and `blocking_end_s: null`; the failed R2/B trace
has no tool calls at all. With no positive blocking intervals, the interval
union is exactly 0 seconds for every observed turn and 0 seconds for the failed
trial fallback row.

All 12 shard rows report `observed_blocking_wall_s: 0`.

| Invariant | Expected from raw state | Shard value | Verdict |
| --- | ---: | ---: | --- |
| Rows with non-zero union blocking wall | 0 | 0 | PASS |
| Per-row union blocking wall | 0 s for all 12 | 0 s for all 12 | PASS |

## Observed required completions

A required job completion can only be observed on a physical status result.
Because the raw traces contain zero `job_status` calls, there are zero observed
required job completions in every canonical row.

All 12 shard rows report `observed_required_completions: 0`.

| Invariant | Expected from raw state | Shard value | Verdict |
| --- | ---: | ---: | --- |
| Total observed required completions | 0 | 0 | PASS |
| Rows with non-zero required completions | 0 | 0 | PASS |

## Terminal states

Raw `trial.json` status is the independent terminal-state authority. Eleven
canonical trials are `completed`; the R2/B timeout trial
`r2-20260923T154139-d85ce7fb3f` is `failed`. The shard matches every run.

| Trial | Expected raw terminal | Shard terminal | Verdict |
| --- | --- | --- | --- |
| `r1-20260923T153114-e4eb49b0eb` | completed | completed | PASS |
| `r1-20260923T153237-67ac207754` | completed | completed | PASS |
| `r1-20260923T153409-5cf19620a0` | completed | completed | PASS |
| `r1-20260923T153537-509df2fe2f` | completed | completed | PASS |
| `r1-20260923T153652-844d73ddfe` | completed | completed | PASS |
| `r1-20260923T153816-36c09bb6d7` | completed | completed | PASS |
| `r2-20260923T154139-d85ce7fb3f` | failed | failed | PASS |
| `r2-20260923T154756-58d6369649` | completed | completed | PASS |
| `r2-20260923T154921-f527640167` | completed | completed | PASS |
| `r2-20260923T155047-71bebf98f7` | completed | completed | PASS |
| `r2-20260923T161110-da49a27454` | completed | completed | PASS |
| `r2-20260923T161240-35e63b9edb` | completed | completed | PASS |

Terminal-state aggregate: expected `completed=11, failed=1`; shard
`completed=11, failed=1`. Verdict: PASS.

## Exact commands used

Source/shard hashes and base lineage:

```bash
git status --short --branch
git log -5 --oneline
sha256sum \
  benchmarks/chat-mode-scheduling-v2/phase1-step3-read-heavy-ab-2026-09-23.json \
  benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step3.json
```

The raw-state summary command was run as:

```bash
bash /tmp/p36-manager/p3-audit-phase1-step3-summary.sh
```

The helper executed the following state reads and filters:

```bash
set -e
root=/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs
for run in \
  r1-20260923T153114-e4eb49b0eb \
  r1-20260923T153237-67ac207754 \
  r1-20260923T153409-5cf19620a0 \
  r1-20260923T153537-509df2fe2f \
  r1-20260923T153652-844d73ddfe \
  r1-20260923T153816-36c09bb6d7 \
  r2-20260923T154139-d85ce7fb3f \
  r2-20260923T154756-58d6369649 \
  r2-20260923T154921-f527640167 \
  r2-20260923T155047-71bebf98f7 \
  r2-20260923T161110-da49a27454 \
  r2-20260923T161240-35e63b9edb
do
  printf '%s\n' "RUN $run"
  bash /tmp/p36-manager/statecat.sh "$root/$run/trial.json" |
    grep -E '^  "(arm|run_id|scenario_id|stage|status)":' || true
  bash /tmp/p36-manager/statecat.sh "$root/$run/trace.json" |
    grep -E \
      '^  "(assistant_complete|timing_status)":|"tool": "job_status"|"blocking_(start|end)_s":' ||
    true
done
```

Source-to-shard comparison was run as:

```bash
python3 - <<'PY'
import collections
import json

source = (
    "benchmarks/chat-mode-scheduling-v2/"
    "phase1-step3-read-heavy-ab-2026-09-23.json"
)
shard = (
    "benchmarks/chat-mode-scheduling-v2/"
    "phase3-corpus-shards/phase1-step3.json"
)

with open(source) as handle:
    source_data = json.load(handle)
with open(shard) as handle:
    shard_data = json.load(handle)

source_counts = collections.Counter(
    (row["scenario_id"], row["arm"])
    for row in source_data["canonical_slots"]
)
shard_counts = collections.Counter(
    (row["scenario"], row["arm"])
    for row in shard_data["rows"]
)

print("SOURCE_COUNTS", dict(sorted(source_counts.items())))
print("SHARD_COUNTS", dict(sorted(shard_counts.items())))
print(
    "SOURCE_TERMINALS",
    [
        (row["run_id"], "failed" if row["interrupted"] else "completed")
        for row in source_data["canonical_slots"]
    ],
)
print(
    "SHARD_TERMINALS",
    [(row["trial_id"], row["terminal_state"]) for row in shard_data["rows"]],
)
print(
    "SOURCE_POSITIVE_JOB_STATUS_COUNTS",
    [
        (row["run_id"], row["positive_job_status_calls"])
        for row in source_data["canonical_slots"]
    ],
)
print(
    "SOURCE_BLOCKING_WALL",
    [(row["run_id"], row["blocking_wall_s"]) for row in source_data["canonical_slots"]],
)
print(
    "SHARD_WAIT_LENGTHS",
    [(row["trial_id"], len(row["waits"])) for row in shard_data["rows"]],
)
print(
    "SHARD_BLOCKING_WALL",
    [
        (row["trial_id"], row["observed_blocking_wall_s"])
        for row in shard_data["rows"]
    ],
)
print(
    "SHARD_REQUIRED_COMPLETIONS",
    [
        (row["trial_id"], row["observed_required_completions"])
        for row in shard_data["rows"]
    ],
)
PY
```

No extractor source code or extractor CLI path was used for the re-derivation.

## Focused validation

The task-specific assertion validator re-read the immutable state through
`statecat.sh` and asserted all requested invariants against the shard.

```bash
chmod +x /tmp/p36-manager/p3-audit-phase1-step3-validate.py &&
  /tmp/p36-manager/p3-audit-phase1-step3-validate.py
```

Validation output:

```text
PASS canonical_slots=12 shard_rows=12 scenario_arm_counts=R1/A:3,R1/B:3,R2/A:3,R2/B:3 terminal_matches=12 positive_waits=0 nonzero_union_rows=0 required_completions=0
```

AUDIT phase1-step3: PASS
