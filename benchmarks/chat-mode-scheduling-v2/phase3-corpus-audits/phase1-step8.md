# Phase 3 corpus audit: phase1-step8

## Scope and evidence

This audit independently re-derives the Step-8 replay invariants from the
immutable Phase-1 report and its six frozen `trial.json` / `trace.json`
pairs. It does not use the corpus extractor implementation as an authority.

| Evidence | Path | SHA-256 |
| --- | --- | --- |
| Phase-1 source report | `benchmarks/chat-mode-scheduling-v2/phase1-step8-repeated-dependency-barrier-ab-2026-09-23.json` | `98a3744b0deb5b441e892d34d025bb17d45d9e043ca54805a50afe9524e71a6f` |
| Phase-3 shard | `benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step8.json` | `be0b57741415bccd2676e1dc7914beaf50b1a887983819cda22c5698f933ff40` |

The immutable state evidence hashes used for reconstruction are:

| Run | `trial.json` SHA-256 | `trace.json` SHA-256 |
| --- | --- | --- |
| `r7-20260923T202711-94f01d2ec7` | `c0825747175829b7ba3052ce028f5f3aa43d7ad212d0210311b8ee5560117b9b` | `29649a1f72e51c4fbd4d4e992c6cc23b912bd1230187a1b9364cf1d808715f82` |
| `r7-20260923T203224-5ac2484c75` | `b96b8c47b5e4bf1b165570a53b4b077290f7475ea178377d45a519f8beb4b7af` | `874c4d8a251df42308f20750cdaea402178eacd9d2fb2fb99bd4096ca531b2e1` |
| `r7-20260923T203622-d51ce307ef` | `aa2ec12322a5c34a797924054efc734799b25358101f74c8bc1129fdd70a9e6b` | `f7cf26966fdbf84aa87cee45a80051d30e909d19f0c64dc3a1c35972f3145b79` |
| `r7-20260923T204617-91387f101b` | `957914c492bfd70d0a56b1c7989ded767f7c383ae4028ae7fcbc686275269bcf` | `15b253f6b1cba9498c09d919a9c982d6b28c17b21f6ab2c65938a3764e17e48a` |
| `r7-20260923T210916-adb0ab6d70` | `360d94515eb978c5c562c5b782b5305042d8d5031d1c703329ca0ddc06b8ad8e` | `88b7505750dd08036bea06c1380e35fd8a2d014790a431e83e55cccac006646c` |
| `r7-20260923T211346-942d651555` | `3e85528aab41a7319f757f4a5ab85907f7efd14a3f9af8bf31bafeea2b92cd7c` | `5dae297851f1cad6eb779fd12f69e8cacae88323e899fc8160e2818c3834a54e` |

A positive `job_status` wait is selected from raw trace evidence only when
`args.wait_seconds > 0`; its physical duration is always the observed
`result.waited_s`. Union blocking wall is reconstructed by merging raw
`blocking_start_s` / `blocking_end_s` intervals independently for each
base turn. Required completion nodes are taken from the Phase-1 report's
frozen R7 specification correction: `wait_first` and `wait_second`.

## Canonical submitted slots

| Invariant | Expected from Phase-1 source | Shard value | Verdict |
| --- | --- | --- | --- |
| Scenario R7, arm A submitted slots | 3 | 3 | PASS |
| Scenario R7, arm B submitted slots | 3 | 3 | PASS |
| Total submitted canonical slots | 6 | 6 rows / 6 trials | PASS |

## Positive job-status waits and actual waited time

The sequences below are in physical trace order. Each entry is
`node_id:actual_waited_s`; `none` is the raw non-DAG status call whose
`node_id` is null. All selected calls had a positive requested wait even
when the observed physical wait was zero.

| Trial | Expected from raw trace | Shard value | Verdict |
| --- | --- | --- | --- |
| `r7-20260923T202711-94f01d2ec7` | `[wait_first:50.001, wait_first:0.001, none:0.000, wait_second:15.000, wait_second:15.000, wait_second:15.000, wait_second:15.000, wait_second:2.491]` | `[wait_first:50.001, wait_first:0.001, none:0.000, wait_second:15.000, wait_second:15.000, wait_second:15.000, wait_second:15.000, wait_second:2.491]` | PASS |
| `r7-20260923T203224-5ac2484c75` | `[wait_first:50.000, wait_first:2.490, wait_second:50.000, wait_second:20.007]` | `[wait_first:50.000, wait_first:2.490, wait_second:50.000, wait_second:20.007]` | PASS |
| `r7-20260923T203622-d51ce307ef` | `[wait_first:50.001, wait_first:0.001, wait_second:50.000, wait_second:0.000]` | `[wait_first:50.001, wait_first:0.001, wait_second:50.000, wait_second:0.000]` | PASS |
| `r7-20260923T204617-91387f101b` | `[wait_first:50.000, wait_first:4.993, wait_second:50.000, wait_second:20.512]` | `[wait_first:50.000, wait_first:4.993, wait_second:50.000, wait_second:20.512]` | PASS |
| `r7-20260923T210916-adb0ab6d70` | `[wait_first:50.000, wait_first:2.490, wait_second:50.001, wait_second:16.004]` | `[wait_first:50.000, wait_first:2.490, wait_second:50.001, wait_second:16.004]` | PASS |
| `r7-20260923T211346-942d651555` | `[]` | `[]` | PASS |
| Total positive-request waits | 24 | 24 | PASS |

