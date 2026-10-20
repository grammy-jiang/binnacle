# Development Intelligence implementation — P3/P4/P5 product experiments

| | |
| --- | --- |
| **Status** | Session-sized execution plan split 2026-09-30 |
| **Current baseline** | `f1493ee` |
| **Purpose** | Private inspect_symbol, conditional public semantic navigation, and conditional diagnostics experiments |
| **Roadmap index** | `docs/lsp-development-intelligence/implementation-plan.md` |

> Execute exactly one work item per ChatGPT session unless the item itself is split further.

---

## 6. Phase P3 — private `semantic.inspect_symbol(...)` experiment

Goal: test one coarse semantic-navigation intent without registering an MCP tool.

Read:

- `product-surface.md` §12
- `runtime-architecture.md`
- semantic-quality/performance sections in `testing-performance.md`

### P3.1 — normalized semantic result model

**Depends:** P1/P2.

**Scope:** internal definition/declaration/implementation/reference/type/provenance data
types and bounded status model.

**Validate:** serialization/normalization unit tests.

### P3.2 — path + line + symbol anchor resolver

**Depends:** P3.1, P1.8/P1.9.

**Scope:** locate symbol occurrence on authoritative disk text and convert to LSP position.

**Validate:** same-line duplicates, Unicode, missing symbol, ambiguity.

### P3.3 — definition/declaration aggregation

**Depends:** P3.2.

**Scope:** normalize provider definition/declaration/implementation locations.

**Validate:** unique + multiple result fixtures.

### P3.4 — bounded references aggregation

**Depends:** P3.2.

**Scope:** normalize, deduplicate, count, bound, truncate references.

**Validate:** deterministic ordering and truthful total/truncation.

### P3.5 — hover/type/signature enrichment

**Depends:** P3.2.

**Scope:** optional capability only; no failure if provider lacks it.

**Validate:** supported/unsupported fake cases.

### P3.6 — inspect_symbol status/provenance

**Depends:** P3.3–P3.5.

**Scope:** aggregate one private result with ok/partial/ambiguous/unavailable status and
provider provenance.

**Validate:** failure/partial matrix.

### P3.7 — semantic corpus schema + Python cases

**Depends:** P3.6.

**Scope:** define corpus record format and reviewed Python gold cases only.

**Do not benchmark.**

### P3.8 — add TypeScript/JavaScript corpus cases

**Depends:** P3.7.

**Scope:** reviewed TS/JS cases only.

### P3.9 — add Rust/C/C++ corpus cases

**Depends:** P3.7.

**Scope:** reviewed compiled-language cases only.

### P3.10 — add Markdown/Shell corpus cases

**Depends:** P3.7.

**Scope:** reviewed Markdown/Shell cases only.

### P3.11 — direct internal semantic benchmark

**Depends:** P3.7–P3.10.

**Scope:** call private API directly; measure correctness/result size/provider latency.

### P3.12 — temporary FastMCP test assembly

**Depends:** P3.6.

**Scope:** expose candidate only in test assembly/non-production profile.

**Do not change:** production `register_all` or `client_tools`.

### P3.13 — integration phase timings

**Depends:** P3.12.

**Scope:** workspace lookup, sync, dispatch, raw LSP, normalization, serialization timings.

### P3.14 — A/B workflow harness

**Depends:** P3.7–P3.12.

**Scope:** implement/freeze comparison harness only. Do not run final corpus.

### P3.15 — A/B execution

**Depends:** P3.14.

**Scope:** run frozen corpus only; produce raw artifact.

### P3.16 — A/B analysis

**Depends:** P3.15.

**Scope:** analyze correctness, steps, calls, tokens, wall/API time. No product decision.

### P3.17 — P3 decision

**Depends:** P3.16.

**Scope:** decision record only.

**Decision:** STOP / KEEP PRIVATE / PROCEED TO P4.

---

## 7. Phase P4 — conditional public `inspect_symbol` experiment

Start only if P3.17 says PROCEED.

Read:

- `product-surface.md`
- `testing-release-gates.md`

### P4.1 — anchor-schema comparison

**Scope:** compare `path+line+symbol` and `path+line+column` in temporary profile/model
tests.

**Done:** one selected candidate with evidence.

### P4.2 — candidate MCP schema/result budget

**Depends:** P4.1.

**Scope:** temporary/non-production tool only; freeze descriptions/annotations/output
bounds.

### P4.3 — tool-selection/argument reliability run

**Depends:** P4.2.

**Scope:** model evaluation only; no production registration.

### P4.4 — standing surface/token cost analysis

**Depends:** P4.2.

**Scope:** measure projected tool count/surface token delta and golden fixture size.

### P4.5 — public-product decision

**Depends:** P4.3/P4.4.

**Scope:** decision record only: REJECT / DEFER / SHIP.

### P4.6 — production registration

**Depends:** P4.5 = SHIP.

**Scope:** register tool + intentional `client_tools` change only.

**Validate:** focused surface/visibility tests show expected new tool count.

### P4.7 — contract/golden/token updates

**Depends:** P4.6.

**Scope:** update surface hashes, golden fixture, token budget history, instructions/docs.

**Validate:** contract suite.

### P4.8 — deployment/client compatibility checkpoint

**Depends:** P4.7.

**Scope:** no feature coding. Run required quality/deploy/client gates and document result.

---

## 8. Phase P5 — conditional diagnostics / `check_code`

This phase is independent of P4 approval, but requires safe analyzer foundations.

Read:

- `product-surface.md` §13
- `providers-and-safety.md`
- `testing-safety-contracts.md`
- `testing-release-gates.md`

### P5.1 — diagnostic usage mining

**Scope:** analyze real `run_command` history for pyright/ruff/mypy/eslint/etc frequency,
steps, output size, failures.

**Done:** demand evidence; no runtime code.

### P5.2 — normalized diagnostic result model

**Depends:** P2.4/P2.5.

**Scope:** severity/path/range/code/message/provider/coverage/truncation model.

### P5.3 — safe analyzer orchestrator

**Depends:** P5.2.

**Scope:** run eligible analyzer profiles and merge normalized results.

**Do not expose:** MCP tool.

### P5.4 — private `check_code` API

**Depends:** P5.3.

**Scope:** path/scope semantics plus ok/partial/unavailable coverage truthfulness.

### P5.5 — diagnostic A/B harness

**Depends:** P5.4.

**Scope:** compare current `run_command` workflow with private normalized diagnostics.

### P5.6 — diagnostic A/B execution

**Depends:** P5.5.

**Scope:** run frozen tasks only; produce raw artifact.

### P5.7 — diagnostic A/B analysis

**Depends:** P5.6.

**Scope:** analyze workflow/quality/cost metrics only.

### P5.8 — diagnostics product decision

**Depends:** P5.7.

**Scope:** decision record only: STOP / KEEP PRIVATE / PUBLIC EXPERIMENT.

### P5.9 — temporary public-schema experiment

**Depends:** P5.8 = PUBLIC EXPERIMENT.

**Scope:** non-production profile only; model-selection and token-cost evaluation.

### P5.10 — public diagnostics decision

**Depends:** P5.9.

**Scope:** decision record only: REJECT / DEFER / SHIP.

### P5.11 — production `check_code` registration

**Depends:** P5.10 = SHIP.

**Scope:** registration/visibility only.

### P5.12 — diagnostics contract updates

**Depends:** P5.11.

**Scope:** surface/golden/token/READ-side-effect contracts only.

### P5.13 — diagnostics deploy/client checkpoint

**Depends:** P5.12.

**Scope:** no feature coding; run live/client gates and record result.

---
