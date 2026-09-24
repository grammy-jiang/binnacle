# Chat mode scheduling v2 — Phase 3 progress

Status: IN PROGRESS

Updated: 2026-09-25T06:07:39+10:00

## Canonical state

- Branch: feature/chat-mode-scheduling-v2-phase3
- Worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3
- Audited source HEAD: 5f2be143352aaa63fb680c1c79e289d46be201fe
- Last completed step: 3.8
- Next step: 3.9 full Phase-3 validation; Phase-4 live calibration remains blocked by NO_LIVE_CANDIDATE
- Dependency audit: phase3-dependency-audit-2026-09-25-r01.json, r01, SHA-256 d3bec25ba8d49ed4db78e07930542b9e963608ad264c198f8fbf04c4ccfa473a
- Task graph: phase3-task-graph.json, r01, SHA-256 44cbedb0524fe87a9d111579a96d0d33f4171dfee6ece34eb53baa4c506696b2
- Initial orchestrator-state checkpoint SHA-256: cec108b23fcf319a48d699f123b8fbf713919f3873d1cae4968a16844b80ed12
- Validated synchronized baseline HEAD: 806a23053043be46f6ba35ad046833168caa904d
- Frozen replay path HEAD: 9c768800f1e97f9e06d18bd32b173e24d93e82f0
- Frozen scenario path HEAD: 7107f142ae6746e17180ae92b4d4be0e6e3957d2
- Frozen corpus path HEAD (revision 1 lineage): 3e498a33294708c7fe1996b49e78752d8720523d
- Frozen corpus path HEAD revision 2: 19d5951b9617936c655664a992dc0c419051c4f7
- Replay corpus revision: 2
- Frozen replay corpus SHA-256: 4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d
- Superseded replay corpus revision 1 SHA-256: c2c2809abde13c7b697e3a8c3e91a547fe68bbd83fdbd816c611b3f0e94808de
- Replay corpus report SHA-256: f6e46b89b60bb89c918ab4c5d9ab11d0dea5da2b27bf3794c96f1e34ebc440bd
- Corpus audit status: PASS
- Audited corpus SHA-256: 4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d
- Frozen corpus audit HEAD: 207000caa3727f37f494675f34934fd61fc6cdd5
- Frozen replay promotion HEAD: 2382ae0dca4fee931d9af33c049e9dad97514e64
- Frozen candidate shortlist HEAD: 06c86f8db508be2d311ccd27f5aaffe2740597a3
- Candidate shortlist JSON SHA-256: 51db08d70ad8ebfcc46de9e53c661b517b9f3ed41b10579d49057aa395f8d11d
- Candidate shortlist Markdown SHA-256: bd4a258152e66277e663af2a5d7e6fbac0daa2592cfe51d2d3caf1bb644a9c85
- Phase-3 offline verdict: NO_LIVE_CANDIDATE
- Live candidates: none
- Preferred live candidate: none
- Phase-4 input contract: benchmarks/chat-mode-scheduling-v2/phase4-input-contract.json
- Phase-4 input contract SHA-256: bc2fc07ab945504b3acc726c1779d2b46533f43472535f803f2f17b986321024
- Scenario catalog SHA-256: 45002efd15fe7aa07fa5933180752c6537bea6584520f41a4e1d6b6de61ab5fd
- Provenance classifier commit: 2b5e83c4f8015f3077794dabb9e864a3c4d806b6
- Canonical v2 instruction SHA-256: b7df6953a3c64bd245b3d5ff13b6f2667e940d5a154e650fec0b10e6a22cf094
- Required logical arms: A/B/C/H
- Production baseline re-observed: 2026-09-25T01:10:16+10:00

## Deviation

- public_base_freshness: DEVIATION — public master and proof-of-concept advanced to 821cd3addc787a3ec6c6764ebc2327a67de72dd0 during preflight. The epoch-1 orchestrator deferred the lower-stack restack pending owner ratification; catch-up is scheduled for Step 4.0 or earlier at the owner's request. This does not block Phase 3 under the binding task-manager decision.

## Step status