## Union blocking wall per turn

| Trial | Base turn | Expected union wall (s) | Shard wall (s) | Verdict |
| --- | --- | ---: | ---: | --- |
| `r7-20260923T202711-94f01d2ec7` | `d986c765-98e0-45b5-ab2d-e77afe9d0e31` | 112.493 | 112.493 | PASS |
| `r7-20260923T203224-5ac2484c75` | `5d785826-bfdd-481c-b1f7-e61505a0fb34` | 122.497 | 122.497 | PASS |
| `r7-20260923T203622-d51ce307ef` | `09c338ed-923c-4af0-ab38-1e612fb8dd09` | 100.002 | 100.002 | PASS |
| `r7-20260923T204617-91387f101b` | `86344832-fa17-48ec-9a6c-880f60d71803` | 125.505 | 125.505 | PASS |
| `r7-20260923T210916-adb0ab6d70` | `d87af3bf-b514-4a42-8d59-bec2ea83ec3f` | 118.495 | 118.495 | PASS |
| `r7-20260923T211346-942d651555` | no physical status turn; shard sentinel `trial` | 0.000 | 0.000 | PASS |

## Observed required completions

A required completion is counted once per required R7 wait node when raw
`job_status` evidence reports `state == "exited"`.

| Trial | Expected completions | Shard completions | Verdict |
| --- | ---: | ---: | --- |
| `r7-20260923T202711-94f01d2ec7` | 2 | 2 | PASS |
| `r7-20260923T203224-5ac2484c75` | 2 | 2 | PASS |
| `r7-20260923T203622-d51ce307ef` | 2 | 2 | PASS |
| `r7-20260923T204617-91387f101b` | 2 | 2 | PASS |
| `r7-20260923T210916-adb0ab6d70` | 2 | 2 | PASS |
| `r7-20260923T211346-942d651555` | 0 | 0 | PASS |

## Terminal states

Terminal state is read directly from each immutable `trial.json` `status`
field.

| Trial | Expected terminal state | Shard terminal state | Verdict |
| --- | --- | --- | --- |
| `r7-20260923T202711-94f01d2ec7` | `failed` | `failed` | PASS |
| `r7-20260923T203224-5ac2484c75` | `completed` | `completed` | PASS |
| `r7-20260923T203622-d51ce307ef` | `failed` | `failed` | PASS |
| `r7-20260923T204617-91387f101b` | `completed` | `completed` | PASS |
| `r7-20260923T210916-adb0ab6d70` | `failed` | `failed` | PASS |
| `r7-20260923T211346-942d651555` | `failed` | `failed` | PASS |

## Exact reproduction commands

The following commands were run with workdir `/tmp`. They read the source,
shard, and frozen state directly; they do not import or execute the replay
corpus extractor.

### Evidence hashes

```bash
python3 - <<'PY'
import hashlib, json, pathlib
w=pathlib.Path("/home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-audit-phase1-step8")
report=w/"benchmarks/chat-mode-scheduling-v2/phase1-step8-repeated-dependency-barrier-ab-2026-09-23.json"
shard=w/"benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step8.json"
obj=json.loads(report.read_text())
paths=[report,shard]
for s in obj["canonical_slots"]:
    if s.get("submitted"):
        d=pathlib.Path(s["state_dir"])
        paths += [d/"trial.json", d/"trace.json"]
for p in paths:
    h=hashlib.sha256(p.read_bytes()).hexdigest()
    print(f"{h}  {p}")
PY
```

### Invariant comparison

