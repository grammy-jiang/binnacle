# Prelaunch audit and exact operator checklist

Status: DOCUMENTATION / CONTRACT REVIEW COMPLETED; **REAL EXPERIMENTS NOT STARTED**.

Audit scope: source branch research/job-awareness-parallel-verification-20261010, initial documentation commit ff37b869571b105983dd34abb0351ecebfd26540 and the present review changes. The exact current plan commit SHA must be recorded after this review is committed. Binnacle production master is not changed by this review.

## 1. Findings from the final input/output audit

| Review area | Detected weakness before this round | Corrective artifact | Verification |
| --- | --- | --- | --- |
| Per-case inputs | W1–W5 scenarios were described but individual input paths and dependency contracts were not frozen | STEP-IO-MATRIX.md, step-io.json, schemas/step-io.schema.json | Static plan validator cross-checks all 6 S0 + 39 worker + 5 supervisor step IDs and no cross-worker result dependencies |
| Paired performance statistics | W4 previously lacked a pair ID and did not permit negative candidate-minus-control latency | Added pair_id and signed nearest-rank percentile reproducibility | Aggregates recomputed from raw paired measurements; no fabricated nonnegative overhead |
| Per-file formats | Terms such as result, evidence and matrix lacked one authoritative format | I-O-FORMATS.md, schemas/*.schema.json | Strict versioned JSON schema, CSV header order, JSONL event contract |
| Model/effort handoff | CLI plan requested a model but there was no durable startup proof that an agent actually selected it | HANDOFF-MODEL-AND-EFFORT.md, schemas/model-selection.schema.json, mandatory Wn/model-selection.json | CLI/GUI requested and effective model+effort independently checked before a PASS |
| W5 dual models | Initial worker-result subject-model object differed from the executor model validation format | Unified model schema for both actor/ChatGPT subject | Contract negative tests fail on missing subject model verification |
| Proof provenance | Server-sent tool response could be mistaken for client receipt/model action | events.jsonl proof layers, indexed raw trace and semantic_evidence.py | Fail-closed checks for unsupported proof promotion and false ACK |
| Sample completeness | A worker could leave a scenario unreported or claim result PASS with absent artifacts | worker-result.schema.json, validate_contracts.py, evidence-index SHA checks | Every assigned scenario present, indexed traces and immutable input checksum checks |
| Worker independence | Possible hidden dependency on W1 selecting a winning result carrier before W5 could begin | Frozen S0 carrier/fixture matrix and distinct worker-input packets | W1–W5 have no worker-to-worker dependencies, S0-only starts |
| Desktop identity | Installed chatgpt launcher points to codex-launcher, not proof of ChatGPT Chat mode | DESKTOP-OPERATOR.md, surface-capability.schema and W5 prerequisite | Genuine Chat mode cannot be claimed by Codex Desktop or Work |
| A/B validity | Unfixed model, trial order or incomplete pair could bias behavior claims | Frozen trial_schedule, W5 trials.csv schema/validation | Fixed ChatGPT subject model/effort, 12 registered pairs per viable carrier |
| Host safety | Primary Binnacle worktree was behind origin/master and dirty with unrelated docs | Isolated documentation worktree and worker worktree isolation | No reset/stash/clean of primary, no production source/service modification |

All worker execution outputs, including a BLOCKED result, retain provenance. An unobserved client receipt is UNKNOWN/blank, not silently false or acknowledged.

## 2. Actual pre-launch validation run

The following are checks of the **plan/contracts only**, not Job Awareness feasibility outcomes. The standalone verifier uses [validator-requirements.txt](validator-requirements.txt) to pin jsonschema==4.26.0 independently of Binnacle product dependencies. Run from the dedicated isolated worktree with the pinned dependency available in its dev environment:

~~~bash
uv run --offline python -m tests.job_awareness_feasibility.validate_contracts --plan
uv run --offline python -m unittest discover \
  -s tests/job_awareness_feasibility -p 'contract_suite.py' -v
uv run --offline ruff check docs/job-awareness-feasibility/*.py \
  tests/job_awareness_feasibility/*.py
~~~

The suite contains **32 synthetic contract validation tests passed** at final plan review. It generates complete, explicitly NOT_RUN synthetic S0, five worker outputs and manager decision in a temporary directory. Positive cases validate that a coherent packet is accepted. Deliberately negative cases reject incorrect hashes, incomplete worker scenarios, missing startup selector receipt, model/effort disagreement, false client ACK, absent raw evidence and inaccessible Chat mode masquerading as PASS.

The real test result of W1–W5 remains **NOT_RUN**.

## 3. Startup checklist for supervisor (next session; not executed now)

1. Confirm the approved plan commit and its repository branch, current origin/master SHA, model/effort policy, unmodified production services, and worker worktree safety.
2. Explicitly hand off prompts/S0.md to Codex CLI using **gpt-6-sol / medium**; no ambient defaults. Require S0/preflight.json and all frozen inputs. If an account connection/GUI capability requires a user action, record that one scoped W5 prerequisite; do not block four CLI lanes.
3. Run the structural validator --run RUN_ROOT, compare source/plan/fixture hashes, available RAM/CPU, resource namespace and the requested models before authorizing fan-out.
4. Send each worker **only** its frozen inputs/Wn.input.json, exact prompt and writable namespace. Start W1 Codex gpt-6-astra/high; W2 Claude opus/high; W3 Codex gpt-6-astra/xhigh; W4 Claude sonnet/medium; W5 operator gpt-6-astra/high (if supported), genuine ChatGPT subject GPT-6/Medium. Explicit CLI/UI selectors are mandatory.
5. Require a Wn/model-selection.json receipt before experiments; if unavailable/unsupported, the worker returns a complete BLOCKED report and no silent model substitution.
6. Launch W1–W5 **concurrently after S0**. Give W5 exclusive physical Desktop control; A/B/C test chats can interleave, but do not create multiple GUI owners.
7. Each worker executes only its own scenarios and outputs model-selection.json, results.json, events.jsonl, evidence-index.json, findings.md and lane-specific CSV/JSON. PASS/FAIL means tested evidence quality; hypotheses SUPPORTED/REFUTED separately.
8. Collect each terminal packet without modifying its files. Validate using --worker RUN_ROOT Wn; if a worker is active, don't launch a second writer. If a worker is BLOCKED, other lanes continue.
9. When all lanes have terminal evidence, reconcile only by RUN_ID/source/docs/fixture SHA, proof layers, actual model selector receipts and scenario traces. The supervisor writes decision.json and MANAGER-SUMMARY.md only.
10. Validate with --final RUN_ROOT, submit one Chinese management summary. No implementation, PR, production merge, deploy or restart authorized by this feasibility plan.

## 4. Mandatory stop conditions (lane-specific, not blanket project stop)

| Observation | Correct response |
| --- | --- |
| Source, plan, fixture or worker input hash mismatch | Reject the run or relevant worker packet; regenerate with new RUN_ID |
| Worker model or effort unavailable | Return BLOCKED/UNAVAILABLE in startup receipt; do not silently fall back |
| ChatGPT Desktop cannot operate true Chat mode | W5 BLOCKED, W1–W4 continue independently |
| Cross-chat Job ID leaked in test | G3 FAIL and isolate/terminate unsafe reminder arm; do not downgrade isolation |
| Result was served but no client receipt evidenced | Do not ACK; W3 records unsupported implicit receipt if appropriate |
| Missing raw trace or invalid JSON/CSV/hash | Worker output is invalid, return to same worker for bounded correction |
| Performance affected by uncontrolled concurrent host load | Preserve raw results, classify performance INCONCLUSIVE |
| ChatGPT user turn ends before another tool response | Record platform boundary; don't claim MCP hints can wake the turn |
| Agent claims completed without output schemas, events, selected model proof | Treat as missing evidence; no manager GO |
| Resource cleanup fails | Record exact owned test resource and cleanup blocker; never delete production data |

## 5. Ready to begin — decision boundary

**The plan and evidence contracts are ready for the S0 preparation gate once committed and reviewed.** This does not assert the production candidate, vendor model availability, real Chat mode access or the tested Job Awareness mechanism are ready.

At startup, a genuinely unavailable model or ChatGPT UI route is a **measured blocker**, not permission to use defaults or an unapproved transport. The CLI lanes must continue wherever they can safely produce independent results.

The Supervisor's only substantive deliverable is a verified synthesis; it does not implement or execute the worker experiments.