| Step | Status |
| --- | --- |
| 3.0 | complete |
| 3.1 | complete |
| 3.2 | complete |
| 3.3A | complete |
| 3.3B | complete |
| 3.3C | complete |
| 3.3D | complete |
| 3.4A | complete |
| 3.4B | complete |
| 3.4C | complete |
| 3.5M | complete |
| p3-source-phase1-step3 | complete |
| p3-source-phase1-step4 | complete |
| p3-source-phase1-step5 | complete |
| p3-source-phase1-step6 | complete |
| p3-source-phase1-step7 | complete |
| p3-source-phase1-step8 | complete |
| p3-source-operational-journal | complete |
| p3-fix-opjournal-extractor | complete |
| p3-source-operational-journal-r2 | complete |
| p3-audit-phase1-step3 | complete |
| p3-audit-phase1-step4 | complete |
| p3-audit-phase1-step5 | complete |
| p3-audit-phase1-step6 | complete |
| p3-audit-phase1-step7 | complete |
| p3-audit-phase1-step8 | complete |
| p3-audit-operational-journal-r2 | complete |
| p3-audit-aggregate | complete |
| 3.5A | complete |
| 3.6A | complete |
| 3.6B | complete |
| 3.6C | complete |
| 3H | complete |
| 3.7 | complete |
| 3.8 | complete |
| 3.9 | not_started |
| 3.10 | not_started |

## Step 3.0 notes

- All nine mandatory dependency-audit rows PASS.
- Public-base freshness is a documented non-blocking DEVIATION; no lower-stack branch or worktree was changed.
- Bootstrap summary SHA-256: 6bc13077758824ea72f5ba723f7ed095842debfc7a50eb67abdd5908f4ca7cfd.
- Phase-3 workspace was created from Phase-2 HEAD 5f2be143352aaa63fb680c1c79e289d46be201fe.
- Six planning-only commits were replayed in order; Phase-3 execution-plan bytes match the planning worktree.
- Graph validation: PASS 9/9.
- Initial scheduler state: 3.0 complete, 3.1 ready, 18 other static tasks blocked on predecessors.

## Step 3.0 validation

- Ad-hoc phase3-task-graph.json validator: PASS 9/9.
- JSON syntax checks for task graph and dependency audit: PASS.
- File-scoped pre-commit on all Step-3.0 Git outputs: PASS.

## Step 3.1 notes

- Validated the canonical Phase-3 worktree at pre-step HEAD
  806a23053043be46f6ba35ad046833168caa904d.
- Audited Phase-2/test-efficiency HEAD
  5f2be143352aaa63fb680c1c79e289d46be201fe and all six replayed planning
  commits are ancestors of the synchronized baseline.
- The Phase-3 execution-plan SHA-256 remains
  84e6567197d364323b87f64874e81c92efcc611764f10225be1bed64db73a453
  and matches the planning-worktree copy byte-for-byte.
- Final test-efficiency Step 3.7 remains PASS; the frozen test-efficiency
  progress, testing documentation, repository default budget definition, and
  host-safety guard hashes match Step 3.0 audit evidence.
- The current 1162-passed/3-skipped aggregate is not post-audit drift. The
  historical pre-rebase Step-3.7 source f706136 had a different tests tree;
  audited source 5f2be143 and this validated baseline have identical tests-tree
  and runner blobs.
- The focused matrix defines no separate Step-3.1 pytest target; the optimized
  full-suite smoke is the Step-3.1 gate.
- Production was re-observed after the smoke and remained unchanged.

## Step 3.1 validation

- uv run python scripts/run_test_suite.py --workers 4 --seed 12345: PASS.
- Parallel-safe lane: 1160 passed, 3 skipped.
- Ordinary-process no_xdist lane: 2 passed, 1163 deselected.
- Aggregate: 1162 passed, 0 failed, 3 skipped.
- Runner elapsed: 42.87 s; wrapper wall: 42.94 s; resolved workers: 4.
- Pre-run host snapshot: 4 cores; load average 0.40 0.63 0.52.
- Production isolation check after the smoke: PASS at
  2026-09-25T01:10:16+10:00.

## Step 3.2 notes

- All six mandatory Phase-1 macro report SHA-256 values match the Step-1.9
  aggregate authority.
- Canonical submitted population is frozen at 48 slots = 24 A + 24 B; no
  submitted failure was dropped.
- All 48 canonical state/evidence directories exist and all 48 normalized
  traces retain the raw timing/state fields required for replay. The corpus
  contains 32 positive `job_status` calls across 13 trials.
- Observed valid-completion subset: 39 trials = 21 A + 18 B.
- Operational source `operational-journal` is available with 4073 retained
  `job_status_timing` lines from short-unix 1789777318.789691 through
  1790263827.324505.
- `phase3-source-inventory.json` SHA-256: `1a147dd0d1632c567d91a4e35e83085ecca062a9f0bcab251b8ccd7a2a62bc9f`.
- `phase3-source-inventory.md` SHA-256: `4a8046cdd0227c81ba5a50412377027e239a291f80f95b0b40783bf32bbd6191`.
- Empty/header `phase3-replay-corpus.json` contract SHA-256: `54841770dc38fb50160562278beb52770a25c88ab46df7f0a9466201933fe1c7`.
- Replay schema version 1 freezes 12 turn fields, 13 wait fields, exact
  Section-14.5 output names, C120/C300/C600 cumulative-union semantics, H10,
  completion preservation, hashed job ids, and the no-conversation-prose rule.

