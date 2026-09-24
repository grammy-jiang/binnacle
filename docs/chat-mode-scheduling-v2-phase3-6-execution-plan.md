# Chat mode scheduling v2 — Phase 3–6 execution index

Status: **PLANNED; PHASE 3–6 NOT STARTED**

This file is intentionally short. The original combined Phase 3–6 runbook was
split because loading four long phases at once made dependency state harder to
see and increased the risk that a cold-start agent would silently assume an
upstream phase had passed.

Use **one phase document at a time**:

- Phase 3: `docs/chat-mode-scheduling-v2-phase3-execution-plan.md`
- Phase 4: `docs/chat-mode-scheduling-v2-phase4-execution-plan.md`
- Phase 5: `docs/chat-mode-scheduling-v2-phase5-execution-plan.md`
- Phase 6: `docs/chat-mode-scheduling-v2-phase6-execution-plan.md`

## Canonical stacked branch topology

Later phases use a **stacked-branch workflow**. A later phase never skips its
immediate predecessor merely because the predecessor's tree is already present in
`master`/`proof-of-concept`.

```text
public integration refs:
  master / proof-of-concept
        |
        v
Phase 0: feature/chat-mode-scheduling-v2-phase0
        |
        v
Phase 1: feature/chat-mode-scheduling-v2-phase1
        |
        v
Phase 2: feature/chat-mode-blocking-wall-guard
         (Phase 2 implementation + completed test-efficiency maintenance)
        |
        v
Phase 3: feature/chat-mode-scheduling-v2-phase3
        |
        v
Phase 4: feature/chat-mode-scheduling-v2-phase4
        |
        v
Phase 5: release/chat-mode-scheduling-v2-staging
        |
        v
Phase 6: release/chat-mode-scheduling-v2-phase6-review
```

The separate `planning/chat-mode-scheduling-v2-phase3-6` branch carries planning
documents and is itself rebased on Phase 2 while Phase 3 has not started.

When the public base changes, do **not** rebase an upper phase directly onto the
new public tip. Restack from the earliest affected lower layer in order:

```text
public/master-side changes
-> Phase 0
-> Phase 1
-> Phase 2
-> Phase 3/planning
-> later active phase branches
```

At planning-time restack on 2026-09-24, current Phase-2 content was verified
tree-identical to `master`/`proof-of-concept` while retaining the explicit
Phase0->Phase1->Phase2 history. This historical equality does not permit future
phases to bypass predecessor branches.

## Dependency DAG

```text
Phase 2 COMPLETE + 2.12a
        |
        +---- test-suite efficiency program FINAL + CI green
        |
        v
Phase 3.0 dependency audit PASS
        |
        v
Phase 3 offline replay COMPLETE
        |  live candidate shortlist + R4/R6/R10/R12 + provenance
        v
Phase 4.0 dependency audit PASS
        |
        v
Phase 4 live A/B/C/H COMPLETE
        |  verdict must be GO_PHASE5
        |  + explicit owner approval
        v
Phase 5.0 dependency audit PASS
        |
        v
Phase 5 staged deployment COMPLETE
        |  Stage-1 PASS after 24/48/72h observation + Stage-2 smoke + T0
        v
Phase 6.0 dependency audit PASS
        |
        v
Phase 6 24h/7d review -> final operational verdict
        |
        +-- GO + explicit owner approval -> primary integration
        |                                -> primary 24h confirmation
        |
        +-- FAIL -> rollback / stop
```

## Hard rule: each phase re-audits its dependencies

A conversational statement such as "Phase 3 is done" is not an entry condition.
Every phase begins with a numbered **N.0 Dependency Audit / Entry Gate** in its
own document. That step must read and hash the previous phase's canonical
progress/report/supporting evidence, verify Git lineage and CI, verify external
prerequisites, and write a dependency-audit JSON/Markdown artifact.

No Phase N implementation, parallel worker, live trial, connector mutation,
deployment action, or observation timer starts until Phase N.0 is committed with
`overall_status=PASS`.

If a hashed dependency or frozen external identity changes later, the audit is
invalidated and N.0 must be rerun before work continues.

## Canonical final artifacts and handoffs

| Phase | Final report | Next-phase handoff |
| --- | --- | --- |
| 3 | `phase3-policy-replay-YYYY-MM-DD-rNN.{json,md}` | live candidate shortlist + corpus/scenario/provenance hashes |
| 4 | `phase4-live-confirmatory-YYYY-MM-DD-rNN.{json,md}` | verdict + selected budget + source/instruction identities |
| 5 | `phase5-staged-deployment-YYYY-MM-DD-rNN.{json,md}` | Stage-1 verdict + Stage-2 T0 + staging/rollback identities |
| 6 | `phase6-post-deployment-review-YYYY-MM-DD-rNN.{json,md}` | terminal Phase 0–6 result; no implicit next phase |

Each phase's progress JSON contains a `handoff` object. The next phase's N.0
dependency audit recomputes report/artifact hashes and must reject disagreement.

`rNN` starts at `r01`; reopening/re-auditing never overwrites committed evidence.
The progress/handoff object names the one current canonical revision.

## Parallelism model

Maximum planned concurrency is four ChatGPT sessions. Parallelism occurs only
inside phase-defined waves with separate worker worktrees and disjoint ownership.
Canonical progress, integration, live shared Project/connector mutation,
deployment, and final verdict steps remain serial.

High-level waves:

| Phase | Parallel wave | Up to 4 sessions |
| --- | --- | ---: |
| 3 | corpus / replay engine / scenarios / provenance | 4 |
| 3 | C120 / C300 / C600 / H10 replay | 4 |
| 4 | endpoint / harness / analyzer / setup audit | 4 |
| 4 | targeted candidate calibration | 4 |
| 4 | evidence review | 4 |
| 5 | Stage-1 observation review (24h; repeated at 48/72h only if activity is insufficient) | 4 |
| 6 | T+24h review | 4 |
| 6 | T+7d review | 4 |

Phase-4 full A/B/C timing is parallel only if its quantitative contention
qualification passes; otherwise it is serial/randomized.

## Current checkpoint

At index split time:

```text
Phase 0 COMPLETE
Phase 1 COMPLETE
Phase 2 COMPLETE including 2.12a
Phase 3 NOT STARTED
Phase 4 NOT STARTED
Phase 5 NOT STARTED
Phase 6 NOT STARTED

test-suite efficiency optimization:
  COMPLETE — Step 3.7 PASS; final workflow integrated into proof-of-concept/master
  planning-time integrated base: 77a3f03
  authoritative planning-time fast runner:
    uv run python scripts/run_test_suite.py --workers 4 --seed 12345
  authoritative planning-time coverage gate:
    uv run tox -e coverage-policy -- --seed 12345

next scheduling-v2 execution action:
  execute Phase 3 Step 3.0 dependency audit against the current Phase-2 branch;
  Step 3.0 first verifies the full Phase0->Phase1->Phase2 stack is fresh relative
  to current master/proof-of-concept and restacks lower phases first if required
```

Planning branch:
`planning/chat-mode-scheduling-v2-phase3-6`

Splitting/reviewing these documents does **not** start Phase 3.
