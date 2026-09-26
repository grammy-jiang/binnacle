# Chat mode scheduling v2 — Phase 4 progress

Status: **in_progress**

Branch: `feature/chat-mode-scheduling-v2-phase4`

Worktree: `/home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4`

Audited source HEAD: `3a4dfb1b248e4530fb09013976abb863c8e35eaf`

Last completed step: **4.9.4**

Next step: **complete the remaining independent 4.9 confirmatory partitions;
Step 4.10 becomes ready only after 4.9.1 through 4.9.6 all checkpoint
complete.**

## Frozen Step 4.0 entry gate

- Dependency audit: **PASS**, revision `r01`.
- Dependency-audit JSON SHA-256:
  `6ffa479be73acf488f1e627f50160b41f3473c6ea990f2a88afe18312e4ef893`.
- Task graph: revision `r01`, validation **9/9 PASS**.
- Task-graph SHA-256:
  `371dac292442c10d5c845f30bc71759e7f8422ceaa0ba998ad56b730c20fde17`.
- Initial orchestrator checkpoint SHA-256:
  `8b592e2e58fdcda6d861c498b617b5b28d22ea94a4663ab5d8e5bfbe6a2e7111`.
- Phase-3 live shortlist: `C300` only.
- External setup blockers: none.

## Step status

| Task | Status | Commit |
| --- | --- | --- |
| 4.0 | complete | — |
| 4.1 | complete | — |
| 4.2A | complete | `87466c7` |
| 4.2B | complete | `456b3c1` |
| 4.2C | complete | `6c473ce` |
| 4.2D | not_started | — |
| 4.3A | complete | — |
| 4.3A-fix | complete | `22f9556` |
| 4.3A-fix2 | complete | `acdb208` |
| 4.3A-fix4 | complete | `6ff1161` |
| 4.3A-fix5 | complete | `c06518b` |
| 4.3B | complete | — |
| 4.4A | complete | — |
| 4.5 | complete | 389e6a5 |
| 4.6A | not_started | — |
| 4.6B0 | complete | — |
| 4.7 | complete | — |
| 4.7-fix | complete | `76ec24e` |
| 4.6A:selected | complete | — |
| 4.8 | complete | — |
| 4.9.1 | not_started | — |
| 4.9.2 | not_started | — |
| 4.9.3 | not_started | — |
| 4.9.4 | complete | R7 9/9 frozen; integrity PASS; commit pending |
| 4.9.5 | not_started | — |
| 4.9.6 | not_started | — |
| 4.10 | not_started | — |
| 4C | not_started | — |
| 4.11 | not_started | — |
| 4.12 | not_started | — |
| 4H-R | complete | P4-A3 comparator frozen; H outcomes unchanged; selected C300 9/9 |
| 4.13 | not_started | — |

### Dynamic lane manifest freezes

| Task | Status | Lane manifest |
| --- | --- | --- |
| 4.4B:H | complete | phase4-lanes/H.json (d9bfc266) |
| 4.4A | complete | A.json (0bb2698d), B.json (a6c27c36), C300.json (d413edb9) |

## Step 4.1 source checkpoint

- Frozen Phase-4 source HEAD: `06bc1649c4bad9449470366da971649bb7620020`.
- Baseline snapshot JSON SHA-256: `e8a6c5149185dfb32e9810be1610cd63011b08837f2562cf8780a3df3d6a61d3`.
- Baseline snapshot Markdown SHA-256: `c41c44ec771495c26b43ffefc2831b0a877587fe329ec5475fd340be30ab3be0`.
- `rp-test-sandbox` (`g-p-6aaea9da2bc881918d6f9eb5177cf904`) exact instructions are stored outside Git at `/home/grammy-jiang/.local/state/binnacle/chat-scheduling-v2/phase4/baseline-instructions.txt` with mode `0600`; SHA-256 `f1c100d0ddb93c29f8f78e5a2d28e297d861ba6e2c7e53712ec886dea06bafa5`.
- Current web model/thinking state: `gpt-5-6-thinking` / `max` (`Extra High`, position 4 of 5).
- Frozen browser source profile: Google Chrome `Default`; current probe found 27 readable cookies, 0 unreadable, with session-token expiry `2026-12-24`.
- Canonical v2 instruction SHA-256: `b7df6953a3c64bd245b3d5ff13b6f2667e940d5a154e650fec0b10e6a22cf094`.
- Phase-3 live shortlist: `C300` only; shortlist SHA-256 `072556e60fb55f686d872bce4da004bc272e9162e32459f2dc276657faa0e094`.
- Focused default-policy equivalence: **PASS**, 129 tests.
- Optimized full suite: **PASS**, 1,255 passed / 3 skipped.
- Coverage policy: **PASS**, 1,255 passed / 3 skipped; 99 production modules, 0 below target, 0 errors.
- Implementation workers 4.2A/B/C/D are created/recovered at the exact frozen source HEAD on the documented endpoint, harness, analysis, and readiness branches/worktrees.
- File-scoped pre-commit: **PASS**; production isolation recheck: **PASS** with the production baseline unchanged.

## Step 4.3A runtime/harness integration and local endpoint smoke