## Step 3.2 validation

- Integrity validator: PASS — 6 canonical source reports; 48 trials = 24 A +
  24 B; 48/48 raw replay evidence present; 32 positive waits; 39 valid
  completions; operational journal available; fixture has zero rows.
- JSON syntax checks for source inventory and replay-corpus fixture: PASS.
- Focused test matrix: no dedicated Step-3.2 pytest target.
- File-scoped pre-commit on all Step-3.2 Git outputs: PASS.

## Step 3.3A notes

- Corpus-extractor worker completion packet 3.3A--a1 matches the assignment
  evidence for commit 5bf38be3c6570bf9a89bc6f8dc0130c18b1ac6b9 on
  feature/chat-mode-scheduling-v2-phase3-corpus.
- Integrated worker output hashes match the completion packet:
  scripts/chat_scheduling_replay_corpus.py
  98fe885409bc2a23aa0e7f5ff731e53fe5696795c920d3dce605d0901db5d6a4
  and tests/scripts/test_chat_scheduling_replay_corpus.py
  0d888d5204c74023d913afedcf563c2721a429a15a2eecd8beb247477acf7129.

## Step 3.3A validation

- uv run pytest -q tests/scripts/test_chat_scheduling_replay_corpus.py: PASS
  in the worker worktree, 11 passed in 0.31s.

## Step 3.3B notes

- Replay-engine worker completion packet 3.3B--a1 matches the assignment
  evidence for commit 9c768800f1e97f9e06d18bd32b173e24d93e82f0 on
  feature/chat-mode-scheduling-v2-phase3-replay.
- Integrated worker output hashes match the completion packet:
  scripts/chat_scheduling_replay.py
  c741cc6dbba5812e15acfce4e6a33033bbc1157b126ec386d9918dd8dcdf5443
  and tests/scripts/test_chat_scheduling_replay.py
  9227c7590383c18f71473dd15f50dd95359cecee7b8c7a7c7e602e027781dc39.

## Step 3.3B validation

- uv run pytest -q tests/scripts/test_chat_scheduling_replay.py: PASS in
  the worker worktree, 10 passed in 0.34s.

## Step 3.3C notes

- Scenario/oracle worker completion packet 3.3C--a1 matches the assignment
  evidence for commit 80dc8362a8b27d00dd64ff73e0acc3a725505b35 on
  feature/chat-mode-scheduling-v2-phase3-scenarios.
- All eight worker output SHA-256 values match the canonical integrated files
  after cherry-pick.

## Step 3.3C validation

- uv run pytest -q tests/scripts/test_chat_scheduling_manifest.py
  tests/scripts/test_chat_scheduling_oracle.py: PASS in the worker worktree,
  26 passed in 1.65s.

## Step 3.3D notes

- Provenance/evidence worker completion packet 3.3D--a1 matches the assignment
  evidence for commit dc7249e91883e55ce862fbfdbd4fb40945cd4fe3 on
  feature/chat-mode-scheduling-v2-phase3-provenance.
- All three worker output SHA-256 values match the canonical integrated files
  after cherry-pick.

## Step 3.3D validation

- uv run pytest -q tests/scripts/test_chat_scheduling_provenance.py
  tests/scripts/test_chat_scheduling_analyzer.py
  tests/scripts/test_chat_scheduling_evidence.py: PASS in the worker worktree,
  25 passed in 1.42s.

## Step 3.4A notes

- Integrated 3.3A then 3.3D by deterministic cherry-pick because both worker
  commits were based at f01dc93c3aa015d8932f58c9c5233cdb1cb3f361 while
  canonical HEAD had already advanced through Steps 3.4B and 3.4C.
- Cherry-pick mapping:
  5bf38be3c6570bf9a89bc6f8dc0130c18b1ac6b9 to
  f7cdff80326d80a33e925094b64783bd0be4a669, then
  dc7249e91883e55ce862fbfdbd4fb40945cd4fe3 to
  2b5e83c4f8015f3077794dabb9e864a3c4d806b6.
- All five integrated worker output SHA-256 values match the verified
  completion packets.
- Frozen phase3-source-inventory.json SHA-256 reverified as
  1a147dd0d1632c567d91a4e35e83085ecca062a9f0bcab251b8ccd7a2a62bc9f;
  the inventory includes operational-journal with status available.
