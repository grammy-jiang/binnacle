# Development Intelligence implementation — P2 providers

| | |
| --- | --- |
| **Status** | Session-sized execution plan split 2026-09-30 |
| **Current baseline** | `f1493ee` |
| **Purpose** | Provider profile model, trusted discovery, per-provider compatibility, and benchmark characterization |
| **Roadmap index** | `docs/lsp-development-intelligence/implementation-plan.md` |

> Execute exactly one work item per ChatGPT session unless the item itself is split further.

---

## 5. Phase P2 — provider profiles and characterization

Goal: prove the internal client is not Pyright-specific and create the first audited
profiles. One provider or one benchmark workload per session.

Read:

- `providers-and-safety.md`
- relevant provider subsection in `testing-performance.md`
- `testing-safety-contracts.md`

### P2.1 — provider profile model

**Depends:** P1.

**Scope:** language, command, intents, settings, side-effect class, project-code flag,
cache policy, root strategy.

**Validate:** profile validation unit tests.

### P2.2 — trusted discovery policy

**Depends:** P2.1.

**Scope:** explicit trusted config > audited service PATH > unavailable; reject automatic
repo-local executables.

**Validate:** PATH/.venv/node_modules/wrapper cases.

### P2.3 — Pyright LSP profile

**Depends:** P2.1/P2.2.

**Scope:** navigation-safe command/settings/capability adapter only.

**Validate:** real smoke + workspace manifest unchanged.

### P2.4 — Pyright CLI diagnostic profile

**Depends:** P2.1/P0.6.

**Scope:** one-shot JSON diagnostics, bounded execution/parsing.

**Validate:** known type error + side-effect manifest.

### P2.5 — Ruff diagnostic profile

**Depends:** P2.1/P0.6.

**Scope:** structured diagnostics, force no-fix/no-cache.

**Validate:** known lint error; no cache/source mutation.

### P2.6 — TypeScript/JavaScript LSP profile

**Depends:** P2.1/P2.2.

**Scope:** one provider profile for TS/JS.

**Validate:** cross-file gold definition/references.

### P2.7 — rust-analyzer benchmark profile

**Depends:** P2.1/P2.2.

**Scope:** benchmark/compatibility config only; no READ eligibility decision.

**Validate:** Cargo settling then gold symbol/definition/references.

### P2.8 — clangd C/C++ benchmark profile

**Depends:** P2.1/P2.2.

**Scope:** C/C++ compatibility with index persistence disabled/redirected.

**Validate:** separate C and C++ gold navigation cases.

### P2.9 — Marksman benchmark profile

**Depends:** P2.1/P2.2.

**Scope:** Markdown workspace-marker behavior.

**Validate:** link-to-heading definition/backlinks.

### P2.10 — bash-language-server benchmark profile

**Depends:** P2.1/P2.2.

**Scope:** sourced-function semantics.

**Validate:** definition/references + advertised capabilities.

### P2.11 — make-ls optional descriptor

**Depends:** P2.1.

**Scope:** descriptor + not_installed behavior unless already present. Never install it.

### P2.12 — micro benchmark: Python

**Depends:** P0.7–P0.10, P2.3.

**Scope:** data collection only; no harness changes.

### P2.13 — micro benchmark: TypeScript/JavaScript

**Depends:** P0.7–P0.10, P2.6.

**Scope:** data collection only.

### P2.14 — micro benchmark: Rust

**Depends:** P2.7.

**Scope:** data collection only; preserve cold/settling/warm distinction.

### P2.15 — micro benchmark: C/C++

**Depends:** P2.8.

**Scope:** data collection only.

### P2.16 — micro benchmark: Markdown/Shell/Makefile status

**Depends:** P2.9–P2.11.

**Scope:** data collection only; missing Makefile provider remains not_installed.

### P2.17 — medium/real workload manifest

**Depends:** P2.12–P2.16.

**Scope:** choose exact repos/commits and gold tasks. Do not execute benchmarks.

**Done:** frozen workload manifest.

### P2.18 — medium/real benchmark: Python

**Depends:** P2.17.

**Scope:** execute only Python workload.

### P2.19 — medium/real benchmark: TypeScript/JavaScript

**Depends:** P2.17.

**Scope:** execute only TS/JS workload.

### P2.20 — medium/real benchmark: Rust

**Depends:** P2.17.

**Scope:** execute only Rust workload.

### P2.21 — medium/real benchmark: C/C++

**Depends:** P2.17.

**Scope:** execute only C/C++ workload.

### P2.22 — medium/real benchmark: Markdown/Shell/Makefile

**Depends:** P2.17.

**Scope:** execute only those text/build-script workloads that have installed providers.

### P2.23 — provider characterization synthesis

**Depends:** P2.18–P2.22.

**Scope:** analysis/documentation only.

**Done:** explicit GO list for P3; unsafe/uncertain profiles remain benchmark-only.
