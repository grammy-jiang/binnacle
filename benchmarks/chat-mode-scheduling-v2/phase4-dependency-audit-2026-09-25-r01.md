# Phase 4 dependency audit — r01

## Result

**PASS.** Phase 4 is bootstrapped directly from canonical Phase-3 closeout
`3a4dfb1b248e4530fb09013976abb863c8e35eaf`. All required dependencies pass,
the bounded inherited source smoke is green, and there are no external setup
blockers.

## Frozen entry evidence

- Phase-3 closeout: `3a4dfb1b248e4530fb09013976abb863c8e35eaf`
- Phase-3 evidence commit: `83a3d2a9a19592fdb32e08885310f79a0f936e68`
- Phase-3 report JSON SHA-256:
  `54e46772ba0a1ee06b2c4d92cf5a55036e8bedd106466e25916ff6fab5c1aaae`
- Phase-3 candidate shortlist SHA-256:
  `072556e60fb55f686d872bce4da004bc272e9162e32459f2dc276657faa0e094`
- Live shortlist: `C300` only; preferred budget 300 seconds.
- Scenario catalog SHA-256:
  `45002efd15fe7aa07fa5933180752c6537bea6584520f41a4e1d6b6de61ab5fd`
- Public master/proof-of-concept fingerprint:
  `260bc009a55e7a78716ac42faf64ae88cf2c6724`
- Phase-4 runbook SHA-256:
  `85faf9411a319bd6903fc340bf27b635b49725ef947b786f8ac635605b373248`

## Dependency matrix

| Dependency | Result | Evidence |
| --- | --- | --- |
| phase3_progress | PASS | Phase complete; every active slot complete; Phase 4 ready |
| phase3_replay_report | PASS | Canonical r02 report/corpus/candidate hashes recomputed |
| live_candidate_shortlist | PASS | C300 alone passes all five amended gates |
| scenario_catalog | PASS | 12 manifests; R4/R6/R10/R12 present; 26 manifest/oracle tests pass |
| provenance_classifier | PASS | Restacked byte-equivalent classifier verified; 9 tests pass |
| phase3_ci | PASS | Evidence CI 36083115418 and closeout CI 36083288849 both succeed |
| stacked_lineage_phase0_phase1_phase2_phase3 | PASS | Fresh direct ancestry checks pass |
| public_base_freshness_master_and_poc | PASS | Public refs unchanged; Phase-2/public trees identical |
| test_runner_inheritance | PASS | Optimized runner, coverage policy, safety guard unchanged |
| benchmark_project_snapshot | PASS | Current rp-test-sandbox instruction fingerprint captured safely |
| isolated_endpoint_prerequisites | PASS | Ports 8110–8115 free; isolated control plane is automatable |
| production_isolation | PASS | Production remains clean and observation-only |

## Bounded inherited source smoke

Command:

```text
uv run pytest -q tests/unit/core/test_config_loading.py   tests/unit/core/test_blocking_wall_guard.py   tests/contracts/test_job_schemas.py   tests/contracts/test_protocol.py
```

Result: **63 passed in 10.63 seconds**. Pre-run host state was 4 CPUs with
1-minute load average 1.68. This is the Step-4.0 bounded source-level viability
smoke; Step 4.1 retains the authoritative optimized test/coverage gate.

## External prerequisite snapshot

Explicit Chrome access is healthy. Project creation, custom connector
registration, tunnel list/get/create/delete, and tunnel profile
start/teardown are available without an owner UI action. Required started lanes
are A, B, C300, and H. C120 and C600 remain reserved and unprovisioned.

Production remains untouched. The primary checkout is clean at
`260bc009a55e7a78716ac42faf64ae88cf2c6724`, the blocking-wall budget key is
absent, the four production services remain active/running, and no benchmark
scheduler namespace exists.

## Deviations

D1 is informational and non-blocking. The Phase-3 handoff stores pre-restack
provenance commit `2b5e83c4f8015f3077794dabb9e864a3c4d806b6`; restacked commit
`b09cb68b9b764c7066beef1932f14f2cde217e51` is byte-equivalent for the
classifier and its tests and is an ancestor of the current Phase-3 closeout.
The mapping is retained for the separately scheduled housekeeping/restack work.

The default ChatGPT helper auto-profile still selects a stale Chromium token,
but explicit Chrome access is healthy and is the benchmark path. This does not
block Phase 4.

## Exit

The dependency audit passes, the Phase-3 shortlist and direct-predecessor source
HEAD are frozen for Step 4.1, and external setup blockers are empty. After the
task graph and initial orchestrator state validate, the next allowed step is
`4.1`.
