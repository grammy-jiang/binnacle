# E2 independent implementation review and scope (2026-10-21)

**Technical outcome: GO for limited host-local E2 candidate sampling; manual task verification remains NOT COMPLETED.**

The independent reviewer was an ephemeral read-only local Codex task directed exclusively at E2 source and synthetic tests, explicitly prohibited from opening private captures, observer SQLite, host config, credentials, network sources or raw user data. It made no code edits and did not provide a substitute for real task-goal annotation.

## Chronological findings and fixes

| Round | Finding | Resolution |
| --- | --- | --- |
| Initial REWORK | Unhandled SQLite errors and argparse failures might print sensitive input values | E2 CLI uses constant sanitized parse/error responses; synthetic injection tests verify no private values escape |
| Initial REWORK | Race between symlink/owner check and file open; private key path reopen | Ancestor directory descriptors with `O_DIRECTORY/O_NOFOLLOW`; key read with `O_NOFOLLOW/O_NONBLOCK` and `fstat` on the owned descriptor |
| Initial REWORK | Partial final file on crash, conflicting/failed retries and a partly written concurrent key | Write/fsync temporary file, atomically create final name via no-overwrite hardlink, exclusive creation, identical retries only; 0700 directory and 0600 data/key |
| Follow-up REWORK | Identical retries could skip directory `fsync` after previously failed persistence | Both new publication and identical-existing retry now synchronize the final directory before success; injected failure regression |
| Further REWORK | Newly created output directory's parent might never be synced, or retry could skip a previously failed parent sync | Require existing ancestors; create only the last private directory; synchronize its parent on **every entry**, including retries |
| Final targeted reviewer | Technical E2 limited-scope **GO**, with a nonblocking FD-cleanup note | Post-GO cleanup repair closes newly opened child directory FD on failed parent sync; explicit synthetic leak test added and native Mac/Linux tests pass |
| Manual labeling | Historical tasks, snapshots, gold and sensitivity/specificity not independently verifiable from MCP-only history | All records stay `R0_unverified`; no task/effectiveness approval |

The same bundle was verified on all three hosts and the E2 subset yielded **39/39 native passes per host** after cleanup hardening. Key/manifest permissions and an idempotent same-batch rerun succeeded on each host. No raw log was copied into this repo or sent to the reviewer.

The GO is for the **sampling/storage tool**, not the entire E2 manual label acceptance, E3 replay, LSP performance or public MCP tool selection.