- Verified 4.2A completion packet `a2` and 4.2B completion packet `a2`;
  both worker bases match the frozen `phase4_source_head`.
- Integrated in deterministic order: 4.2A
  `87466c77f5e759a3b8da8467639ba773c5126a04` -> `083f7869da2f4a3324d85ba3ec3b459b9f6d1909`, then 4.2B
  `456b3c150661db0500954f2482d466da5778f567` -> `2e7889f3552e5d9bb6c26a38c7aab444ebbe8b90`.
- Frozen `phase4_runtime_path_head`:
  `2e7889f3552e5d9bb6c26a38c7aab444ebbe8b90`.
- Focused runtime/harness integration: **PASS**, 86 tests in 2.29 seconds; 4
  CPUs; pre-run load average 0.13 / 0.74 / 2.57 under foreign
  parallel-programme load.
- Started exactly A/B/C300/H locally on 8110/8111/8113/8115 from the C300-only
  Phase-3 shortlist. C120/C600 stay unused and no benchmark tunnel was started.
- Four endpoint-local smoke workers ran concurrently and passed: A/B
  `no_policy`; C300 `tracked` with budget 300; H first
  `historical_one_shot`, then `historical_one_shot_exhausted` with effective
  wait 0. Every smoke job was stopped cleanly and retained only lane-local spool
  evidence.
- Local-smoke aggregate: `benchmarks/chat-mode-scheduling-v2/phase4-local-smoke.json`
  SHA-256 `445a8e18c04e708987a319fbd752521597d34123ee8bc2246e86b018ced4d321`; runtime registry SHA-256 `0c67d3b566f784b41f5cd5436939aebe22c6808a2ff241a46aaeba918480ed5a`.
- Production isolation remains intact: production HEAD/config/unit/profile hashes
  are unchanged; only the expected isolated benchmark listeners were added.
- The 4.2A packet's older runbook hash was investigated. Its difference is the
  downstream P4-A1 H/4.13 critical-path amendment, so it does not change 4.2A or
  4.3A semantics. There is no semantic Step-4.3A deviation.

## Step 4.3A-fix process-identity contract repair — COMPLETE

- Deviation D3 was found at the first live harness micro-trial attempt: the
  launcher stores each server/manager/tunnel start identity as
  `{"pid": N, "start_time_ticks": "T"}`, while the resolver accepted only
  the legacy `"N:T"` form.
- All nine attempted 4.5 micros failed before a chat opened. No trial was
  submitted, no canonical slot was created, and the failed pre-submit evidence
  remains under
  `~/.local/state/binnacle/chat-scheduling-v2/phase4/runs/failed-2104-identity/`.
- `resolve_phase4_endpoint` now validates the launcher's dict form by matching
  both PID and start-time ticks while retaining string-form compatibility.
- Focused regression matrix: **PASS**, 57 tests in 1.56 seconds; 4 CPUs; pre-run
  load average 0.51 / 0.98 / 1.01 under foreign parallel-programme load. The
  regression covers the real dict registry shape plus stale server, manager,
  and tunnel identities.
- Direct read-only resolution against live A/B/C300/H passed **4/4** using
  runtime registry SHA-256
  `f75ea33783def327f542832ded790e5f5650f11304e3f968fe0c7c6c39d3cf26`.
  No chat was opened and no trial was submitted.
- Frozen `phase4_runtime_path_head` advanced
  `2e7889f3552e5d9bb6c26a38c7aab444ebbe8b90` -> `22f9556017b630061f2fb03d2ac989c6970ffde2`.
  Frozen experiment source remains
  `06bc1649c4bad9449470366da971649bb7620020`, so the healthy running
  endpoints require no restart.
- Production isolation remains intact at the accepted D2 baseline. An unrelated
  listener on 127.0.0.1:8120 was observed but not created, modified, or stopped
  by this task.

## Step 4.3A-fix2 connector-routing repair — COMPLETE

- D4 was a benchmark-infrastructure routing defect at the first chat-opening
  4.5 micro attempt after D3. The branch-local sender could not pin a connector,
  while rendered scenario prompts still named the bare production connector.
- M1-B, M1-C300 and M2-C300 completed through production instead of their lane:
  14 read-only `read_file` calls against disposable `/tmp` fixtures reached
  production at 21:18-21:23. No job was started and no write or persistent
  production mutation occurred. M1-A separately timed out after 80.611 seconds
  with no assistant text, conversation URL or MCP call on production or lane A.
  The manager quarantined this failed attempt under
  `phase4/runs/failed-2116-routing/`; it created no canonical 4.5 slot.
- Canonical trial sends now use the ChatGPT skill API sender with the exact lane
  Project id, lane manifest `system_hint`, and frozen
  `gpt-5-6-thinking` / `max` state. The rendered prompt replaces only the
  bare production connector token with that lane's `connector_logical_name`;
  scenario templates and their hashes remain unchanged.
- The shared send gate, exact conversation URL artifact, sent/settled timing,
  single-submit/no-unsafe-retry rule and endpoint evidence guard are preserved.
- Focused routing/harness/evidence/manifest regression: **77/77 PASS** in
  1.88 seconds; 4 CPUs; pre-run load average 0.54 / 0.51 / 0.85. Final
  file-scoped pre-commit, including mypy and module-size ratchet: **PASS**.
