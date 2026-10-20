# Development Intelligence: agent capability portfolio

**Status:** Proposal only — candidate capabilities, not authorized public tools.
**Date:** 2026-10-20
**Source baseline:** Binnacle `ce943ced`, V2 docs `861ab299`, focused sub-server ADR `723e750d`.
**Purpose:** prioritize development-agent capabilities beyond raw LSP methods without duplicating Binnacle Files, Search or Commands.
**Decision owner:** P0.5 architecture/product review. No production feature or tool-surface change is implied.

## 1. Product thesis and measurable problem

Existing Binnacle provides file reading/editing, regex/literal search and process/command execution. Development Intelligence should give the AI agent **grounded code understanding, change risk evidence, precise test recommendations, and structured diagnostics**.

Recommended lifecycle: orient -> inspect symbol/structure -> assess change impact -> modify through existing tools -> choose and run tests through existing Commands -> analyze failures and quality evidence. The new child supplies code-aware evidence at the steps that today demand several separate shell/text interactions.

2026-09-27 usage analysis (historical, not a fresh October baseline):

- Approximately 26,403 precisely turn-attributed ChatGPT tool calls across 683 turns in that September window. A broader journal-derived count of 42,847 over-attributes work to ChatGPT; do not reuse it as a ChatGPT-only baseline.
- The most common workflows spend meaningful serial model steps on Python shell commands, file reading, source search, Git inspections, and test runs. Polling was separately identified as a major inefficiency, but belongs to durable Commands, **not** this sub-server.
- Older experiments found that adding batch file reads did not save enough *model steps* even when raw call counts looked large. Likewise, the removed indexed `search_text @context` feature had insufficient retrieval accuracy. Therefore measure full agent workflow benefit, not number of server functions or raw request latency.

## 2. Capability candidates, priorities and proof requirements

Priority refers to research/benchmark order, not a promise to publish a public MCP tool.

| Capability | Primary AI agent question | Internal engine / candidate data | Proposed priority | Risk or required proof |
| --- | --- | --- | --- | --- |
| **Symbol inspection** | What is this concrete symbol, definition and true references? | Existing V2 LSP inspect_symbol plan; optional type/hover | A0 / already planned | Position ambiguity, stale disk, incomplete cross-repository references |
| **Structured code query** | Which functions/classes/calls satisfy a syntax pattern, independent of formatting? | Python `ast` for PoC, Tree-sitter or ast-grep for languages | A1 | Distinguish syntax matches from semantically resolved usages; language/parser coverage |
| **Change impact assessment** | What is probably affected by this diff? | Bounded local Git diff, LSP references/type hierarchy, AST dependencies | A1 | Dynamic dispatch, over-claiming certainty and undiscovered external consumers |
| **Related test selection** | Which existing tests should I run first for these changed symbols/files? | Test file discovery, test IDs, reference evidence, optional per-test coverage contexts | A1 | Heuristic tests are suggestions, never permission to skip mandatory gates |
| **Code diagnostics** | What type/lint issues exist in the actual analyzed scope? | Existing V2 Pyright CLI, Ruff CLI and LSP diagnostics plan | A0 / already planned | Must report provider coverage, never falsely imply globally clean |
| **Failure triage** | What failed and where is the likely failure point? | Parsed pytest/JUnit/traceback, optional command job output adapter | A2 | Distinguish deterministic failure evidence from speculative root cause |
| **Semantic diff / review evidence** | How do code meanings/contracts change across a patch? | AST/API signatures + type/LSP + local diff | A2 | Do not pretend an automated review is proof of absence of bugs |
| **Safe refactoring preview** | Which exact files would a symbol rename affect? | LSP rename/code action as *preview only* | A2 | Preview may be incomplete; executing write/command is a distinct privilege |
| **Public API compatibility review** | Is an interface or configuration schema break likely? | Python exported signatures, OpenAPI/schema diff, type relationships | A2 | Dynamic reflective APIs need manual/explicit verification |
| **Project outline/orientation** | What are the likely entrypoints/modules/public symbols? | Bounded repository manifest, symbol outlines, package manifests | A2 (internal first) | Avoid resurrecting low-precision natural-language retrieval or creating a project memory store |
| **Data/control-flow investigation** | How may this input flow to the risky operation? | Optional targeted CodeQL/static analysis | A3 | Expensive and partial; dynamic Python makes global graph incomplete |
| **Interactive debugging** | Can the agent inspect a stopped execution and variable state? | Debug Adapter Protocol (DAP) behind an explicitly trusted debugger profile | A3 / separate design | Launch/attach/evaluate may execute code or expose secrets, cannot be READ |
| **Performance/profile interpretation** | Where is this workload slow or allocating heavily? | Existing profiler output + Python profiling tools | A3 | Execution authority, cost, reproducibility and trace volume |
| **Third-party/dependency security insights** | Which reachable package or code path creates risk? | Optional local dependency/provenance + vetted static rules | A3 | Network/trust/license, false positives, scope creep into package manager |

