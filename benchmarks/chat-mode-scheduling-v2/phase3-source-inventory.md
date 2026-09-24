# Chat mode scheduling v2 — Phase 3 source inventory

Frozen: 2026-09-25T01:36:54+10:00

## Freeze contract

- Source baseline HEAD: `9b72546b5380fc0bbacfb069cd567df79fdaa0cd`.
- Step-1.9 aggregate authority: `benchmarks/chat-mode-scheduling-v2/phase1-step9-aggregate-go-no-go-2026-09-23.json` (SHA-256 `aca120453c1aff60e75bcfad20476507205debe09cc1f77c6ca4409affae7cee`).
- All six mandatory Phase-1 macro report hashes match the SHA-256 values recorded by Step 1.9.
- Canonical submitted population: 48 slots = 24 A + 24 B; expected 24 A + 24 B.
- Observed valid-completion subset: 39 (21 A + 18 B).
- Raw replay evidence is present when the normalized `trace.json` provides start/end timing, requested positive wait, actual `waited_s`, job id, and state for every positive `job_status` call. Zero-wait traces remain valid members of the reliability population.

## Canonical Phase-1 sources

| Source ID | Report | SHA-256 | Step-1.9 match | Trials |
| --- | --- | --- | --- | ---: |
| `phase1-step3` | `benchmarks/chat-mode-scheduling-v2/phase1-step3-read-heavy-ab-2026-09-23.json` | `bfb2a31f79a20ac6a292d1ec095a05d7dd462bdf26d22b1922bc2389cb253190` | yes | 12 |
| `phase1-step4` | `benchmarks/chat-mode-scheduling-v2/phase1-step4-background-barrier-ab-2026-09-23.json` | `835ad53b639ed53a67bb7731e05cf4075b641449da56d7a5ac267f73b7988d11` | yes | 12 |
| `phase1-step5` | `benchmarks/chat-mode-scheduling-v2/phase1-step5-development-journey-ab-2026-09-23.json` | `1e2257a98e3c13d809f32134483a6ccaf1c1bf8fd81048099230e2b8a28f021d` | yes | 6 |
| `phase1-step6` | `benchmarks/chat-mode-scheduling-v2/phase1-step6-recovery-journey-ab-2026-09-23.json` | `c6438ce993dd73e495379beeda3a3dea7cb1331a7c5ad678c00481bfed6b576e` | yes | 6 |
| `phase1-step7` | `benchmarks/chat-mode-scheduling-v2/phase1-step7-multiround-planning-ab-2026-09-23.json` | `8703003bf2bd1c57f098d869e41dd9ed8eaa9bc574cc691af582bd0b6e50909f` | yes | 6 |
| `phase1-step8` | `benchmarks/chat-mode-scheduling-v2/phase1-step8-repeated-dependency-barrier-ab-2026-09-23.json` | `98a3744b0deb5b441e892d34d025bb17d45d9e043ca54805a50afe9524e71a6f` | yes | 6 |

## Canonical submitted trials

### phase1-step3

| Trial ID | Arm | Scenario | Submitted | State/evidence dir | Dir exists | Raw replay evidence | Positive waits | Valid completion |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| `r1-20260923T153114-e4eb49b0eb` | A | R1 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r1-20260923T153114-e4eb49b0eb` | true | true | 0 | true |
| `r1-20260923T153237-67ac207754` | B | R1 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r1-20260923T153237-67ac207754` | true | true | 0 | true |
| `r1-20260923T153409-5cf19620a0` | B | R1 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r1-20260923T153409-5cf19620a0` | true | true | 0 | true |
| `r1-20260923T153537-509df2fe2f` | A | R1 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r1-20260923T153537-509df2fe2f` | true | true | 0 | true |
| `r1-20260923T153652-844d73ddfe` | A | R1 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r1-20260923T153652-844d73ddfe` | true | true | 0 | true |
| `r1-20260923T153816-36c09bb6d7` | B | R1 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r1-20260923T153816-36c09bb6d7` | true | true | 0 | true |
| `r2-20260923T154139-d85ce7fb3f` | B | R2 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r2-20260923T154139-d85ce7fb3f` | true | true | 0 | false |
| `r2-20260923T154756-58d6369649` | A | R2 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r2-20260923T154756-58d6369649` | true | true | 0 | true |
| `r2-20260923T154921-f527640167` | A | R2 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r2-20260923T154921-f527640167` | true | true | 0 | true |
| `r2-20260923T155047-71bebf98f7` | B | R2 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r2-20260923T155047-71bebf98f7` | true | true | 0 | true |
| `r2-20260923T161110-da49a27454` | B | R2 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r2-20260923T161110-da49a27454` | true | true | 0 | true |
| `r2-20260923T161240-35e63b9edb` | A | R2 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r2-20260923T161240-35e63b9edb` | true | true | 0 | true |