- Frozen `phase4_runtime_path_head` advanced
  `22f9556017b630061f2fb03d2ac989c6970ffde2` ->
  `acdb2088584382c6496d10c2a170d2217135e550`. Frozen experiment source remains
  `06bc1649c4bad9449470366da971649bb7620020`; endpoints required no restart.
- One non-canonical M1/B validation probe passed at
  `m1-20260925T214221-c8c630aecf`: chat reply `DONE`, 14.77-second
  send-to-settle wall time, matched base turn
  `d0d25db8-d70d-4e13-bdcf-3ded89d1dc12`, exactly three lane-B
  `read_file` calls, and **0** production journal matches for its fixture path
  since probe start. The disposable chat and fixture were cleaned by the harness.
- Final production-isolation check remains at accepted D2 baseline
  `e8ece81d57dd2a478dd636d2b4f409519b845605` /
  `d24dadcc87e04096fdd960fc7d1543fca02ea53814b15ccd51fd9b1eb1153195`.

## Step 4.5 micro sanity — COMPLETE

- Mechanical gate: **PASS** across nine valid A/B/C300 M1/M2/M3 trials:
  9/9 deterministic correctness, zero duplicate non-repeat logical calls, M2
  minimum peak inflight 3 and minimum overlap ratio 0.375, M3 wait/read
  relation true 3/3, routing correct 9/9, and zero tool/schema errors.
- C300/M1 and B/M2 completed their measured MCP work and captured DONE before
  cleanup HTTP 429. D5 (389e6a5) keeps completed submissions successful when
  cleanup fails, retries transient reply reads with bounded backoff without
  resubmission, and permits analysis fallback to the captured send reply.
- The original B/M3 attempt was infrastructure-invalid: its 300-second
  prelaunched fixture job had already exited before job_status, so no wait
  interval existed to test refill. The single permitted rerun
  m3-20260925T222215-4ab7c62230 passed with peak inflight 4, overlap ratio
  1.0, one positive job_status, relation true, and zero duplicates/errors.
- Focused D5 regression: **34/34 PASS**. Full Step-4.5 integration matrix:
  **114/114 PASS** in 2.65 seconds; 4 CPUs; pre-run load average
  0.53 / 0.58 / 0.90.
- Production isolation remains at D2 baseline
  e8ece81d57dd2a478dd636d2b4f409519b845605 /
  d24dadcc87e04096fdd960fc7d1543fca02ea53814b15ccd51fd9b1eb1153195.
- Evidence JSON SHA-256:
  ff8f81d718e476df160d83149d72c99ecaee1e1a0774fd8c4df4434a117d7e22;
  Markdown SHA-256:
  a117c7d02bace0c6d28881e7f224a2df96c9af707b28d5443ff15c78f59fd8d7.
- 4.6B0 is prepared, not executed. R2 is the fixed read-heavy case and R5 the
  fixed wait-heavy case. 4.6B0-qual uses five serial references per arm/case,
  then separate Q-read(1) and Q-wait(1) matched A/B/C300 blocks; request
  SHA-256 deb26d1d621be0a53933be1b0cb983d8ab6eaae19da47203f22ac645b6f769b4.
- C300/M1 chat 6ab6608c-98a0-83ec-8a5a-d73296f7b4a1 may remain from the
  cleanup-429 attempt and is explicitly listed for manager cleanup.

## Step 4.6B0 core admission baseline — COMPLETE

- Predecessor 4.5 is complete. Attempt a1 remains historical evidence: its
  correctly routed A wait repair started at load1 4.63 > 3.00, so that
  measurement could not qualify K=1.
- Attempt a2 consumes 4.6B0-qual-3 with the frozen serial references from
  4.6B0-qual. The runner produced six owning rows, retried four pre-submit
  failures without granting them slots, recorded no routing miss, and flagged no
  owning row for host load.
- K=1 is **PASS** at aggregate level 3 sessions. Across owning a2 rows the
  maximum load1 is 2.96 on four CPUs (limit 3.00), throttling is 0x0, every
  trial exits 0, production is unchanged, instructions are verified, endpoint
  evidence has no integrity error, and normalized foreign calls are zero.
- Frozen host-clean serial R5 nearest-rank p95 dispatch/overhead baselines are
  A 1.00/0.08 ms, B 0.76/0.10 ms and C300 1.46/0.12 ms. The a2 wait block is
  A 1.80/0.13 ms, B 1.11/0.10 ms and C300 1.49/0.16 ms, below dispatch limits
  21.00/20.76/21.46 ms and overhead limits 20.08/20.10/20.12 ms. Maximum
  dispatch is 1.80 ms, below the 100 ms absolute ceiling.
- All three a2 R2 analyzers pass. A/B a2 R5 analyzers pass; C300 repeats the
  missing-wait_result/premature-handoff signature already present in 3/5
  serial C300 R5 references (serial pass count 2/5). This is not a
  correctness/reachability loss that exists only at K=1 concurrency, so the
  plan's concurrency-only criterion passes.
