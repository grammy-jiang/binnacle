# Chat mode scheduling v2 — Phase 3 progress

Status: IN PROGRESS

Updated: 2026-09-25T03:28:42+10:00

## Canonical state

- Branch: feature/chat-mode-scheduling-v2-phase3
- Worktree: /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3
- Audited source HEAD: 5f2be143352aaa63fb680c1c79e289d46be201fe
- Last completed step: 3.4A
- Next step: 3.5M integrate source shards and freeze replay corpus
- Dependency audit: phase3-dependency-audit-2026-09-25-r01.json, r01, SHA-256 d3bec25ba8d49ed4db78e07930542b9e963608ad264c198f8fbf04c4ccfa473a
- Task graph: phase3-task-graph.json, r01, SHA-256 44cbedb0524fe87a9d111579a96d0d33f4171dfee6ece34eb53baa4c506696b2
- Initial orchestrator-state checkpoint SHA-256: cec108b23fcf319a48d699f123b8fbf713919f3873d1cae4968a16844b80ed12
- Validated synchronized baseline HEAD: 806a23053043be46f6ba35ad046833168caa904d
- Frozen replay path HEAD: 9c768800f1e97f9e06d18bd32b173e24d93e82f0
- Frozen scenario path HEAD: 7107f142ae6746e17180ae92b4d4be0e6e3957d2
- Frozen corpus path HEAD: 3e498a33294708c7fe1996b49e78752d8720523d
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
| 3.5M | running |
| 3.5A | not_started |
| 3.6A | not_started |
| 3.6B | not_started |
| 3.6C | not_started |
| 3H | not_started |
| 3.7 | not_started |
| 3.8 | not_started |
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
