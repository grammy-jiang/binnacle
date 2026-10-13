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

## Third independent review follow-up — R6W3-06

A third read-only delta review on 72e107786e03121ffa6f9a04b9a24e2079ca7d37
confirmed the four previous P2 issues fixed but returned REVISE/NO_GO for a
new P2: a bootstrap error with revision unknown was misclassified as
STALE by doctor and accepted by the W3 startup doctor wrapper.

The remediation in the isolated master-merge candidate changes
check_startup_imports to recognize an older revision ONLY when both the
recorded and current revisions are verified Git SHA tokens. Unknown, missing,
installed or malformed revisions fail closed. End-to-end test coverage
records an early failure, checks doctor output and passes the result through
the W3 doctor parser; a genuine, known different Git SHA still produces
STALE as designed.

Release remains unapproved until exact-SHA qualification and independent
review of this follow-up on top of the concurrent production master.

## Fourth independent exact-SHA review: dce2b9f (REVISE)

The independent reviewer found two P2 errors on
dce2b9ff0ddade094f188901012d19426e56f62b:

- TIMESTAMP-P2: the Darwin manager bootstrap installed a timestamp-free root
  logging formatter before the operational telemetry configuration. Python
  basicConfig leaves an existing handler alone, so exit events had no parseable
  timestamp and could be omitted from the time-window log analyzer.
- FSYNC-P2: after metadata replace succeeded but directory fsync failed, the
  job exit was queued. Retry then observed the visible terminal JSON, skipped
  fsync, dequeued the exit, released the owner and emitted zero terminal
  job_exit events.
  A further native API regression verifies that a visible but not-yet-fsynced
  terminal record reports UNKNOWN to state, job_counts and stop_job until
  the queued fsync succeeds. Duplicate terminal notifications remain inert.

The review also confirmed that the R6W3-06 test file duplicated the
R6W3 E1 lifecycle suite. The dedicated replacement test commit d67de74
removes the duplicate and checks the actual record -> doctor -> W3 parser
chain (41 affected tests passed).

## Fourth review P2 remediation in isolated topic branch

- The early manager bootstrap uses the timestamped operational format on both
  Darwin and Linux. A new fresh-process test configures startup logging then
  operational logging and passes the actual emitted event to the Darwin
  time parser; the parser extracts a valid timestamp on both operating systems.
- Metadata fsync is extracted into a descriptor-only, no-follow directory sync
  helper. The retry path recognizes that a terminal JSON is visible but has a
  queued unconfirmed exit, retries the directory fsync under the same writer
  transaction, and only then dequeues, acknowledges and logs the terminal
  event. Duplicate notifications after acknowledged persistence never log
  another exit.
- New test-owned synthetic EIO tests first reproduced both failures against
  the old implementation; after the fix, failures on the first or first two
  directory sync attempts remain queued and unacknowledged until the next
  successful fsync. Exactly one durable exit event follows.
- The Darwin service module stays within the 500-line source ceiling. The
  tracked OS6 mutable source reconciliation is refreshed for the newly split
  modules; the immutable OS0 baseline manifest is unchanged and the OS6 check
  reports zero architecture violations.
- These results do not authorize deployment. The exact repaired SHA still
  requires fresh Mac/Pi testing, seven green CI jobs and an independent code
  reviewer APPROVE before considering the original quiet, idle-job and
  rollback-controlled J7m-a5 production gate.

## Fifth independent review: c385365 (REVISE, three P2 races)

The independent reviewer checked signed
c385365e0e0e6483ab87146697d9512f0a94b944 and confirmed the sequential
post-replace directory fsync retry and timestamp fixes, but found three
concurrent durability defects:

- A replaced terminal JSON was visible before a pending marker was published.
  A second request could report EXITED or acknowledge ownership before the
  first directory fsync was confirmed.
- An earlier writer that timed out acquiring the record lock could enqueue a
  stale exit after a competing writer had successfully committed. The stale
  entry caused state to regress from EXITED to UNKNOWN and could cause a
  second terminal event.
- A launch-retention prune could delete terminal metadata that was visible
  after an unsuccessful directory fsync, losing the pending exit.

No production rollout or commit to master was approved for c385365.

## Sixth repair: atomic pending/commit/ack transaction

The next isolated repair marks the exit pending before replacing terminal
JSON. A failing transaction inserts the retry marker before releasing the
writer lock; a lock-acquisition failure uses the queue's committed-ID
tombstones to reject stale late arrivals. Success atomically removes the
pending marker and remembers committed job IDs before release. Terminal
status, job counts and stop remain UNKNOWN until the directory fsync is
confirmed. Retention explicitly excludes queued exits, including visible
terminal records whose metadata directory is not yet synced.

The new test-owned deterministic interleaving cases cover:

- pausing inside directory fsync after atomic replace and observing UNKNOWN;
- suspending the failing writer inside retry enqueue and proving the writer
  lock remains held;
