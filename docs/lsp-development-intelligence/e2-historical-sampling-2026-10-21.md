# E2 — stratified historical candidate sampling (2026-10-21)

**Verdict:** Technical E2 sampler **GO for private local internal use**; **E2 independent task-label/accuracy gate remains OPEN**. This is a proposal/sampling layer, not a task-correctness, replayability or product efficiency approval.

**Baseline:** LSP branch rebased to fetched `origin/master ab60a33`. Frozen local capture cutoff `2026-10-21T01:00:00Z` (12:00 AEDT, exclusive), matching [E0/E1](e0-e1-trace-pilot-2026-10-21.md). The three hosts' full-capture opt-in start times differ. No production LSP runtime/provider, MCP tool, logging service, historical command or cloud-connected reviewer was invoked to produce these results.

## 1. What was implemented

- `scripts/lsp_e02_selection.py`: deterministic group-level, multi-stratum candidate/negative-control classification and a seeded balanced selection policy. Existing E0/E1 exact correlations and bounded sequence checks are reused, not approximated with timestamps or command snippets.
- `scripts/lsp_e02_samples.py`: fixed-cutoff CLI with count-only reports, missingness and quality strata; selected cases receive **no** automatic task-goal, source-revision or Gold Answer certification.
- `scripts/lsp_e02_private.py`: optional owner-only local case manifest writer. Directory operations use non-symlink-following file descriptors with secure owner/mode validation; the existing parent must preexist and parent/final directory entries are synchronized before a completed write is reported. Files and local lookup key use mode `0600`, directory `0700`; exclusive atomic hardlink publication rejects conflicting batches and accepts only identical retries. The manifest contains opaque HMAC lookup references and categorical evidence, **not** raw commands, paths, source text, request identifiers or output.
- Synthetic tests: `tests/scripts/test_lsp_e02_samples.py` and `test_lsp_e02_durability.py`, including seeded reproducibility, negative controls, malformed evidence, privacy, nonblocking FIFOs, symlink substitution, concurrency, interrupted publication, file/parent fsync retry and cleanup failures.

A private `pilot-20261021-noon.json` plus host-specific `e02-local-key.bin` was written to each host's own `~/.local/state/binnacle/dev-intelligence-e2/` directory. These are **local metadata artifacts**, not an export of private historical MCP content. The private files were validated in place and re-run idempotently on all three hosts. Do not commit these files or copy their raw lookup references into review reports.

## 2. Frozen three-host sample

| Measure | MacBook Pro | Raspberry Pi | Sextant | Combined |
| --- | ---: | ---: | ---: | ---: |
| All captured tool calls | 352 | 827 | 127 | **1,306** |
| Calls without trustworthy request-group attribution | 72 | 410 | 0 | **482** |
| Attributable request groups | 14 | 28 | 15 | **57** |
| Groups selected (max 20 per host) | 14 | 20 | 15 | **49** |
| Negative controls selected | 1 | 5 | 5 | **11** |
| Rule-derived provisional subgoal hints | 13 | 16 | 12 | **41** |
| Selected groups with known result incompleteness | 8 | 4 | 0 | **12** |
| Independently verified original task goals | 0 | 0 | 0 | **0** |
| Independently verified historical source snapshots / Gold Answers | 0 | 0 | 0 | **0** |
| R2/R3 replay-ready cases | 0 | 0 | 0 | **0** |

The 49 groups **do not** establish 49 independent human development tasks. Controls are request groups with observed noncandidate/polling behavior, not experimentally randomized agent control arms. A `complete_tool_inputs` internal status means *no recognized command/pattern input loss*, **not** that task prompts, source files or full run-command stdout are proven complete.

### Disjoint sample strata

| E2 selection stratum | Selected groups | Interpretation |
| --- | ---: | --- |
| Navigation / source inspection | 14 | Query/read activity; not a verified symbol-navigation goal |
| Git change inspection without confirmed chain | 9 | Source or diff exploration, may be incidental |
| Git change → source inspection chain | 2 | Strict sequence candidate from E0/E1 |
| Search → read chain | 2 | Strict navigation sequence candidate |
| Structural/declaration-oriented lexical query | 4 | Candidate AST or symbol use, not verified AST demand |
| Testing | 5 | Test-related command activity |
| Lint/type diagnostics | 2 | Rule-derived analyzer/lint category |
| Negative polling | 4 | Explicit non-LSP optimization control |
| Negative other | 7 | Noncandidate control by current lexical rubric |
| **Total** | **49** | **38 positive candidate groups, 11 controls** |

