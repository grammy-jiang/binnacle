# P2 upstream-first adoption assessment: Microsoft multilspy

Date: 2026-10-21. Status: research complete; preferred dependency migration
candidate, with concrete compatibility gates. **Not a runtime migration or
P2.4 release approval.**

Upstream source: <https://github.com/microsoft/multilspy>
Audited tag: v0.1.1, commit 62acb3cf2d7a0746992ca08767d8a4fded402ebb
MIT; upstream metadata classifies its maturity as Pre-Alpha.
Source inspected in a detached, disposable /tmp checkout, not Binnacle.
Main branch and PyPI release were NOT treated as equivalent to this tag.
GitHub v0.1.1 (Oct 13, 2026) differs from PyPI latest 0.0.15 (Apr 3, 2025).
No Binnacle source or deployment state was changed by this investigation.

## Upstream adoption decision

Prefer using the upstream multilspy API to maintaining duplicate Python
JSON-RPC / LSP / language-specific adapters. This supersedes the **selection
direction** of the original P2.1 stdlib ADR, but does not invalidate the
already-tested private P2.2/2.3 implementation; retain it as an independent
fault/behavior oracle until replacement passes. Do not add multilspy to
production dependencies or delete the current client until the POC gates pass.
Avoid a persistent private fork; prefer upstream contributions.

## Direct upstream functionality

- LanguageServer.create, async start_server, definition, references, hover,
  completion, document symbols, workspace symbol, file buffers/didOpen/didClose.
- Integrated JSON-RPC stdio, language-specific initialize parameters,
  binary download/setup, subprocess process-tree shutdown.
- Language enum: python/Jedi, java, kotlin, rust, csharp, typescript,
  javascript, go, ruby, dart, cpp/clangd, php and elixir (13 names).
- Binnacle's nine planned provider profiles map directly to only three
  bundled adapters: typescript, clangd and rust_analyzer. Pyright, marksman,
  bash, make, yaml and json are absent. Python exists only via Jedi, not
  the currently planned Pyright.
- Additional JVM/Node/Dart/Dotnet/Elixir runtimes may be needed for their
  language providers; cross-platform behavior requires native tests.

## Concrete gaps / blockers

1. P2.4 process ownership integration: upstream handler uses
   asyncio.create_subprocess_exec and psutil recursive child termination;
   no public injected-owned-stream transport or Binnacle process-lifecycle
   interface. Need one authoritative process owner, resource ceilings,
   cancellation and cleanup_unverified handling across Linux/macOS.
   Binnacle process confinement is NOT proven by multilspy's cleanup.

2. No-install/offline invariant: server_binary can bypass automatic downloads
   for several adapters, but Java/JDTLS and Kotlin adapter sources do not
   consult config.server_binary at all. Elixir's setup executes
   mix local.hex --force before checking config.server_binary. These
   languages cannot be enabled under Binnacle no-side-effect policy as-is.
   Other adapters may do network/package setup unless pinned binaries are
   selected and verified. The factory/config alone is not an allowlist.

3. Python provider mismatch: LanguageServer.create(python) always returns
   JediServer. Its startup asserts Jedi-specific completion capabilities;
   pointing server_binary at pyright-langserver does not turn it into a
   Pyright adapter and does not supply Pyright --stdio argv. Pyright
   integration needs a tested upstream adapter or small guarded provider
   contribution; do not claim Pyright is supported.

4. Authorized file and returned URI handling: upstream open_file constructs
   PurePath(repository_root, relative_file_path), then reads directly;
   no equivalent of Binnacle's allowed-root, symlink, TOCTOU and returned
   Location URI filtering is present. Binnacle retains P2.5 path and file
   snapshot policy, protects returned URIs, and disallows client-edit APIs.
   Upstream open_file scopes didOpen/didClose to each query and maintains
   in-memory buffer versions, which need freshness/concurrency tests.

5. Protocol strictness and timeouts: upstream send_request waits on a
   condition with no built-in request deadline; canceled waits can leave
   _response_handlers entries. run_forever reads Content-Length without a
   bounded frame maximum. Need upper bounds, pending limits, completion /
   timeout cleanup, malformed payload fail-closed checks and cancel semantics.
   Upstream-first fixes are preferable to permanent proprietary patches.