- a late timed-out writer arriving AFTER another writer commits, with exactly
  one terminal event and no state regression;
- retention of an undurable terminal record despite keep_newest=1;
- duplicate exit notifications, which cannot enqueue or emit another event.

The five core concurrent interleavings passed 15 consecutive replays, and
54 affected native manager tests plus MyPy and all 25 architecture imports
passed on the local repair worktree. This is preliminary local validation;
fresh CI, final Mac/Pi qualification and independent APPROVE on the exact
signed SHA remain mandatory. The original J7m-a5 quiet/rollback gate must
still pass before any production deployment.

## Sixth independent review: 83053ec (REVISE; three P2)

The exact read-only delta review of
83053ec08b56464f86bba65b74a266f44212af07 marked the previous
early-pending / stale-writer / prune issues FIXED, but found three further
failure-state and lifecycle defects:

1. A transient unreadable meta.json is represented by read_meta as None.
   The retry branch previously dequeued that job and exposed an unsynced,
   visible terminal record as EXITED.
2. The in-memory committed-ID set grew by one entry per completed job
   forever, even as the owning process continued and retained jobs were
   pruned.
3. An unexpected owner.release exception occurred after a confirmed fsync
   but before job_exit logging. The durable completion marker suppressed
   requeuing, so the event was lost and owner acknowledgement was not retried.

The reviewer used isolated in-memory fault cases; no live production
processes or developer worktrees were altered.

## Seventh repair: truthful exit phases with bounded in-flight pins

An isolated candidate worktree addresses these as follows:

- A pending unsynced job cannot be dequeued when a metadata read
  momentarily fails or the owner identity cannot be verified. It stays
  UNKNOWN and is retried; the durability status never becomes optimistic.
- Committed IDs use a bounded 2048-entry recency window, but any still
  executing callback or reaper batch pins its job ID until the last writer
  exits. This prevents a timed-out writer from resurrecting its exit even
  after thousands of other commits, while memory does not accumulate
  forever with successful throughput.
- Exit logging follows confirmed metadata fsync and precedes owner
  acknowledgement. An unexpected owner release failure becomes a redacted
  owner-ack retry, not a failed metadata commit or suppressed job_exit.
  The normal reaper loop retries deferred owner acknowledgements even
  when there are no unsynced metadata records.
- Six regression tests initially reproduced the three defects and exercise
  timed-out writers, direct busy-reaper batches, bounded cache memory,
  transient unreadable JSON and deferred owner acknowledgement.
- No production restart, broad Git merge or CI override is permitted on
  the basis of this local repair. Independent exact-commit review,
  coverage and managed Mac/Pi acceptance remain required.

## Seventh independent review: 1e428a1 (REVISE)

An independent read-only reviewer checked exact signed SHA
1e428a177250b469aff2ab859f63783c40a9556a. The original metadata
read failure was FIXED; owner-release retry and bounded completion history
were PARTIAL, with two P2 findings:

- A snapshot of pending unrecorded exits did not pin all entries at the time
  of the snapshot. After thousands of other successful commits evicted the
  completion mark, a later pending entry could requeue and log a duplicate
  exit. The already-reviewed reaper batch had a pin mechanism, but the retry
  batch did not.
- Permanent owner.release failure could accumulate an unbounded ack backlog.
  Every reaper pass attempted every pending acknowledgment with no limit,
  backoff or stop policy. This grew memory and degraded the unique reaper's
  latency despite the completed exit history having its own limit.

These were reproduced by the reviewer with test-owned in-memory method
substitutions, not by interacting with production services.

## Eighth repair: pinned retry snapshots and bounded fail-closed owner ack

The pending-exit retry batch now captures and pins all its entries while
holding the queue mutex, before processing any record. The shared pin helper
covers reaper and retry batches, with exception-safe release. An in-flight
stale writer remains pinned through unrelated commits and cannot revive an
already durable exit after cache eviction.

Owner release acknowledgments have an explicit 1024-ID admission ceiling and
a 16-ID retry budget per pass. Repeated failures use exponential backoff
(up to 30 seconds) and rate-limited warnings. At the ceiling the manager
raises a structured backlog-overflow event and sets its shared stopping
event: the launched service stops admitting work and follows its existing
guarded stop/restart path rather than allowing unbounded memory growth or
silently discarding responsibility.

Three newly added negative regressions first failed against 1e428a1.
They now pass, including an actual retry snapshot containing 1000 pending
exits and more than 5000 unrelated completions, and synthetic permanent
ack failures. The expanded 31 Darwin tests also passed under Python 3.10,
3.13 and 3.14, and source size and MyPy checks are green.

This is local implementation evidence only. Independent exact-SHA code
review, GitHub CI 7/7, full Mac/Pi acceptance, original J7m-a5 quiet window,
idle-jobs and guarded rollback gate remain requirements before any release.
