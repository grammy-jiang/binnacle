# R6 W3 independent review remediation — 2026-10-13

## Reviewed candidate and issues

Independent read-only review of fd95323b4df3aefac8f4fc3e8c41691e248f4c17,
based on f7bdd55f90d5d7fd028937023a388b852ad67b8e, returned REVISE
with two P2 issues. No production deployment was approved.

### R6W3-01: protected imports execute after business imports

Production command entries, the server and manager module entries could load
business modules before startup import checks. The repair provides minimal
entry wrappers for binnacle serve and binnacle-jobs, protects both Linux and
Darwin Python -m manager entrypoints, and delays server tool imports until
after the startup guard. The manager imports config inside the same guard
so later failure records use the configured state root; if config itself fails,
exit 70 and a redacted log still apply and no guessed state location is used.
Signed integration must update the package scripts, generated module inventory,
architecture manifest and packaging tests. The new real-entry negative tests
pin exit 70, error class, secret suppression and configured failure receipt.

### R6W3-02: frontend interpreter mistaken for manager

doctor.run_all previously checked its own Python version, which may be 3.12
while the authenticated Darwin job manager runs correctly on Python 3.13+.
The repair uses the actual manager capability reported by authenticated ping.
The explicit local Python floor check remains available for manager launch
preflights. A regression asserts separation of the frontend and manager.

## Earlier GitHub CI regression repairs

The first feature-branch CI failed two obsolete Linux socket refusal tests,
unintended Webmin companion eager import, and three Markdown style checks.
Repairs update the tests to the cross-OS shared refusal contract, exclude
Webmin from the required frozen server imports, and fix those Markdown checks.
This is not evidence of a new green CI run.

## Open release gates

Require independent read-only re-review of the exact repaired source,
a seven-job green GitHub CI on that same SHA, full Mac and Pi native
acceptance, a verified original J7m-a5 quiet/rollback gate and guarded
deployment smoke. Do not sync or restart production while any gate is red.

## Second exact-SHA review: aa808a6 (REVISE)

The independent read-only reviewer examined
aa808a6bb0c568e35fa7ead90a40452fac185a4d and returned
**REVISE / NO_GO** with four remaining P2 findings:

- R6W3-01: provenance imported at bootstrap before its required import guard.
- R6W3-03: CLI import SystemExit leaked the exception message and exited 1.
- R6W3-04: the failure-receipt callback retried Settings initialization,
  allowing a secondary SystemExit to replace the original exit 70.
- R6W3-05: the Darwin failure receipt used frontend environment-overridden
  settings rather than the manager's strict file-only configuration.

The reviewer reproduced these faults with isolated synthetic exceptions. It
also confirmed R6W3-02 was fixed, the original J7m-a5 gate's exact SHA-256
matched cad6ac5aa4a4ed65ad54e6c34b2a82867d7208f8f2591aaf167551cd83fca343,
and prior source-bound FDW refusal logic remained in place. The report is
saved outside the repo in /tmp/binnacle-r6w3-review-aa808a6-20261013.txt.

## Third remediation (pending exact-SHA review)

The new security-fix branch removes the unguarded provenance import and
retrieves the revision only from an already loaded module (fallback unknown);
it converts CLI import SystemExit to the same redacted 70 response; resolves
and freezes a configured state root *before* importing the remaining modules;
and prevents secondary receipt failures from replacing the first exception.
Darwin roots are resolved through the manager's file-only read_config, not
the frontend's environment-enabled Settings.

New isolated process tests cover each original reviewer negative case,
including failing provenance, CLI SystemExit, an early config/composition
SystemExit, and a rejected Darwin jobs-directory override. Unit cases also
verify a failure callback cannot override exit 70 or reinitialize Settings.
These tests are necessary but do not waive the requirement for an independent
fresh read-only review and exact-SHA Mac/Pi qualification.

The existing macOS full-suite findings from aa808a6 (unregistered platform
skip sites and an earlier Commands server factory refactor contract) were
fixed on qa2 signed commit 28767b768765bc786fc26b1b5c72b15af2f4ff38:
88 affected native/contract tests passed and all-file quality gates passed.
Do not call those older snapshots a clean final acceptance.

**Release remains NO_GO** until all repairs, the precise integrated commit,
GitHub CI, independent read-only review and the guarded deployment gates pass.
