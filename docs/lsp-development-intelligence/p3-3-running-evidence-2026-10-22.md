# P3.3 running evidence — Linux ARM64

Scope: existing isolated worktree; preserve prior edits; no integration or deployment.

- Read implementation plan, P3.1 admission and testing safety contracts.
- Read existing P3.3 probe/tests and peer QA reproduction (read only).
- Confirmed installed multilspy provenance matches `08ba0dbe60b6e0a3eff4796cb77ff5c0837bc892`.
- Root cause: Pyright env-node shebang receives inherited workspace PATH.
- Doctor: lock/tool checks pass; `.venv` and both Git hooks missing. Use local `.qa-p33`.
- Worktree inventory read; no branch or other worktree mutations.
- Usage guard unavailable; no unattended manager launched.

Planned verification: red/green real Pyright PATH attack; cross-root and symlink
admission; child environment; synthetic side effects and OS primitive checks;
private LSP and public-contract regressions; static gates. READ remains NO-GO.

Completed:

- Initial attack regression: 11 failures / 1 pass; all four poisoned PATH cases
  executed the disposable sentinel before remediation.
- Fixed launch admission: initial 12 cases pass; all selected and resolved
  interpreter paths and intermediate links are checked against every root.
- Focused P3.3/P3.1/owner run: 69 passed with isolated configuration.
- Native synthetic control: workspace/cache writes, loopback connection and
  bounded Python child succeed; synthetic environment secret absent.
- Bubblewrap control: read-only workspace and isolated network deny effects;
  cache write and bounded Python child succeed. Primitive evidence only.
- Real Pyright trace: failed Python discovery execs exist despite zero children
  in periodic samples. Socket sampling incomplete. No confinement claim.
- Linux mypy: 906 source files, no issues (before final added tests).
- Corrected audit CLI to module invocation; fixed synthetic socket teardown.
- Regression identified stale expected multilspy SHA; updated exact provenance
  assertion to the already-selected locked fork commit, without weakening it.

Further verification:

- Broad real-upstream/private-LSP/public-contract selection: 620 passed,
  1 opt-in skip, 1 existing FastMCP deprecation warning (seed 12345).
- Owner lifecycle + P3 selection: 89 passed, 97.29% statement/branch coverage.
- Final path review found a `//` symlink-target normalization bypass. Added a
  failing regression, then canonicalized each path anchor before traversal.
- Added upstream command/environment drift and unreadable-launcher rejections.
- Repository pre-commit all-files hooks pass. New-file hooks additionally cover
  untracked P3.3 files; fixed the optional multilspy import typing annotation.
- First pre-push run failed on read-only home fixture paths and a non-root-owned
  `/tmp` in this execution environment. No test was waived. A disposable
  Bubblewrap mount namespace maps worktree-owned directories over test state
  and `/tmp`, without modifying host directories. The 44-case diagnosis rerun
  and the complete pre-push hook both pass under that test-only isolation.
- Managed four-lane full coverage run started in the same isolated environment.
  The complete OS6 inventory was regenerated; 281 modules / 69 scripts,
  zero architecture violations. Its larger diff includes older baseline drift.

Final-code checks:

- Focused P3.3/P3.1/owner selection: **80 passed**, seed 12345.
- Probe rejects mismatched Pyright package metadata before launch and emits
  sanitized JSON on expected CLI failures; both changes have red/green tests.
- Final standalone real-Pyright probe: clean exit, no synthetic-tree changes,
  synthetic secret absent, READ NOT_PROVEN. Sampling varied across runs and
  cannot establish absence of short-lived effects.
- All-files static hooks pass on the final source. Raw syscall traces removed.
- Managed coverage first run exposed the required Linux skip-policy registration
  and a pre-existing synthetic guardian/journal-observer race. Registered only
  the Linux namespace test; added bounded guardian completion synchronization
  in the existing test helper. No Darwin product code changed.
- Owner source SHA-256: `8315f5cac2e4769cb521e7500bd533085d25d5c5b013afc39e9c8a41032e70e4`.
- Probe source SHA-256: `17756ee38250d8d4cfcbf2e321c0194a856532084b095150c8f8e7c518eb21c4`.

Final managed verification (final source, seed 12345, local `.qa-p33`):

| Managed lane | Passed | Skipped | Subtests |
| --- | ---: | ---: | ---: |
| Unit parallel-safe | 3380 | 4 | 68 |
| Unit ordinary-process | 1 | 0 | 0 |
| Non-unit parallel-safe | 4673 | 303 | 19 |
| Non-unit ordinary-process | 97 | 0 | 0 |
| Total | **8151** | **307** | **87** |

All four lanes exited zero. The configured `check_coverage_policy.py` gate
exited zero: 256 production modules / 68 non-init scripts, 0 errors, and 20
below-final-target notices under the existing policy. No floors were changed.
Private owner coverage is **98.31%**. The probe's CLI subprocess coverage is
not merged into this report (22.90% measured); its real CLI behavior is tested
separately. This run used the repository's managed coverage scripts directly
in the allowed QA venv, not a new tox environment or the multi-Python matrix.

Remaining: independent security review; integrated real-provider OS isolation;
full package/dependency integrity policy; other-OS acceptance; hosted CI and
integration/deployment gates. Development doctor still reports the intentionally
absent `.venv` and Git hooks. No tests remain failing in the final run. Public
READ/tools remain disabled; no commit, push, branch change or deployment occurred.