### A0/A1 recommendation

The highest marginal value beyond the existing LSP plan is a **change-centered workflow**:

- identify the changed code *semantically*, not just the textual Git diff;
- discover direct references and likely callers/implementations;
- suggest ranked tests and explain why each is relevant;
- optionally pair with a separate scoped diagnostic check;
- return source locations, confidence class, excluded scope and a short action-oriented summary.

Implement impact/test selection as internal composable services first. Do not build a repository-wide persistent graph just to deliver the first test.

### A2 recommendation

Failure triage should consume **existing test artifacts**, not reimplement `run_command`. Parsing a traceback, pytest node ID, failing assertion and concise application-frame stack can be deterministic. Root-cause hypotheses must be labelled as hypotheses and not silently counted as verified findings.

AST-aware rename and code-action preview are helpful, but write execution remains with explicit existing Files/Commands tooling and its approval path. Recheck the original source hash before applying any proposed edit.

### A3 recommendation

Treat DAP as a possible future sibling subsystem under the same Development Intelligence domain, not an assumed LSP extension. Interactive debugger launch/attach/evaluate is a higher-privilege process-control activity. Only start its design when a clear user task cannot be efficiently answered by the existing `run_command` and structured failure analysis.

## 3. What the Agent could call (not frozen public schemas)

An exploratory maximum of **four public intent-centered tools**, introduced *individually after separate A/B gates*, rather than 20+ raw LSP/AST commands:

| Candidate | Example input intent | Bounded result | Product release gate |
| --- | --- | --- | --- |
| `inspect_symbol` | path + line + text/column | accurate definition, references, type, provenance, scope | Existing V2 P4-P5 |
| `search_code_structure` | explicit syntax pattern or purpose-specific query | AST matched declarations/calls, capped locations, exact parser semantics | Separate syntax-search vs regex/search workflow comparison |
| `analyze_change` | local Git diff base/ref or explicit changed-file set | impacted declarations/references, ranked tests, incompleteness reasons | Correctness-qualified impact/test A/B and strict filesystem/command audit |
| `check_code` | path/project analysis scope | normalized diagnostics, used/skipped analyzers, actual coverage | Existing V2 P6 separate decision |

A future `analyze_failure` is conditional on proof that a structured failure diagnosis saves steps above existing command output, and must not increase standing tool surface until approved. `project_outline`, caller tree, test suggestions and semantic review may be nested results/modes only when they naturally fit the existing *single intent* and stay bounded; otherwise keep them private rather than stuffing one mega-tool.

Tool naming should be tested with ChatGPT and other target agents on **tool-selection and argument-generation** accuracy. Do not expose `lsp_definition`, `lsp_hover`, `tree_sitter_query`, `test_collect`, and `git_diff` as separate standing primitives without independent evidence.

## 4. Three internal engines, one focused sub-server

The fourth child `binnacle-development-intelligence` remains mounted on the existing Binnacle root, once public intent(s) are approved. Internally compose:

| Engine | Responsibility | Boundaries |
| --- | --- | --- |
| **Semantic engine** | Versioned LSP profiles, symbol identity, references, hover, available hierarchies | Provider capability is not proof of correctness; not the same as dynamic execution trace |
| **Syntax engine** | Pure or audited bounded AST parsing/query, named constructs, structural source snapshots | Grammar imports/dynamic extensions must be trusted, no unreviewed parser downloads or code execution |
| **Change and evidence engine** | Parse local Git diff, connect semantic/AST evidence, test relevance, code diagnostics/failure artifacts | No automatic Git fetch or remote connector, no build/test scheduling and no changes to the working tree |

Shared internal support: allowed root grants, content digests, result URI reauthorization, input and output bounds, language detection, provider provenance and sparse telemetry. Avoid a universal persistent index or complex distributed store until real model steps/correctness demonstrate necessity.

The existing Files/Search/Commands children remain unchanged. Sub-server logic calls internal native domain contracts where appropriate; it does not recursively invoke sibling MCP tools as an agent would.

### Source authority and evidence classes

- `precise`: LSP/compiler-backed response verified for the versioned document and authorized scope.
- `structural`: exact AST pattern match for a specified language/parser, **not** verified reference identity.
- `observed`: actually executed test/coverage/profiler evidence with run identity.
- `heuristic`: naming/convention/import approximation, not proof of completeness.
- `unavailable` / `partial` / `stale`: explicit coverage/trust/freshness reasons.

Never translate structural/heuristic results into a global claim such as 'all callers' or 'all impacted tests.' For Python, dynamic imports, monkey patching, reflection, plugin registration and runtime dispatch are material incompleteness sources.

