# P1.9 deterministic fixture reliability acceptance — 2026-10-21

**Verdict: GO for the P1 synthetic fixture/test-infrastructure foundation only.**
**Review path:** initial independent [REWORK](p1-9-initial-review-2026-10-21.md) on `3327531` -> focused corrections on two independent branches -> merge `57c3044` -> independent [GO](p1-9-followup-review-2026-10-21.md). Reviewers did not edit source during either read-only audit.

## Closure of four independent blockers

| Finding / risk | Correction and regression proof | Status |
| --- | --- | --- |
| Benchmark could accept a wrong or duplicate Content-Length header | ProcessObserver now uses LspPeer's shared, bounded JSON-object decoder; malformed framing and invalid benchmark artifacts tested through both peer types | PASS |
| Post-spawn constructor exception could leak an owned process, pipe or selector | Transactional rollback for selector creation, registration, pipe setup and set-blocking; fault injection and cooperative synthetic escaped-child reaping; failures cannot silently certify cleanup | PASS |
| Unsupported runtime import: `typing.Self` on Python 3.10 | Removed runtime-only incompatible import; Python 3.10–3.14 interpreter tests ran natively | PASS |
| Timeout mid-header/body destroyed partial frame state | Persist pending frame length across calls; test staged Unicode/UTF-8 splits, timeouts and coalesced next response | PASS |

Independent follow-up additionally checked cleanup error propagation, stdout EOF versus timeout distinction and that destructive signals refer only to owned subprocess handles, never to untrusted trace-supplied PIDs.

## Executable evidence — native platforms

Every count below includes the entire P1 synthetic test corpus after merging the reliability test cases from both development branches, including P1.1–P1.8. All runs were native host executions, **not Codex's restricted sandbox**.

| Host | Interpreter | Seed(s) | Result |
| --- | --- | --- | --- |
| MacBook Pro, Darwin arm64 | CPython 3.10.22 | 8675309 | **373 passed** |
| MacBook Pro, Darwin arm64 | CPython 3.11.17 | 12345 | **373 passed** |
| MacBook Pro, Darwin arm64 | CPython 3.12.15 | 12345 | **373 passed** |
| MacBook Pro, Darwin arm64 | CPython 3.13.16 | 12345 | **373 passed** |
| MacBook Pro, Darwin arm64 | CPython 3.14.8 | 8675309 | **373 passed** |
| Raspberry Pi, Linux aarch64 | CPython 3.13.5 | 12345, 8675309 | **373 passed per seed** |
| Sextant, Linux aarch64 | CPython 3.13.5 | 12345, 8675309 | **373 passed per seed** |

Linux test source was updated only in the existing synthetic `/tmp/binnacle-lsp-p1-full-20261021` directories. A five-file tar archive was verified after transfer with SHA-256 `5f1f5f487aecd43f1bf19fa5af32aac36b1070b9c48931418b5322ba9b79f8f3`. A temporary local Git commit was created within each test fixture directory for reproducible benchmark identities; neither production Git repository nor running MCP service was modified.

The first development Codex sandbox run reported two native `ps` skips because process enumeration was denied. These skips are **excluded** from acceptance counts. Native Mac and Linux tests ran without those skips. Initial cross-platform stderr-drain races had already been fixed by prior commit `bc233d5`.

## Existing MCP compatibility and quality gates

- Existing Binnacle surface/visibility, composition, golden outputs, token budget, exact search and preservation subset: **66 passed, 13 skipped, 2 xfailed** (pre-existing skip/xfail policies retained).
- Ruff check and formatting of all 24 synthetic fixture/test modules: passed.
- Architecture policy: **259 production modules; zero forbidden reverse dependencies**.
- Import Linter: **25 contracts kept; zero broken**.
- Frozen startup module inventory generator `--check`: passed.
- New/changed test modules adhere to the 500-physical-line ceiling (maximum observed: 384 lines).

## Scope boundaries / risk carried into P2–P3

- This is **not** validation of a production LSP client, protocol dispatcher, provider registry or FastMCP-mounted new public tool.
- No actual Pyright/clangd/TypeScript/rust-analyzer Provider was launched during P1 testing; provider correctness, untrusted repository execution safety, OS sandbox confinement and full descendant cleanup under hostile escape require later native audits.
- Synthetic descendants cooperate through a private control pipe; `ps` sampling can miss short-lived children and sums shared RSS pages. A final-state filesystem manifest cannot exclude transient reverted writes. Index settling remains unobserved.
- P1's normalized fake gold and timings are not proof that a seventh ChatGPT tool saves model steps or tokens.
- The **full repository CI workflow and full coverage-policy job were not executed** as part of this P1.9 acceptance. The selected existing contracts and architecture/lint gates listed above passed, but they are not a substitute for later P2/P5 release gates.

## Go/no-go handoff

**P1.9 GO; P1.1–P1.9 is complete as private synthetic test infrastructure.** P0.6 remains GO. P2.0–P2.8 are not started. Before implementing P2, discuss the strict configuration contract, in-house JSON-RPC versus vetted client dependency, and Linux/Darwin process owner strategy. Keep `search_text` exact and existing six/eight MCP tool surfaces unchanged until later explicit product approval. No production rollout is permitted by this report.
