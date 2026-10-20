# Development Intelligence testing — public surface, CI, and release gates

| | |
| --- | --- |
| **Status** | Split from the revalidated 2026-09-30 testing design |
| **Current baseline** | `f1493ee` |
| **Purpose** | Future public-tool contracts, CI lanes, reproducibility, coverage, phase gates, and stop conditions |
| **Project index** | `docs/lsp-development-intelligence/README.md` |

> Read only the sections required by the current implementation-plan work item.

---

## 19. Future public-tool contract tests

Create these only after the corresponding product gate approves a public tool.

### 19.1 `inspect_symbol` metadata and schema

If semantic navigation is approved, assert:

- name exactly `inspect_symbol` unless the product experiment selected a better final name;
- `readOnlyHint=true` only when every enabled provider profile satisfies the READ policy;
- `openWorldHint=false` if that remains truthful;
- a small model-friendly anchor schema;
- bounded references/result budget;
- explicit ambiguous/partial/unavailable semantics.

### 19.2 `inspect_symbol` semantic contract

Cases:

- unique definition;
- same-name ambiguity;
- imported/re-exported symbol;
- bounded references with total/truncation;
- unsupported hover/type capability;
- stale disk change synchronized before query;
- provider missing;
- provider timeout/crash;
- path outside roots.

No response may fabricate a unique resolution when the provider result is ambiguous.

### 19.3 `check_code` metadata and coverage

If diagnostics is separately approved, assert:

- name exactly `check_code`;
- truthful READ/open-world annotations;
- minimal path input unless evidence justified more;
- bounded output;
- description states what counts as unavailable/partial.

Coverage cases:

- one provider succeeds, zero diagnostics -> provider listed and analyzed scope explicit;
- one provider unavailable, another succeeds -> exact ok/partial policy;
- selected provider fails -> partial/unavailable;
- no eligible provider -> unavailable, not "clean";
- output truncated -> counts/coverage/truncation truthful.

### 19.4 Side-effect gate for every public READ tool

Run the actual public tool against synthetic projects and compare full manifests.

A single workspace mutation or project-code execution caused by an enabled profile fails
the READ contract.

### 19.5 Intentional ChatGPT surface change

When a tool is intentionally enabled:

- update `client_tools`;
- update `tests/contracts/test_tool_surface.py` tool count/order/hashes;
- add/update golden output snapshot(s);
- measure `tests/contracts/test_surface_tokens.py` and document any budget increase;
- update server instructions/description deliberately;
- run the quality guard's deploy smoke and client-compatibility checks.

If `inspect_symbol` is added first, `check_code` would be a possible **eighth** ChatGPT
tool, not automatically "the seventh".

---

## 20. CI strategy

Do not make the default CI dependent on globally installed language servers.

Suggested lanes:

### Lane A — normal fast suite

Runs on every PR:

- framing;
- dispatcher;
- positions;
- profiles;
- fake provider integration;
- analyzer fake integration;
- existing contracts.

### Lane B — integration/process suite

Runs on every PR or main CI depending on runtime:

- real subprocess fake LSP server;
- concurrency;
- timeouts;
- process-group cleanup;
- FastMCP lifespan.

### Lane C — integration performance guard

Extend or closely mirror the existing `scripts/weekly_bench.py` temporary-server harness.

Cover:

- startup;
- provider-absent baseline;
- manager-enabled/no-provider overhead;
- resident-provider overhead on existing six tools;
- fake-provider/private semantic call overhead;
- candidate public-tool call only in a temporary non-production profile.

Use regression ratios plus absolute deltas. Do not make normal CI depend on
machine-specific real-provider timings.

### Lane D — standalone real-provider benchmark

Developer/local or scheduled lane with explicitly installed/versioned providers.

Run the multi-provider matrix and write a machine-readable benchmark artifact containing
latency, correctness, process-tree RSS, versions, and workload identity.

Run it under the same isolation philosophy as `scripts/weekly_quality.py`: never in the
production checkout, never against the production server, and abort/defer when the host is
not quiet enough for meaningful performance data.

Do not block normal packaging on provider availability unless Binnacle later chooses to
ship one as a dependency, which this design currently rejects.

---

## 21. Test data and reproducibility

Every semantic corpus case should record:

- repository fixture commit/hash;
- query;
- gold file/symbol evidence;
- why the gold is correct;
- expected ambiguity;
- allowed result variants if appropriate.

Every live provider measurement should record:

- provider executable path;
- version;
- Binnacle commit;
- Python version;
- host class;
- cold/warm condition.

