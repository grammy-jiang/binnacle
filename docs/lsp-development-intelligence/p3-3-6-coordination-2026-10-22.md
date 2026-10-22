# P3.3–P3.6 coordinated implementation — 2026-10-22

User approval: autonomous implementation of P3.3 through P3.6 without checkpoint questions, with original safe/conditional release gates retained.
Primary baseline: `66697d2` (P3.1 admission), no production deployment and no public MCP registration. The unmerged Microsoft multilspy Pyright adapter is reused rather than duplicated.

## Isolated host work and recoverable jobs

| Stage | Host | Worktree | Branch | Background MCP job |
| --- | --- | --- | --- | --- |
| P3.3 | raspberrypi | `~/Projects/binnacle-lsp-p33-security-audit-20261022` | `feat/lsp-p31-profile-admission-20261022` (dirty, original stage) | `ed098236b7be` |
| P3.4 | sextant | `~/Projects/binnacle-lsp-p34-breadth-20261022` | `feat/lsp-p34-breadth-20261022` | `f2d9159b0eb3` |
| P3.5 | raspberrypi | `~/Projects/binnacle-lsp-p35-benchmarks-20261022` | `feat/lsp-p35-benchmarks-20261022` | `3424d6faedf2` |
| P3.6 | sextant | `~/Projects/binnacle-lsp-p36-policy-20261022` | `feat/lsp-p36-policy-20261022` | `9f50bd90c871` |

Consolidation target (partially populated): raspberrypi `~/Projects/binnacle-lsp-p33-p36-integration-20261022`, branch `feat/lsp-p33-p36-integration-20261022`. The P3.4, P3.5 and P3.6 changes are staged as uncommitted code and evidence; P3.3 is pending. Overlapping plan and mapbook edits were merged without discarding stage reports.

On each Linux host, `job_status(job_id)` can recover process lifecycle. The Codex JSONL worker output is private `/tmp/binnacle_pXX_codex_20261022.jsonl`, with tail summaries in MCP job logs. Recover by reading Git worktree status and docs; do not assume a background agent reached completion.

## First observations and constraints

- P3.3 synthetic red/green tests reproduced a Pyright `#!/usr/bin/env node` workspace PATH interpreter hijack (including second writable root and symlink variants); 12 launch-regression tests passed after local remediation. Synthetic process-control testing also demonstrated workspace/cache writes, loopback network, and transient Python child capability. Do not confuse these synthetic controls with observed real Pyright behavior or OS enforcement. READ certification is NO-GO.
- P3.4 initial inventory: TS/JS, clangd, rust-analyzer, Marksman, Bash, YAML, JSON installed on Sextant; make-language-server absent. Upstream multilspy currently has adapters for TS/JS, clangd and rust-analyzer, not the other named profiles. Probes are development-only.
- P3.5 correctness/latency/RSS harness in progress. Concurrent developer processes prevent authoritative timing until a quiet host window; a single-request smoke is only functional evidence.
- P3.6 offline fail-closed evaluator scaffold in progress. Must not infer measured instance count/TTL/deadlines from historical or tiny samples; respect P3.1 allowlist and existing P2.6 limits.

## Handoff / acceptance

1. Wait for all four jobs to finish, read their final results, inspect changes and evidence. Do not silently start duplicate agents or overwrite dirty worktrees.
2. Exclude unrelated generated changes; independently review every security-sensitive change and all no-GO labels.
3. Integrate the four bounded work packages into the new integration worktree without discarding work, resolve overlapping docs, run Linux integration and contract/static checks; run native macOS parity against identical candidate bytes through established SSH connectivity from Pi to Mac.
4. Run controlled, correctness-gated benchmarks only on authorized disposable corpora with machine/version attribution. Honest gaps remain REWORK/NO-GO; do not publish READ, P4/P5 or production rollout.
5. Only after the job is complete and acceptance is verified, create any final code commit/push. Preserve upstream multilspy PR #168 unchanged unless a separate reviewed upstream patch is necessary.

## Direct postprocessing checkpoint (2026-10-22, local)

- No new local AI agents were started for postprocessing. Work was performed through MCP shell commands.
- P3.4 Codex and P3.6 Codex returned terminal exit code 0; P3.5 Codex subsequently also returned terminal exit code 0. P3.3 Codex was still running at the last check.
- Independently reran P3.4 52 focused tests and P3.6 165 focused tests on Sextant; both passed, and targeted Ruff checks passed.
- Verified P3.4 sanitized native evidence has 9 pass and 1 not-installed rows, with exact SHA-256 matches for four emitted probe scripts. P3.6 pending evidence has null safety, capability and measurement stages.
- Staged the P3.4/P3.5/P3.6 files, scoped tests and evidence into this dedicated integration worktree. Updated `implementation-plan.md`, `capability-mapbook-v2.md`, and README without overwriting unrelated project history. Deliberately excluded historical `docs/os-independent-stage1-evidence/os6-source-reconciliation.json` drift; regenerate this inventory at full integration review.
- **Combined staged integration tests: 266 passed, 1 optional native smoke skipped.** Targeted Ruff and `git diff --check` passed. These results are local focused checks, not complete pre-commit/pre-push/CI or OS-security acceptance.
- P3.5 native smoke is an opt-in sample of size one per semantic operation; it is not an authoritative p50/p95/p99 or resident capacity/TTL measurement. Do not import it as full P3.6 evidence.
- Remaining: finish P3.3, integrate its final safe changes, reconcile the Pyright/multilspy pin used by P3.5 and P3.3, rerun cross-platform native suites, complete full quality/security gates and independent review.
- **No commit, push, deployment, public MCP registration, READ promotion or production profile changes** were made during this postprocessing checkpoint.