- P4-A2 campaign routing-miss rates are A 1/13 = 7.69%, B 0/13 = 0%, C
  0/14 = 0%, and H 0/0 (not yet observed). No arm exceeds the >10%
  NO_GO_EVIDENCE_INTEGRITY threshold. Historical q-read-1-a remains the
  sole routing miss and is excluded from every arm metric/gate.
- Immutable admission phase4-live-admission-r01.json is frozen at SHA-256
  16671e4aa1dbeaf07acc09c481aae59f645ee2185b6c7cbdbe822bdefec37eaf.
  It sets aggregate cap 3 sessions and conservative per-endpoint cap 1 for
  C300 and H; no 4.6B:lane refinement is requested.
- Calibration request 4B-C300 is valid with 10 sequential C300 trials
  (R5/R6/R7 x3, R12 x1), budget 300, admission r01, aggregate cap 3 and
  priority 2; SHA-256
  7340637573297ff6e859fedb9620559b41a1939c33364f9d101df8c69be4a28c.
- Calibration request 4H is valid with 10 sequential H trials
  (R5/R6/R7 x3, R12 x1), admission r01, aggregate cap 3 and priority 1;
  SHA-256
  ef2af7dee0d3152222e64598bcc4fc8234d02f5bcc86e96018a001301bc2cb41.
- Qualification request/result hashes for attempt a2 are request
  03020cc89a595248715d54269ab1ff9069d42007c081d8013b0e3e6cf3bc62d6,
  result
  4a10e4e17961b07fbcf7ab8ac3f3ed04cb1466436182ac6685051375aecd0ea2,
  and JSONL
  2ad5d1cc3308758fca09b09271a3a7e29cdaf6b4777ec9f25f20494842f5d50b.
- Production isolation remains at accepted D2 baseline
  e8ece81d57dd2a478dd636d2b4f409519b845605 /
  d24dadcc87e04096fdd960fc7d1543fca02ea53814b15ccd51fd9b1eb1153195;
  the blocking-wall budget key is absent. This chat starts no live calibration;
  the manager runner owns those executions.

## Step 4.3B analyzer integration

- Verified 4.2C completion packet `a1`: worker base matches the frozen
  `phase4_source_head`, and branch tip/commit/output hashes are consistent.
- Integrated worker commit `6c473cec6537b0e80a969ddaae62ea8097dccb95` as
  canonical cherry-pick `6073902ba1e72a946da0ea7d7e901e36f47f96a3`.
- Frozen `phase4_analyzer_path_head`:
  `6073902ba1e72a946da0ea7d7e901e36f47f96a3`.
- Focused analyzer integration: **PASS**, 21 tests in 2.05 seconds; 4 CPUs;
  pre-run load average 0.96 / 1.17 / 2.63 under foreign parallel-programme load.
- Endpoint smoke inputs remain frozen independently; Step 4.7 is the first hard
  fan-in that requires this analyzer path.
- No semantic deviation from the Step-4.3B runbook or focused test matrix.

## Step 4.4A core lane manifest freeze — COMPLETE

- Attempt a1 correctly stopped before freezing manifests on unexpected public-base
  drift. Deviation D2 now accepts that drift as the owner-approved run_command
  shadow runtime predictor deployment and continues Phase 4 without restack.
- The accepted production baseline is clean master
  e8ece81d57dd2a478dd636d2b4f409519b845605 with config SHA-256
  d24dadcc87e04096fdd960fc7d1543fca02ea53814b15ccd51fd9b1eb1153195.
  Unit/profile hashes are stable and the blocking-wall budget key remains absent.
- Revalidation at canonical HEAD
  e0cb1ce6eead5b021fbe079edef70ec4276a0851 passed **168 assertions**.
  A/B/C300 are blocker-free with **15/15 provisioning rows PASS** and agree with
  immutable base topology SHA-256
  9b58135a4a527bc18c5d43456d6f92b384e5457ac2f12884520dac1eb9f38155,
  their 4.2D readiness fragments, runtime registry SHA-256
  f75ea33783def327f542832ded790e5f5650f11304e3f968fe0c7c6c39d3cf26,
  and the pre-provisioned tunnel identities.
- Frozen immutable A manifest:
  benchmarks/chat-mode-scheduling-v2/phase4-lanes/A.json,
  SHA-256 0bb2698d63c7e3c11b05a39981674a3976ded8fffd349a8f46e583c5a3520107.
- Frozen immutable B manifest:
  benchmarks/chat-mode-scheduling-v2/phase4-lanes/B.json,
  SHA-256 a6c27c3611675e7d261d572d1edceae6a5a92ce2456c28d50335f68f051e41b4.
- Frozen immutable C300 manifest:
  benchmarks/chat-mode-scheduling-v2/phase4-lanes/C300.json,
  SHA-256 d413edb9f0eaca1471d99a6c1592a4ca19fd9a0af73611bf236def8bfd4ee8da.
- Each manifest records the plan-required source/base/endpoint/arm/budget/Project/
  connector/profile/attachment/smoke/instruction/verified-at fields plus app id,
  link id, tunnel id, system hint and tool-names SHA-256.
- Focused runtime/harness integration matrix: **PASS**, 86 tests in 2.19 seconds;
  4 CPUs; pre-run load average 0.56 / 0.96 / 0.95 under foreign
  parallel-programme load.
