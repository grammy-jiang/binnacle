# Phase 3 corpus audit — phase1-step5

## Scope and inputs

This audit independently re-derives the Phase-1 Step-5 replay invariants from the
immutable Phase-1 source report and each referenced raw `trial.json` and
`trace.json`. It does not import or execute the Phase-3 corpus extractor.

Source report:

`benchmarks/chat-mode-scheduling-v2/phase1-step5-development-journey-ab-2026-09-23.json`

SHA-256:

`1e2257a98e3c13d809f32134483a6ccaf1c1bf8fd81048099230e2b8a28f021d`

Shard:

`benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step5.json`

SHA-256:

`f2f3b655d809efef8b0d059c6cb07c809b18bfd4b16034cf226a67403ee12685`

The source report references six submitted R8 state directories. Each referenced
`trial.json` and `trace.json` was read directly from the immutable Phase-1
state evidence.

## Canonical submitted slot counts

- R8/A: expected 3; shard 3; **PASS**.
- R8/B: expected 3; shard 3; **PASS**.
- Total submitted canonical slots: expected 6; shard `row_count=6` and
  `trial_count=6`; **PASS**.

## Positive job_status waits and actual waited_s

The source report records `positive_job_status_calls=0` for every submitted
slot. Direct scans of all six raw traces independently found no `job_status`
tool calls, therefore there are no positive actual `waited_s` values to replay.

- `r8-20260923T180224-d0c955df6d`: expected `[]`; shard `[]`; **PASS**.
- `r8-20260923T180409-ca0d0fdb6a`: expected `[]`; shard `[]`; **PASS**.
- `r8-20260923T180545-3b8eec8a30`: expected `[]`; shard `[]`; **PASS**.
- `r8-20260923T180712-95a7c47b91`: expected `[]`; shard `[]`; **PASS**.
- `r8-20260923T180831-4fec1a5f8c`: expected `[]`; shard `[]`; **PASS**.
- `r8-20260923T180940-6f6970131e`: expected `[]`; shard `[]`; **PASS**.

Invariant verdict — every positive `job_status` wait uses actual observed
`waited_s`: **PASS**. The positive-wait population is empty for this source.

## Union blocking wall per turn

With no positive physical `job_status` intervals, the independently derived
per-turn interval map is empty for every trial and its union is 0 seconds. The
source report also records `blocking_wall_s=0.0` for every submitted slot.

- `r8-20260923T180224-d0c955df6d`: expected per-turn union `{}`, total
  `0.0 s`; shard `0 s`; **PASS**.
- `r8-20260923T180409-ca0d0fdb6a`: expected per-turn union `{}`, total
  `0.0 s`; shard `0 s`; **PASS**.
- `r8-20260923T180545-3b8eec8a30`: expected per-turn union `{}`, total
  `0.0 s`; shard `0 s`; **PASS**.
- `r8-20260923T180712-95a7c47b91`: expected per-turn union `{}`, total
  `0.0 s`; shard `0 s`; **PASS**.
- `r8-20260923T180831-4fec1a5f8c`: expected per-turn union `{}`, total
  `0.0 s`; shard `0 s`; **PASS**.
- `r8-20260923T180940-6f6970131e`: expected per-turn union `{}`, total
  `0.0 s`; shard `0 s`; **PASS**.

Invariant verdict — union blocking wall per turn: **PASS**.

## Observed required completions

A required completion is counted only when a positive historical physical
`job_status` call returns the observed completion. Because the raw traces have
no such calls, the independently derived count is zero for every trial.

- `r8-20260923T180224-d0c955df6d`: expected 0; shard 0; **PASS**.
- `r8-20260923T180409-ca0d0fdb6a`: expected 0; shard 0; **PASS**.
- `r8-20260923T180545-3b8eec8a30`: expected 0; shard 0; **PASS**.
- `r8-20260923T180712-95a7c47b91`: expected 0; shard 0; **PASS**.
- `r8-20260923T180831-4fec1a5f8c`: expected 0; shard 0; **PASS**.
- `r8-20260923T180940-6f6970131e`: expected 0; shard 0; **PASS**.

Invariant verdict — observed required completions: **PASS**.

## Terminal states