- Frozen phase3_corpus_path_head at 3e498a33294708c7fe1996b49e78752d8720523d, the HEAD produced by the
  Step-3.4A completion progress commit.
- No semantic deviation from the Step-3.4A runbook or focused test matrix.

## Step 3.4A validation

- uv run pytest -q tests/scripts/test_chat_scheduling_replay_corpus.py
  tests/scripts/test_chat_scheduling_provenance.py
  tests/scripts/test_chat_scheduling_analyzer.py
  tests/scripts/test_chat_scheduling_harness.py: PASS, 54 passed in 1.73s;
  run-command runtime 2.713s.
- Pre-run host snapshot: 4 cores; load average 0.32 0.50 0.61.
- Timing was measured under foreign parallel-programme load.

## Step 3.4B notes

- Integrated the replay-engine worker by strict fast-forward from f01dc93c3aa015d8932f58c9c5233cdb1cb3f361
  to 9c768800f1e97f9e06d18bd32b173e24d93e82f0; the worker commit parent exactly matched the
  pre-integration canonical HEAD.
- Frozen phase3_replay_path_head at 9c768800f1e97f9e06d18bd32b173e24d93e82f0.
- Source-shard worktrees were not touched or restarted; their immutable inputs
  remain valid as required by Step 3.4B.
- No semantic deviation from the Step-3.4B runbook or focused test matrix.

## Step 3.4B validation

- uv run pytest -q tests/scripts/test_chat_scheduling_replay.py: PASS,
  10 passed in 0.44s; real 1.16s.
- Pre-run host snapshot: 4 cores; load average 0.92 1.01 0.86.
- Timing was measured under foreign parallel-programme load.

## Step 3.4C notes

- Integrated 3.3C by deterministic cherry-pick because the worker branch was
  based at f01dc93c3aa015d8932f58c9c5233cdb1cb3f361 while canonical HEAD had
  already advanced through Step 3.4B.
- Cherry-pick mapping:
  51cdf6d36dec2eb737d356cb802f2311428b7b8a to
  e0f34f7790e6b588b9303f965e3eb6e242f8e6eb, then
  80dc8362a8b27d00dd64ff73e0acc3a725505b35 to
  7107f142ae6746e17180ae92b4d4be0e6e3957d2.
- Frozen phase3_scenario_path_head at
  7107f142ae6746e17180ae92b4d4be0e6e3957d2.
- All eight integrated output SHA-256 values match the 3.3C completion packet.
- No semantic deviation from the Step-3.4C runbook or focused test matrix.

## Step 3.4C validation

- uv run pytest -q tests/scripts/test_chat_scheduling_manifest.py
  tests/scripts/test_chat_scheduling_oracle.py: PASS, 26 passed in 1.96s;
  real 2.99s.
- Pre-run host snapshot: 4 cores; load average 1.37 0.82 0.74.
- Timing was measured under foreign parallel-programme load.

## Step 3.5M revision 2 notes

- Revision 1 corpus `c2c2809abde13c7b697e3a8c3e91a547fe68bbd83fdbd816c611b3f0e94808de` is retained as superseded history after its
  operational-journal audit exposed the extractor/window-count defect.
- Integrated the verified extractor fix `c7b0b8bf1c308812d3b391c556b8a302d5b8c125` as canonical
  `13879b7`, then revision-2 operational-journal shard `5d240da6dd35baa438f2775551e65a4eee329a42`
  as canonical `e86a0e3`.
- Frozen revision-2 corpus path HEAD: `19d5951b9617936c655664a992dc0c419051c4f7`.
- Operational journal is now available across the frozen
  1789777318.789691..1790263827.324505 window: 4,073 token-filtered lines,
  4,045 parsed timing records, 2,968 replayable waits, and 278 rows. The 28
  token-bearing non-timing/wrapped records are not an expiration gap.
- Revision-2 operational source SHA-256:
  `c1a18c4095de00cd68833fb66dabc9db6fbfc2a1122ab6019095f15acd8a1948`;
  shard SHA-256: `40186dbf2adde0936a47d0a270c802f71fad5adf8dca9c8a3d9c039590b97cff`.
- Deterministic merge produced 326 rows: the canonical submitted population
  remains 48 = 24 A + 24 B, plus 278 operational-history rows. All 10 submitted
  Phase-1 failures remain present.
- All 32 Phase-1 positive waits match raw `result.waited_s`. All 2,968
  operational waits carry actual `waited_s`; 2,135 differ from requested wait.
