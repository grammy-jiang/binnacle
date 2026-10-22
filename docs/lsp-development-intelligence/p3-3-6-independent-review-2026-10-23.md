# P3.3–P3.6 independent code and security review — 2026-10-23

**Review target:** Binnacle commit `ae545d13adc35bdb09f5772e259da7cc6120daf0` against `66697d2`.

**Independent reviewer:** local Claude Code, Sonnet, high effort, read-only source tools (no Bash/Edit/Write), no PR/commit/push/deploy permissions. Review completed successfully with about US$0.87 in reported model-call cost. This is a source review, **not** an authenticated third-party security attestation or OS sandbox certificate. The subsequent fixes described below were made **after** this review and require the same normal regression/CI gates.

## Findings and remediation

| Finding | Severity | Disposition in follow-up candidate |
| --- | --- | --- |
| H1: `scripts/lsp_benchmark/native.py` recorded PATH-selected Node while `PrivatePyrightProcessOwner` launched the selected Pyright alias's sibling Node | High | **Fixed** by resolving and hashing that sibling Node, never using PATH discovery. Source-bound negative/identity tests revised. |
| H2: Pyright Node/JS/native executable file/path ownership, writable ancestor, hardlink and mount/TOCTOU risks are not fully OS-enforced | High proof gap | **Open, READ NO-GO**. The selection is operator-explicit-trust only; don't represent the path checks as isolation or allow untrusted repository READ. Proper filesystem/network/process containment and trusted package inventory require a separate acceptance gate. |
| H3: P3.6 structured JSON allows synthetic self-declared reviewer fields; no verified artifact importer or cryptographic reviewer identity, so a standalone policy predicate GO cannot attest real P3.3–P3.5 runs | High | **Still open for P3.6 acceptance / P4**. Offline decision result now explicitly carries `attestations_verified=false` and the CLI returns nonzero (3) even for candidate predicate GO; public READ/release remain NO-GO. External evidence verification remains unimplemented. |
| M1: P3.4 would report `pass` before checking synthetic fixture mutation or confirmed document-symbol gold | Medium | **Fixed**: pass now requires unchanged fixtures, no extra root entries, and proven symbol gold; added an actual side-effect test. |
| M2: P3.6 envelope did not bind timeout settings; 0-second-ish soak and zero RSS/latency could count positively | Medium | **Fixed in offline policy**: request/idle timeout must match selected settings, soak at least 60 s, RSS/latency samples strictly positive. Does not assert real measurements exist. |
| M3: P3.5 functional `valid` could accept incomplete resources, unsupported operations, or unverified initial gold | Medium | **Fixed**: cold result checked against gold, all requested operations/instances and observed positive RSS with no sampling errors required. Validity still means functional synthetic/selected-source check, never authoritative production admission. |
| M4: Manager definition measurements use Binnacle P2.5/P2.6, other methods use direct LSP; source-subset snapshots are not whole-repository indexing | Medium | **Clearly recorded as limitation**, not a manager-overhead subtraction or full-repository result. A validated separate measurement schema is needed before feeding P3.6. |
| M5: Optional real Pyright tests require explicit environment, are skipped in default generic suites | Medium proof gap | Opt-in Pyright and native P3.5 were exercised separately on macOS and Linux. Generic skipped counts are still accurately reported; full review of platform-specific confinement remains open. |
| M6: P3.4 upstream adapter constructors run in process outside the child Peer environment restrictions | Medium proof gap | Scope remains operator-trusted synthetic QA; no production adapter or untrusted executable adoption. Additional constructor side-effect controls are required before wider provider admission. |

The reviewer also noted narrower low-severity process-group PID-reuse race windows, sensitivity of language locale variables, and lack of source-bound strong external review authentication. These are **not** represented as fixed merely because the existing regression suite is green.

## Evidence and acceptance gates

- P3.3/P3.4/P3.5/P3.6 functionality stays disabled by default; public MCP tool inventory is unchanged. `READ` and `public_release` in P3.6 remain literal `NO-GO`.
- Prior integrated native Linux (Raspberry Pi) managed full suite: 8,379 passes, zero failures; pre-commit, pre-push, coverage-policy gates passed. Independent source remediation needs a fresh final CI cycle.
- macOS and Sextant rechecks of the new remediation have passed their scoped Pyright/decision suites. The source-subset workload results are retained in [the post-review P3.5 report](p3-5-reviewed-real-subset-2026-10-23.md), with hashed, reproducible manifest and raw sanitized output.
- GitHub Actions run [39793203424](https://github.com/grammy-jiang/binnacle/actions/runs/39793203424) on the original `ae545d1` integration commit failed Python 3.10 because an existing Issue #30 test raced the independent Guardian holding a journal lease. Other 3.11/3.12/3.14, Code Quality, Coverage and Packaging checks passed. The test-only bounded retry for the specific transient journal lock condition now passes **20 of 20** independent focused Python 3.10 reproductions, and the Python 3.10 managed full suite passed 8,274 parallel-safe tests plus 98 ordinary-process tests (353 and one optional skip, respectively), with no failures. A new hosted CI run is required after committing the remediation.
- Independent review was limited to code and selected tests, not a binary integrity certificate, runtime OS isolation, long production soak, or real multi-project Agent value evaluation.

## Final verdict, separated by authorization boundary

| Gate | Current status | Rationale |
| --- | --- | --- |
| P3.3–P3.6 private code integration | **REWORK until post-review CI is green** | Major concrete source-review issues fixed; remaining regressions and hosted Python matrix must confirm the changed revision. |
| READ on untrusted repositories / general OS confinement | **NO-GO** | No proven strict OS filesystem/network/process sandbox or atomically pinned executable tree. |
| P3.6 production resource envelope or evidence-qualified GO | **REWORK** | Actual resource benchmarks are narrow and do not have source-verified reviewer attestations, idle/TTL/soak/runtime-envelope completeness. |
| P4 private Agent-facing experiment | **REWORK** | P3.6 requires a validated cross-stage evidence importer and safety gate before advancing. No public tool will be registered. |

**No production deployment, READ promotion or GitHub merge is authorized by this report.**