Every result should disclose requested vs analyzed scope, source commit/content hashes, provider and version, total/truncation, stale status and directly navigable file/line evidence. Recheck external URIs against allowed roots before returning them to the caller.

## 5. Reuse and nonduplication rules

- **Files:** no new general `read_file`, `write_file`, `edit_file` or `list_files`.
- **Search:** no generic regex/literal replacement and no hidden `@context` resurrection; structural query semantics must be *explicitly different* and measured.
- **Commands:** no second generic shell runner, background job owner, test executor, profiler supervisor or `git` CLI tool. Test selection returns recommendations; execution continues through existing Commands. An explicitly audited, fixed-argv one-shot analyzer is permitted as a *private* analysis backend after security review.
- **Per-language MCP tools:** none. Provider profiles are internal to one sub-server.
- **Other local agents:** do not require ChatGPT-specific state or a global cluster controller.

Project-specific source/test mapping must preserve each repository's independence. There is no cross-host LSP daemon or central index.

## 6. Minimal validation program before adding the tools

Use independent labelled test groups, controlled by one manager and reported separately:

| Pilot | Minimum meaningful coverage | Primary metric |
| --- | --- | --- |
| Symbol navigation | Similar names, same-line duplicates, multi-file refs, Unicode, stale edits | Wrong-definition rate, correct references and model steps |
| Structural query | Regex-equivalent and syntax-distinct examples in Python/TS | Correct matching + false positives and tool selection |
| Change impact | Python method rename, public signature change, plugin/dynamic-dispatch negative, cross-file inheritance | Ranked evidence accuracy and **explicit** missed scope |
| Related tests | Parametrized pytest IDs, fixture-driven tests, renamed files, prior coverage contexts | Precision@k, critical-test recall on fixed gold set, total test-time cost |
| Failure triage | Assertion failure, import/setup failure, timeout, unexpected exit, multiple failures | Correct diagnosis/unknown rate, calls and tokens |
| Safety | False READ settings, parser extensions, symlink paths, stale ref/file, cache/process/network side effects | No unauthorized writes/exec, containment and truthful failure |

A/B each candidate against the existing six-tool workflow on identical real tasks, model settings and authorized roots. Pre-register minimum workflow gain and correctness thresholds before collecting final results. Track p50/p95 agent steps, tokens, wall time, wrong answer rate and memory/process impact separately. A faster response that produces a wrong or falsely complete answer is a product failure.

Test selection must never silently replace mandatory CI or repository quality gates. Run metadata and source/test evidence are versioned so a changed worktree cannot reuse stale conclusions.

## 7. Proposal on phased integration

1. Add this capability portfolio to **P0.5** discussion; do not prematurely treat proposed V2 LSP runtime/contract foundations as approved.
2. Finish original V2 private LSP navigation and Python analyzer foundations first.
3. Run a low-risk local Python `ast` proof of concept and test-oriented impact evidence without any public MCP registration.
4. Decide independently whether structural query and change impact justify a new standing surface. If two candidates fail, preserve the internal capability mapbook but stop exposing them.
5. Keep runtime debugging, refactoring edits, global CodeQL graphs, cross-repository SCIP indexing and project memory in a future ADR unless operational evidence justifies them.

## 8. External primary references (background, not deployed dependency approvals)

- [Official LSP 3.18](https://microsoft.github.io/language-server-protocol/): symbol/definition/references, hierarchies, diagnostics and edit surfaces.
- [Serena tools](https://oraios.github.io/serena/01-about/035_tools.html) and [Serena project](https://github.com/oraios/serena): symbol search, references, refactoring, diagnostics and editing. Its broader surface is not a requirement for Binnacle.
- [Tree-sitter queries](https://tree-sitter.github.io/tree-sitter/using-parsers/queries/1-syntax.html) and [ast-grep](https://ast-grep.github.io/guide/quick-start): syntax-aware matching distinct from string regex and type-aware LSP.
- [pytest node IDs and collection](https://pytest.org/en/latest/example/markers.html): selecting collected tests, not identifying all tests that cover a change.
- [coverage.py test contexts](https://coverage.readthedocs.io/en/latest/contexts.html): per-test coverage mapping **only when instrumented**.
- [CodeQL Python data flow](https://codeql.github.com/docs/codeql-language-guides/analyzing-data-flow-in-python/): local/global flows differ materially in precision and runtime cost.
- [Debug Adapter Protocol overview](https://microsoft.github.io/debug-adapter-protocol/overview): debugger launch/attach/breakpoint/step capabilities, not LSP.
- [Sourcegraph SCIP precise code navigation](https://sourcegraph.com/docs/code-navigation/precise-code-navigation): optional indexed cross-project evidence; an index introduces substantial additional production/refresh work.
- [Binnacle prior usage analysis](../usage-analysis-2026-09-27.md), [V2 mapbook](capability-mapbook-v2.md), [focused child ADR](adr-0001-focused-subserver.md).
