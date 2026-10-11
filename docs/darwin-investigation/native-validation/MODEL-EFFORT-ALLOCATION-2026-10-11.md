# Binnacle macOS — agent model and reasoning-effort allocation

**Date:** 2026-10-11 (Australia/Sydney AEDT)
**Scope:** Binding allocation for Mac-first native development, safety review and multi-host verification.
**Permission:** User authorized autonomous design, implementation, guarded master integration and cleanup once full acceptance is proven. This document is not evidence of product acceptance.

## Mandatory launch contract

Every local AI worker MUST have a task manifest containing: lane ID; unique owner; model; effort; target Mac worktree and branch; exact base commit; file ownership allowlist; prerequisite gate; output/result log paths; focused tests; timeout; retry limit; and independent-review requirement. Record actual CLI arguments and observed model evidence. Never silently rely on a default model/effort. If a CLI cannot independently attest to its effective backend, report requested model/effort separately from observed identity.

Launch Codex on Mac through authorized Pi SSH. A supervised native invocation must pass model and effort explicitly as CLI options, use the project's own uv/Python venv, and keep workspace-write scoped to a dedicated worktree. Reviewers use read-only sandboxes and independent worktrees. CLI examples are in DEVELOPMENT.md and docs/mac-first-development-workflow.md.

## Model and effort matrix

| Lane | Objective and exclusive owned output | Model | Effort | Why and checkpoint |
| --- | --- | --- | --- | --- |
| G0 | Read-only Git master and dependency baseline, Linux ABI inventory | gpt-6.1-sol | medium | Mechanical SHA and evidence comparison; no source edits |
| G1 | Branch sync, SSH restart recovery, dual-target MyPy, source-quality safeguards | gpt-6-astra | high | Git mutation security; independent review required |
| G1-M | Module-size refactor, test fixture splitting, formatting, CI wiring | gpt-6.1-sol | medium | Mechanical changes; same semantics and focused tests |
| A0 | Native interface contracts, capability matrix, source-file ownership plan | gpt-6-astra | high | Architecture design before dispatch |
| A1 | Linux StopIntent, reaper and crash-durable process-safety gates | gpt-6-astra | xhigh | Highest process correctness and compatibility risk |
| A2 | Darwin process authority, witness supervision, loss behavior, Commands fail-closed | gpt-6-astra | xhigh | No stale PID fallback, independent native security acceptance |
| A3 | launchd user manager/frontend, AF_UNIX peer identity, generation IPC | gpt-6-astra | high | Authenticated lifecycle and race controls |
| A4 | Darwin Files/Search root descriptors, TCC scope and ripgrep adapter | gpt-6-astra | high | TOCTOU and filesystem security |
| A5 | Native private logs and epoch-safe telemetry, explicit UNAVAILABLE fields | gpt-6-astra | high | Integrity, crash/restart and privacy |
| A6 | Native arm64 wheel, locked dependencies, packaging and setup mechanics | gpt-6.1-sol | medium | Defined mechanical acceptance |
| T0 | macOS-safe unit fixture and pytest collection adaptation | gpt-6.1-sol | medium | Preserve Linux-only tests and meaningful Mac coverage |
| R0 | Independent review preparation and source traceability | gpt-6-astra | high | No author ownership |
| R1 | Exact-SHA process-control/IPC independent security audit | gpt-6-astra | xhigh | Mandatory high-stakes review |
| R2 | Exact-SHA Files, TCC, logging and platform acceptance audit | gpt-6-astra | high | Independent of authors |
| I0 | Integration owner, conflict resolution, GitHub CI, guarded merge | gpt-6-astra | high | One integration writer and exact-SHA gates |
| E0 | Mac test-owned MCP handshake, smoke, CLI/client interoperability | gpt-6.1-sol | medium | Local native protocol validation |
| E1 | Chat vs Work connector/API and auth/security integration | gpt-6-astra | high | Distinct runtime/connection verification |
| D0 | Documentation, results ledger and onboarding guide | gpt-6.1-sol | medium | Low-risk drafting and evidence formatting |

Do not use xhigh for routine shell operations, tests, documentation or dependency installations. Escalate only after a logged substantive blocker. The independent reviewer cannot approve its own authored code.

## Dependencies, concurrency and cost control

The real Mac was observed with 18 logical cores and 128 GiB RAM. Start at up to four disjoint source authors plus one or two reviewers, at most two xhigh jobs. Adjust dynamically for active machine load; do not apply Pi's four-core concurrency cap to Mac. Keep unrelated Pi job-awareness workers unaffected. Eight test workers for focused macOS pytest may be useful, but never run multiple full suites in parallel just to maximize CPU.

G0 must pin current GitHub master, then A0 freezes contracts. G1 infrastructure can progress concurrently with A0. Once both gates pass, A1/A2/A3/A4/A5/A6/T0 may run in parallel in separate Mac worktrees without overlapping ownership. A3/A2 integrate only after the IPC/process contract is frozen. R0 may start rubric work early, but R1/R2 exact candidate reviews wait for frozen author commits. I0 accepts only independently reviewed outputs.

At each author iteration run minimal directly affected tests, dual-target type checks only when changed Python files require them, and targeted pre-commit. When all lanes converge, run a single comprehensive Mac/Linux test, coverage and package matrix with the complete GitHub seven-check gate. Do not mask Darwin full-suite collection failure while the native platform adapter is not implemented.

## Native product safety and staged deployment

Darwin N2 after loss of both trusted manager and witness remains unproven; preserve fail-closed UNKNOWN or reduced Commands until authority is demonstrated. No arbitrary PID/PGID signaling, private libproc adoption by assumption, or fabricated cgroup-wide counters. Closed-lid 70-second foreground trials do not prove sleep, logout or pre-unlock operation. Use test-owned launchd labels only before product gates.

After all features are accepted, full Mac+Linux suites and exact-SHA independent reviews pass, and required GitHub CI checks are green, integrate via the repository's protected master/deployment workflow. Preserve other owners' branches. Cleanup requires explicit project ownership and proof that the tree is clean, merged and idle; no blanket worktree pruning.

ChatGPT ordinary Chat connector and Work mode are two distinct acceptance targets. Native MCP over SSH or local stdio does NOT prove end-to-end ChatGPT custom connector activation. Validate each available surface separately; connector creation/enabling may require a user UI action. No exposure of an unauthenticated Mac service to the LAN.
