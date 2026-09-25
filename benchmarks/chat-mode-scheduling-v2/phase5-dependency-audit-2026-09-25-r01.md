# Phase 5 dependency audit — 2026-09-25 r01

Status: **PASS (speculative preparation only)**

Step 5.0S is permitted by Amendment P5-A1. The rows that depend on the Phase-4 closeout remain pending and must be verified by Step 5.0F before Step 5.2.

## Frozen speculative inputs

- Phase-4 staging branch base: `9e165fd26bda57d938c24c78a826f66f2d5f0440`
- Approved runtime source: `06bc1649c4bad9449470366da971649bb7620020`
- Phase-3 sole live candidate: `C300`
- Speculative selected budget: `300 s`
- Preparation may proceed through Step `5.1E`; deployment is not allowed before `5.0F`.

## Audit rows

| Row | Status | Notes |
| --- | --- | --- |
| phase4_progress | PENDING | Expected under P5-A1; 5.0F re-verifies the final Phase-4 progress. |
| phase4_final_report | PENDING | Phase-4 handoff is not yet available; 5.0F must freeze and hash it. |
| verdict_GO_PHASE5 | PENDING | Phase 4 has not reached Step 4.12. |
| selected_budget | PASS | Speculative selection follows the Phase-3 sole live candidate exactly. |
| all_acceptance_gates | PENDING | Requires final Phase-4 gate matrix and verdict. |
| phase4_ci | PENDING | Requires Phase-4 evidence and closeout CI attestation. |
| benchmark_cleanup | PENDING | Phase-4 endpoints are still active by design; 5.0F must verify cleanup. |
| owner_approval | PENDING | Speculative preparation is approved; explicit post-GO progression approval remains required. |
| project_instruction_snapshots | PASS | Exact current instruction snapshots are private and hash-verified. |
| staging_topology_ready | PASS | Only the coordination worktree created by 5.0S now exists; all later staging runtime/config/service identities remain free. |
| project_connector_attachment_ready | PASS | Provisioning and explicit per-send routing are scriptable without modifying the primary connector. |
| project_connector_routing | PENDING_OWNER_CONFIRMATION | No persistent per-Project connector pinning exists in the observed control plane. This is not a 5.1 preparation blocker, but must be resolved before 5.2. |
| rollback_ready | PASS | Rollback inputs exist before any rollout-Project mutation. |
| production_isolation | PASS | Production checkout/config/unit/profile identities remain unchanged. |
| runtime_source_drift | PASS | No runtime/dependency drift from the approved speculative runtime source to the staging branch base. |
| test_tooling | PASS | Pinned test/runtime tooling is available at the approved source. |

## Connector routing finding

The observed connector model is account-level app plus link. Persistent per-Project app pinning is not exposed or verified. The current `connect_connector.py` helper patches `apps_privacy_control` only; it does not expose or verify `disable_auto_invocation`.

Before Step 5.2, the owner must confirm the containment mechanism. The proposed mechanism is to use a distinct staging app/link, explicit staging-app system hints for orchestrated rollout chats, and a Project-scoped routing convention that names the staging connector while preserving the canonical scheduling block. If the link schema is verified to accept `disable_auto_invocation`, set it to true on the staging link. Step 5.0F records the confirmed mechanism or blocks deployment.

## Pending final-audit rows

- `phase4_progress`
- `phase4_final_report`
- `verdict_GO_PHASE5`
- `all_acceptance_gates`
- `phase4_ci`
- `benchmark_cleanup`
- `owner_approval`
- `project_connector_routing`

## Bootstrap reconciliation

The manager-owned bootstrap state still records the same five task claims as claimed. The assignment packet marks the exact task, attempt, and claim IDs verified, and every matching findings file has an empty blocker list. The bootstrap file was not modified.

## Result

Speculative dependency audit passes for preparation only. Step 5.0F remains a hard gate before Step 5.2.