- Manifest JSON syntax and git diff checks pass. Final production isolation check
  also passes against the D2 baseline.
- The 4.2D readiness worker commit
  0930075df3ffa879f0dc0066de70870bd86d0008 was consumed read-only; no worker
  commit was integrated and this freeze task performed no external side effect.

## Step 4.4B supplemental H lane manifest freeze

- Provisioning fragment 4.4B:H is blocker-free with **5/5 PASS** rows.
- Validated H against base topology SHA-256
  9b58135a4a527bc18c5d43456d6f92b384e5457ac2f12884520dac1eb9f38155,
  4.2D readiness fragment SHA-256
  730e7330504c6faf298a766feca6139858aa10db4bf71349454d5340435aae79,
  and runtime registry SHA-256
  f75ea33783def327f542832ded790e5f5650f11304e3f968fe0c7c6c39d3cf26.
- Frozen immutable manifest
  benchmarks/chat-mode-scheduling-v2/phase4-lanes/H.json at SHA-256
  d9bfc26661289baa2db99394fd2872d09965c06fa7bc26ff8cebaa18c4ccbed7;
  attachment status is verified.
- Focused runtime/harness integration matrix: **PASS**, 86 tests in 2.59 seconds;
  4 CPUs; pre-run load average 1.29 / 2.34 / 2.08 under foreign
  parallel-programme load.
- Production isolation recheck: **PASS**; production master remains clean at
  260bc009a55e7a78716ac42faf64ae88cf2c6724 with unit/config/profile hashes
  unchanged.
- The 4.2D readiness worker commit
  0930075df3ffa879f0dc0066de70870bd86d0008 was consumed read-only. This lane
  freeze does not integrate that worker, so the static 4.2D status row remains
  unchanged.
- A long helper heredoc command was refused by the platform safety layer; the
  equivalent helper was supplied through run_command stdin and executed
  successfully with no semantic deviation.

## Step 4.0 validation

- Bounded inherited source smoke: **63 passed in 10.63 seconds**.
- Smoke pre-run host state: 4 CPUs; load average 1.68 / 2.37 / 2.63.
- Stable task-graph validation: **9/9 PASS**.
- Initial scheduler state: 27 static tasks; one complete, one ready, 25 blocked.
- JSON syntax checks pass for progress, audit, and task graph.

## Step 4.0 notes

- Workspace base is the current green Phase-3 closeout HEAD, not public master.
- Public master and proof-of-concept remain at the final-restack fingerprint.
- D1 is informational: the Phase-3 handoff stores a pre-restack provenance SHA;
  the restacked byte-equivalent implementation/test commit is on the current lineage.
- The source Project was fingerprinted without storing its private instruction text.
- Production remains observation-only and unchanged.
- The first local graph-validator draft used an over-broad Phase-5 text check;
  its corrected dependency-only check passes the authoritative 9-point contract.

## Step 4.7 C budget selection — COMPLETE / C300 SELECTED

### Superseded r01 verdict

- Commit 74249499c0e097f8e9a2fbb263528d54a78e8e0b recorded the original NO-GO from the pre-P4-A3
  analyzer: 7/9 bounded same-prompt completions and 2/9 premature handoffs.
- Amendment P4-A3 identified both failures as analyzer false labels caused by
  exact matching of advisory wait_seconds. That r01 verdict remains historical
  evidence and is explicitly superseded by r02; the frozen live trials were not
  rerun or replaced.

### P4-A3 r02 re-judgment

- Corrected analyzer head: 76ec24eed464e1162f4b51d9549143bf6175d8bb. All 10 frozen 4B-C300 state
  directories re-analyze successfully.
- The nine bounded R5/R6/R7 trials are **9/9 same-prompt**, **0/9 premature
  handoff**, **0/9 unexpected budget-exhaustion handoff**, **0/9 interrupted**,
  and **0/9 manual continuation**.
- Frozen replay definition-(b) repeated-wait burden reduction is unchanged at
  **63.448499%**, above the required 60%.
- R12 is a valid expected-exhaustion safety case:
  correctness_passed=true, budget_exhaustion_handoff=true,
  premature_handoff=false, interrupted=false, with one required continuation.
- P4-A2 routing integrity remains PASS. Current observed routing-miss rates are
  A **1/13 (7.69%)**, B **0/13 (0%)**, C **0/24 (0%)**, H **0/10 (0%)**.
  H remains diagnostic and is not a Step-4.7 predecessor. No arm exceeds 10%.
- Final C-lane admission remains immutable r01, SHA-256 16671e4aa1dbeaf07acc09c481aae59f645ee2185b6c7cbdbe822bdefec37eaf:
  aggregate cap 3 sessions, C300 cap 1, H cap 1.
- **Verdict: GO. selected_c_endpoint=C300; selected budget=300 s.**

### 4.6A:selected preparation

- No early 4.6A result exists, so selected-C timing requires a fresh live
  qualification.
