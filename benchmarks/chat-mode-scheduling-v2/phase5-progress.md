# Chat mode scheduling v2 — Phase 5 progress

Status: **in progress — speculative preparation**

Amendment P5-A1 authorizes preparation through Step `5.1E` while Phase 4
continues. Step `5.0F` remains the mandatory final audit before Step `5.2`.

## Frozen entry identities

- Branch: `release/chat-mode-scheduling-v2-staging`
- Speculative Phase-4 base: `9e165fd26bda57d938c24c78a826f66f2d5f0440`
- Approved runtime source: `06bc1649c4bad9449470366da971649bb7620020`
- Phase-3 live candidate: `C300`
- Speculative selected budget: `300 s`
- Dependency audit: `r01` / `e27269fba4b0d95a8ae84c0bd85ed71057a381ee27e89f90ce4d916a215f538a`
- Task graph: `r01` (speculative) / `777a7953c9c46665fb1cd9aa932c4bd1b2f7fe941ac212223d322f34566892eb`
- Initial scheduler checkpoint: `26fe1b263d77cc9400fbbfff87e239e240756a02aed70ce44fc1a99680f662aa`

## Step status

| Step | Status | Notes |
| --- | --- | --- |
| 5.0S | complete | Speculative audit and scheduler bootstrap complete. |
| 5.0F | not_started | Required before 5.2; waits for Phase-4 closeout, final owner approval, and routing confirmation. |
| 5.1A | not_started | Released by 5.0S; external gates remain claim-time preconditions where declared. |
| 5.1B | not_started | Released by 5.0S; external gates remain claim-time preconditions where declared. |
| 5.1C0 | not_started | Released by 5.0S; external gates remain claim-time preconditions where declared. |
| 5.1C1 | not_started | Released by 5.0S; external gates remain claim-time preconditions where declared. |
| 5.1C2 | not_started | Released by 5.0S; external gates remain claim-time preconditions where declared. |
| 5.1C3 | not_started | — |
| 5.1C4 | not_started | — |
| 5.1D | running | 5.1B/5.1C4 verified; throwaway rollback rehearsal in progress. |
| 5.1E | not_started | — |
| 5.2 | not_started | — |
| 5.3 | not_started | — |
| 5.4 | not_started | — |
| 5A | not_started | — |
| 5.5@24 | not_started | — |
| 5E48 | not_started | — |
| 5.5@48 | not_started | — |
| 5E72 | not_started | — |
| 5.5@72 | not_started | — |
| 5.6A | not_started | — |
| 5.6B | not_started | — |
| 5.7 | not_started | — |

## Step 5.0S notes

- Five preflight findings were fanned in with matching task, attempt, and claim identities. All findings report no blockers.
- The manager-owned bootstrap state still showed those claims as `claimed`; the assignment packet marked the exact claims `verified`. The bootstrap file was not modified.
- The Phase-4 branch advanced during preflight. A fresh fetch/reconciliation selected `9e165fd` as the speculative base, and runtime/dependency paths remain byte-undrifted from `06bc164`.
- Phase-4 benchmark endpoints currently listen on ports 8110, 8111, 8113, and 8115 as expected. Staging port 8120 is free.
- `project_connector_routing` is `PENDING_OWNER_CONFIRMATION`. Connector control is account-level app plus link, not verified persistent Project pinning. The audit records the containment proposal that must be settled by 5.0F.
- Production checkout, services, config, primary tunnel profile, rollout Projects, connectors, and Phase-4 resources were not mutated.
- Final file-scoped pre-commit gate passed all applicable hooks after normalizing the progress table to the repository Markdown style.

## Scheduler checkpoint

- Complete: 1 (`5.0S`)
- Ready: 5 (`5.1A`, `5.1B`, `5.1C0`, `5.1C1`, `5.1C2`)
- Claimed/running: 0
- Blocked by predecessors, conditions, or final gates: 17

The ready nodes still re-check their declared external gates at claim time. In
particular, CPU-heavy preparation and staging-stack work must respect the
Phase-4 live-host isolation rule.