### phase1-step4

| Trial ID | Arm | Scenario | Submitted | State/evidence dir | Dir exists | Raw replay evidence | Positive waits | Valid completion |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| `r3-20260923T165558-5f6c0ac6cc` | A | R3 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r3-20260923T165558-5f6c0ac6cc` | true | true | 1 | true |
| `r3-20260923T170014-f2ea2e57b0` | B | R3 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r3-20260923T170014-f2ea2e57b0` | true | true | 1 | true |
| `r3-20260923T170222-993f7b7f2c` | B | R3 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r3-20260923T170222-993f7b7f2c` | true | true | 0 | false |
| `r3-20260923T170514-349ca3f042` | A | R3 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r3-20260923T170514-349ca3f042` | true | true | 1 | true |
| `r3-20260923T170718-83a5983ce3` | A | R3 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r3-20260923T170718-83a5983ce3` | true | true | 0 | false |
| `r3-20260923T171043-867bec433f` | B | R3 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r3-20260923T171043-867bec433f` | true | true | 1 | true |
| `r5-20260923T171218-8b86263319` | B | R5 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r5-20260923T171218-8b86263319` | true | true | 0 | false |
| `r5-20260923T171626-8943400707` | A | R5 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r5-20260923T171626-8943400707` | true | true | 1 | true |
| `r5-20260923T171751-150174d991` | A | R5 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r5-20260923T171751-150174d991` | true | true | 1 | true |
| `r5-20260923T172045-62e44edbe4` | B | R5 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r5-20260923T172045-62e44edbe4` | true | true | 1 | true |
| `r5-20260923T172519-0cee94f978` | B | R5 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r5-20260923T172519-0cee94f978` | true | true | 1 | true |
| `r5-20260923T172700-fab3c30167` | A | R5 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r5-20260923T172700-fab3c30167` | true | true | 0 | false |

### phase1-step5

| Trial ID | Arm | Scenario | Submitted | State/evidence dir | Dir exists | Raw replay evidence | Positive waits | Valid completion |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| `r8-20260923T180224-d0c955df6d` | A | R8 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r8-20260923T180224-d0c955df6d` | true | true | 0 | true |
| `r8-20260923T180409-ca0d0fdb6a` | B | R8 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r8-20260923T180409-ca0d0fdb6a` | true | true | 0 | true |
| `r8-20260923T180545-3b8eec8a30` | B | R8 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r8-20260923T180545-3b8eec8a30` | true | true | 0 | true |
| `r8-20260923T180712-95a7c47b91` | A | R8 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r8-20260923T180712-95a7c47b91` | true | true | 0 | true |
| `r8-20260923T180831-4fec1a5f8c` | A | R8 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r8-20260923T180831-4fec1a5f8c` | true | true | 0 | true |
| `r8-20260923T180940-6f6970131e` | B | R8 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r8-20260923T180940-6f6970131e` | true | true | 0 | true |

### phase1-step6

| Trial ID | Arm | Scenario | Submitted | State/evidence dir | Dir exists | Raw replay evidence | Positive waits | Valid completion |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| `r9-20260923T185522-00caf17c83` | A | R9 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r9-20260923T185522-00caf17c83` | true | true | 0 | true |
| `r9-20260923T185713-9afb825863` | B | R9 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r9-20260923T185713-9afb825863` | true | true | 0 | true |
| `r9-20260923T185918-36fc982452` | B | R9 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r9-20260923T185918-36fc982452` | true | true | 0 | true |
| `r9-20260923T190117-3ca00c3502` | A | R9 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r9-20260923T190117-3ca00c3502` | true | true | 0 | true |
| `r9-20260923T190254-2eadaa06bc` | A | R9 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r9-20260923T190254-2eadaa06bc` | true | true | 0 | true |
| `r9-20260923T190501-97863702d8` | B | R9 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r9-20260923T190501-97863702d8` | true | true | 0 | false |

### phase1-step7

| Trial ID | Arm | Scenario | Submitted | State/evidence dir | Dir exists | Raw replay evidence | Positive waits | Valid completion |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| `r11-20260923T191434-97685ba785` | A | R11 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r11-20260923T191434-97685ba785` | true | true | 0 | true |
| `r11-20260923T191622-5b9eb4d61a` | B | R11 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r11-20260923T191622-5b9eb4d61a` | true | true | 0 | false |
| `r11-20260923T191936-3f54037f48` | B | R11 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r11-20260923T191936-3f54037f48` | true | true | 0 | true |
| `r11-20260923T192137-e0ef7c549e` | A | R11 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r11-20260923T192137-e0ef7c549e` | true | true | 0 | true |
| `r11-20260923T192313-5af845ba2a` | A | R11 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r11-20260923T192313-5af845ba2a` | true | true | 0 | true |
| `r11-20260923T192438-53a7f2844c` | B | R11 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r11-20260923T192438-53a7f2844c` | true | true | 0 | true |