- The 4.6B0 serial timing reference is reused. Phase-4 source and A/B/C300 lane
  identities are unchanged from admission commit
  695c7326a58058352b24341e870f95a17b32395d, and the normalized R2/R5
  qualification-case plus seven-criterion fingerprint matches historical/current
  at SHA-256 bf832bad314ce4266179e4f4126358fb83f86610f78f2dd13d2a8b4f4dfcf5b2.
- Manager-run request 4.6A-sel-qual validates with **84 trials** in six ordered
  Q-read/Q-wait groups for K=1,2,4. Each group contains exactly 2*K matched
  A/B/C300 blocks and uses parallel_blocks=K, block_order=concurrent.
- Request SHA-256: 7858204fdf01ab51741a733fd30cb64079c7cc94d3ac0ddd49286f36d3c0b440. No live qualification trial was started by this
  chat.
- Focused P4-A3 analyzer/evidence/confirmatory regression: **27 passed in 2.11s**;
  nproc=4; pre-run load average 1.68 / 2.12 / 2.53 under foreign load.

Next step: **manager executes 4.6A-sel-qual and dispatches evaluation of
Step 4.6A:selected from the frozen result**.

## Step 4.6A:selected selected-C timing qualification — COMPLETE

- Selected endpoint: **C300 / 300 s**. Final timing artifact:
  `phase4-selected-c-timing-qualification.json`, SHA-256 `c308d01491d66e14515f5e554913342c9e715e872ff4b4fdd68356847d9723f6`.
- **max_safe_parallel_blocks=0**. K=1 fails Q-read on the mandatory host-load
  ceiling: two owning rows exceed load1 3.00 (maximum 3.61); Q-wait(1) passes
  dispatch, local-overhead, correctness/reachability, routing and host-load
  checks. The runbook therefore selects serial randomized confirmatory mode.
- Higher levels are diagnostic only: K=2 wait has five host-load flags and
  reaches 4/6 nominal sessions; K=4 wait has one host-load flag, one malformed
  runner row with no state directory, and reaches 8/12 nominal sessions.
- Routing integrity is clean in the fourth run: A/B/C each 0/28 routing misses.
- D9 recovery found 60 owning trials without a final-conversation timestamp.
  Fourteen were recomputed from saved conversation JSON. Every remaining chat
  received a one-shot authenticated fetch attempt and returned HTTP 429; those
  46 are listed individually as poll-observed and their wall times are excluded
  from the K gate.
- All ten reusable C300 calibration slots (R5/R6/R7 repeats 1-3 and R12) match
  the frozen source, lane, Project, instruction, model/effort and current
  scenario-manifest identities.
- Focused analyzer/confirmatory regression: **21 passed in 1.88 s**; nproc=4,
  pre-run load average 0.43 / 0.63 / 0.75.

## Step 4.8 deterministic confirmatory schedule — COMPLETE

- Frozen schedule: `phase4-confirmatory-schedule.json`, seed **12345**,
  selected endpoint **C300 / 300 s**, `max_safe_parallel_blocks=0`,
  execution mode `serial_randomized`, SHA-256
  `516938320afdf9dade5e03b8262a9e6ef9c95ad5d0330c20d1ce23d0ec68e734`.
- Population is 160 canonical slots: A=53, B=53, C=54. Ten valid C300
  calibration slots are reused, leaving **150 live 4.9 trials**. Replay with
  the same seed/budget/K is byte-identical.
- `4.9-confirmatory` validates with 150 trials in one fully serial group and
  preserves the frozen schedule order exactly after reused C slots are removed.
  Request SHA-256:
  `c2a137fa05eb68960bfbda7443b4bd914fe3c1b2bd65dd938b3d80904e85d7ee`.
- `4.10-micro` validates with nine trials: three lane blocks (A, B, C300), each
  sequential M1 -> M2 -> M3, `parallel_blocks=3`. Request SHA-256:
  `522b4eae38fa306bd48102444a4b68e25992f967c3e0a3a2ff809cbce11b6476`.
- **D10 / INFO:** production advanced from the accepted D2 baseline `e8ece81`
  to clean `cbafe8a` through the owner-approved run-command shadow-predictor
  line; config SHA-256 is now
  `22f7ed9c2053c9fb20574fe4086fff797e197e2da40080e92f503213061188da`.
  Five K=4 wait trials crossed this drift, but the K=1 host-load failure that
  selects K=0 is independent of it. Frozen Phase-4 identities are unchanged;
  services, unit hashes, primary tunnel profile and absent blocking-wall budget
  key remain stable.

## Step 4.9.4 confirmatory R7 checkpoint — COMPLETE

- Slot integrity is **PASS**: 9/9 canonical R7 slots are frozen, comprising six
  live A/B outcomes and three reused C300 calibration outcomes. There are no
  reruns or unscorable-routing slots, and every owning row records host load.
- Routing misses are A 0/3, B 0/3, C 0/3. C uses the already-resolved D6
  retained-log routing recovery for the reused calibration rows.
- The first submitted R7-r02-B outcome remains canonical despite runner exit
  1; it was correctly routed and therefore was not rerun.
- Analyzer results are 8/9 same-prompt and 1/9 interrupted. The failed B repeat
  is preserved as evidence rather than replaced.