The category allocation is a deterministic *sample*, not a frequency-normalized population estimate. With 14 and 15 attributable groups, MacBook and Sextant selected all available groups; Raspberry Pi selected 20/28 with fixed seed `20261021`. Categories and result quality may change only after a versioned rule or cohort revision.

## 3. Verification and independent review

| Evidence | Outcome |
| --- | --- |
| MacBook E2 synthetic suite | **39 passed** |
| Raspberry Pi, native Linux E2 suite | **39 passed** |
| Sextant, native Linux E2 suite | **39 passed** |
| MacBook CPython 3.10 and 3.14 E2 suites | **39 passed per interpreter** in final native executions |
| E0/E1 synthetic regression on MacBook | **45 passed** |
| Existing LSP P1 synthetic regression on MacBook | **373 passed** |
| Ruff formatting/check; architecture, startup inventory, import contracts | Pass; **no production `src/binnacle` module changed** |
| Three-host E2 source file SHA-256 | All three host-local source copies identical |
| Private cases | 14 / 20 / 15 verified as `R0_unverified` and owner-only |
| Independent review of E2 technical scope | Initial REWORK, repaired exception/FD/atomicity/durability bugs; final targeted reviewer **GO** for technical internal sampling, separate manual evidence gate remains unmet |

Detailed defects and exact review boundaries: [E2 review and closure](e2-independent-review-2026-10-21.md). Native E2 test packages were deployed only to separate `/tmp` test directories; the private metadata manifest alone was retained in the state directory. No production MCP server, job manager, deployment or historical Git checkout was modified.

## 4. Why task-label verification remains open

A read-only, in-place audit of all **1,306 frozen MCP tools/call request payloads** observed `task`, `requestState`, `inputResponses` and `_meta` all null. No direct strict standalone `git rev-parse HEAD` result in the sampled era established a historical clean working-tree revision. Tool names, regex queries and return values do **not** establish a user's task goal or the uncommitted source state at the time of that tool call.

Therefore the technical pipeline intentionally sets **all 49** cases to `R0_unverified`. The 41 provisional subgoal hints are *not* accepted R1 labels, and **sensitivity, specificity and independent Gold Answer rates against real historic task labels are not measurable yet**. Claiming E2's full human-label acceptance criterion passed would be unsupported.

### Required completion gate before E3 replay

An authorized local reviewer must recover an **independent** original task statement (e.g., contemporary project issue, conversation context or dated task plan), an independently checked source snapshot/commit and evidence that uncommitted file state does not invalidate replay. Independently annotate sampled positives **and negatives**, retain undecidable cases as R0/R1, calculate confusion/missingness explicitly and prohibit replay claims unless R2/R3 prerequisites are satisfied. If that is impossible for this captured cohort, use separately labeled *synthetic/prospective frozen tasks*, not fabricated retrospective gold.

## 5. Product prioritization is exploratory only

- **First candidate for E3 task creation:** change impact / related code navigation (`analyze_change`), because Git inspection and navigation are both represented; however only **two strict change-navigation groups** exist. No measured improvement.
- **Simple initial private runtime probe candidate:** `inspect_symbol`, based on navigation/source-read volume, but not proven preferable to current exact `search_text` and `read_file`.
- **Compare rather than replace Shell:** `check_code`; five test and two diagnostics selected groups are not evidence of false-clean bugs or task-step savings.
- **Defer speculative implementation:** `search_code_structure` until independently verified AST-relevant user tasks are available.

**Release gate:** no P2 Runtime deployment, public MCP tools, READ-side-effect claim or model-step/Token benefit is approved by E2. Future E3/P4 must freeze tasks, verify independent correctness, and run a matched agent A/B with the same model, effort, code and tool profile.
