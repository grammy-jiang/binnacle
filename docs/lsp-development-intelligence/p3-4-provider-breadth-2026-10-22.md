# P3.4 provider breadth: opt-in native QA

**Result:** synthetic adapter construction and direct initialize evidence only.
**Not shipped. P3.3 READ NO-GO.** Every launched case is `benchmark_only`.
Explicit operator trust authorizes this QA run; it grants no production admission.
Baseline: `66697d2`. Host: Sextant, Linux aarch64, CPython 3.13.16.
No public MCP tool, production adapter, provider allowlist or service changed.

## Reproduce

Use an isolated checkout and its locked development environment. No provider is
installed by this harness. The optional multilspy dependency is the existing
repository pin, not a new dependency or a provider download.

```bash
UV_CACHE_DIR=/tmp/binnacle-p34-uv uv sync --locked --group dev --extra development-intelligence-pyright
.venv/bin/python -m scripts.lsp_p34_breadth --run-native \
  --output /tmp/p34-breadth.json --timeout 30
.venv/bin/pytest tests/scripts/test_lsp_p34_breadth.py \
  tests/scripts/test_lsp_p34_wire.py \
  tests/unit/core/test_lsp_p31_profile_assessment.py -q --randomly-seed=12345
.venv/bin/ruff check .
```

The CLI refuses execution without `--run-native`. `--provider` can select one
or more fixed cases. `--bin-dir` must be an operator-selected absolute directory;
it defaults to `~/.local/bin`. There is no workspace argument, inherited PATH
search, repository executable discovery, package install or build step.
`node` must exist in that directory for Node providers. The TS package must be
adjacent to the installed language-server package. Missing dependencies are
reported, never downloaded. Normal pytest uses synthetic peers only.

The [machine evidence](p3-4-breadth-native-2026-10-22.json) records executable
SHA-256, package version/manifest hash where applicable, Node identity, explicit
TypeScript entry-point/payload identity, upstream adapter/template hashes,
fixture hashes, fixed initialize settings, and harness source hashes. Paths,
provider messages, snippets and command strings from capabilities are not
exported. Capability snapshots retain booleans and option structure; strings
and unknown extension keys are redacted. Lists are capped at 128 and nesting at
12. This is a sanitized snapshot, not an exact raw initialize transcript.
Launcher/manifest hashes do not attest the full dependency tree or OS libraries.

## Upstream adapter boundary

Inspected and used the existing multilspy factory at
`9203732e4e5f65cc1374b109110f7b6354d3d43b`, the historical P3.4 standalone probe revision (before P3.3 integration), in
`pyproject.toml` and `uv.lock`:

- `TypeScriptLanguageServer` handles both TS and JS.
- `ClangdLanguageServer` uses the `cpp` factory selector, including the C fixture.
- `RustAnalyzer` handles Rust.
- That revision has no Marksman, Bash, Makefile, YAML or JSON factory selector.

Five constructor probes passed with explicit installed binaries. They bypass
upstream runtime installation. An unknown multilspy revision is not used for
construction. The TS module's platform check normally invokes PATH-selected
`file`; this QA probe supplies the current interpreter's pointer width during
construction. No provider starts during constructor probes.

**Constructor success is not an upstream adapter session pass.** The existing
adapters assert specific completion option dictionaries. Their initialization
and startup APIs do not expose this probe's full conservative settings and
argument policy. Rust also waits for its experimental readiness notification.
The clangd/Rust download manifests lack Linux ARM64 artifacts; explicit binaries
bypass those manifests. These are source observations, not runtime failures.

For capability discovery, a small QA-only POSIX stdio peer therefore sends the
fixed handshake directly. It is under `scripts/`, has no production imports,
and is not used by the Binnacle provider owner. No replacement production
adapter was added. Full upstream adapter sessions and semantic APIs remain
unprobed for these installed versions.

## Provider observations

Every installed case completed initialize, shutdown and exit in the final run.
Document-symbol gold checks require the expected name and valid source range.
Definition gold checks require the exact fixture URI and declaration position.
All fixtures use ASCII; this does not establish Unicode coordinate correctness.