- Independent union checks match all 48 Phase-1 metrics. Fourteen operational
  rows contain overlapping wait intervals, and all 14 reproduce the stored union
  metric with zero mismatches.
- Revision-2 replay corpus SHA-256: `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`.
- Revision-2 replay corpus report SHA-256: `f6e46b89b60bb89c918ab4c5d9ab11d0dea5da2b27bf3794c96f1e34ebc440bd`.
- Provisional replay outputs against revision 1 remain historical diagnostics
  and must be rerun against revision 2 under the promotion/invalidation contract.
- No production checkout, service, or configuration was modified.

## Step 3.5M revision 2 validation

- Frozen merge CLI executed twice into the canonical JSON/Markdown paths: PASS;
  both outputs were byte-identical across runs.
- Corpus invariant validator: PASS; 326 total rows, 48 canonical Phase-1 rows,
  278 operational rows, 24 A + 24 B, 10 failures retained, 32 Phase-1 actual-wait
  comparisons, 48 Phase-1 union checks, 2,968 operational actual waits, and 14
  overlapping operational-union checks all matched.
- `uv run pytest -q tests/scripts/test_chat_scheduling_replay_corpus.py`: PASS,
  12 passed in 0.27s; run-command runtime 0.815s.
- Pre-run host snapshot for pytest: 4 cores; load average 0.70 0.68 0.57.
- Timing was measured under foreign parallel-programme load.

## Step 3.5M revision 1 notes (superseded)

- Every source worker completion packet was re-read through `statecat.sh`; all
  seven workers were based at frozen `phase3_corpus_path_head`
  `3e498a33294708c7fe1996b49e78752d8720523d`, and all shard hashes match the
  worker packets.
- Source shards were cherry-picked in deterministic source-id order:
  `phase1-step3`, `phase1-step4`, `phase1-step5`, `phase1-step6`,
  `phase1-step7`, `phase1-step8`, then `operational-journal`.
- Already-verified per-source audits for `phase1-step3`, `phase1-step4`,
  `phase1-step5`, and `phase1-step7` were also integrated. The remaining
  per-source audits continue independently under Step 3.5A.
- Frozen replay corpus SHA-256:
  `c2c2809abde13c7b697e3a8c3e91a547fe68bbd83fdbd816c611b3f0e94808de`.
- Frozen replay corpus report SHA-256:
  `b45934afec305a6575fa67e70fbc19407b7e0cfaf0fbab756b53d9571cd13888`.
- Canonical submitted population is 48 = 24 A + 24 B in the Phase-1 reports,
  frozen inventory, and merged corpus. Raw terminal states are 38 completed and
  10 failed; all 10 submitted failures are preserved.
- All 32 positive-request wait records match raw `result.waited_s`, with zero
  mismatches. Two have zero observed duration and 22 differ from the requested
  duration.
- The raw-trace union calculation reproduces all 48 Phase-1
  `blocking_wall_s` metrics and all 13 positive-wait turn unions with zero
  mismatches. The canonical population contains no overlapping positive-wait
  intervals, so no real overlapping canonical trace sample exists beyond the
  same union calculation.
- The operational journal retention limitation is explicit: frozen window
  2026-09-19T10:21:58.789691+10:00 through
  2026-09-25T01:30:27.324505+10:00 expected 4,073
  `job_status_timing` lines, but 4,045 remained at extraction. The explicit
  unavailable shard records
  `frozen_window_line_count_mismatch_4073_4045`; no rows were synthesized.
- No production configuration, service, or production checkout was modified.

## Step 3.5M revision 1 validation

- Frozen merge CLI executed twice: PASS; JSON and Markdown were byte-identical.
- Independent corpus invariant validator: PASS; 48 trials, 24 A + 24 B,
  10 submitted failures retained, 32 actual-wait comparisons, 48 report-union
  comparisons, and 13 positive-wait turn-union comparisons all matched.
- `uv run pytest -q tests/scripts/test_chat_scheduling_replay_corpus.py`: PASS,
  11 passed in 0.23s; run-command runtime 0.816s.
- Pre-run host snapshot for pytest: 4 cores; load average 2.88 2.10 1.41.
- Timing was measured under foreign parallel-programme load.

## Source-shard worker notes

- `p3-source-phase1-step3`: worker `228dfba924eba6d9b73729a02dd21cb2e452b9e8` on
  `feature/chat-mode-scheduling-v2-phase3-source-phase1-step3` integrated as canonical cherry-pick `f285261`; shard SHA-256 `6c1a6bf8df81bd3a68e697d3cfae9927fba4fec3c569ce27b71eefe134aed118`.