```bash
python3 - <<'PY'
import collections
import json
import math
import pathlib
import sys

W = pathlib.Path(
    "/home/grammy-jiang/Projects/"
    "binnacle-chat-scheduling-phase3-audit-phase1-step8"
)
REPORT = W / (
    "benchmarks/chat-mode-scheduling-v2/"
    "phase1-step8-repeated-dependency-barrier-ab-2026-09-23.json"
)
SHARD = W / (
    "benchmarks/chat-mode-scheduling-v2/"
    "phase3-corpus-shards/phase1-step8.json"
)

report = json.loads(REPORT.read_text())
shard = json.loads(SHARD.read_text())
slots = [s for s in report["canonical_slots"] if s.get("submitted") is True]
rows = {r["trial_id"]: r for r in shard["rows"]}
required = set(report["specification_correction"]["nodes"])
expected_counts = collections.Counter(
    (s["scenario_id"], s["arm"]) for s in slots
)
shard_counts = collections.Counter(
    (r["scenario"], r["arm"]) for r in shard["rows"]
)

failures = []
positive_waits = 0
if expected_counts != shard_counts:
    failures.append("canonical arm/scenario counts")
if not (
    len(slots) == shard.get("trial_count") == shard.get("row_count") == 6
):
    failures.append("canonical total count")

for slot in slots:
    run_id = slot["run_id"]
    row = rows.get(run_id)
    if row is None:
        failures.append(f"{run_id}: missing shard row")
        continue

    state_dir = pathlib.Path(slot["state_dir"])
    trial = json.loads((state_dir / "trial.json").read_text())
    trace = json.loads((state_dir / "trace.json").read_text())
    positive = [
        tool
        for tool in trace["tools"]
        if tool.get("tool") == "job_status"
        and float(tool.get("args", {}).get("wait_seconds") or 0) > 0
    ]
    positive_waits += len(positive)

    expected_waits = [
        (
            tool.get("node_id"),
            float(tool["args"]["wait_seconds"]),
            float(tool.get("result", {}).get("waited_s") or 0.0),
            tool.get("result", {}).get("state"),
        )
        for tool in positive
    ]
    shard_waits = [
        (
            tool.get("node_id"),
            float(tool.get("requested_wait_s") or 0.0),
            float(tool.get("waited_s") or 0.0),
            tool.get("state"),
        )
        for tool in row["waits"]
    ]
    if expected_waits != shard_waits:
        failures.append(f"{run_id}: wait sequence")

    intervals_by_turn = collections.defaultdict(list)
    for tool in positive:
        start = tool.get("blocking_start_s")
        end = tool.get("blocking_end_s")
        if start is not None and end is not None:
            intervals_by_turn[tool["turn"]].append(
                (float(start), float(end))
            )

    turn_union = {}
    for turn, intervals in intervals_by_turn.items():
        merged = []
        for start, end in sorted(intervals):
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            elif end > merged[-1][1]:
                merged[-1][1] = end
        turn_union[turn] = round(
            sum(end - start for start, end in merged),
            6,
        )

    union_total = round(sum(turn_union.values()), 6)
    if not math.isclose(
        union_total,
        float(row["observed_blocking_wall_s"]),
        rel_tol=0,
        abs_tol=1e-6,
    ):
        failures.append(f"{run_id}: blocking wall")

    base_turns = sorted({tool["turn"] for tool in positive})
    base_turn_ok = (
        not base_turns
        and row["base_turn"] == "trial"
    ) or (
        len(base_turns) == 1
        and row["base_turn"] == base_turns[0]
    )
    if not base_turn_ok:
        failures.append(f"{run_id}: base turn")

    completed = {
        tool.get("node_id")
        for tool in positive
        if tool.get("node_id") in required
        and tool.get("result", {}).get("state") == "exited"
    }
    if len(completed) != int(row["observed_required_completions"]):
        failures.append(f"{run_id}: required completions")

    if trial["status"] != row["terminal_state"]:
        failures.append(f"{run_id}: terminal state")

print(f"canonical_rows={len(slots)}")
print(f"positive_waits={positive_waits}")
print(f"blocking_wall_trials={len(slots)}")
print(f"completion_trials={len(slots)}")
print(f"terminal_state_trials={len(slots)}")
print("failures=" + (", ".join(failures) if failures else "none"))
print("AUDIT_RESULT=" + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
PY
```

## Overall verdict

All required invariants match the frozen shard exactly. The independent
comparison covers 6 canonical submitted slots, all 24 positive-request
`job_status` waits with their actual observed `waited_s`, all per-turn
blocking unions, all required-completion counts, and all terminal states.

## Canonical corpus binding (Step 3.5A)

- Canonical revision-2 replay corpus SHA-256:
  `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`.
- Canonical integrated shard SHA-256:
  `be0b57741415bccd2676e1dc7914beaf50b1a887983819cda22c5698f933ff40`.
- The Step 3.5A fan-in binds this independent source/shard PASS to the
  aggregate revision-2 PASS. The shard hash above matches the integrated
  shard bytes and the aggregate audit confirms exact membership in the
  frozen corpus.

AUDIT phase1-step8: PASS
