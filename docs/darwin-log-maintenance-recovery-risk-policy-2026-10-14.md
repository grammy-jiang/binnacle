# Issue #30 — Recovery risk classification without service authority

Status: dormant, pure and **non-mutating**. Developed only on sextant
after PR #44 and PR #45 were merged into Binnacle master; MacBook Pro
was running another project's Android MCP Host tests and Binnacle Jobs.

## Purpose

The private controller transaction journal has monotonic, atomically
committed phases (PR #44) and a distinct inspect-only orphan reader
(PR #45). An independent recovery service must not confuse a *journal
receipt* with an authenticated fact about the presently running
service. In particular a journal at guardian_armed means the writer
may already have been stopped even if the journal never reached
producer_stopped.

The new recovery policy module separates pure classification from real
actions. It accepts one verified JournalSnapshot, optionally accompanied
by typed RecoveryReadings from externally provided observation sources.
It produces only an immutable RecoveryAssessment; there is NO launchctl,
no lsof, no network, no files, no Jobs RPC, no service control and no
archive deletion code.

Every RecoveryAssessment has strictly enforced properties:
manual_review_required=True, production_authorized=False, and
autonomous_restart_allowed=False. Even a completed journal plus
perfectly matching supplied readings cannot authorize a production
mutation. The model is advisory-only, not a controller.

## Diagnostic categories

- Missing/untrusted journal: unverifiable.
- intent through jobs_drained: pre_stop_manual_review.
- guardian_armed through producer_restored:
  possible_outage_manual_review. This conservative classification
  accounts for controller SIGKILL between bootout and a durable
  producer_stopped receipt.
- complete: completion_record_manual_review; receipt alone does
  not prove the current producer is healthy.

With optional observations, additional machine-readable risks report
unknown/mismatched producer PID or generation, protected source inode
mismatch, Watchdog not ACK-paused, guardian not verified, MCP calls
in flight, running or UNKNOWN Jobs and any old raw-inode writable FDs.

Missing observation values always differ from zero or true. Runtime
counts reject bool, negative, float and string coercion. Process IDs,
source inode identities and service generations must use exact types.
Unauthenticated readings are never treated as positive evidence.

## Security limits and remaining work

The RecoveryReadings authenticated flag is supplied by a future real
out-of-process control channel. This data class cannot itself prove
the identity of that caller. Its only effect is changing diagnostic
risk flags, NEVER granting an action, so forged "perfect evidence"
cannot enable a service restart or prune.

The production controller still needs to bind independent launchd
generation checks, MCP/HTTP and Jobs admission and zero/UNKNOWN
drain, Watchdog/KeepAlive pause, complete writable-FD census,
privileged validated guard and bounded recovery supervisor.
Native Mac acceptance and manual maintenance scheduling remain
mandatory. Issue #30 stays OPEN and production pruning stays OFF.

Synthetic Linux/Pi coverage must exceed 90%, with full Ruff/Bandit,
Linux/Darwin Mypy, architecture, manifest and CI gates. No tests
interact with Mac services or real raw archives.