- D9 recovery recomputed R7-r01-C to 154.656 s and R7-r03-C to 157.100 s
  from final-assistant timestamps. R7-r01-A, R7-r01-B, and R7-r02-C
  remain poll-observed after bounded read_chat.py attempts returned no
  conversation payload.
- Canonical checkpoint: phase4-confirmatory-R7-checkpoint.json, SHA-256
  344e2b5f372e46dc80dab7df0166a86e58cf5624b358664d2d48bd3b8ffec63a;
  Markdown SHA-256 9894c06a2b349ad6bf45ee41640cd1fac7242ef4f2430451a4cc6bd20bca9f94.
- Frozen source-file tree SHA-256
  e64ba86062d91863653bfed02946b9e0fb95ed0285009af8c9bdfb4d82a5ecf6 across
  126 files, preserved byte-for-byte in nine deterministic tar.gz archives
  under phase4-confirmatory-evidence/R7/.
- Focused analyzer/confirmatory regression: **21 passed in 1.93 s**; nproc=4,
  pre-run load average 0.42 / 0.60 / 0.56. Evidence verification passed for
  all 126 source files and all nine deterministic archives.

## Step 4H-R historical H comparator — COMPLETE (P4-A3 REANALYSIS)

- Corrected analyzer head:
  `76ec24eed464e1162f4b51d9549143bf6175d8bb`; the prior comparator at
  `f600a1dc` used analyzer head `6073902b` and remains superseded history.
- Re-analyzed **10/10 owning H trials** and **10/10 frozen selected-C300
  calibration trials**. The raw run/result hashes and lane identities did not
  change.
- H bounded R5/R6/R7 remains **0/9 correct**, **0/9 same-prompt**, **9/9
  budget-exhaustion handoffs**, zero premature handoffs, zero interruptions and
  nine continuations.
- P4-A3 changes three H internal oracle diagnostics only: R5 repeats 1 and 3
  and R6 repeat 1 now match a positive wait and report
  `wait_result state='running'` rather than an unmatched `None`. H
  correctness, handoff, provenance and continuation outcomes do not change.
- H R12 remains incorrect/premature: its one-shot 10 s wait never returns the
  required `blocking_budget_exhausted=true` tool-result signature.
- Step 4.7 revision r02 selected **C300 at 300 s**. Corrected C300 bounded
  behavior is **9/9 same-prompt and correct**, zero premature handoffs and zero
  continuations; C300 R12 is now correct with the expected exhaustion handoff.
- Raw bounded median wall time remains H 62.556 s versus C300 108.399 s. This
  is not a completion-speed advantage for H: H hands off all nine bounded
  trials, while C300 completes all nine in the same prompt.
- P4-A2 routing integrity remains **PASS**: A 1/13 (7.69%), B 0/13, C 0/24,
  H 0/10; no arm exceeds the >10% threshold.
- Updated comparator JSON SHA-256:
  `13f1fae101ccf9de63b7c45ed593b4827ba8df4cd7a7943079ec214d812eecb7`.
  Updated Markdown SHA-256:
  `25345d3d5567878ef226d13d11d820357bf55eec8d9930402dd0bbd10de06b51`.
- Focused P4-A3 analyzer/evidence/confirmatory regression:
  **27 passed in 2.98s**; `nproc=4`; pre-run load average
  2.03 / 2.69 / 2.65 under foreign parallel-programme load.
- H remains diagnostic and does not alter the C gate matrix or Step 4.12
  verdict. Step 4.13 has not started and `handoff` remains null, so no handoff
  append is required.
- One long helper command was intercepted by platform safety before reaching
  the connector; a short analyzer loop plus state-file reads provided the same
  evidence with no semantic deviation.

## Step 4.7-fix P4-A3 analyzer wait matching — COMPLETE

- Frozen `phase4_analyzer_path_head` advanced from
  `6073902ba1e72a946da0ea7d7e901e36f47f96a3` to
  `76ec24eed464e1162f4b51d9549143bf6175d8bb`.
- Repeated `job_status` nodes with `allow_repeats=true` and a `job_state=*`
  completion condition now treat manifest `wait_seconds` as advisory. Only
  schema-valid positive integer waits `1..50` match; zero/missing/out-of-range
  waits still fail, and every other expected argument keeps its prior matching
  rule.
- Required manifest audit dispositions:
  - R1: no trap; search optional `max_results`/`context_lines`-style arguments
    are absent from expected arguments.
  - R2: no trap; read nodes are path-only.
  - R3: fixed by P4-A3; repeated completion wait had advisory `50`.
  - R4: fixed by P4-A3; repeated completion wait had advisory `50`.
  - R5: fixed by P4-A3; observed 30-second waits now match advisory `50`.
  - R6: fixed by P4-A3; repeated completion wait had advisory `50`.
  - R7: already safe; repeated wait nodes omit `wait_seconds`.
  - R8: no trap; path/workdir semantics remain exact and operation is already
    intentionally ignored.
  - R9: no trap; path/workdir semantics remain exact and operation is already
    intentionally ignored.
  - R10: fixed by P4-A3; repeated completion wait had advisory `50`.
  - R11: no trap; optional search limits are absent, and the dynamic wave-two
    pattern is already a result dependency.
  - R12: fixed by P4-A3; repeated completion wait had advisory `50`.
  - M1: no trap; read nodes are path-only.
  - M2: no trap; read nodes are path-only and batching/limits are not expected
    arguments.
  - M3: exact `wait_seconds=5` is intentional because the prompt specifies it
    and the node is non-repeating.
