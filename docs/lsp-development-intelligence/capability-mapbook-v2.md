# LSP provider capability mapbook (V2)

**Draft date:** 2026-10-20. **Owner:** Binnacle Development Intelligence design.
**Protocol baseline:** [Language Server Protocol 3.18](https://microsoft.github.io/language-server-protocol/), current official spec as checked 2026-10-20. This is a reference vocabulary, **not** a claim that every installed server implements 3.18.
**Source baseline:** Binnacle `origin/master` at `ce943ced`, previous V1 research last updated 2026-09-30.
**Purpose:** a maintained, evidence-driven catalogue of what each LSP server can actually do, and what Binnacle can safely expose to an AI agent. This is a research artifact, **not** an enabled provider manifest.

**P3.6 synthesis, 2026-10-22:** [offline decision matrix and evidence ledger](p3-6-policy-synthesis-2026-10-22.md).
Provider/resource acceptance remains **REWORK** pending final P3.3–P3.5 evidence
and independent review. No provider has an evidence-backed P3.6 GO. READ and
public release remain **NO-GO**. Historical tables below are not promoted to
current measurements or security certification.

## 1. Strict evidence semantics

Use four independent axes, never one vague `supported` boolean.

| Axis | Allowed values | Interpretation |
| --- | --- | --- |
| Installation | `shell_found`, `service_found`, `absent_on_path`, `not_checked` | A binary may be installed but unreachable to the installed service |
| Protocol | `upstream_claim`, `advertised@version`, `not_advertised@version`, `unprobed` | `initialize` advertised capabilities are version/client-config dependent |
| Correctness | `fixture_pass`, `real_repo_pass`, `failed`, `unprobed` | A correct, bounded result on a known corpus is mandatory for a claim of utility |
| Security | `audited_read_eligible`, `explicit_trust_only`, `benchmark_only`, `not_audited` | READ eligibility additionally depends on executable, options, workspace and OS |

Legend in capability tables:

- **H** = historical 2026-09-27 direct stdio probe returned expected results on tiny fixtures (not a fresh V2 test);
- **D** = provider upstream describes the feature (not locally verified);
- **A** = capability advertised by a versioned `initialize` response in historical research, but result not independently checked;
- **?** = not established, or unknown behavior for this version;
- **—** = not applicable/not proposed for that provider or mode.

`H/D` means both historical probe and upstream documentation. Neither a `D` nor `A` value authorizes a public Binnacle operation. The V2 probe must capture provider executable hash/version, client initialize parameters, response and corpus pass/fail; dynamic registrations can change a capability during a session.

## 2. Agent intents and corresponding LSP methods

| Binnacle intent | Standard LSP method(s) | Internal V1/V2 intent status | Public policy |
| --- | --- | --- | --- |
| Resolve concrete source symbol | `textDocument/definition`, `declaration`, `implementation`, `typeDefinition` | Primary private `semantic.inspect_symbol` | Public `inspect_symbol` **candidate only**, requires A/B gate |
| Find usages of a concrete symbol | `textDocument/references` | Bounded part of private symbol inspection | Do not add separate MCP tool by default |
| Understand symbol type and documentation | `textDocument/hover`, `signatureHelp` | Optional enrichment, provider-dependent | Return only trustworthy, bounded snippets |
| Inspect file/project structure | `textDocument/documentSymbol`, `workspace/symbol` | Provider compatibility and future orientation experiment | Do not assume natural-language repository retrieval |
| Understand callers/inheritance | call/type hierarchy methods | Experimental follow-up only | Not part of first public API |
| Report problems in actual analyzed scope | `publishDiagnostics`, `textDocument/diagnostic`, `workspace/diagnostic`; optionally analyzer CLI | Private `semantic.check_code` candidate; CLI may give a clearer completion boundary | Distinct public `check_code` decision |
| Get editing suggestions | `textDocument/codeAction`, rename, formatting, `workspace/executeCommand` | Capability inventory only | No edit execution / no automatic `workspace/applyEdit` |
| Editor interactions | completion, semantic tokens, inlay hints, Code Lens, selection/folding ranges | Catalogued for coverage, not an initial agent need | Deferred; avoid standing token cost |
| Synchronize state | `initialize`, `initialized`, `didOpen`, `didChange`, `didClose`, `shutdown`, `exit` | Required protocol/lifecycle foundations | Internal only, never raw public verbs |

Result accuracy depends on stable disk snapshots, position encoding and workspace context. No operation claims to know an IDE cursor, active tabs or unsaved edits.

## 3. Provider capability map (research coverage)

This table deliberately avoids a fake complete YES/NO matrix. It covers capabilities relevant to our agent workflow first, with a separate provider-specific drilldown below.

| Language / server | Definition | References | Symbols (see §3.1) | Hover/type | Diagnostics | Main confidence |
| --- | --- | --- | --- | --- | --- | --- |
| Python / Pyright LSP | H/D | H/D | doc H; workspace H | A/D | H (push); pull ? | Strong historical micro evidence, safety pending |
| TypeScript / typescript-language-server | H/D | H/D | workspace H; doc ? | D | D | Historical correctness, costly resident process tree |
| JavaScript / typescript-language-server | H/D | H/D | workspace H; doc ? | D | D | Same server, separate corpus needed |
| Rust / rust-analyzer | H/D after settling | H/D after settling | workspace H; doc ? | D | D | **Unsafe by default** due to project execution |
| C / clangd | H/D | H/D | workspace H; doc ? | D | D | Background index cache writes possible |
| C++ / clangd | H/D | H/D | workspace H; doc ? | D | D | Depends strongly on compile commands |
| Markdown / Marksman | H/D (links) | H/D | H/D (headings) | D (links) | D (links) | Multi-file root/marker matters |
| Shell / bash-language-server | H/D | H/D | workspace H; doc ? | D | D (ShellCheck optional) | Scoping/reference resolution may be limited |
| Makefile / owenrumney make-ls | D | D | D | D | D | Binary newly located; **no historical live probe** |
| YAML / Red Hat yaml-language-server | ? | ? | D | D | D (schema) | Configuration/schema resolution, no local probe |
| JSON / VS Code JSON language server | ? | ? | ? | ? | ? | Binary found; verify exact server/features |
| Go / gopls | D | D | D | D | D | High-value future candidate, absent on both shell PATHs |
| Python lint/format / Ruff native `ruff server` | — | — | — | — | D | Separate LSP diagnostics/format provider; not semantic navigation |

**Not on this list:** a speculative provider is not silently supported. Python type-servers, YAML/JSON schema resolvers and CLI analyzers may expose overlapping functions, but they are not substitutes for semantic navigation without validated contracts.

### 3.1 Method-level coverage gaps (do not infer from a generic capability label)

| Provider | `documentSymbol` | `workspace/symbol` | `declaration` | `typeDefinition` | `implementation` | `callHierarchy` |
| --- | --- | --- | --- | --- | --- | --- |
| Pyright | H | H | A | A | ? | A |
| TypeScript/JavaScript LS | ? | H | ? | ? | ? | ? |
| rust-analyzer | ? | H | ? | ? | ? | ? |
| clangd | ? | H | ? | ? | ? | ? |
| Marksman | H/D | H/D | ? | ? | ? | ? |
| Bash language server | ? | H/D | ? | ? | ? | ? |
| make-ls (owenrumney) | D | ? | ? | ? | ? | ? |
| YAML language server | D | ? | ? | ? | ? | ? |
| JSON language server | ? | ? | ? | ? | ? | ? |
| gopls | D | D | ? | ? | ? | ? |

Historical Pyright `A` entries were advertised by the September initialize probe; they are not successful V2 operation assertions. Historical workspace-symbol timings do not prove document-symbol correctness for the same provider. Providers can implement only some kinds of symbol hierarchy; a dash or question mark must not be silently upgraded to YES.

### 3.2 Diagnostics and editing surfaces (catalog only; not automatic privileges)

| Provider | Push diagnostics | Pull diagnostics | Signature help | Rename / code actions / format |
| --- | --- | --- | --- | --- |
| Pyright | H | ? | D | A / A / ? |
| TypeScript/JavaScript LS | D | ? | D | D / D / D |
| rust-analyzer | D | ? | D | D / D / D; explicit trust only |
| clangd | D | ? | D | D / D / D |
| Marksman | D | ? | ? | D / D / ? |
| Bash language server | D | ? | ? | D / D / D |
| make-ls (owenrumney) | D | ? | ? | ? / D / D |
| YAML language server | D | ? | ? | ? / ? / ? |
| JSON language server | ? | ? | ? | ? / ? / ? |
| gopls | D | ? | D | D / D / D |
| Ruff native LSP | D | ? | — | — / D / D |

Here `D` means only upstream-described general server functionality and may require extra tools/configuration. The table does **not** authorize edits or imply all these methods were individually tested. The LSP `workspace/executeCommand` operation is client-to-server and must not be invoked by Binnacle's READ path; a server-to-client `workspace/applyEdit` request must be refused.

### 3.3 Usability-specific capability tiers

| Priority | Capabilities | Rationale |
| --- | --- | --- |
| Core for agent navigation | Definition, bounded references, location provenance, document synchronization | Direct impact on wrong-symbol mistakes and repeated text searches |
| Strong optional enrichment | Hover, type definition, declaration, implementation, document/workspace symbols | Provider-specific accuracy/value must be proven |
| Research-only exploration | Call/type hierarchy, signature help, Markdown/Makefile relationship views | May add utility but can increase calls and response tokens |
| Separate diagnostic product | LSP push/pull diagnostics, Pyright/Ruff CLI analyzer, severity/rule/coverage | Completion boundary and safety differ from navigation |
| Out of scope for first public READ API | Rename, format, code actions, execute command, auto-completion/apply edits | Write/command effects and standing surface cost; require separate proposal |

## 4. Current host availability (interactive shell, 2026-10-20)

| Provider executable | Raspberry Pi 5 Linux aarch64 | MacBook Pro Darwin arm64 | Verified source/version |
| --- | --- | --- | --- |
| `pyright`, `pyright-langserver` | Found | Not on PATH | 1.1.413, version command |
| `typescript-language-server` | Found | Not on PATH | 6.0.0, version command |
| `rust-analyzer` | Found | Not on PATH | 0.3.3016-standalone, version command |
| `clangd` | Found | Found (`/usr/bin/clangd`) | Linux 19.1.7; macOS version not checked |
| `marksman` | Found | Not on PATH | 2026-02-08, version command |
| `bash-language-server` | Found | Not on PATH | 5.6.0, version command |
| `make-ls` | Found | Not on shell PATH | Local symlink targets `make-ls-v0.1.20/make-ls` |
| `yaml-language-server` | Found | Not on PATH | Version not checked |
| `vscode-json-language-server` | Found | Not on PATH | Version not checked |
| `gopls`, `ruff`, `ty`, `basedpyright-langserver` | Not on PATH | Not on PATH | No auto-install authorized |

This inventory must be repeated against the **deployed service environment** before implementation; a shell PATH lookup is insufficient. No provider was launched in V2 inventory collection.

### Makefile server identity warning

There are different products named `make-ls`. The local `make-ls-v0.1.20` path is consistent with [owenrumney/make-ls](https://github.com/owenrumney/make-ls) v0.1.20, whose upstream documents targets/variables, definition, references, symbols, hover, completion and diagnostics. Another independent `make-ls` exists on [PyPI](https://pypi.org/project/make-ls/) with different features, subprocess and logging behavior. The installed binary identity is **not yet cryptographically verified**; do not combine either server's claims into a profile until executable/source identity is captured. Even the upstream feature table is only D status.

## 5. Per-provider operational notes and safety candidates

### 5.1 Pyright — first navigation candidate

- Primary internal capabilities: Python definition, declaration, references, symbols and hover, with LSP push diagnostics observed historically; historical Pyright 1.1.413 did not advertise pull diagnostics in the old probe.
- Recommended first private profile only after process, cache, permission and workspace configuration audit. Use an explicitly selected, audited global binary, not arbitrary repository `.venv/bin/pyright-langserver`.
- CLI `pyright --outputjson` is a **separate analyzer**, suitable for bounded one-shot diagnostics; completeness/exit/timeout must be evaluated independently of LSP.
- Project interpreter and import-resolution configuration influence correctness. Treat analysis environment identity as part of evidence.
- Pyright also ships a distinct [Type Server Protocol](https://github.com/microsoft/pyright/blob/main/docs/type-server.md) with computed/declared/expected type queries. This is **not standard LSP**; record as a future research candidate, never silently call it from generic LSP code.
- Sources: [Pyright features](https://github.com/microsoft/pyright/blob/main/docs/features.md), [settings](https://github.com/microsoft/pyright/blob/main/docs/settings.md).

### 5.2 TypeScript / JavaScript — strong navigation, resource-sensitive

- Historical tiny-fixture definition/references worked after initialization; TS and JS need separate gold corpora.
- TypeScript service subprocesses greatly affect memory. Constrain instance count, idle policy and workload-size measurements.
- Propose `disableAutomaticTypingAcquisition=true` where supported and audit workspace TypeScript plugins/configuration. No npm installs or network-dependent type acquisition as an implicit READ behavior.
- Treat `typescript-language-server` plus tsserver child tree as one accounted ownership unit. Verify shutdown and detached child cleanup on both platforms.
- Sources: [typescript-language-server](https://github.com/typescript-language-server/typescript-language-server), [configuration](https://github.com/typescript-language-server/typescript-language-server/blob/master/docs/configuration.md).

### 5.3 rust-analyzer — benchmark or explicit trust only

- The official [rust-analyzer security documentation](https://rust-analyzer.github.io/book/security.html) explicitly says it assumes code is trusted. Build scripts/proc macros may execute, and toolchain/Cargo configuration can redirect commands.
- Even if capabilities work and macros/checks are nominally disabled, the exact safe profile must be independently audited. Initial Binnacle READ tool must **not** auto-enable rust-analyzer.
- Historical raw results were empty/stale during Cargo model settling; correctness samples must record project-settled state and reject misleading fast-empty measurements.
- Source: [rust-analyzer configuration](https://rust-analyzer.github.io/book/configuration).

### 5.4 clangd — compilation database and index containment

- Definition/references work in a controlled compilation database fixture; project-wide completeness depends on compile commands and indexing.
- [clangd's index design](https://clangd.llvm.org/design/indexing) documents cached `.idx` files under `.cache/clangd/index` near the compilation database. Default workspace-purity must not be assumed.
- Consider disabled/redirected background index only after tests show usable symbol results; distinguish a correctly incomplete result from full project coverage.
- Benchmark C and C++ separately. No implicit execution of build commands to generate `compile_commands.json`.

### 5.5 Marksman — document/heading/link semantics

- Useful for cross-document Markdown heading definitions and references, not general code-type navigation.
- Real multi-file tests require VCS root or `.marksman.toml` marker, and must check navigation outside allowed roots.
- Upstream documents document/workspace symbols, hover on links, diagnostics for wiki-links, Code Lens and rename; editing-related capabilities stay disabled.
- Source: [Marksman features](https://github.com/artempyanykh/marksman/blob/main/docs/features.md).

### 5.6 Bash language server — useful but scope-limited

- Upstream supports declaration navigation, references, hover, symbols, diagnostics and formatting; scope analysis is stated to be limited.
- ShellCheck/shfmt/explainshell integrations are optional dependencies, not implicit authorization to spawn unreviewed helper tools.
- Source: [bash-language-server](https://github.com/bash-lsp/bash-language-server).

### 5.7 Makefile / make-ls — newly available candidate

- Published owenrumney feature set: target/variable definition and references, hover, document symbols, diagnostics, include resolution, formatting and fixes.
- Verification priority: executable identity, `initialize` response, file URI handling, include traversal outside workspace, zero-write test, and detection of any actual `make` recipe execution. No feature assumed safe merely because a parser is described as static.
- Source: [owenrumney/make-ls](https://github.com/owenrumney/make-ls).

### 5.8 YAML / JSON schema servers — future configuration intelligence

- YAML upstream describes JSON Schema mapping, completion/validation and custom schema sources. Schema URLs and remote resolution introduce explicit network/trust questions; forbid unapproved outbound fetches by default.
- JSON server binary was located on Pi PATH, but **no version/capability test or source-identity check** was done; all feature cells remain unverified.
- These providers should be evaluated for a dedicated config-file validation or schema navigation intent, not automatically made part of `inspect_symbol`.
- Source: [YAML language server](https://github.com/redhat-developer/yaml-language-server).

### 5.9 Go / gopls — expansion priority

- gopls is the official Go language server with navigation, diagnostics, code-intelligence and refactor features; install status is absent-on-PATH, not impossibility.
- Evaluate module/cache/network and process-side effects, multi-module workspace semantics and performance before READ designation; never auto-download modules.
- Source: [official gopls features](https://go.dev/gopls/features/).

### 5.10 Ruff — analyzer first, LSP alternative later

- For `check_code`, keep the CLI `ruff check --output-format json --no-cache` (non-fixing) as a private candidate, provided the exact local version and cache/side-effect audit pass.
- Ruff also has a native [`ruff server` language server](https://github.com/astral-sh/ruff-lsp), but it is focused on lint/format features and should not be counted as a Pyright-equivalent definition/reference provider.
- Historical study found default Ruff CLI creates `.ruff_cache`; `--no-cache` avoided that in synthetic tests. Repeat on actual profiles before any READ exposure.

## 6. Historical raw-provider timing (NOT acceptance measurements)

V1 recorded a 2026-09-27 tiny synthetic project run that bypassed Binnacle entirely. Warm medians below are *indicative*, not directly comparable to current larger workspaces, deployed service PATHs, hardware, or MCP overhead.

| Provider | Historical warm definition | Warm references | Approx. resident process-tree RSS |
| --- | ---: | ---: | ---: |
| Pyright 1.1.413 | 0.6–1.2 ms | 0.9–1.4 ms | 147–153 MiB |
| TypeScript LS 6.0.0 | 3–4 ms | 6–15 ms | 540–585 MiB |
| JavaScript via TS LS | 2–4 ms | 6–10 ms | 560–630 MiB |
| rust-analyzer | 0.22 ms | 0.48 ms | 19–21 MiB (tiny fixture only) |
| clangd C/C++ | 0.1–0.3 ms | 0.1–0.2 ms | 110–180 MiB |
| Marksman | 1–4 ms | 1–5 ms | 83–86 MiB |
| bash-language-server | 0.4–3 ms | 1.6–3 ms | 110–190 MiB |
| make-ls, YAML, JSON, gopls, Ruff | Not measured | Not measured | Not measured |

Never count a wrong/empty answer as a successful latency observation. New reports must include correctness, percentile distribution, resident RSS/idle CPU, long-session growth, cold/settling/warm labels, Binnacle overhead and total agent task cost.

## 7. LSP protocol compliance and runtime feature negotiation

A provider profile contains a **maximum allowlist**, not a claim that every version exposes it. Eligibility is the intersection of:

1. operator-enabled, trusted provider profile;
2. allowed language and workspace scope;
3. startup `initialize` advertised capabilities plus tracked dynamic registrations;
4. audited method safety classification;
5. capability-specific correctness/latency evidence at the exact version/configuration;
6. the budget and completeness needed for the requested agent intent.

Handle LSP 3.18 as protocol vocabulary; support the older requests required by our selected providers rather than implementing every new 3.18 feature. Negotiate/validate UTF-8 or UTF-16 position encoding instead of assuming Python string indexes equal protocol character offsets. Handle `Location`, `LocationLink`, null and multiple locations, server-to-client requests, cancellation/late replies and partial results explicitly.

Refuse server-to-client `workspace/applyEdit`; never send a client-to-server `workspace/executeCommand` from a READ path. Do not grant arbitrary workspace/configuration values or execute commands simply because the server asks. Treat every returned URI, Markdown hover and diagnostic message as untrusted provider output.

## 8. Capability mapbook evidence record (future machine-readable artifact)

Each successful or refused provider/method probe should produce one structured record with at least:

| Group | Required recorded fields |
| --- | --- |
| Identity | run ID, UTC timestamp, Binnacle commit, OS/arch/Python, provider name/path/hash/version |
| Initialization | sanitized argv/env hash, workspace identity/hash, initialization options, client capabilities, server capabilities and position encoding |
| Operation | LSP method, request/response shape, input fixture ID/content hash, expected assertions and actual outcome |
| Provenance | `upstream_claim` vs `advertised` vs `fixture_pass` vs `real_repo_pass`; observed side-effect class |
| Coverage and errors | document/project scope, unavailable/refused reasons, timeout, ambiguity, partial/truncated and stale detection |
| Performance | cold/start/settle time, warm p50/p95/p99, raw provider vs Binnacle time, bytes/tokens, subprocess-tree RSS and idle CPU |
| Security | directory sentinels/hashes before/after, external cache writes, network attempts, child processes and trust/profile verdict |

Version/configuration updates invalidate dependent verification until re-probed. Keep raw protocol captures outside source control (redacted, time-bounded); commit only small safe summaries and reproducible fixtures. Never include credentials or private source in telemetry.

## 9. Recommended verification order and product gates

1. **Inventory/identity first:** version, binary origin, installed-service PATH, exact command/args, side effects; revise table cells without touching MCP tool list.
2. **Python first:** Pyright 1.1.413 raw LSP `initialize` and symbol micro corpus, then medium/real repo; independent Pyright CLI diagnostic completeness.
3. **Provider breadth early:** Makefile, Markdown, TS/JS, C/C++, Bash plus YAML/JSON protocol handshake to avoid a Pyright-specific client; rust-analyzer only in isolated trusted fixtures.
4. **Security before READ:** filesystem, child processes, cache and network probes for exact profiles on both OSes; unsafe profiles stay benchmark-only.
5. **Private API A/B:** `semantic.inspect_symbol` vs baseline `search_text` + `read_file`. Measure correctness, wrong-definition rate, calls, model steps, tokens, total task time and failure/recovery rate.
6. **Public decision separate:** a candidate passing raw feature tests is not sufficient. Repeated agent workflow gain, operational safety and acceptable standing tool budget are required.
7. **`check_code` separately:** compare audited CLI diagnostics to LSP push/pull; never interpret no findings as globally clean when providers did not analyze the requested scope.

Every proposed expansion starts as an evidence row; only documented per-provider gates can promote it to a production profile.

## 10. Primary sources / provenance

- [Official LSP specification](https://microsoft.github.io/language-server-protocol/) (latest 3.18 at review).
- [Pyright features](https://github.com/microsoft/pyright/blob/main/docs/features.md), [configuration](https://github.com/microsoft/pyright/blob/main/docs/settings.md), [Type Server Protocol](https://github.com/microsoft/pyright/blob/main/docs/type-server.md).
- [TypeScript language server](https://github.com/typescript-language-server/typescript-language-server).
- [rust-analyzer security](https://rust-analyzer.github.io/book/security.html), [configuration](https://rust-analyzer.github.io/book/configuration).
- [clangd indexing](https://clangd.llvm.org/design/indexing).
- [Marksman features](https://github.com/artempyanykh/marksman/blob/main/docs/features.md).
- [bash-language-server](https://github.com/bash-lsp/bash-language-server).
- [owenrumney make-ls](https://github.com/owenrumney/make-ls) vs [different make-ls on PyPI](https://pypi.org/project/make-ls/).
- [YAML language server](https://github.com/redhat-developer/yaml-language-server).
- [gopls official features](https://go.dev/gopls/features/).
- [Ruff native LSP migration](https://github.com/astral-sh/ruff-lsp).
- Binnacle prior [V1 provider study](providers-and-safety.md) and [V1 safety testing plan](testing-safety-contracts.md). Historical probes are not fresh 2026-10-20 results.

## 11. P3.4 native breadth evidence — 2026-10-22

**Opt-in native QA, not shipped. P3.3 READ NO-GO.** This update supersedes
historical/unprobed cells only for the exact Sextant Linux aarch64 versions and
fixed synthetic settings below. All launched rows are `benchmark_only`.
Service PATH, OS confinement and real-workspace correctness remain untested.
See the [provider evidence and caveats](p3-4-provider-breadth-2026-10-22.md) and
[sanitized machine report](p3-4-breadth-native-2026-10-22.json).

| Provider | Version | Newly observed | Advertised but unverified (selected) | Unsupported / not advertised / caveats |
| --- | --- | --- | --- | --- |
| TypeScript LS / TypeScript | 6.0.0 | Initialize/shutdown; document symbol; cross-file definition | References, hover, workspace symbols, type definition, implementation | Declaration, call hierarchy, pull diagnostics not advertised; no project plugins or type downloads |
| TypeScript LS / JavaScript | 6.0.0 | Separate JS initialize/shutdown, symbol and cross-file definition | Same as TS | Same omissions; no broader JS project claim |
| clangd / C | 19.1.7 | Initialize/shutdown; C11 symbol and same-file definition | References, hover, declaration, type definition, implementation, hierarchy | Pull diagnostics not advertised; background index/config disabled |
| clangd / C++ | 19.1.7 | Separate C++17 initialize/shutdown, symbol and same-file definition | Same as C | No build or whole-project index proof |
| rust-analyzer | 0.3.3065-standalone | Initialize/shutdown; detached-file symbol | Navigation, hierarchy, pull diagnostics | Cargo, build scripts, proc macros, project readiness untested; benchmark-only |
| Marksman | 2026-02-08 | Initialize/shutdown; heading symbol | Link definition, references, hover, workspace symbols | No type/declaration/hierarchy/pull-diagnostic advertisement; cross-file link correctness unprobed |
| Bash LS | 5.6.0 | Initialize/shutdown; function symbol after document readiness notification | Definition, references, hover, workspace symbols | No declaration/type/hierarchy/pull-diagnostic advertisement; helpers disabled, sourced navigation unprobed |
| make-language-server | Not installed | No launch | None | Separate `make-ls` alias present but unreviewed and unlaunched; no support claim |
| YAML LS | 1.24.0 | Initialize/shutdown; key symbol | Definition, hover, completion, editing suggestions | No references/workspace-symbol/hierarchy/pull-diagnostic advertisement; remote stores disabled |
| VS Code JSON LS | extracted package 4.10.0 | Initialize/shutdown; key symbol | Hover, pull diagnostics, code actions | No definition/references/workspace-symbol/completion/formatting advertisement for this client profile |

Existing multilspy constructors were exercised for TS, JS, C through the `cpp`
selector, C++ and Rust at pinned revision `9203732`. Full upstream adapter
sessions were not exercised. Direct bounded handshakes supply the capability
evidence; the runner adds no production adapter. Other listed languages have
no upstream factory selector at that revision. Not-advertised does not mean
universally absent, especially where dynamic registration or client capability
negotiation changes the response. No editing or command capability was invoked.