- `p3-source-phase1-step4`: worker `31b554833d40c5704627a5e0c6afcdeb2d20d20c` on
  `feature/chat-mode-scheduling-v2-phase3-source-phase1-step4` integrated as canonical cherry-pick `4e1f1ff`; shard SHA-256 `332a8a6c449d48b617a752f9a1a8244497eddd1853ea59c9fe7586fa984ec9e1`.
- `p3-source-phase1-step5`: worker `7f6b7a82d6562bc395e4cf5e443d572f8ae582bd` on
  `feature/chat-mode-scheduling-v2-phase3-source-phase1-step5` integrated as canonical cherry-pick `f080a2e`; shard SHA-256 `f2f3b655d809efef8b0d059c6cb07c809b18bfd4b16034cf226a67403ee12685`.
- `p3-source-phase1-step6`: worker `981db98beb299d05de5d83e41b7365dc43bb8f27` on
  `feature/chat-mode-scheduling-v2-phase3-source-phase1-step6` integrated as canonical cherry-pick `d528fbd`; shard SHA-256 `4c8f7a23d025730f90a87a9f746f517c7801b8f6a73f3caed83d103e355ad19a`.
- `p3-source-phase1-step7`: worker `2167fb1c18c99c85dec08633d75bacabafba6177` on
  `feature/chat-mode-scheduling-v2-phase3-source-phase1-step7` integrated as canonical cherry-pick `4c80548`; shard SHA-256 `98fbab4cc39735db0e2fa9b1079c5a7a74841e53748edcaff7da4501e338fed3`.
- `p3-source-phase1-step8`: worker `d2c89b8f858565731ca77696ff3fce490c320d37` on
  `feature/chat-mode-scheduling-v2-phase3-source-phase1-step8` integrated as canonical cherry-pick `53f2855`; shard SHA-256 `be0b57741415bccd2676e1dc7914beaf50b1a887983819cda22c5698f933ff40`.
- `p3-source-operational-journal`: worker `809b7156de2112477deeb873507a89afd35585a2` on
  `feature/chat-mode-scheduling-v2-phase3-source-operational-journal` integrated as canonical cherry-pick `5a6a5a2`; shard SHA-256 `f1124faced67d51e9ea30311f9dea25e17bd2f82d2c2e0a3cdbb4842de080bbe`.

## Revision 2 worker notes

- `p3-fix-opjournal-extractor`: worker `c7b0b8bf1c308812d3b391c556b8a302d5b8c125` on
  `feature/chat-mode-scheduling-v2-phase3-fix-opjournal`, integrated as
  canonical `13879b7`; extractor SHA-256
  `b46ea65a8c24e20ede17e6bf4d9f2598e94fc23b7cb1cc0db7b5b6493fe827af`.
- `p3-source-operational-journal-r2`: worker `5d240da6dd35baa438f2775551e65a4eee329a42` on
  `feature/chat-mode-scheduling-v2-phase3-source-operational-journal-r2`,
  integrated as canonical `e86a0e3`; shard SHA-256
  `40186dbf2adde0936a47d0a270c802f71fad5adf8dca9c8a3d9c039590b97cff`.

## Step 3.5A notes

- Step 3.5A is PASS against revision-2 corpus
  `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`.
- Required per-source audits PASS for `phase1-step3`, `phase1-step4`,
  `phase1-step5`, `phase1-step6`, `phase1-step7`,
  `phase1-step8`, and available `operational-journal`; the aggregate
  audit also PASSes against the same corpus SHA.
- The four audits already integrated before revision 2 were reverified
  byte-for-byte. Newly integrated worker-to-canonical mappings are:
  `a3467546d` to `5e1a97f`, `45345c838` to
  `94304fa`, `9b8de4aa7` to `d6615fd`, and
  `af218f658` to `0ad10fb`.
- Per-source audits began before the merged corpus existed. The canonical fan-in
  therefore adds Step-3.5A binding annotations with the revision-2 corpus SHA
  while preserving the independent source/shard audit conclusions.
- Frozen corpus-audit evidence HEAD:
  `207000caa3727f37f494675f34934fd61fc6cdd5`.
- The operational-journal note now records revision 2: 4,073 token-filtered
  lines, 4,045 extractor parser records, 4,043 independently correlated true
  timing events, 2,968 positive waits, and 278 rows.
- Revision-1 operational-journal audit
  `5518a09b30fd21356f7659f63f1318b39d769431` is retained as historical
  FAIL evidence in `corpus_revisions[]`; it is not cherry-picked or counted
  as the required audit. Its extractor defect was fixed in
  `c7b0b8bf1c308812d3b391c556b8a302d5b8c125`.
