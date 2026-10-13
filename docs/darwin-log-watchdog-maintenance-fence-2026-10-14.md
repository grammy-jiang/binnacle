# Issue #30 — Opt-in Watchdog restart-pause fence

Date: 2026-10-14. **Dormant**, not production enabled.

The Mac watchdog currently supports a legacy pause file, but checking
that file once per cycle does not prove a maintenance controller cannot
race with a restart already in flight. A production log finalizer may
only hold and stop its producer when the watchdog cannot undo that stop.

This implementation adds a new, explicit, opt-in flag to the ordinary
service-watchdog CLI: --maintenance-pause-dir PRIVATE_DIR. The installed
Mac LaunchDaemon and the repository's rendered production plist do NOT
include that flag; the active deployed Watchdog remains unchanged.
There is no new CLI for starting a log maintenance transaction.

## Shared action interlock and receipt

A 0700 user-owned private directory holds:

- restart.lock: 0600 regular single-link, an exclusive nonblocking flock.
  The Watchdog holds it from its final pause check THROUGH its permitted
  watchdog restart and persistent state write. If a controller holds this
  lock, Watchdog fails closed rather than starting another restart.
- request.json: 0600 single-link JSON, exact version=1, fresh lowercase
  32-character nonce, scope=all and wall-clock until within 180 seconds.
  A malformed, unknown, unreadable or expired request stays a PAUSE,
  not a reason to restart a stopped service.
- ack.json: 0600 single-link, atomically published by Watchdog under
  the same lock, containing exact nonce and watchdog PID.

The future **out-of-band controller** must first acquire the separate
J7 deployment and Jobs interlocks, prove no in-flight jobs/RPC calls, and
arm an independent crash-durable producer restoration guardian. Only
then may it publish request.json under restart.lock. The Watchdog observes
and acknowledges this request inside its own restart serialization lock.

The watchdog checks pause state once per cycle and once AGAIN while
holding restart.lock immediately before any restart action. This closes
the window between a health observation and the actual restart call:
an already-in-progress restart holds restart.lock, so a controller
cannot publish its pause request until that restart finishes.
The controller must separately verify ACK nonce, launchd PID and full
watchdog incarnation identity. ACK is NOT a permanent lease or evidence
that the MCP/Jobs producer has stopped writing its old inode.

request_pause(root, nonce, until) publishes only a private pause request
and never issues launchctl, Job Manager RPC, log archive or sudo calls.
confirmed_ack(root, nonce, watchdog_pid) is a read-only observation
that fails closed for stale/missing/invalid records.
release_pause(root, nonce) unlinks only a matching private request and
ACK while holding the same restart lock; a missing/foreign ACK refuses
to remove a live request. The caller MUST restore and verify the actual
log producer before releasing the pause. Expired but recognizable
requests can be released by their exact owner after recovery.

The protocol is opt-in and an isolated prerequisite only. There is no
production controller, launchd acceptance, automatic caller-side
lease renewal, or completed liveness gate in this PR.

## Test and safety requirements

Tests operate only in temporary user-owned directories; no real
Watchdog, MCP/Jobs service or Binnacle log is restarted, disabled,
compressed or deleted. Scenarios include:

- no request: unchanged Watchdog service restart behavior;
- valid request: no restart, acknowledgement of the exact nonce/PID;
- malformed/expired/symlinked/unreadable request: no restart or false ACK;
- request received after the cycle observation but before restart:
  final action lock rechecks and refuses;
- controller subprocess blocked by actual watchdog flock during a
  restart, then succeeds after release;
- foreign hardlink, wrong mode, missing directory and mutex contention;
- distinct old ACK, rejected duplicate request, short/failed write,
  UUID temp collision and foreign temporary-file replacement;
- release by the wrong nonce, expired request release only after
  verified owner, unreadable/mismatched ACK, failed unlink.

The project still requires >90% full branch coverage of new modules,
Ruff/Bandit/Mypy Linux+Darwin, module size, architecture, full Python
3.10-3.14 CI, and independent review. No J7 or production lease
authorization may be inferred from these isolated fixture tests.

## Remaining integration blocks

Before enabling the flag in a production plist: validate the exact
owner identity of the installed Watchdog, coordinate with any other
watchdog/launchd restart actors, prove actual admitted RPC and Jobs
drain, retain a correct production writer hold, and test durable
restoration after controller/guardian SIGKILL and watchdog restart.

Issue #30 remains OPEN and production raw log pruning remains disabled.
