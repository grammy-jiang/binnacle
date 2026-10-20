# Development Intelligence implementation — P6/P7 expansion

| | |
| --- | --- |
| **Status** | Session-sized execution plan split 2026-09-30 |
| **Current baseline** | `f1493ee` |
| **Purpose** | Provider production expansion template and future design-only evolution |
| **Roadmap index** | `docs/lsp-development-intelligence/implementation-plan.md` |

> Execute exactly one work item per ChatGPT session unless the item itself is split further.

---

## 9. Phase P6 — production provider expansion

Benchmark compatibility does not imply READ/public eligibility.

Use this four-session template for each provider demanded by real usage.

### P6.Xa — provider safety audit

**One provider only.**

Inspect:

- workspace writes/caches;
- project-code/build-script/plugin execution;
- required safe settings;
- resource cost;
- capability/version behavior.

**Decision:** ELIGIBLE / EXPLICIT-TRUST-ONLY / BENCHMARK-ONLY.

No public enablement in the audit session.

### P6.Xb — provider production profile implementation

Start only after `P6.Xa = ELIGIBLE`.

Implement audited settings/profile for that single provider plus focused unit/safety tests.
Do not run the full real-provider/resource checkpoint in this session.

### P6.Xc — provider real safety validation

**Depends:** P6.Xb.

Run only the real-provider smoke and filesystem/project-code side-effect checks.

**Decision:** SAFE AS IMPLEMENTED / REWORK.

Do not collect the full residency/resource baseline in this session.

### P6.Xd — provider resource and contract baseline

**Depends:** P6.Xc = SAFE AS IMPLEMENTED.

Measure resident RSS/CPU/latency for the provider and run the relevant existing contract
suite. No profile-design changes unless a new work item is created.

Create separate Xa/Xb/Xc/Xd groups for:

- TypeScript/JavaScript;
- rust-analyzer;
- clangd;
- Marksman;
- bash-language-server;
- make-ls.

Do not combine providers in one enablement session.

---

## 10. Phase P7 — future evolution

These are intentionally not implementation tasks yet.

Create a new design/benchmark work item before pursuing any of:

- natural-language semantic repository retrieval;
- automatic semantic routing;
- raw additional LSP verbs as public tools;
- generic per-provider cgroup service/delegation;
- provider downloads/install management;
- write-oriented code actions/rename/format.

The removed indexed-`@context` pilot remains the precedent: a feature that is fast but fails
workflow quality should be removed, not rationalized.

---