- No revision-2 corpus defect remains. Step 3.7 remains gated on all required C
  candidate reports referencing this audited corpus SHA.

## Step 3.5A validation

- Audit binding validator: PASS, 7/7 per-source audits plus aggregate.
- Aggregate consistency audit: PASS, 96/96 checks; 326 unique rows and 3,000
  waits; canonical Phase-1 population remains 48 = 24 A + 24 B.
- Deterministic aggregate merge evidence: PASS, 2/2 fresh JSON and Markdown
  outputs byte-identical to the frozen corpus/report.
- Focused test matrix defines no dedicated Step-3.5A pytest target.
- File-scoped pre-commit on normalized audit evidence and the revision-2
  operational-journal note: PASS.

## Step 3.6A/B/C and 3H integration notes

- C120 worker 859da76a0b2741c7483430383dbf3436381af641 integrated as
  canonical 9b06d99; C300 worker
  6e6018399cf36b23d06b20decd5a2c9ab0b1e19c integrated as
  canonical b7f59e3; C600 worker
  c13669d3bc46199feed05815d7bad707bb893d7c integrated as
  canonical 1ca62ea.
- H10 worker 09a9096256a0db1be29776be375ca2f9f630bdd4 was independently
  verified from its completion packet, integrated as canonical 1d2c26d, and
  promoted for Step 3.10 consumption.
- All four reports reference audited revision-2 corpus 4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d.
- Promotion changed only audit metadata to audit_status=pass and
  provisional=false; the deterministic replay rows were not rerun or changed.
- H10 remains historical-comparator evidence only and is excluded from the
  C-candidate shortlist.

## Step 3.7 notes

- Attempt a2 corrects the gate-population error found after repository
  verification; thresholds and gate definitions are unchanged.
- Superseded shortlist JSON SHA-256: 23edc0fbba3210aae5da205122be51a806b7be54ab5ca5c590d98de6c931b975.
- Corrected shortlist JSON SHA-256: 51db08d70ad8ebfcc46de9e53c661b517b9f3ed41b10579d49057aa395f8d11d.
- Superseded shortlist Markdown SHA-256: cfaf76ecaa4d8ac462e916b2ccf4de9c8f3666f68532a0594a3e0e2878fb941e.
- Corrected shortlist Markdown SHA-256: bd4a258152e66277e663af2a5d7e6fbac0daa2592cfe51d2d3caf1bb644a9c85.
- Gates 1, 2, 3 and 5 now use canonical Phase-1 evidence. Gate 4 uses the
  available 278-row operational-journal population, with canonical fallback
  only when operational history is unavailable.
- C120 before/after: gate 1 88.888889% -> 88.888889%; gate 2 47.766323% ->
  15.384615%; gate 3 0 -> 0 early exhaustions; gate 4 75.123692% ->
  75.772057%; gate 5 0 -> 0 missing-evidence records.
- C300 before/after: gate 1 100.0% -> 100.0%; gate 2 29.209622% -> 0.0%;
  gate 3 0 -> 0 early exhaustions; gate 4 52.467818% -> 52.927366%;
  gate 5 0 -> 0 missing-evidence records.
- C600 before/after: gate 1 100.0% -> 100.0%; gate 2 17.869416% -> 0.0%;
  gate 3 0 -> 0 early exhaustions; gate 4 29.565116% -> 29.824066%;
  gate 5 0 -> 0 missing-evidence records.
- Corrected gate-2 canonical denominators are 13 positive-wait turns for each
  candidate: C120 exhausts 2/13, C300 0/13 and C600 0/13.
- Operational exhaustion is diagnostic only: C120 137/278 = 49.280576%,
  C300 85/278 = 30.57554%, C600 52/278 = 18.705036%. Combined diagnostics
  preserve the previously reported 47.766323%, 29.209622% and 17.869416%.
- The corrected verdict remains NO_LIVE_CANDIDATE. C120 fails gates 1 and 2;
  C300 and C600 fail gate 4 only. live_candidates remains empty and
  preferred_live_candidate remains null.
- open_evidence_limitations remains empty and no production budget is declared.
- Step 3.8 is invalidated only because its Phase-4 input contract embeds the
  superseded shortlist hash; its live-candidate semantics remain unchanged.

## Step 3.7 validation

- Focused report pytest: PASS, 6 tests including a mixed canonical/operational
  regression proving gate 2 counts canonical positive-wait turns only.
- Frozen shortlist command ran twice exactly and produced byte-identical JSON
  and Markdown at SHA-256 51db08d70ad8ebfcc46de9e53c661b517b9f3ed41b10579d49057aa395f8d11d and bd4a258152e66277e663af2a5d7e6fbac0daa2592cfe51d2d3caf1bb644a9c85.