| Provider / language | Installed version | Observed correctness | Advertised, not exercised (selected) | Not advertised in this client profile / unsupported |
| --- | --- | --- | --- | --- |
| TypeScript LS / TS | 6.0.0; TypeScript 6.0.3 | `answer` symbol; cross-file `twice` definition | References, hover, workspace symbols, type definition, implementation, completion | Declaration, call hierarchy, pull diagnostics absent |
| TypeScript LS / JS | 6.0.0; separate JS fixture | `answer` symbol; cross-file `twice` definition | Same selected capabilities as TS | Same omissions as TS |
| clangd / C | 19.1.7 | `twice` symbol and same-file definition | References, declaration, hover, workspace symbols, type definition, implementation, call hierarchy | Pull diagnostics absent |
| clangd / C++ | 19.1.7; separate C++ fixture | `twice` symbol and same-file definition | Same selected capabilities as C | Pull diagnostics absent |
| rust-analyzer | 0.3.3065-standalone | Detached-file `twice` symbol | Definition, references, hover, workspace symbols, hierarchy, pull diagnostics | Cargo workspace semantics and project readiness unprobed |
| Marksman | 2026-02-08 | `Probe` heading symbol with `.marksman.toml` and linked document | Link definition, references, hover, workspace symbols | Declaration, type definition, implementation, hierarchy, pull diagnostics absent |
| Bash LS | 5.6.0 | `answer` function symbol after document diagnostics notification | Definition, references, hover, workspace symbols | Type definition, declaration, hierarchy, pull diagnostics absent; sourced-function navigation unprobed |
| make-language-server | Not installed | None; no process launched | None observed | No adapter or protocol support claim |
| YAML LS | 1.24.0 | `answer` key symbol | Definition, hover, completion, rename, code actions, formatting | References, workspace symbols, type definition, hierarchy, pull diagnostics absent |
| VS Code JSON LS | extracted package 4.10.0 | `answer` key symbol | Hover, pull diagnostics, code actions | Definition, references, workspace symbols, completion, rename, formatting absent |

The requested `make-language-server` executable is absent. A separate `make-ls`
symlink exists. It was not executed or accepted as the requested server. Its
identity and arguments need review. The JSON records
`alternate_make_ls=present_unreviewed_not_launched`; it does not imply support.
Earlier mapbook inventory described another host/date and is not this probe.

Absence means **not advertised for these initialize capabilities/settings**,
not proof that the server never implements the method. Dynamic registrations
are refused. In particular, JSON completion/formatting may depend on client
capabilities. Advertised editing/command capabilities are inventory only;
no rename, formatting, code action or execute-command request was sent.

## Conservative fixture controls and limits

- All projects, HOME, XDG cache/config/data and temporary files are disposable.
  Environment injection such as `NODE_OPTIONS`, `PYTHONPATH`, proxy and Cargo
  configuration is not inherited. PATH contains only the explicitly selected
  Node helper. No npm, Cargo, compiler, ShellCheck or shfmt is exposed on PATH.
