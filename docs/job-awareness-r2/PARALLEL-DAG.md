# R2 parallel execution DAG and worker isolation

Status: ready for **R2-0 preparation**, not a claim that any R2 worker ran.

## Dependencies and gates

~~~mermaid
flowchart TD
  S["R2-0 read-only R1 validation, immutable R2 inputs"]
  A["R2-A isolated custom MCP connection"]
  B["R2-B trusted chat identity / isolation"]
  C["R2-C result receipt / pagination"]
  D["R2-D transport / latency / token"]
  E0["R2-E0 ChatGPT trial preparation"]
  E1["R2-E1 real Chat mode visibility canary"]
  E2["R2-E2 trusted per-chat reminder, receipt and A/B"]
  F["R2-F independent supervisor decision"]
  S --> A
  S --> B
  S --> C
  S --> D
  S --> E0
  A --> E1
  E0 --> E1
  E1 --> E2
  B --> E2
  C --> E2
  A --> F
  B --> F
  C --> F
  D --> F
  E1 --> F
  E2 --> F
~~~

Do not accidentally turn A→B, W1→D or C→A into implementation dependencies. A/B/C/D all consume frozen R2-0 input, not each other's unfinished code. R2-E2 is intentionally gated.

## R2-0 entry conditions

1. Verify no R2 writer already active and choose one unique R2_RUN_ID.
2. Freeze the exact R2 plan Git SHA and original product SOURCE_SHA. Document that product source has not changed, and test only against the actual pinned frozen source.
3. Inventory R1 results W1–W4 and all evidence indices and validate against the previously recorded revision; take SHA-256 of each source result, without modifying files. R1 W5 remains NOT_RUN.
4. Freeze versioned R2 synthetic fixtures, trial order, negative-case control data, and source hashes for all lanes. Never reuse a writable R1 spool.
5. Record installed Codex CLI version, model IDs and effort availability as distinct requested vs observed facts. Do not assume cached model names are usable.
6. Inventory existing Pi CPU/RAM/swap, unit health and unrelated running agents. Resource admission must avoid starving another project; do not stop existing jobs.
7. Pre-allocate exclusive result roots and independent Git worktrees for A/B/C/D; E0 gets a separate writable fixture/prompt namespace and single owner.
8. Build and SHA-fix five standalone input packets; inspect them for real user secrets and cross-write permissions.
9. Produce R2-0 preflight and run-manifest; if a real Chat plugin cannot be connected at R2-0, continue A–D and E0, marking only E1/E2 as gated.

## Parallel ownership

| Lane | Single owner | Exclusive workspace | Shared read-only | Prohibited |
| --- | --- | --- | --- | --- |
| R2-A | Codex gpt-6-sol/medium | workspaces/A, A/ | R1 evidence and R2-0 fixture | Production plugin, public tunnel changes or user account actions |
| R2-B | Codex gpt-6-astra/xhigh | workspaces/B, B/ | W2/identity sources and R2-0 | Unauthenticated chat-specific hints on production |
| R2-C | Codex gpt-6-astra/xhigh | workspaces/C, C/ | W3/receipt sources and R2-0 | Real job spool, output deletion |
| R2-D | Codex gpt-6-astra/high | workspaces/D, D/ | W1/W4 raw evidence and R2-0 | Global package upgrade, production port, full repeated R1 suites |
| R2-E0 | Chat-mode protocol preparation owner (Codex only offline if needed) | E0/ | Immutable A/B scripts | Browser/account/chat interactions before appropriate authorization |
| R2-E1/E2 | One genuine ChatGPT Chat interface operator | E/ | A/B/C artifacts only after each relevant gate | Codex Desktop-as-Chat, W5 self-grading |
| R2-F | Supervisor only | supervisor/ | Terminal A–E evidence | Worker code edits, CLI experiment execution, deployment |

Each CLI worker is a separate top-level Codex process. A healthy running worker must not receive a second overlapping writer. The supervisor reports active job ID, effective model/effort and last real evidence timestamp, not an inferred running status from a stale file.

## Run/cancel semantics

- Workers A/B/C/D may complete in any order. An A connection blocker does not stop B/C/D.
- Only on actual S0 corruption can all execution be blocked.
- If B finds no authenticated chat identity, E2 per-chat auto-reminder tests must be BLOCKED. E1 harmless direct tool-visibility may still proceed if A is connected.
- If C cannot provide defensible receipt, E2 auto-ack proof must be BLOCKED; E1 and a limited no-ACK behavior test can proceed.
- If W5 Chat subject model/effort cannot be pinned, E1/E2 BLOCKED and not counted as a Chat mode PASS.
- Absent/unsupported custom-plugin permission is an account capability blocker, not evidence that FastMCP's transport failed.
- Local code may use only disposable fixture processes, synthetic tools and individually owned temporary ports, bound to loopback by default. No shared GUI/browser profiles.
- Per-stage targeted tests only; a worker must not run the full Binnacle repository suite for a synthetic evidence task.

## Synthesis states

R2-F starts once A–D and E0 are terminal and E1/E2 are either terminal or explicitly BLOCKED with provenance. It validates result manifests, structured evidence, hash consistency, raw tool-call events and absence of cross-chat leaks. No worker self-grades a cross-lane gate.

Decision is one of: GO_TO_IMPLEMENTATION_PLAN, CONDITIONAL_GO, NO_GO, INCONCLUSIVE. None is production implementation or rollout authorization. Even GO merely licenses a separately reviewed implementation plan.