### phase1-step8

| Trial ID | Arm | Scenario | Submitted | State/evidence dir | Dir exists | Raw replay evidence | Positive waits | Valid completion |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| `r7-20260923T202711-94f01d2ec7` | A | R7 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r7-20260923T202711-94f01d2ec7` | true | true | 8 | true |
| `r7-20260923T203224-5ac2484c75` | B | R7 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r7-20260923T203224-5ac2484c75` | true | true | 4 | true |
| `r7-20260923T203622-d51ce307ef` | A | R7 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r7-20260923T203622-d51ce307ef` | true | true | 4 | false |
| `r7-20260923T204617-91387f101b` | B | R7 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r7-20260923T204617-91387f101b` | true | true | 4 | true |
| `r7-20260923T210916-adb0ab6d70` | A | R7 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r7-20260923T210916-adb0ab6d70` | true | true | 4 | true |
| `r7-20260923T211346-942d651555` | B | R7 | true | `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r7-20260923T211346-942d651555` | true | true | 0 | false |

## Operational journal

- Source ID: `operational-journal`.
- Status: available.
- Command format: `journalctl --user -u binnacle-mcp.service -o short-unix`.
- Filter: `job_status_timing`.
- Retained line count: 4073.
- Oldest retained timestamp: `1789777318.789691` (2026-09-19T10:21:58.789691+10:00).
- Newest retained timestamp: `1790263827.324505` (2026-09-25T01:30:27.324505+10:00).
- The journal is a mutable operational source, so Step 3.2 freezes its window bounds and line count rather than asserting an immutable file SHA-256.

## Replay semantics frozen by Step 3.2

- C120/C300/C600 use a per-`(client, base_turn)` cumulative union-wall budget with the 50-second per-call cap preserved.
- Overlapping waits charge union wall once. A historical wait is clipped by the candidate remaining budget, and later positive requests become simulated non-blocking when less than one second remains.
- H10 keeps at most 10 seconds for the first positive wait in a historical turn and converts every later positive wait in that turn to zero seconds.
- A required historical completion is preserved only when the candidate effective interval still contains the observed job-exit point.
- Replay never fabricates waits that were not observed in the historical trace.

## Compact corpus schema — version 1

The empty contract fixture is `benchmarks/chat-mode-scheduling-v2/phase3-replay-corpus.json`. Each future row is one historical base turn.

Turn fields, in canonical order:

- `source_id`
- `source_sha256`
- `trial_id`
- `scenario`
- `arm`
- `base_turn`
- `observed_blocking_wall_s`
- `waits`
- `observed_required_completions`
- `terminal_state`
- `correct`
- `same_prompt`

Each `waits` entry uses these fields, in canonical order:

- `wait_index`
- `node_id`
- `job_id_hash`
- `requested_wait_s`
- `call_start_offset_s`
- `call_end_offset_s`
- `blocking_start_offset_s`
- `blocking_end_offset_s`
- `waited_s`
- `state`
- `job_exit_offset_s`
- `required_completion`
- `observed_completion`

Field rules:

- `source_sha256` is the immutable Phase-1 source-report SHA-256 for benchmark rows; operational rows may omit it because the journal source is mutable.
- `base_turn` is the normalized historical base-turn identifier; all timing offsets are seconds from the first observed tool-call start for that base turn.
- `blocking_start_offset_s` and `blocking_end_offset_s` may be null only when the positive request produced no physical blocking interval; `waited_s` remains the authoritative observed wait duration.
- `job_id_hash` is the SHA-256 hex digest of the historical job id; raw job ids are not required in the repository corpus.
- `terminal_state`, `correct`, and `same_prompt` preserve the final historical terminal/correctness/same-prompt state without storing conversation prose.
- The corpus contains no user or assistant conversation prose. Only replay timings, source hashes, scenario/arm identifiers, states, hashed job ids, and completion markers are permitted.

## Replay output field names — per historical turn

The replay engine uses these exact compact field names for the Section 14.5 per-turn result contract:

- `source_id`
- `trial_id`
- `scenario`
- `arm`
- `base_turn`
- `observed_blocking_wall_s`
- `candidate_blocking_wall_s`
- `burden_reduction_pct`
- `candidate_exhaustion_offset_s`
- `positive_waits_observed`
- `waits_clipped`
- `waits_nonblocking`
- `observed_required_completions`
- `required_completions_preserved`
- `completion_at_risk`
- `historical_terminal_state`
- `historical_correct`
- `historical_same_prompt`
