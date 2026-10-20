# Development Intelligence — providers and safety

| | |
| --- | --- |
| **Status** | Split from the revalidated 2026-09-30 design |
| **Current baseline** | `f1493ee` |
| **Purpose** | Provider measurements, language matrix, analyzer side effects, discovery, trust, and read-only eligibility |
| **Source index** | `docs/lsp-development-intelligence-design-2026-09-27.md` |

> Read this file only when its topic is relevant. The project index is
> `docs/lsp-development-intelligence/README.md`.

---

## 5. Live LSP findings

### 5.1 Headless Pyright is feasible

A direct stdio JSON-RPC probe started pyright-langserver --stdio and successfully
completed:

- initialize / initialized;
- textDocument/didOpen;
- push textDocument/publishDiagnostics;
- textDocument/documentSymbol;
- workspace/symbol;
- shutdown / exit.

The probe left the Git worktree unchanged.

Pyright 1.1.413 advertised, among others:

- definition;
- declaration;
- references;
- document symbols;
- workspace symbols;
- hover;
- type definition;
- call hierarchy;
- code actions;
- rename;
- execute command.

It did **not** advertise diagnosticProvider in this probe; diagnostics arrived through
textDocument/publishDiagnostics.

This validates the headless client model, but it also proves that provider capability
negotiation cannot be replaced with assumptions derived from provider names.

### 5.2 Cold start is a secondary metric; resident steady state is primary

The first draft gave too much architectural weight to the first workspace-wide request.

Cold measurements against the Binnacle repository did show that provider initialization
and workspace semantic readiness are different events:

~~~text
Pyright initialize:                 roughly 0.26-0.77 s in the probes
first target diagnostics:           roughly 2.3-3.1 s in one cold series
first workspace/symbol:             several seconds while the workspace index warmed
~~~

That remains useful operational information, but it should **not** drive the normal
architecture. The intended development usage is a long-lived Binnacle process with a
long-lived LSP process reused across many tool calls and chat turns. A cold start should
be relatively rare.

The performance priority is therefore:

1. **warm/resident request latency and correctness**;
2. Binnacle integration overhead around that request;
3. sustained CPU/RSS and leak behavior while the provider stays resident;
4. cold process/project startup as a separate first-use metric.

The implementation does not need a separate `COLD/WARM/DEGRADED` state machine merely
to predict whether a semantic operation will be fast. `READY` can continue to mean that
LSP initialization completed. An existing-tool enrichment request may then use a small,
hard deadline; if the provider is still indexing and misses that deadline, Binnacle falls
back for that call. Later calls naturally benefit once the same resident process settles.

This is both simpler and closer to the real operating model.

### 5.3 Preliminary multi-provider raw-LSP benchmark

A small standalone benchmark was run on this host on 2026-09-27. It intentionally bypassed
Binnacle and spoke stdio LSP directly, so these measurements isolate the language server
rather than MCP integration.

The fixtures were tiny synthetic projects. Each semantic operation was repeated several
times; the table below reports representative **warm median** latency from those probes.
This is a feasibility baseline, not a statistically complete performance result.

| Provider | Language | Warm workspace symbol | Warm definition | Warm references | Approx. resident process-tree RSS | Result check |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Pyright 1.1.413 | Python | ~0.4-1.2 ms | ~0.6-1.2 ms | ~0.9-1.4 ms | ~147-153 MiB | expected symbols/definition/references returned |
| TypeScript LS 6.0.0 | TypeScript | ~2-6 ms | ~3-4 ms | ~6-15 ms | ~540-585 MiB | expected cross-file definition/references returned |
| TypeScript LS 6.0.0 | JavaScript | ~2-4 ms | ~2-4 ms | ~6-10 ms | ~560-630 MiB | expected cross-file definition/references returned |
| rust-analyzer 0.3.3016 | Rust | ~0.27 ms | ~0.22 ms | ~0.48 ms | ~19-21 MiB in the small fixture | valid after Cargo workspace/model settling |
| clangd 19.1.7 | C++ | ~0.1-0.4 ms | ~0.1-0.3 ms | ~0.1-0.2 ms | ~110-175 MiB | expected definition/references returned |
| clangd 19.1.7 | C | ~0.2-0.6 ms | ~0.1-0.3 ms | ~0.2-0.4 ms | ~120-180 MiB | expected definition/references returned |
| Marksman 2026-02-08 | Markdown | ~0.6-2.3 ms | ~1-4 ms | ~1-5 ms | ~83-86 MiB | valid cross-file link results with a multi-file workspace marker |
| bash-language-server 5.6.0 | Shell | ~0.4-1.6 ms | ~0.4-3 ms | ~1.6-3 ms | ~110-190 MiB | expected function definition/references returned |
| make-ls | Makefile | not measured | not measured | not measured | not measured | executable not installed on this host |

Important observations:

- The steady-state semantic RPC itself is usually **milliseconds**, often well below the
  existing tens-of-milliseconds repository-search paths.
- TypeScript/JavaScript had much higher resident memory than the other small fixtures
  because the language-server process also owns TypeScript service children. Residency
  policy therefore needs real per-provider RSS evidence, not one universal idle timeout.
