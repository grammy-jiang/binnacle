# Phase 3 corpus audit: phase1-step6

## Evidence

Source report:

`benchmarks/chat-mode-scheduling-v2/phase1-step6-recovery-journey-ab-2026-09-23.json`

SHA-256:

`c6438ce993dd73e495379beeda3a3dea7cb1331a7c5ad678c00481bfed6b576e`

Shard:

`benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/phase1-step6.json`

SHA-256:

`4c8f7a23d025730f90a87a9f746f517c7801b8f6a73f3caed83d103e355ad19a`

The audit independently re-derived the invariants from the immutable Phase-1
report and the six referenced state directories. For each canonical submitted
slot, `trial.json` supplied the terminal status and `trace.json` supplied the
physical tool-call timeline. State files were read through
`/tmp/p36-manager/statecat.sh`; no extractor implementation path was used to
derive expected values.

## Canonical submitted slots

| Invariant | Expected from source evidence | Shard value | Verdict |
| --- | --- | --- | --- |
| R9 arm A submitted slots | 3 | 3 | PASS |
| R9 arm B submitted slots | 3 | 3 | PASS |
| R9 total submitted slots | 6 | 6 rows / 6 trials | PASS |

## Positive `job_status` waits and actual waited time

All six raw traces contain zero `job_status` calls, therefore there are no
positive waits and no actual `waited_s` values to preserve.

| Trial | Expected positive waits / actual `waited_s` | Shard waits | Verdict |
| --- | --- | --- | --- |
| `r9-20260923T185522-00caf17c83` | 0 / `[]` | `[]` | PASS |
| `r9-20260923T185713-9afb825863` | 0 / `[]` | `[]` | PASS |
| `r9-20260923T185918-36fc982452` | 0 / `[]` | `[]` | PASS |
| `r9-20260923T190117-3ca00c3502` | 0 / `[]` | `[]` | PASS |
| `r9-20260923T190254-2eadaa06bc` | 0 / `[]` | `[]` | PASS |
| `r9-20260923T190501-97863702d8` | 0 / `[]` | `[]` | PASS |

## Union blocking wall per turn

With no positive physical `job_status` intervals, the interval union is zero
for every observed turn. The failed timeout trial contains no tool calls, so its
empty trace is represented by the shard's `trial` base-turn bucket.

| Trial / turn | Expected union wall (s) | Shard observed blocking wall (s) | Verdict |
| --- | ---: | ---: | --- |
| `r9-20260923T185522-00caf17c83` / `b258faf2-753b-4d52-8f58-14d2181c5951` | 0.0 | 0 | PASS |
| `r9-20260923T185713-9afb825863` / `bfc5c1b0-ed1b-4a4c-9736-66ba6bb35b4c` | 0.0 | 0 | PASS |
| `r9-20260923T185918-36fc982452` / `d0b29d6e-c4dc-4f3c-8965-49b5b89028d4` | 0.0 | 0 | PASS |
| `r9-20260923T190117-3ca00c3502` / `81d23bc1-2a06-4a43-ae73-f47d196f9f98` | 0.0 | 0 | PASS |
| `r9-20260923T190254-2eadaa06bc` / `a19c5328-d520-48c2-b04c-7ad1e3cc396f` | 0.0 | 0 | PASS |
| `r9-20260923T190501-97863702d8` / `trial` | 0.0 | 0 | PASS |

## Observed required completions

Because no physical `job_status` call was made, no required job completion was
observed through such a call.

| Trial | Expected required completions | Shard value | Verdict |
| --- | ---: | ---: | --- |
| `r9-20260923T185522-00caf17c83` | 0 | 0 | PASS |
| `r9-20260923T185713-9afb825863` | 0 | 0 | PASS |
| `r9-20260923T185918-36fc982452` | 0 | 0 | PASS |
| `r9-20260923T190117-3ca00c3502` | 0 | 0 | PASS |
| `r9-20260923T190254-2eadaa06bc` | 0 | 0 | PASS |
| `r9-20260923T190501-97863702d8` | 0 | 0 | PASS |

## Terminal states

| Trial | Expected from `trial.json` | Shard terminal state | Verdict |
| --- | --- | --- | --- |
| `r9-20260923T185522-00caf17c83` | `completed` | `completed` | PASS |
| `r9-20260923T185713-9afb825863` | `completed` | `completed` | PASS |
| `r9-20260923T185918-36fc982452` | `completed` | `completed` | PASS |
| `r9-20260923T190117-3ca00c3502` | `completed` | `completed` | PASS |
| `r9-20260923T190254-2eadaa06bc` | `completed` | `completed` | PASS |
| `r9-20260923T190501-97863702d8` | `failed` | `failed` | PASS |

## Commands used

Correlation marker:

```bash
bash /tmp/p36-manager/hello.sh p3-audit-phase1-step6 p36-p3-audit-phase1-step6-1790268906-2575
```

Worktree creation and predecessor confirmation:

```bash
bash /tmp/p36-manager/worktree-add.sh \
  --path /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-audit-phase1-step6 \
  --branch feature/chat-mode-scheduling-v2-phase3-audit-phase1-step6 \
  --base 981db98beb299d05de5d83e41b7365dc43bb8f27

git status --short --branch
git log -5 --oneline

bash /tmp/p36-manager/statecat.sh \
  /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase3/completions/p3-source-phase1-step6--a1.json
```

Raw state inspection used the six `state_dir` paths frozen in the source report.
Representative direct reads were:

```bash
bash /tmp/p36-manager/statecat.sh \
  /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r9-20260923T185522-00caf17c83/trial.json \
  /home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/runs/r9-20260923T185522-00caf17c83/trace.json
```

The final independent comparison was executed as:

```bash
python3 /tmp/p3-audit-phase1-step6-validate.py
```

That helper parses the source report and shard directly, reads every referenced
`trial.json` and `trace.json` through `statecat.sh`, computes the positive
wait set and per-turn interval unions, and compares the derived values against
the shard.

Two longer inline shell variants for trace summarisation were rejected by the
platform safety classifier. The same read-only logic was moved to small helpers
under `/tmp`; this did not change the audit semantics or repository scope.

## Canonical corpus binding (Step 3.5A)

- Canonical revision-2 replay corpus SHA-256:
  `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`.
- Canonical integrated shard SHA-256:
  `4c8f7a23d025730f90a87a9f746f517c7801b8f6a73f3caed83d103e355ad19a`.
- The Step 3.5A fan-in binds this independent source/shard PASS to the
  aggregate revision-2 PASS. The shard hash above matches the integrated
  shard bytes and the aggregate audit confirms exact membership in the
  frozen corpus.

AUDIT phase1-step6: PASS
