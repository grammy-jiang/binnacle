# P1 deterministic infrastructure — three-host native validation (2026-10-21)

**State:** P1.1–P1.8 implemented as synthetic test-only fixtures, native validation complete, **P1.9 independent review pending** at the time of this record.
**Scope:** one isolated LSP Git branch on MacBook Pro, with SHA-256 verified test bundles executed in dedicated `/tmp` directories on both Raspberry Pi hosts. No production modules, services, client tool contracts, actual LSP providers, remote GitHub connectors, or deployment have been modified or exercised.

## Evidence class, limits and fixed test corpus

All tests are **synthetic / fixture-only**, not tests of a production Binnacle LSP client/manager. The fake LSP, protocol peer, fake CLI analyzer, side-effect manifests, resource sampler and raw benchmark are Python test infrastructure. The benchmark's pre-registered synthetic gold manifest is versioned and SHA-256 pinned; semantic payload equality is required **before** latency becomes valid evidence. `initialize` is **not** proof that a real language server indexed a project. `settling` remains unobserved; there is no fixed real-provider RSS budget or warm-memory certification.

The Linux test bundle was compressed and transported through the existing host MCP commands, SHA-256 verified after transfer, and unpacked only under `/tmp/binnacle-lsp-p1-full-20261021`. Archive SHA-256:
`ec599cb5a39a46abef326439ff016cfc99c3a7600dac936f4651a9cf0f364330`.
A temporary Git repository and **synthetic** local fixture commit were created in each test directory solely to satisfy reproducible benchmark source-revision recording. Neither production Git repository was modified. No host-installed Pyright, clangd, rust-analyzer, TypeScript LS, or other third-party provider was started.

## Native execution matrix

| Host | OS and tested Python | Seed 12345 | Seed 8675309 | Real `ps` observation |
| --- | --- | --- | --- | --- |
| MacBook Pro | Darwin arm64, project venv Python 3.13.16 | **176 passed** | **176 passed** | Enabled; benchmark/resource tests **70 passed** during earlier focused probe |
| Raspberry Pi (`raspberrypi`) | Linux aarch64, project venv Python 3.13.5 | **176 passed** | **176 passed** | Enabled (no resource tests skipped) |
| Raspberry Pi (`sextant`) | Linux aarch64, project venv Python 3.13.5 | **176 passed** | **176 passed** | Enabled (no resource tests skipped) |

These are six independent full fixture-suite passes at two deterministic `pytest-randomly` seeds; unit and integration tests cover protocol, bidirectional dialogue, framing faults, process cleanup, analyzer, benchmark gold, resource accounting and compatibility negative cases. The initial Codex restricted-sandbox run had 2 `ps` cases skipped because sandbox process enumeration was denied; **this is not used as native proof**. All native host suites ran without those skips.

A first Linux run failed the stderr-flood fixture on both Pis (**98 passed, 1 failed each**) because the test confused the writer's flush with the independent reader having drained all 256 KiB. Fixed in `bc233d5` with a bounded wait for complete observed consumption. Both Pis then passed the 99-case P1.1–P1.6 suite and the subsequent 176-case full suites. The counterexample is preserved as fault-detection evidence, not hidden.

## Work package / test traceability

| Work package | Test assets and coverage |
| --- | --- |
| P1.1 | `tests/fixtures/lsp/fake_stdio_server.py`, `tests/unit/core/test_fake_lsp_server.py`; initialize/definition/shutdown/exit |
| P1.2 | `tests/fixtures/lsp/lsp_payloads.py`, `lsp_peer.py`, `tests/unit/core/lsp_capabilities_test.py`; false/true capabilities, null/multi/LocationLink and hover/reference results |
| P1.3 | `lsp_dialogue.py`, `tests/unit/core/lsp_dialogue_test.py`; didOpen/Change/Close, server requests and edit/command denial |
| P1.4 | `lsp_transport.py`, `tests/unit/core/lsp_transport_test.py`; split/coalesced/malformed/oversized frames, wrong/late/duplicate IDs |
| P1.5 | `process_faults.py`, `process_observer.py`, `tests/integration/test_lsp_process_faults.py`; hang, crash, EOF, cancellation, non-exit, cooperative descendant and escaped-session cleanup witnesses |
| P1.6 | `fake_analyzer.py`, `analyzer_audit.py`, `side_effects.py`, `tests/integration/test_lsp_analyzer_audit.py`, `tests/unit/core/lsp_analyzer_test.py`; no-false-clean, cache/workspace writes, symlink and manifest anomalies |
| P1.7 | `benchmark_manifest.json`, `raw_benchmark.py`, `tests/integration/test_lsp_raw_benchmark.py`; gold-before-timing, versioned provider/harness identity and 30 resident requests |
| P1.8 | `resource_sampling.py`, `benchmark_compare.py`, `tests/integration/test_lsp_benchmark_resources.py`; cold/settling/warm, tree-inclusive RSS/CPU, PID identity, comparator rejection of incompatible or invalid evidence |

No test module exceeded the repository's 500-line Python-module hard limit. Test helpers do not become production MCP modules or public tools.

## Other unchanged Binnacle quality gates (MacBook Pro)

- Existing composition, tool surface/visibility, golden responses, token budget, exact `search_text` and search preservation: **66 passed, 13 skipped, 2 xfailed** (baseline tests; existing skips/xfails are not newly waived).
- Ruff check and format on all new fixture/integration/unit assets: passed.
- Architecture policy: **259 modules checked, 0 forbidden reverse dependencies**.
- Import Linter: **25 contracts kept, 0 broken**.
- Generated startup import inventory `--check`: passed, intentionally unchanged because no production source module was introduced.

## Boundary of evidence

P1 does **not** prove a real provider can safely read untrusted code, execute without side effects, recover all descendants after a supervisor crash, remain within resource budgets, or produce correct results on a real repository. Synthetic escaped-session descendants are cooperative and controlled by private pipe/watchdog. Filesystem manifests observe **final state**, so transient writes that are reverted cannot be excluded. Periodic `ps` can miss short-lived children, and RSS includes shared-page double counting. These limitations are intentionally reflected in benchmark metadata and must remain blockers for READ/public claims.

**Next:** P1.9 independent code/test reliability review, issue tracking and signed GO/REWORK for the P1 foundation. P2 remains unstarted and requires its own later authorization and implementation gates.
