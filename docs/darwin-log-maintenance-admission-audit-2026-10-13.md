# Issue #30: read-only Jobs/launchd admission audit

Date: 2026-10-13. **Advisory-only; no production maintenance authorized.**

The first production-facing prerequisite for the macOS log finalizer is a
repeatable *refusal* gate, not another way to stop a launchd service.
The already-merged PR #32 provides an inert, checksum-verified archive
data plane; Draft PR #34 demonstrates crash-recovery on fixture-only
LaunchDaemons. Neither includes an authorized production controller.

## Implemented audit

The new module offers:

- A pure, injected decision engine for read-only Jobs observations;
  usable in tests on Linux and macOS.
- A Darwin-only adapter using the existing **authenticated** Jobs Manager
  client, a read-only launchctl status observation of the real Jobs
  producer, and the existing read-only durable job-store inspector.
  It never calls bootout, kill, kickstart, restart, newsyslog, chmod,
  truncate, compress, or unlink.
- An AdmissionAudit result whose approved attribute is structurally
  and permanently False. Its constructor rejects a result without the
  mandatory maintenance_barrier_not_held reason. This audit MUST NOT
  be passed to the raw finalizer as a writer hold.

The audit checks, fail-closed: the absolute, canonical, owned private
0700 Jobs directory without leaf symlinks; first and second authenticated
Manager pings; exact owner instance ID, PID, revision and manager-reported
Jobs directory; valid nonnegative integer running/unknown counts (not
boolean or string); matching launchd PID; a bounded, readable durable
record census; unchanged directory dev/inode; consistent live/history
counts; and the fact that no actual RPC admission barrier was acquired.

A running, UNKNOWN, interrupted, unreadable or unexpectedly changed job
results in a refusal. A point-in-time zero does not prove no new job may
arrive between the audit and a future writer maintenance operation.

### Usage: manual, read-only diagnostic

From a local **out-of-band** Python shell on the Mac:

    from binnacle.config import get_settings
    from binnacle.companions.darwin_log_maintenance_admission import inspect_local_jobs

    report = inspect_local_jobs(get_settings().jobs.dir)
    print(report.reasons, report.approved)

Do not run this through a live MCP command intending to stop the same MCP
service: it is diagnostics only and cannot grant control authorization.
The exact manager generation and counts should be rechecked after
separately acquiring a real maintenance lease in any future transaction.

The first native audit of the local machine correctly refused because
another activity was using the Jobs Manager. This observation was
read-only; other projects' development and the production services
continued untouched.

## Non-negotiable next production gates

1. Acquire the existing **real** J7 Mac deploy lock at
   ~/.local/state/binnacle/mac-deploy-gate.lock and the J7 Jobs
   service lock at ~/.local/state/binnacle/j7/jobs-service.lock.
   The former is not assumed to exist: an audit MUST NOT create it
   or claim to own it. Reuse the J7 lock-order/owner contract, with
   watchdog coordination, before authorizing a maintenance action.
2. Introduce a controller outside the MCP/Jobs process group with a
   fresh **exclusive RPC admission/drain barrier** and proof there are
   no executing/unknown requests. The two read-only ping observations
   are not an adequate substitute for this guarantee.
3. Require a production service writer-generation/FD closure protocol
   (including inherited children) with independent crash recovery
   prepared *before* any real bootout. Current PR #34 guardian is
   deliberately unable to bootstrap actual production labels.
4. Recheck disk reserve (at least 100 GiB), source inode, no live writer,
   configured owner/mode, J7 lease and guardian health immediately
   before unlink. Fail closed on any uncertainty and retain the raw
   source; no automatic pruning.

### Test/CI policy

Linux + Darwin can exercise the pure audit without service side effects.
Tests cover stable zero, active and UNKNOWN jobs, forged/malformed pings,
owner/PID/count races, symlink and permission refusals, durable-record
inspection failures, callbacks that raise, and forbidden attempts to
treat a read-only result as authorization. The existing project Ruff,
Bandit, Mypy, skip-policy and module-size gates must pass. Coverage for
this new module must exceed the repository's 90% new-module target.
