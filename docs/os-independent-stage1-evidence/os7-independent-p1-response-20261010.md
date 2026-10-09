# OS7 independent review P1 response — resubmission pending

Task: BINNACLE-OS-STAGE1-IMPLEMENT-20261009.

## Independent finding

- Review provider: `chatgpt-codex-connector[bot]` (GitHub PR code review)
- Review ID: `5472898306`; inline comment ID: `4232455465`
- Original reviewed commit: `a1a11f9201b2dab87b029b205a90b4f9fcdb406d`
- Submitted: `2026-10-09T16:47:05Z`
- Disposition by this implementation owner: **P1 / CHANGES_REQUIRED**
- Affected source: `src/binnacle/platform/linux/job_identity.py`
- Finding: an owned setuid/root descendant can reject a native signal with
  `PermissionError`. A previously early exception prevented later verified
  processes, especially the job leader, from receiving the same signal.
  Generic stop and manager RPC did not provide a controlled partial result.

## Source corrections

1. Native `LinuxJobSignalLease.signal()` still sends only through pinned
   verified pidfds. It now attempts **every** verified target even when one
   produces an `OSError` (including EPERM/EACCES). Vanished processes retain
   the existing `ProcessLookupError` ignore behavior. After all attempts,
   it raises a typed `JobSignalDeliveryError` with the failed target count.
2. OS-neutral `job_stop.stop_embedded()` holds the same pinned lease through
   TERM, wait and optional KILL. A partial delivery is remembered while
   durable exit is observed; any partial outcome raises a controlled error
   instead of claiming that every descendant was stopped.
3. `JobManager._stop()` returns an explicit unsuccessful RPC response for
   `JobSignalDeliveryError`, not an opaque `internal job-manager error`.
   Standard successful RPC and public MCP payloads are unchanged.
4. All pinned pidfds are closed even when a partial delivery is reported.

## Negative tests and verification

- `test_unsignalable_descendant_does_not_prevent_signaling_job_leader`: the
  root/setuid-like descendant rejects the signal; the other descendant and
  job leader still receive TERM; the lease reports partial failure.
- `test_multiple_native_permission_errors_report_after_all_pinned_attempts`:
  two failed targets do not suppress the remaining leader signal.
- `test_native_partial_termination_is_reported_even_if_leader_exits`:
  partial TERM cannot be silently converted into a successful stop result.
- `test_partial_sigterm_and_sigkill_both_attempted_without_false_success`:
  escalation remains on the same verified lease and reports both failures.
- `test_partial_kill_only_still_returns_explicit_delivery_failure`: late
  failure is not suppressed, the lease closes.
- `test_partial_native_signal_failure_returns_controlled_rpc_error`: Job
  Manager responds with an explicit partial-failure message.

Focused post-fix test population includes native identity, OS-neutral stop,
manager edges, full durable manager/lifecycle, original metadata spool,
old/new manager RPC and exact FastMCP wire parity: **102 passed**,
seed `12345`. Ruff, mypy (152 modules), Import Linter (21 contracts) and
architecture negative gate (0 violations) also pass.

This response is authored by the implementer. It is **not** a second
independent review or approval. The corrected new commit must be pushed,
tested at exact GitHub SHA and re-reviewed independently. The production
quiet-window and active durable Job Manager gates remain unchanged.
