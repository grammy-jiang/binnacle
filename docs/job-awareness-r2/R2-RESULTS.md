# R2 Job Awareness — execution results ledger

**Status: RUNNING / PARTIAL EVIDENCE — not a final Go/No-Go decision.**

This file is the user-facing reporting document for the separate R2 study. It is updated **only after inspecting concrete worker evidence**. The frozen testing contracts remain pinned to R2 docs SHA cc386613a20f14cd466f19d0fbd3e38ec6ce9927 regardless of later reporting-only commits to this research branch.

## Investigation lineage

- Final R1 results: [R1 investigation report](https://github.com/grammy-jiang/binnacle/blob/50cca28695dce8b2f11810b92aa792179b0e9eb4/docs/job-awareness-feasibility/R1-INVESTIGATION-RESULTS.md).
- R2 evidence handoff: [R1 → R2](R1-EVIDENCE-HANDOFF.md).
- R2 run ID: R2-20261010-191506-889bdb8e.
- R2 experiment evidence root: /home/grammy-jiang/Projects/binnacle-job-awareness-r2-results/R2-20261010-191506-889bdb8e.
- Product source SHA: d61761356ee0fce8ea6d73b0c3043b4881c5645e.
- Frozen R2 plan SHA: cc386613a20f14cd466f19d0fbd3e38ec6ce9927.
- Frozen R2 fixture SHA-256: 74c97e6d1b35f86be8484560d4cbb3f7a56090ceaa87da4303a206771016847e.

## Verified progress at 10 October 2026, 19:25 AEDT

| Lane | Model and effort requested | Observed status at snapshot | Available evidence |
| --- | --- | --- | --- |
| R2-0 input freeze | Codex gpt-6-sol / medium | **Completed, PARTIAL** | R2-0/preflight.json, R2-0/readiness.md, run-manifest.json |
| R2-A private test connection | Codex gpt-6-sol / medium | **Running** | Live Codex process and _coordinator/A-events.jsonl |
| R2-B trusted chat identity | Codex gpt-6-astra / xhigh | **Running** | Live Codex process and _coordinator/B-events.jsonl |
| R2-C authenticated receipt | Codex gpt-6-astra / xhigh | **Running** | Live Codex process and _coordinator/C-events.jsonl |
| R2-D HTTP/compatibility/cost | Codex gpt-6-astra / high | **Running** | Live Codex process and _coordinator/D-events.jsonl |
| R2-E0 offline Chat trial preparation | Codex gpt-6-sol / medium | **Completed, PASS** | E0/results.json, E0/model-selection.json, E0/evidence-index.json |
| R2-E1 actual Chat mode visibility | Genuine ChatGPT GPT-6 / Medium | **BLOCKED / NOT RUN** | Real test app connection/account permission not established |
| R2-E2 multi-chat workflow/receipt A/B | Genuine ChatGPT GPT-6 / Medium | **BLOCKED / NOT RUN** | Requires E1 and proven B/C safety/receipt gates |
| R2-F independent supervisor synthesis | This coordinating ChatGPT | **NOT DONE** | This preliminary ledger is not a final multi-worker decision |

R2-0 successfully froze 12 synthetic jobs, 12 pre-registered trial pairs for each of META, TEXT and STRUCT, five independent input packets and separate product-source checkouts. All seven R2-0 JSON schemas and packet/input hash references were reported PASS. The host independently verified production service health. No R2 feature implementation or production deployment has occurred.

## Next evidence collection

On A/B/C/D termination, for each lane check results.json, model-selection.json, events.jsonl, evidence-index.json, all lane-specific CSV/JSON traces and exact SHA provenance. A worker exit code 0 is not proof of all assigned hypotheses. An initial positive result limited to simulated transport is not a true ChatGPT receipt.

Update this document with factual findings, limitations, any failed security/receipt design assumptions and status of actual ChatGPT client permission. Only when all lanes are terminal or honestly BLOCKED should R2-F issue the G0–G7 matrix, decision and final Chinese Supervisor summary.

At this report snapshot, **R2 is underway but not finished**. In particular there is no completed real ChatGPT Chat model-visibility or workflow experiment.
