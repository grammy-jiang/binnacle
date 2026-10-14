# Issue #30: independent read-only recovery observation over Darwin A3

**2026-10-14 — dormant integration, no production deployment.** This
work package builds on merged PRs #44 (crash-durable evidence journal),
PR #45 (non-adopting orphan observer) and PR #46 (manual-only recovery risk
policy). It does not complete the out-of-band production controller.

## Reuse the existing authenticated transport

Binnacle already has Darwin A3 authenticated Unix domain IPC in
platform.darwin.ipc_transport. This library validates peer UID/PID,
private 0700 runtime directories and 0600 socket/credentials, and uses
generation-specific HMAC challenges, fresh two-nonce session transcripts,
sequenced signed requests/replies, authenticated endpoint publication
and a process-lifetime lock. Time-out/broken channels produce UNKNOWN
results, never transparent replay.

The independent recovery observer must **reuse A3**, not invent a
separate local authentication mechanism.

platform.darwin.log_maintenance_recovery_rpc supplies an explicit-only
observation handler, A3 client wrapper and A3 sidecar server wrapper.
There is no installed entrypoint, launchd plist, CLI registration, MCP
command, start-at-boot hook or production configuration wiring.

## Exact service and request scope

The service requires a preapproved private transaction directory named
txn-<32 lowercase hex nonce> and a separate private A3 runtime
directory ending in log-maintenance-observer-ipc.

The only endpoint is observe.sock with a ServiceLease label of
com.binnacle.log-maintenance-observer. Calls to installed Binnacle
MCP/Jobs/Watchdog sockets or a different label are rejected before
connecting. A3 then validates the actual peer and generation.

The entire request schema has version 1, op inspect, and the required
32-lowercase-hex nonce field. Version must be an integer, not boolean;
operation must be inspect; nonce must equal the **trusted
server-configured transaction root**. Extra fields, arbitrary paths,
service labels and control verbs such as bootout, bootstrap, stop,
restart, prune, kill and deploy are refused. A client never specifies
a log pathname.

The server handler calls only the merged inspect-only orphan reader
and pure recovery risk classifier. Successful replies contain nonce,
phase, exact revision, manual-only status and diagnostic risks, plus
the constant flags:

- manual_review_required = true
- production_authorized = false
- autonomous_restart_allowed = false

A missing/corrupt/busy journal produces only the generic error
journal_unavailable; the error discloses no paths, private process
details or credentials. Replies are integrity-protected by A3.
The client independently requires exact schema, nonce, revision/phase,
manual-only flags and the same re-derived classification and risk list.
A forged positive or action-authorizing reply cannot be accepted.

## Review and acceptance evidence

Fixture-only tests on sextant Raspberry Pi 5 cover:

- Every legal phase; corrupted journal, busy controller lock and root
  replacement; all control verbs, extra fields, unknown nonce/version
  and invalid endpoint/label/owner conditions.
- Incorrect reply permissions, version, phase, revision, risk lists,
  contradictory statuses, missing/extra fields, malformed timeout,
  and failure without RPC auto-replay.
- Isolated A3 Unix socket authentication with a private Linux temporary
  runtime, including a separate **child-process sidecar**, while the
  client verifies A3 peer identity, key, nonce, generation, HMAC
  transcript and request/response signature.
- An unauthenticated raw socket client that cannot execute the
  observation RPC, followed by a valid authenticated request.
- No modification to transaction bytes, inode metadata or mtime
  during observation, and cleanup of the fixture-only A3 endpoint.

Linux cannot use Darwin getpeereid(3) or RENAME_EXCL. **Only in test
fixtures**, these syscalls are mapped to Linux SO_PEERCRED and a
private, single-owner rename. The A3 authentication, HMAC, transcript
sequencing, framing and production transport source is unchanged.
Linux tests do not replace native macOS acceptance.

All tests use temporary, disposable Linux directories and subprocesses
spawned by the test. No Mac workload, installed Binnacle service,
production archive or real log is accessed or mutated.

## Still unavailable in production

Actual out-of-process launchd-managed controller installation and
independent authentication against the live Mac, Jobs/MCP drain,
Watchdog/KeepAlive coordination, privileged exact-generation FD census,
independent bounded guardian crash/power-loss restoration and manual
maintenance window are still needed.

The A3 sidecar is deliberately *read-only*. Its success does not
authorize service restart, raw deletion or production log pruning.
Issue #30 remains OPEN and production cleaner OFF.