- Corrected population validator: PASS. Gates 1/2/3 canonical; gate 4
  operational-journal; gate 5 canonical; operational and combined exhaustion
  are diagnostic fields rather than gates.
- File-scoped pre-commit for the corrected report CLI, population helper,
  renderer, tests and shortlist artifacts: PASS.

## Step 3.8 notes

- Step-3.7 attempt a2 corrected gate populations and changed the shortlist
  SHA-256 from `23edc0fbba3210aae5da205122be51a806b7be54ab5ca5c590d98de6c931b975` to `51db08d70ad8ebfcc46de9e53c661b517b9f3ed41b10579d49057aa395f8d11d`.
  `live_candidates=[]`, `preferred_live_candidate=null`, and
  `NO_LIVE_CANDIDATE` are unchanged.
- Refreshed `benchmarks/chat-mode-scheduling-v2/phase4-input-contract.json`
  at commit `be92c23118a714fabef2c09fb9dc7b8c51c67bd8`. Its SHA-256 is now
  `bc2fc07ab945504b3acc726c1779d2b46533f43472535f803f2f17b986321024`; the only contract byte change was
  `candidate_shortlist_sha256`.
- C budgets remain C120=120 s, C300=300 s and C600=600 s. H10 remains
  historical-only and is not a live candidate.
- Scenario catalog SHA-256 remains `45002efd15fe7aa07fa5933180752c6537bea6584520f41a4e1d6b6de61ab5fd`, using the canonical
  sorted R1-R12 relative-path-to-file-SHA object required by the handoff contract.
- Provenance classifier commit remains `2b5e83c4f8015f3077794dabb9e864a3c4d806b6`. Frozen
  Phase-1 R7 timeout examples still split correctly between
  `active_turn_browser_timeout` and `mcp_completed_browser_timeout`.
- Canonical v2 instruction SHA-256 remains `b7df6953a3c64bd245b3d5ff13b6f2667e940d5a154e650fec0b10e6a22cf094`.
- Current historical A baseline source Project remains
  `g-p-6aaea9da2bc881918d6f9eb5177cf904` / `rp-test-sandbox`; its current
  instructions SHA-256 is `dd81ecafb56bf235fa1933a0727fb5fd196c7e5ae86519e39866234a6f4b2b78`. The instruction text is not
  stored in Phase-3 artifacts.
- H10 remains `historical_one_shot`: first original-positive wait uses
  `min(bounded_wait, 10)`, later original-positive waits use zero, and
  later zero-wait decisions use `historical_one_shot_exhausted`. Phase 4
  must provide the benchmark-only adapter; no production runtime mode is allowed.
- Required logical analysis arms remain exactly `A/B/C/H`.
- Endpoint routing and C/H harness support are not implemented or required in
  Phase 3. The Phase-3 harness remains A/B-only and
  `scripts/chat_scheduling_endpoints.py` is absent.
- No live ChatGPT trial was run. The corrected offline verdict remains
  `NO_LIVE_CANDIDATE`, so Phase-4 live calibration remains blocked unless a
  future Phase-3 revision produces at least one passing C candidate.
- The Step-3.7 correction invalidation is resolved: the Phase-4 input contract
  now binds the corrected shortlist and Step 3.8 is complete again.

## Step 3.8 validation

- Refresh validator: PASS; 12/12 R manifests loaded, R12 rendered
  H10/C120/C300/C600 runtimes 40/150/330/630 s with the expected safety oracle,
  two frozen Phase-1 timeout examples classified correctly, and the 326-row
  corpus plus all three C reports plus corrected shortlist share audited corpus
  SHA-256 `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`.
- Contract binding: PASS; corrected shortlist SHA-256 is
  `51db08d70ad8ebfcc46de9e53c661b517b9f3ed41b10579d49057aa395f8d11d`; refreshed contract SHA-256 is
  `bc2fc07ab945504b3acc726c1779d2b46533f43472535f803f2f17b986321024`; live candidates remain zero.
- Relevant constituent pytest: PASS, 41 tests in 1.91 s (real 2.86 s);
  nproc=4, pre-run loadavg=0.37 0.42 0.52, timing under foreign
  parallel-programme load.
- Historical A Project identity refresh: PASS; only the current id/name and
  instructions SHA-256 were retained.
- File-scoped pre-commit for the refreshed input contract: PASS.
- The focused test matrix defines no dedicated Step-3.8 pytest target; the
  relevant manifest/oracle/provenance/report tests and explicit contract
  validator were rerun.