## P3.3 four-stage merge checkpoint (2026-10-23)

- Four Codex work packages were already complete; no new AI agents were launched.
- Selectively integrated P3.3 security owner, pinned `multilspy` VCS source,
  four original P3.3 test modules and audit scripts, and the Linux skip-policy
  metadata; excluded accumulated OS6 generated-history drift.
- Updated P3.5 future probe to exact `08ba0db` provenance. Its historical
  single-sample `9203732` Linux smoke JSON remains unchanged and is explicitly
  historical, not evidence for the integrated revision.
- First integrated Linux run reported 875 passed / 5 failed / 14 setup errors;
  the errors were due to setting source-worktree verification mode while using
  a packaged wheel, and the five failures were a P3.4 old-revision guard.
  Reviewed the upstream delta (process-env/launch only), updated the exact
  guard and reran using installed-wheel VCS verification.
- **Final first-pass integrated Linux suite: 894 passed, 1 skipped** with
  actual Pyright and MCP contract checks, fixed seed 12345.
- Mac candidate was created at the same `66697d2` base and all 45 initial
  changed files were transferred by hash; local Mac Python 3.13 uses
  exact `08ba0db` wheel. Mac synthetic suite: 338 passed, 8 skipped;
  P3.3 real trust-only suite: 68 passed; real P2.4/P2.6 plus contracts:
  71 passed, 7 skipped, 2 expected failures.
- Found an additional Mac P3.5 readiness failure: first workspace-symbol
  request may be empty before index completion, while the second correct
  result arrives. A bounded exact-gold preflight, with attempts recorded,
  was added to the private benchmark harness. **Mac real Pyright recheck:
  52 passed**, and Linux P3.5 synthetic recheck: 51 passed, 1 skipped.
- Raspberry Pi fresh P3.4 native probe at current pin: 9 pass, 1 absent,
  zero fail; all integrated script hashes verified.
- Full repository gates, formal resource trials, and independent security
  review remain separate open acceptance gates. No production rollout or
  READ promotion is authorized.

## Integrated candidate quality gates — 2026-10-23

- Initial managed full suite failed five cases: three tests checking newly
  introduced cross-platform skip declarations, one nested contract assertion
  caused by those declarations, and one full-capture configuration override
  inserted only by the QA command. The latter was not a product regression.
  The test skip policy was corrected without module-level blanket skipping;
  explicit opt-in native smoke missing a trusted binary now fails instead of
  silently skipping. A focused repro returned **125 passed, 1 skipped**.
- **Raspberry Pi final managed Linux full suite, seed 12345:** parallel-safe
  lane **8,281 passed, 348 skipped, 87 subtests passed**, plus ordinary-process
  lane **98 passed**; both lanes exited 0. No test was waived.
- **Sextant managed Fast Suite:** 3,914 parallel-safe passed, eight skipped,
  68 subtests passed; ordinary-process lane one passed. Both lanes exited 0.
- **Sextant managed coverage pipeline:** all four lanes and unit/full JSON
  generation exited 0. Configured coverage policy **256 production modules,
  75 top-level scripts, 20 previously recognized below-final-target debts,
  zero errors**. No target or temporary floor was relaxed.
- **Raspberry Pi pre-push hook run** and all changed/untracked pre-commit
  hooks passed. Ruff, Linux/Darwin mypy, Bandit, module-size, Markdown,
  dependency and architecture contracts remain clean.
- **MacBook Pro native parity:** P3.3 trust-only Pyright checks **68 passed**;
  provider manager/contracts **71 passed, 7 skipped, 2 expected failures**;
  corrected P3.5 native smoke **52 passed**; platform selection checks
  **108 passed**. Targeted candidate source hashes matched Linux.
- **P3.5 Sextant synthetic medium evidence:** two two-resident runs each
  measured 200 correct calls per operation, with RSS 825/845 MiB and Manager
  definition p95 150/157 ms; a one-resident run measured 100 correct calls
  per operation with RSS 428 MiB and Manager p95 109 ms. Full JSON and
  limitations retained in the versioned P3.5 report. Provisional 100 ms
  p95 and two-resident 512 MiB budget were not satisfied; no release GO.
- Separate OS-enforced untrusted READ, third-party/whole-package identity,
  independent security review, representative workload soak and P4 agent-value
  experiments remain **NO-GO / REWORK**. No product install or public MCP
  tool registration was attempted as part of these QA gates.
