# Issue #30: isolated multi-barrier quiescence rehearsal

Status: **fixture-only; production actions explicitly impossible**.
Date: 2026-10-14.

The test-only harness under tests/issue30_rehearsal_support.py combines the dormant prerequisites already tested in
Draft PRs #34 through #41, without installing or using any of them in the
running production MCP, Jobs Manager or Watchdog service. The test harness is deliberately OUTSIDE the production src package to respect the architectural boundary around Darwin native adapters. It has
no launchctl, sudo, real log pathname, delete-raw, compression or
service-stop operation. Its result is structurally incapable of
authorizing production maintenance.

## Admitted fixture scope

Only a user-owned, private 0700 directory whose final component starts
with issue30-fixture- is eligible, containing four additional
user-owned/private fixture roots: j7-state (with its private j7 child),
watchdog, manager-pause and jobs. The manager must have its **jobs_dir**
equal to the owned fixture Jobs directory.

These are test-owned, temporary directories; production user state
paths do not match. A fake Manager process owner spawns **no real process**.
There is no remote user-facing entry point or accepted production mode.

## Serialized lifecycle

The rehearsal calls existing guarded APIs in a strict order:

1. Acquire exactly the two J7-interlock flock files inside the
   temporary fixture. The J7 deployment/Jobs lock order is preserved.
2. Publish a private, time-bounded Watchdog request under its restart
   mutex, and invoke an explicitly injected synthetic watchdog action.
   It must return a matching nonce and PID ACK. Missing or malformed
   ACK refuses.
3. Permanently fence the fixture MCP application generation with a
   one-time nonce, then wait a finite duration for already accepted
   tool calls to complete. Timeout or active call refuses.
4. Atomically publish a private, versioned Jobs pause request while
   holding the Manager's ACTUAL test Jobs transaction lock. Its
   owner ID and PID are pinned to the active fake Manager generation.
   Publication is create-only: a foreign request or UUID scratch file
   cannot be overwritten or deleted.
5. Require a synchronized Manager ping reporting the same owner/PID,
   the exact paused nonce, and zero running AND UNKNOWN Jobs under
   the same Manager transaction lock; independently require the
   durable record census to report no unfinished/unknown records.
6. Verify both J7 flock inodes still match their held names and return
   a successful **fixture-only** observation. No producer is stopped.

Since this rehearsal stops no writer, on return or failure it releases
only its own matching private Jobs and Watchdog pause markers. It
NEVER unlocks another controller's lock, overwrites a foreign request,
or reopens the same MCP application generation. A failure to prove
cleanup retains the pause and refuses rather than guessing a safe
resumption; test-owned temporary roots can then be retired.

## Fault injection and acceptance

Tests inject in-flight MCP tools, preexisting/UNKNOWN Jobs, missing
Watchdog ACK, wrong PID, J7 lock contention, wrong nonce, foreign request,
symlinked/public/missing directory, request write/fsync failure, UUID
name collision, scratch pathname replacement, and owner/request inode
replacement during release. All must refuse and preserve foreign bytes.

Mac + independent Linux acceptance, full Python 3.10-3.14/coverage CI,
Ruff/Bandit and both-platform Mypy must pass before an integration
review. New module full branch coverage must exceed 90%.

## What remains unsolved

An actual **out-of-process authenticated controller** must communicate
with running MCP and Jobs services; no in-memory Python reference to
a fake Manager is a substitute for authenticated, live lifecycle
binding. The controller must have crash-durable lease/identity/guardian
ownership, coordinate with the actual Watchdog action loop,
validate launchd current writer generations and writable FDs, and
prove clean restart/readiness after compressed verification. The
fixture rehearsal is not sufficient to run production log pruning.
Issue #30 therefore remains OPEN and production cleanup DISABLED.