Never silently compare measurements from different provider versions as if they were the
same experiment.

---

## 22. Coverage and mutation-testing expectations

New protocol/state code is highly branchy.

Targets should include:

- branch coverage for framing/error paths;
- mutation tests for:
  - timeout comparison;
  - max-size guards;
  - request-ID matching;
  - state transitions;
  - read-only profile classification;
  - process escalation logic;
  - result truncation boundaries.

Do not chase mutation score by writing meaningless assertions. Focus on decisions where a
mutant could weaken safety or create a hang.

---

## 23. Phase-by-phase quality gates

### Gate 0 — harness

Pass before production protocol code:

- fake server can emulate all required success/failure modes;
- side-effect harness catches intentional write;
- process-tree fixture is observable.

### Gate 1 — protocol/lifecycle

Pass before real provider profile:

- framing/dispatcher green;
- all pending requests resolve on exit;
- shutdown/reload leaves no processes;
- Unicode position tests green;
- existing six-tool contracts unchanged.

### Gate 2 — cross-provider characterization and audited profiles

Pass before private semantic integration:

- standalone benchmark harness works across every installed target provider;
- Python, TS/JS, Rust, C/C++, Markdown, and Shell have gold-validated compatibility
  results on this host;
- Makefile is explicitly `not_installed` until a benchmark environment provides it;
- Pyright/Ruff diagnostic profile side-effect tests pass;
- no project-local auto-execution;
- service-PATH absence handled quietly.

### Gate 3 — private MCP integration and semantic navigation

Pass before any public semantic tool experiment:

- feature-off/absent/manager-only/resident-provider overhead is within the provisional
  budget;
- raw LSP and end-to-end Binnacle timings are both available;
- existing tool-surface/golden/token contracts stay unchanged;
- reviewed symbol-navigation corpus has strong correctness;
- private `inspect_symbol` A/B shows measurable workflow benefit;
- resident p95/p99 latency fits budget.

### Gate 4 — public semantic-navigation tool

Pass before adding `inspect_symbol` to ChatGPT:

- temporary-profile model tests select/use the candidate reliably;
- A/B improves at least one meaningful workflow metric without quality regression;
- full side-effect contract is green for every enabled provider;
- tool surface/golden/token budget changes are intentional and reviewed;
- post-deploy/client-compatibility gates are green.

### Gate 5 — public diagnostics tool

Pass before adding `check_code`:

- real usage need is established;
- A/B beats the current `run_command` workflow on meaningful metric(s);
- full side-effect contract is green;
- public-surface cost remains acceptable given any previously added semantic tool;
- live/client-compatibility gates are green.

---

## 24. Stop conditions

Stop or redesign rather than "finish the roadmap" if any of these occurs:

- provider lifecycle cannot be made leak-free under source reload;
- read-only profiles cannot be proven workspace-safe;
- resident semantic calls are slow or resource-heavy enough to erase workflow benefit;
- `inspect_symbol` does not improve reviewed symbol-navigation tasks or model-step
  efficiency versus current search/read workflows;
- provider availability is too low to justify complexity;
- standing MCP surface/token cost is larger than the measured workflow gain;
- `check_code` does not materially improve real workflows over `run_command`;
- protocol/library complexity becomes disproportionate to measured benefit.

The removed indexed-context pilot is a precedent for stopping a fast implementation that
fails the actual workflow-quality bar.

---

## 25. Definition of done for the investigation-to-implementation handoff

Another AI agent with no prior conversation should be able to start Phase 0 using only:

1. `docs/lsp-development-intelligence-design-2026-09-27.md`;
2. this testing design;
3. the project-local references listed by the parent design;
4. current source/tests on master `f1493ee` or a later explicitly revalidated baseline.

Before coding, that agent should understand:

- why LSP is optional;
- why READ safety is stricter than "no fix flag";
- why project-local executable auto-discovery is prohibited;
- why cold/settling/warm are benchmark conditions while lifecycle stays simple;
- why current `search_text` must remain exact-only;
- why the removed indexed-`@context` pilot is historical evidence, not an integration host;
- why semantic navigation and natural-language repository retrieval are separate problems;
- why private `semantic.inspect_symbol(...)` is tested before any seventh tool;
- why `check_code` is a separate later product decision;
- why raw-LSP performance and Binnacle-integration performance are measured separately;
- how the current surface pins, golden outputs, token budget, weekly benchmark, and quality
  guard constrain implementation;
- why job cgroup accounting is a design precedent but not a drop-in LSP resource manager.

That is the quality bar for this planning branch.
