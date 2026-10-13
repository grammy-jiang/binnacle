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
