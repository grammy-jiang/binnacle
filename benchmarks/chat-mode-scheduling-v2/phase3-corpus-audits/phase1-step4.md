# Phase 3 corpus audit: phase1-step4

## Evidence identity

- Source: `benchmarks/chat-mode-scheduling-v2/phase1-step4-background-barrier-ab-2026-09-23.json`
- Source SHA-256: `835ad53b639ed53a67bb7731e05cf4075b641449da56d7a5ac267f73b7988d11`
- Shard: `benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step4.json`
- Shard SHA-256: `332a8a6c449d48b617a752f9a1a8244497eddd1853ea59c9fe7586fa984ec9e1`
- Raw evidence: each canonical slot's immutable `trial.json` and `trace.json`
  under the `state_dir` named by the source report.

The audit re-derived all expected values from the source report plus those raw
state files. It did not call or import the Phase-3 corpus extractor.

## Canonical submitted slot counts

| Scenario | Arm | Expected | Shard | Verdict |
| --- | --- | ---: | ---: | --- |
| R3 | A | 3 | 3 | PASS |
| R3 | B | 3 | 3 | PASS |
| R5 | A | 3 | 3 | PASS |
| R5 | B | 3 | 3 | PASS |
| Total | all | 12 | 12 | PASS |

Invariant verdict: **PASS**.

## Positive `job_status` waits

Every raw `job_status` result with `waited_s > 0` is listed below. The expected
values are the actual observed `result.waited_s` values, not requested waits.
All eight calls requested 50 seconds and returned terminal state `exited`.

| Trial | Scenario | Arm | Slot | Expected `waited_s` | Shard `waited_s` | Verdict |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `r3-20260923T165558-5f6c0ac6cc` | R3 | A | 1 | 14.505 | 14.505 | PASS |
| `r3-20260923T170014-f2ea2e57b0` | R3 | B | 2 | 16.510 | 16.510 | PASS |
| `r3-20260923T170514-349ca3f042` | R3 | A | 4 | 14.511 | 14.511 | PASS |
| `r3-20260923T171043-867bec433f` | R3 | B | 6 | 12.005 | 12.005 | PASS |
| `r5-20260923T171626-8943400707` | R5 | A | 2 | 23.524 | 23.524 | PASS |
| `r5-20260923T171751-150174d991` | R5 | A | 3 | 23.520 | 23.520 | PASS |
| `r5-20260923T172045-62e44edbe4` | R5 | B | 4 | 21.516 | 21.516 | PASS |
| `r5-20260923T172519-0cee94f978` | R5 | B | 5 | 23.520 | 23.520 | PASS |

Expected positive-wait count: 8. Shard positive-wait count: 8.

Invariant verdict: **PASS**.

## Union blocking wall, required completions, and terminal states

The expected union blocking wall is the interval union of each turn's positive
`job_status` `blocking_start_s` to `blocking_end_s` intervals. Trials with no
positive wait have an expected union of 0 seconds. A required completion is
counted only when the scenario's required wait node (`validation_result` for R3,
`wait_result` for R5) is present as a positive wait and returns `state=exited`.
Terminal state is independently read from the raw `trial.json` `status` field.

| Trial | Expected union (s) | Shard union (s) | Expected completions | Shard completions | Expected terminal | Shard terminal | Verdict |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `r3-20260923T165558-5f6c0ac6cc` | 14.505 | 14.505 | 1 | 1 | completed | completed | PASS |
| `r3-20260923T170014-f2ea2e57b0` | 16.510 | 16.510 | 1 | 1 | completed | completed | PASS |
| `r3-20260923T170222-993f7b7f2c` | 0.000 | 0.000 | 0 | 0 | failed | failed | PASS |
| `r3-20260923T170514-349ca3f042` | 14.511 | 14.511 | 1 | 1 | completed | completed | PASS |
| `r3-20260923T170718-83a5983ce3` | 0.000 | 0.000 | 0 | 0 | completed | completed | PASS |
| `r3-20260923T171043-867bec433f` | 12.005 | 12.005 | 1 | 1 | completed | completed | PASS |
| `r5-20260923T171218-8b86263319` | 0.000 | 0.000 | 0 | 0 | failed | failed | PASS |
| `r5-20260923T171626-8943400707` | 23.524 | 23.524 | 1 | 1 | completed | completed | PASS |
| `r5-20260923T171751-150174d991` | 23.520 | 23.520 | 1 | 1 | completed | completed | PASS |
| `r5-20260923T172045-62e44edbe4` | 21.516 | 21.516 | 1 | 1 | completed | completed | PASS |
| `r5-20260923T172519-0cee94f978` | 23.520 | 23.520 | 1 | 1 | completed | completed | PASS |
| `r5-20260923T172700-fab3c30167` | 0.000 | 0.000 | 0 | 0 | failed | failed | PASS |

Expected required completions: 8. Shard required completions: 8.
Expected terminal-state totals: 9 completed and 3 failed. Shard totals: 9
completed and 3 failed.

Invariant verdicts:

- Union blocking wall per turn: **PASS**.
- Observed required completions: **PASS**.
- Terminal states: **PASS**.

## Provenance and structural checks

- Expected source SHA linkage: the source report SHA above at shard top level and
  on every shard row.
- Shard source SHA linkage: exactly
  `835ad53b639ed53a67bb7731e05cf4075b641449da56d7a5ac267f73b7988d11`
  at top level and across all rows.
- Expected row/trial counts: 12/12.
- Shard row/trial counts: 12/12.

Invariant verdicts:

- Source hash linkage: **PASS**.
- Row/trial counts: **PASS**.

## Exact audit commands

The material shell commands used for derivation and comparison were:

```bash
python3 /tmp/p36-audit-phase1-step4-derive.py
sha256sum benchmarks/chat-mode-scheduling-v2/phase1-step4-background-barrier-ab-2026-09-23.json benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step4.json
python3 /tmp/p36-audit-phase1-step4-compare.py
uv run pre-commit run --files benchmarks/chat-mode-scheduling-v2/phase3-corpus-audits/phase1-step4.md
```

The two `/tmp` audit helpers read the source report and each canonical slot's raw
`trial.json`/`trace.json`; the comparison helper additionally reads the frozen
shard. The comparison command reported `7 passed, 0 failed` across canonical slot
counts, positive waits, blocking-wall unions, required completions, terminal
states, source-hash linkage, and row/trial counts.

One earlier bundled exploratory Python inspection command was rejected by the
platform safety filter. The provided `statecat.sh` helper was used instead for
that inspection; this did not alter evidence or audit logic.

## Canonical corpus binding (Step 3.5A)

- Canonical revision-2 replay corpus SHA-256:
  `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`.
- Canonical integrated shard SHA-256:
  `332a8a6c449d48b617a752f9a1a8244497eddd1853ea59c9fe7586fa984ec9e1`.
- The Step 3.5A fan-in binds this independent source/shard PASS to the
  aggregate revision-2 PASS. The shard hash above matches the integrated
  shard bytes and the aggregate audit confirms exact membership in the
  frozen corpus.

AUDIT phase1-step4: PASS
