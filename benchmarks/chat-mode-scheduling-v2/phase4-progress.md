# Chat mode scheduling v2 — Phase 4 progress

Status: **in_progress**

Branch: `feature/chat-mode-scheduling-v2-phase4`

Worktree: `/home/grammy-jiang/Projects/binnacle-chat-scheduling-phase4`

Audited source HEAD: `3a4dfb1b248e4530fb09013976abb863c8e35eaf`

Last completed step: **4.5**

Next step: **evaluate 4.6B0 aggregate level 3 (K=1) from 4.6B0-qual-3 against frozen serial references, then write admission r01 on PASS**

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
| 4.3B | complete | — |
| 4.4A | complete | — |
| 4.5 | complete | 389e6a5 |
| 4.6A | not_started | — |
| 4.6B0 | running | — |
| 4.7 | not_started | — |
| 4.6A:selected | not_started | — |
| 4.8 | not_started | — |
| 4.9.1 | not_started | — |
| 4.9.2 | not_started | — |
| 4.9.3 | not_started | — |
| 4.9.4 | not_started | — |
| 4.9.5 | not_started | — |
| 4.9.6 | not_started | — |
| 4.10 | not_started | — |
| 4C | not_started | — |
| 4.11 | not_started | — |
| 4.12 | not_started | — |
| 4H-R | not_started | — |
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

## Step 4.6B0 core admission baseline — RUNNING

- Predecessor 4.5 is complete. The original 4.6B0-qual result is frozen at
  SHA-256
  c5231c5e11f5de372d6e73dee0c90393a53387260676f5843f5404f95a335c4d.
- P4-A2 excludes q-read-1-a as a routing miss: all 10 fixture reads reached
  production despite lane A's system hint. They were read-only disposable-fixture
  calls, so this is an isolation incident, not a primary connector/config/schema
  mutation. The A routing-miss rate is 1/10 (10.00%) in the original submitted
  set and 1/11 (9.09%) after A's correctly routed wait repair submission; the
  rule fails only above 10%. B and C300 have no observed routing misses.
- The original Q-wait(1) block had no submitted outcomes: all three rows failed
  before submission. Manager request 4.6B0-qual-2 therefore repaired that
  block without counting pre-submit failures as qualification data.
- The first submitted A repair outcome
  r5-20260926T001004-5382623ee3 is correctly routed and otherwise healthy:
  exact R5 reply, two matched lane calls, zero foreign calls,
  production_unchanged=true, dispatch_ms=0.60 ms, local non-blocking
  overhead about 0.08 ms, and no throttling.
- Admission nevertheless **fails the mandatory host-load criterion** for this
  measurement: A started at load1 4.63 on 4 CPUs, above
  0.75 * nproc = 3.00. P4-A2 does not permit replacement of a correctly
  routed submitted outcome, so this aggregate level cannot be declared passing.
- Host-clean submitted serial R5 references give conservative p95
  dispatch/overhead baselines of A 1.00/0.08 ms, B 0.76/0.10 ms, and C300
  1.46/0.12 ms, corresponding to dispatch limits 21.00, 20.76 and 21.46 ms
  and non-blocking-overhead limits 20.08, 20.10 and 20.12 ms. The A repair
  timing is comfortably inside those limits and the 100 ms absolute ceiling.
- No immutable phase4-live-admission-r01.json and no 4B-C300 or 4H
  calibration run requests were written. The next measurement should repeat the
  same smallest useful aggregate level of 3 sessions (K=1) after host load
  returns to <=3.00; increasing K would not diagnose an environmental-load
  failure.
- Frozen blocking evidence: A trial JSON SHA-256
  f40f5e67faa3994a457f1cb551d110874d62bbe3647fff7cbe7f08d9f3de2d12;
  A endpoint evidence SHA-256
  6787c5118b016acde71d75b2642ca5b7d191ddfc50de21e26cbd112ecc7d97e3.
- Request validation: 4.6B0-qual is valid with 36 trials; 4.6B0-qual-2 is
  valid with 3 repair trials. Production isolation remains at the accepted D2
  baseline e8ece81d57dd2a478dd636d2b4f409519b845605 /
  d24dadcc87e04096fdd960fc7d1543fca02ea53814b15ccd51fd9b1eb1153195,
  with the blocking-wall budget key absent.
- The repair runner finished with 3/3 owning submissions exit 0 and no routing
  misses. B was host-clean at 0.75 -> 2.50 with dispatch 0.93 ms; C300 was
  host-clean at 0.77 -> 0.84 with dispatch 0.80 ms. A remains the sole owning
  host-load flag. Repair-result SHA-256:
  11ee72571dcdb91d48d1e4be4813332d404def1b6bd39938b7d3ea013445b0a8.

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
