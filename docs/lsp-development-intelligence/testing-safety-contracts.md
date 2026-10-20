# Development Intelligence testing — safety and compatibility

| | |
| --- | --- |
| **Status** | Split from the revalidated 2026-09-30 design |
| **Current baseline** | `f1493ee` |
| **Purpose** | Provider side-effect safety, analyzer execution, existing MCP contracts, and failure containment |
| **Source index** | `docs/lsp-development-intelligence-testing-2026-09-27.md` |

> Read this file only when its topic is relevant. The project index is
> `docs/lsp-development-intelligence/README.md`.

---

## 11. Provider-profile safety tests

Every built-in profile gets a safety contract.

### 11.1 Profile metadata assertions

For a profile eligible for READ workflows, assert:

- side_effect_class is workspace_pure or external_cache_only;
- may_execute_project_code=false;
- no fix/apply argument;
- controlled cache policy;
- executable discovery source is permitted;
- initialization settings do not enable mutation features.

### 11.2 Filesystem side-effect harness

Git status alone is insufficient because caches are often gitignored.

Use a synthetic workspace and build a manifest before and after provider execution.

Manifest should include, excluding only the test harness control directory:

- relative path;
- file type;
- file size;
- mode;
- content hash for regular files;
- symlink target.

Run the provider scenario.

Compare manifests.

For workspace_pure:

- manifest must be identical.

For external_cache_only:

- workspace manifest must be identical;
- writes may occur only under an explicitly supplied external cache/state directory.

### 11.3 Read-only command profiles

Ruff profile:

- force --no-cache;
- no --fix;
- prove no workspace write.

mypy explicit profile, if implemented:

- force --cache-dir=/dev/null;
- prove no workspace write;
- do not auto-discover project-local command.

Pyright CLI profile:

- structured JSON mode;
- prove no workspace write on synthetic project.

clangd/rust-analyzer:

- no READ eligibility until their profiles pass this harness under the chosen settings.

### 11.4 Project-code execution test

A synthetic project should contain a build/plugin hook that writes a sentinel when
executed.

A provider classified may_execute_project_code=false must not trigger it.

This is particularly important before adding Rust/C++ profiles.

---

## 12. Analyzer-execution tests

One-shot analyzer runner tests:

- successful JSON output;
- diagnostics + non-zero exit code;
- malformed output;
- huge output;
- timeout;
- crash;
- stderr content;
- signal termination;
- child process spawn;
- cancellation/cleanup.

Result normalization tests:

- severity mapping;
- path normalization;
- zero-based versus one-based lines/columns;
- missing end range;
- provider code/rule;
- multiline message;
- Unicode message;
- duplicate diagnostic handling policy.

Never fabricate coordinates absent from provider output.

---

## 13. Baseline six-tool compatibility tests

These are mandatory from Phase 1 onward, but most of the required infrastructure already
exists on current master. Do not duplicate it.

### 13.1 Surface invariance

Before a public-tool phase, run the existing contract pin:

- `tests/contracts/test_tool_surface.py`.

It already pins:

- which tools each client profile receives;
- ChatGPT tool count = 6;
- default-client tool count = 8;
- name/description/input schema/output schema/annotations hashes;
- server instructions hash.

Development Intelligence implementation must not require changing those pins in private
Phases 0-3.

### 13.2 Golden result invariance

Run the existing:

- `tests/contracts/test_golden_outputs.py`.

Existing tool outputs must remain identical on their fixed fixtures while Development
Intelligence is disabled, absent, resident, or failing in the background.

This is stronger than adding LSP-specific "schema unchanged" assertions because it protects
the actual structured payload.

### 13.3 Standing surface-token budget

Run:

- `tests/contracts/test_surface_tokens.py`.

Before a public-tool phase the current 2262-token budget history must need no update.

If `inspect_symbol` or `check_code` is later approved, changing the budget is intentional:
record the new measured value and reason in `BUDGET_CHANGES` in the same change.

### 13.4 Exact `search_text` preservation

The 2026-09-28 indexed-pilot removal added dedicated preservation tests:

- `tests/contracts/test_search_text_surface.py`;
- `tests/unit/tools/test_search_text_plain_patterns.py`.

Development Intelligence must keep them green.

In particular:

- no hidden LSP routing is added;
- a pattern beginning `@context` followed by a space remains an ordinary regex/literal pattern;
- adaptive discovery remains result shaping over exact search, not semantic retrieval.

### 13.5 Visibility invariance

Until a public tool is explicitly approved:

- ChatGPT modern identity sees six;
- ChatGPT legacy identity sees six;
- hidden write tools remain hidden;
- default/other clients retain current behavior.

A private semantic API belongs below MCP registration and therefore does not need a
visibility exception.

### 13.6 Public-tool change procedure

If a public candidate is approved, its contract tests are changed **on purpose**, not
worked around.

The same commit should:

1. add the tool implementation/registration;
2. update client visibility intentionally;
3. update tool-count/surface hashes;
4. add golden output fixture(s);
5. update surface-token budget history when needed;
6. update descriptions/server instructions;
7. run the post-deploy/client-compatibility gates required by the quality guard.

---

## 14. Failure-containment matrix

Each row requires a test.

| Fault | Existing six tools | Private Development Intelligence API | Future public semantic/diagnostic tool |
| --- | --- | --- | --- |
| provider executable missing | unchanged | unavailable | truthful unavailable/partial |
| initialize timeout | unchanged | bounded timeout/unavailable | bounded partial/unavailable |
| process crash | unchanged | provider operation fails cleanly | partial/unavailable |
| malformed frame | unchanged | provider instance fails cleanly | partial/unavailable |
| oversized frame | unchanged | provider instance fails cleanly | partial/unavailable |
| unsupported capability | unchanged | capability reported unavailable | bounded result without fabricated capability |
| server requests `workspace/applyEdit` | unchanged; request rejected | edit rejected | edit rejected |
| provider request exceeds semantic deadline | unchanged | semantic call times out | explicit timeout/partial |
| analyzer writes workspace unexpectedly | unchanged | provider profile fails safety gate | tool must not be annotated READ |
| analyzer output malformed | unchanged | analyzer operation fails cleanly | partial/unavailable |
| semantic result budget exceeded | unchanged | private result bounded/truncated | complete bounded result + truncation |
| path outside roots | existing ToolError semantics | normal path validation error | normal ToolError |

The strict invariant is:

> A Development Intelligence failure must never convert a successful pre-feature
> `read_file`, `list_files`, `search_text`, `run_command`, `job_status`, or `stop_job`
> operation into an error.

That invariant is now simpler to prove than in the old enrichment design because existing
tools do not invoke LSP at all during private phases.

---