- TS/JS use a pinned-by-hash installed tsserver path, no plugins, disabled
  automatic typing acquisition and `noEmit`. The fixtures contain no package
  scripts or workspace plugins. See upstream [TS configuration](https://github.com/typescript-language-server/typescript-language-server/blob/master/docs/configuration.md).
- clangd runs with background index, clang-tidy and project config disabled,
  memory PCH and one worker. Separate C11/C++17 compile flags are supplied;
  no build command or query-driver permission is supplied.
- Rust uses a detached file, no Cargo manifest, no linked project, no sysroot,
  and disabled build scripts, checks and proc macros. This is syntax evidence,
  not Cargo navigation evidence. Upstream explicitly assumes trusted code;
  see [rust-analyzer security](https://rust-analyzer.github.io/book/security.html).
- Bash uses `start`, disabled ShellCheck/shfmt/explainshell and background
  indexing. Its configuration round trip precedes analysis. A bounded wait for
  that document's diagnostics avoids a false fast-empty symbol result. This
  notification is not a workspace diagnostic-completion proof. See
  [Bash LS](https://github.com/bash-lsp/bash-language-server).
- YAML/JSON use `--stdio`, no schema associations or schema URLs. YAML schema
  and Kubernetes CRD stores are disabled; JSON schema downloads are disabled.
  See [YAML LS settings](https://github.com/redhat-developer/yaml-language-server).
- All fixed fixture files remained unchanged, with no extra top-level project
  entries in the final run. This is a narrow observation, not a complete
  filesystem, network, child-process or transient-write audit.

The session deadline covers sends, receives, reverse requests and semantic
checks. Frames are limited to 8 KiB headers and 1 MiB bodies. Stderr is discarded;
notifications are not accumulated. Reverse configuration returns only fixed
settings. Apply-edit is explicitly denied; commands, dynamic registrations,
custom schema requests and other requests receive method-not-found.

Cleanup closes pipes, reaps the leader and sends TERM then KILL to its dedicated
POSIX process group, even when the leader has exited. It has an independent
bounded cleanup budget. Same-group child cleanup and TERM resistance are tested.
`group_signaled_leader_reaped` is deliberately not an assertion that detached
or escaped descendants were contained. No OS network or filesystem sandbox is
provided. Native QA requires trust in the installed provider binaries.

## Validation and remaining gates

The first native attempt had five Node-provider failures because the harness
assumed `/usr/bin/node`. Explicit helper selection fixed that assumption. A
subsequent Bash symbol request returned empty before its async initialization
finished; the source-bound diagnostics barrier fixed that race. One later C++
run acknowledged shutdown but exceeded the initial three-second exit budget;
cleanup ran and the case was correctly failed. The final exit budget is five
seconds within the unchanged total session deadline. No failed request is
counted as valid latency evidence; this task reports no performance ranking.

Final validation on this checkout:

| Check | Actual result |
| --- | --- |
| Native synthetic matrix | **9 passed, 0 failed; 1 requested executable not installed**; run `47ce32ad808a41e7b8f7fb9c36be32a8`, UTC `2026-10-22T12:41:05.328943+00:00` |
| Focused pytest, seed 12345 | **82 passed, 0 failed** in 5.91 s: 52 P3.4 synthetic cases and 30 existing P3.1 policy cases |
| Existing MCP surface/golden selection | **2 passed, 15 failed**; the identical 15 failures reproduced from a temporary archive of untouched `66697d2` using the same locked environment |
| Ruff check of repository / format of seven added Python files | Passed |
| Bandit on four probe modules | Passed |
| Linux mypy, `src/binnacle tests scripts` | **908 source files passed** |
| Dependency audit (`deptry`) | Passed |
| Architecture / import contracts | Zero architecture violations; **25 contracts kept, 0 broken** |
| Module size | **908 modules**, zero errors; 81 existing warnings; all added modules below 450 lines |
| OS6 inventory generation and check | **281 production modules, 72 scripts, zero architecture violations**; ran locally, then restored the old generated report because this task does not integrate source boundaries and regeneration also rewrites unrelated historical entries |
| `git diff --check` | Passed |
| Development doctor | Locked environment, interpreter and lock pass; two shared Git hooks remain missing; shared hooks were not installed |
| Full pre-commit | **Incomplete**: first bootstrap failed on read-only npm cache; retry with disposable npm/uv/pre-commit caches timed out after 240 s while installing `markdownlint-cli2` |
| Pre-push, authoritative coverage-policy, Python matrix, hosted CI | Not run; no integration or release GO claimed |

The existing MCP failures report a rejected initialize handshake for protocol
`2026-07-28`, with two identity variants reporting unavailable full capture.
The original combined selection was 69 passed / 15 failed before the later
P3.4 tests were added. No production source or contract snapshot was changed to
make these baseline failures pass.

Development test failures were also retained in the work record: an incorrect
fake-frame length (1 failed / 36 passed), the upstream platform check invoking
`file` (2 failed / 71 passed), and an immediate descendant-state assertion
racing SIGKILL delivery (1 failed / 81 passed). These were corrected by fixing
the fake frame, supplying interpreter bitness to the constructor probe, and
using a bounded child-exit wait. The final 82-case result above includes these
regressions. The additional cases exercise malformed framing, blocked writes,
notification floods, denied reverse requests, cleanup failures, TERM resistance,
and child cleanup after the leader has already exited.

The usage guard command was unavailable on this host. No unattended manager
was started. Native fixtures and optional adapter construction required no
change to production configuration or shared host installations.

P3.5 medium/real corpora, resident memory and latency evidence remain open.
P3.3 filesystem/network/process containment and independent security review
remain separate gates. No provider is READ eligible. No commit, push, rebase,
deployment, shared-hook installation or edit to another worktree was performed.

## Integrated candidate revision note — 2026-10-23

The P3.3–P3.6 integration candidate pins `08ba0dbe60b6e0a3eff4796cb77ff5c0837bc892`,
a descendant of the historical P3.4 `9203732` adapter revision. The intervening
upstream diff changes process-environment configuration and shared launch wiring,
not the TypeScript/clangd/Rust adapter implementation files. The integration
copy of `scripts/lsp_p34_evidence.py` admits ONLY the new exact lock revision.
The original native P3.4 JSON (Sextant, October 22) remains historical and
contains source hashes of the original probe; these should not be interpreted
as hashes of the modified integration script. A fresh native integrated report
with the new script digest is required and will be recorded separately.
This change neither certifies READ nor claims whole-adapter runtime tests.

### Integrated pinned-revision native rerun

On Raspberry Pi Linux ARM64 the actual *integrated* optional multilspy VCS
revision `08ba0dbe60b6e0a3eff4796cb77ff5c0837bc892` was installed with
`uv sync --locked`. The fresh [sanitized native report](p3-4-breadth-native-integrated-2026-10-23.json)
ran **9 of 10 installed-language fixtures successfully, zero failures**, with
one `make-language-server` not installed. Every probe script SHA-256 matches
the integrated working source; this supersedes the original Sextant report
for source identity while retaining the latter as historical evidence.
This is synthetic, trust-only QA. It does not imply OS confinement, full
multilspy adapter execution, or P3.6 resource acceptance.

## Postreview native fixture status, 2026-10-23

The actual P3.3–P3.6 follow-up candidate runs P3.4 with stricter side-effect
gating: an installed provider passes only if its fixture is unchanged, the
workspace contains no unexpected file, a reviewed semantic gold succeeded,
and the session/cleanup completed safely. Re-running all ten synthetic
provider profiles resulted in **9 pass, 1 not installed, 0 failures**.
All four probe script SHA-256 values in the
[postreview raw report](p3-4-breadth-native-postreview-2026-10-23.json)
match their actual source bytes. This remains opt-in synthetic/private
provider evidence, **not** an OS sandbox certificate or READ authorization.