Each immutable raw `trial.json` records `status="completed"`.

- `r8-20260923T180224-d0c955df6d`: expected `completed`; shard
  `completed`; **PASS**.
- `r8-20260923T180409-ca0d0fdb6a`: expected `completed`; shard
  `completed`; **PASS**.
- `r8-20260923T180545-3b8eec8a30`: expected `completed`; shard
  `completed`; **PASS**.
- `r8-20260923T180712-95a7c47b91`: expected `completed`; shard
  `completed`; **PASS**.
- `r8-20260923T180831-4fec1a5f8c`: expected `completed`; shard
  `completed`; **PASS**.
- `r8-20260923T180940-6f6970131e`: expected `completed`; shard
  `completed`; **PASS**.

Invariant verdict — terminal states: **PASS**.

## Exact audit commands

Hashes were independently verified with:

```bash
sha256sum \
  benchmarks/chat-mode-scheduling-v2/phase1-step5-development-journey-ab-2026-09-23.json \
  benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step5.json
```

The invariant derivation and shard comparison used this standalone Python
command. It reads only the source report, shard, and source-referenced immutable
raw state evidence; it imports no project extractor code.

```bash
python3 - <<'PY'
import json
from collections import Counter, defaultdict
from pathlib import Path

root = Path(".")
source = root / "benchmarks/chat-mode-scheduling-v2/phase1-step5-development-journey-ab-2026-09-23.json"
shard = root / "benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step5.json"

src = json.loads(source.read_text())
sh = json.loads(shard.read_text())
slots = [slot for slot in src["canonical_slots"] if slot["submitted"]]
rows = {row["trial_id"]: row for row in sh["rows"]}

counts = Counter((slot["scenario_id"], slot["arm"]) for slot in slots)
assert counts == Counter({("R8", "A"): 3, ("R8", "B"): 3})
assert sh["row_count"] == sh["trial_count"] == len(slots) == 6
assert Counter((row["scenario"], row["arm"]) for row in sh["rows"]) == counts

for slot in slots:
    state = Path(slot["state_dir"])
    trial = json.loads((state / "trial.json").read_text())
    trace = json.loads((state / "trace.json").read_text())
    row = rows[slot["run_id"]]

    waits = []
    intervals = defaultdict(list)
    completions = 0
    for tool in trace.get("tools", []):
        if tool.get("tool") != "job_status":
            continue
        waited_s = tool.get("result", {}).get("waited_s")
        if isinstance(waited_s, (int, float)) and waited_s > 0:
            waits.append(waited_s)
            start = tool.get("blocking_start_s")
            end = tool.get("blocking_end_s")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                intervals[tool.get("turn")].append((start, end))
            if tool.get("result", {}).get("state") == "exited":
                completions += 1

    union_by_turn = {}
    for turn, spans in intervals.items():
        total = 0.0
        current_start = current_end = None
        for start, end in sorted(spans):
            if current_start is None:
                current_start, current_end = start, end
            elif start <= current_end:
                current_end = max(current_end, end)
            else:
                total += current_end - current_start
                current_start, current_end = start, end
        if current_start is not None:
            total += current_end - current_start
        union_by_turn[turn] = total

    blocking_wall_s = sum(union_by_turn.values())
    assert slot["positive_job_status_calls"] == len(waits) == 0
    assert slot["blocking_wall_s"] == blocking_wall_s == 0
    assert row["waits"] == []
    assert row["observed_blocking_wall_s"] == blocking_wall_s
    assert row["observed_required_completions"] == completions == 0
    assert row["terminal_state"] == trial["status"] == "completed"

print("phase1-step5 audit: 6/6 trials and 5 invariant groups PASS")
PY
```

## Canonical corpus binding (Step 3.5A)

- Canonical revision-2 replay corpus SHA-256:
  `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`.
- Canonical integrated shard SHA-256:
  `f2f3b655d809efef8b0d059c6cb07c809b18bfd4b16034cf226a67403ee12685`.
- The Step 3.5A fan-in binds this independent source/shard PASS to the
  aggregate revision-2 PASS. The shard hash above matches the integrated
  shard bytes and the aggregate audit confirms exact membership in the
  frozen corpus.

AUDIT phase1-step5: PASS