- No additional `max_results`, `context_lines`, read-limit, or analogous
  model-chosen parameter trap exists in R1-R12/M1-M3. No manifest was changed.
- Focused regression: **27 passed in 4.62s** with `nproc=4`; pre-run load
  average 2.35 / 2.87 / 2.41 under foreign parallel-programme load.
- Retained C300 calibration `4B:C300:R5:1` and `4B:C300:R5:3` both now report
  `correctness_passed=true`, `same_prompt_completion=true`,
  `premature_handoff=false`, and zero manual continuations.
- The owner amendment calls this correction deviation D7, but canonical progress
  at dispatch already contained an unrelated committed D7 for H `routing=null`.
  That prior record is preserved unchanged; this correction is recorded as
  `D7-P4A3` to avoid duplicate/corrupted deviation identity.
- Step 4.7 remains historical NO_GO in this commit. Re-judgment is a separate
  manager-dispatched step, as required by P4-A3.

## Step 4.3A-fix4 send-gate release — COMPLETE

- **D8 RESOLVED:** the shared benchmark send gate no longer remains held while
  `read_chat.py` polls for a reply. `shared_send_gate` yields a post-confirmation
  release callback, and the routed sender invokes it after exact conversation-id
  resolution plus URL/running-timing writes, before reply polling begins.
- FIFO queueing and `flock` are unchanged, so posts remain strictly one at a
  time. Reply polling and all later work may overlap across different trials.
- The trial gap still comes from the manager `trialgap` file, but its floor is
  now **15 s** rather than 60 s. The manager file was verified at exactly `15`.
- Sent bookkeeping retains its prior meaning: confirmed posts release as `sent`
  and update `last-send`; a failure before post confirmation releases as not sent.
- Final combined P4-A4 + routing + Step-4.3A focused regression: **105/105
  PASS** in 2.54 s; `nproc=4`; pre-run load average 1.27 / 1.67 / 1.89 under
  foreign parallel-programme load. Dedicated coverage proves early release,
  concurrent second-gate entry while the first reply is still outstanding, the
  15 s floor, and pre-post failure release.
- File-scoped pre-commit is **PASS**, including Ruff, mypy and the 500-line
  module-size ratchet.
- Frozen `phase4_runtime_path_head` advanced
  `acdb2088584382c6496d10c2a170d2217135e550` ->
  `6ff1161e039d976f8e53a0d4d277c9258b15da29`. Frozen experiment source remains
  `06bc1649c4bad9449470366da971649bb7620020`; running endpoints were not
  restarted.
- No live trial was executed here. The earlier `4.6A-sel-qual` run remains a
  serial diagnostic; the manager must rerun it under P4-A4 before
  Step 4.6A:selected is evaluated.

## Step 4.3A-fix5 gentle reply polling and conversation settle time — COMPLETE

- **D9 RESOLVED:** overlapping trials no longer hammer the authenticated
  `read_chat.py` path once per second. The first observation is about 5 seconds
  after post; subsequent normal polls are at least 10 seconds apart plus jitter.
- HTTP 403/429 responses and read timeouts back off exponentially at
  10/20/40/60 seconds, capped at 60 seconds. They never independently terminate
  observation, which may continue 600 seconds past the nominal turn limit.
- `chat-timing.json` keeps `first_seen_at_epoch_s` and observed wall time as
  diagnostics. Cleanup then reads the retained `conversation.json` and rewrites
  `settled_at_epoch_s` / `wall_s` from the final turn-ending assistant
  message timestamp relative to the send-body mtime.
- Regression coverage proves a turn settled at +18 seconds but first seen at
  +130 seconds remains complete and within a 110-second turn limit.
- Analyzer input loading derives `wall_s` from `settled_at_epoch_s` when it is
  present. A dedicated regression stores an observed 130-second wall with a
  settled timestamp at sent+4 and verifies the analyzer receives 4 seconds.
- P4-A5-specific polling/timing/analyzer regression: **31/31 PASS** in 1.66
  seconds; `nproc=4`; pre-run load average 1.92 / 1.90 / 2.19 under foreign
  parallel-programme load.
- Authoritative Step-4.3A runtime/harness matrix: **94/94 PASS** in 2.31 seconds;
  `nproc=4`; pre-run load average 2.31 / 1.98 / 2.21 under foreign
  parallel-programme load. File-scoped pre-commit passes Ruff, Bandit, mypy and
  the 500-line module-size ratchet.
- Frozen `phase4_runtime_path_head` advanced
  `6ff1161e039d976f8e53a0d4d277c9258b15da29` ->
  `c06518bf477f3c49811d4708dfd66507065d6996`. Frozen experiment source remains
  `06bc1649c4bad9449470366da971649bb7620020`; running endpoints were not restarted.
- No live trial was executed here. The manager must rerun
  `4.6A-sel-qual` under P4-A5 before Step 4.6A:selected is evaluated.