- Rust demonstrated why correctness and settling state must be recorded together with
  latency. Requests sent while the Cargo project model was reloading could be empty or
  return `content modified`; after the workspace settled, repeated workspace-symbol,
  definition, and reference requests returned the expected results at sub-millisecond
  median latency.
- Marksman cross-file navigation required a multi-file workspace marker
  (`.marksman.toml` in the synthetic fixture), matching its project model.
- A latency sample that returns the wrong or empty answer where gold evidence requires a
  result is **invalid performance evidence**, not a fast result.

The next benchmark round must increase sample count and use three workload scales:
micro fixtures, medium controlled repositories, and real development repositories.

### 5.4 Target provider/language matrix

The early investigation should cover the languages that are realistically used on this
development host, even if production support is introduced provider-by-provider.

| Language/file type | Primary benchmark provider | Local availability now | Core operations to validate |
| --- | --- | --- | --- |
| Python | Pyright | installed | diagnostics, document/workspace symbols, definition, references |
| TypeScript | typescript-language-server | installed | symbols, definition, references, diagnostics |
| JavaScript | typescript-language-server | installed | symbols, definition, references, diagnostics |
| Rust | rust-analyzer | installed | symbols, definition, references, diagnostics/project settling |
| C | clangd | installed | symbols, definition, references, diagnostics |
| C++ | clangd | installed | symbols, definition, references, diagnostics |
| Markdown | Marksman | installed | heading symbols, link definition/references, diagnostics |
| Shell | bash-language-server | installed | symbols where supported, definition, references, diagnostics |
| Makefile | make-ls | not installed | target/variable symbols, definition, references, diagnostics |

The standalone benchmark matrix is intentionally broader than the first production
provider profile. Testing several providers early prevents the internal client from
accidentally being "Pyright-shaped".

### 5.5 One-shot diagnostics can still be better through CLI

A local `pyright --outputjson` probe returned a complete structured summary and diagnostic
in about one second without creating files in the synthetic workspace.

For a one-shot "check this file/project" intent, that completion boundary is clearer
than waiting for an asynchronous push-LSP diagnostic stream.

This does not mean "never use LSP diagnostics". It means the runtime should select the
execution model that gives truthful completion semantics for that provider.

---

## 6. Analyzer side-effect findings

### 6.1 Ruff

A default Ruff check created .ruff_cache in a synthetic workspace.

Running Ruff with --no-cache did not create that cache in the same test.

A read-only Ruff profile must therefore force non-fixing, no-cache behavior regardless
of project defaults.

### 6.2 mypy

Repository-venv mypy 2.3.1 created .mypy_cache by default in a synthetic workspace.

Upstream mypy documentation states that even non-incremental operation still writes
cache unless --cache-dir=/dev/null is used on Unix.

There is a second problem: a globally installed mypy may find a repository's
pyproject.toml but not have that project's plugin/runtime environment. A local probe with
system mypy encountered exactly that class of configuration/environment mismatch with
pydantic.mypy.

Therefore:

- mypy is **not** a safe generic auto-discovered analyzer;
- an explicit trusted profile may use a specific interpreter/command plus
  --cache-dir=/dev/null;
- project-local mypy must not be auto-executed merely because it exists.

### 6.3 clangd

clangd's documented background index stores *.idx files, including under
.cache/clangd/index near the compilation database.

A default clangd process is therefore not workspace-pure.

A future read-only profile would need to disable background indexing or redirect and
contain all cache writes, then pass the side-effect test suite.

### 6.4 rust-analyzer

rust-analyzer documents default Cargo/check/build-script behavior, including cargo check,
build-script/proc-macro handling, and target output.

That can both write build artifacts and execute project-controlled code.

rust-analyzer must therefore **not** back a ChatGPT READ tool in the initial rollout.
Navigation support can be investigated later under a more explicit trust posture.

---

## 8. Provider profiles and trust model

Generic “find executable then run it” is too weak.

Each supported provider needs a built-in audited profile.

Illustrative internal shape:

~~~text
ProviderProfile
  key
  kind: lsp | analyzer
  languages/extensions
  executable_names
  argv
  environment policy
  initialization options/settings
  intents allowed
  side_effect_class
  may_execute_project_code
  cache policy
  workspace-root strategy
  result parser / protocol adapter
~~~

### 8.1 Side-effect classes

Use explicit classes such as:

- workspace_pure — no workspace writes expected;
- external_cache_only — writes only to a Binnacle-owned cache/state directory;
- may_write_workspace;
- may_execute_project_code.

Only the first two may ever back a tool annotated readOnlyHint=true. The second requires
Binnacle to select/control the external cache location.

### 8.2 Discovery priority

Recommended order:

1. explicit trusted Binnacle configuration;
2. built-in audited executable names resolved on the **service PATH**;
3. unavailable.

Do not auto-execute:

- .venv/bin executables;
- node_modules/.bin executables;
- repository scripts;
- editor LSP command configuration;
- package.json commands;
- arbitrary project configuration naming a server.

A user can explicitly configure such a command after deciding that repository/environment
is trusted.

### 8.3 Capability negotiation still wins

A profile says what Binnacle knows how to use safely. It does **not** say what the
running version actually implements.

After initialize, store the advertised capability map and use only supported methods.

Profile + negotiated capability + runtime latency state together determine eligibility.

---