6. Wire response normalization: request_definition requires
   originSelectionRange for LocationLink, although LSP 3.17 defines that
   property as optional. request_references asserts list, although LSP
   allows null. Both are direct correctness POC cases and candidates
   for upstream fixes. Binnacle still needs result provenance, semantic
   status and clipping for agent-facing inspect_symbol.

7. UTF-16 conversion/capabilities: upstream public query arguments use
   caller-supplied line/column and TextUtils measures Python codepoints.
   Non-BMP text requires explicit UTF-16 conversions. Language adapters
   impose fixed initialize/completion assertions that can reject
   compatible servers with different but valid capability responses.
   Binnacle retains P2.3 position and capability checks as oracle.

8. Reverse requests and logging: upstream language handlers register
   method-specific callbacks including dynamic client/registerCapability.
   Its message handler logs raw payloads when trace is enabled and raw
   server stderr through logger callbacks. Binnacle needs its exact
   reject-edit/execute whitelist, bounded logging, and no sensitive source
   or raw server errors in exported tool responses.

9. Provider management and diagnostic capability: upstream does not supply
   Binnacle host-level enabled/disabled tool admission, resident registry,
   multi-workspace single-flight/cooldown/TTL, READ classification or
   independent check_code analyzer contract. P2.0/P2.5/P2.6/P2.7, P3
   provider auditing, and P6 remain Binnacle responsibilities.

10. Packaging: v0.1.1 requires Python >=3.10,<4 and declares
    jedi-language-server==0.41.3, requests==2.33.0,
    psutil>=7,<8, typing-extensions>=4.2. Binnacle supports Python
    3.10–3.14; each supported version and native Darwin arm64 /
    Linux aarch64 must resolve/install and pass actual tests. Jedi is
    a mandatory package dependency even if only clangd is used.
    Exact upstream commit/version, license, build and offline artifact
    identity must be pinned for reproducible host deployment.
    MultilspyConfig.from_dict silently discards unknown keys: use only
    validated Binnacle P2.0 settings when constructing upstream config.

## Current host readiness (PATH inventory only)

- MacBook Pro: Darwin arm64; clangd present; Jedi, Pyright,
  rust-analyzer, TypeScript language server, Marksman and Bash LS absent.
- Raspberry Pi and Sextant: Linux aarch64; Pyright, clangd,
  rust-analyzer, TypeScript LS, Marksman and Bash LS present; Jedi absent.
- Existence on PATH does NOT establish the backend version, service PATH,
  trust, resource, network or file side-effect eligibility.

## Minimum bounded migration POC (no E2/E3 historical research)

A. Build an isolated, pinned multilspy v0.1.1 environment with no
   preinstalled-provider auto downloads. Confirm Python 3.10/3.14
   packaging and the native host combinations.

B. Run existing P1 fake and a preinstalled TS/clangd provider on a
   disposable workspace. Verify initialization, definition/ref/hover,
   null and LocationLink variants, UTF-16, exact file snapshot and
   returned URI authorization. Add Jedi-vs-Pyright explicit decision.

C. Reuse the P1 failure fixtures: malformed/giant frame, hung request,
   writing backpressure, late/duplicate response, cancellation, child
   spawn/kill, unrelated process safety, denied edit/execute commands.
   No network or unapproved workspace modification.

D. Choose ONE lifecycle integration: preferably upstream injected
   transport/process-owner extension or an upstream-managed process
   under validated Binnacle supervisory constraints. Reject uncertain
   descendant containment; log cleanup_unverified honestly.

E. If POC passes, write only a thin Binnacle multilspy adapter and
   retire overlapping custom runtime modules. Preserve test oracles,
   existing root six/eight tool surface, default-off child and no
   public READ claim until P3 provider audit and release gates.

**Decision gate:** multilspy is preferred, but cannot yet be claimed
drop-in compatible or production safe. Limit the next POC to these
few deterministic tests; do not restart retrospective evaluation.
