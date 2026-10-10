# Stage 1 follow-up: Codex P2 callback storage failure

Task: BINNACLE-OS-STAGE1-IMPLEMENT-20261009.

## Independent reviewer finding

- Reviewer: `chatgpt-codex-connector[bot]` on GitHub PR #18.
- Reviewed commit: `8000c74d9ce170359f21330eb83cf137b91e23bd`.
- Inline finding: `4234988402`, `src/binnacle/features/commands/job_stop.py:78`.
- Finding: on an EPERM/partial native signal, a storage OSError from the
  injected `on_partial` callback escaped as a raw storage error before the
  `JobSignalDeliveryError` outer handler could retry; a `False` result from
  `mark_signal_delivery_partial` was ignored as success.

## Narrow source correction for independent review

- `job_stop.persist_partial_or_raise` calls the marker writer and checks its
  positive `bool` result. Both OSError and a False result produce a controlled
  `JobSignalDeliveryError("partial stop not persisted")`.
- `jobs.stop_job_embedded` wraps the immediate `on_partial` callback with this
  checked policy so errors reach the existing outer partial-stop exception
  handler; that handler makes one additional checked marker attempt, to permit
  recovery from a transient read-only/full disk condition.
- If a marker is successfully written on the retry, later owner/direct-RPC
  calls still reject the partial stop even after the reaper records leader
  exit. If both attempts fail, the current request returns a controlled partial
  error and **never reports stop success**.
- The public JSON-RPC version, older durable job record format, successful
  stop path and Linux process ownership lease mechanism are unchanged.

## Regressions and qualification

- Callback OSError and callback `False` cannot leak raw OSError or yield a
  successful stop response. Both release the lease before a reaper wait.
- A one-attempt disk outage is retried; durable marker is retained by a later
  record_exit; a second stop fails explicitly rather than claiming success.
- Direct `JobManager._stop` maps a callback OSError to the controlled v1 RPC
  error shape rather than an opaque manager-internal error.
- Focused unit tests: 25 passed; expanded 13-file job, protocol and architecture
  tests: 283 passed (seed 12345) before the final additional manager regression
  test; final gates must be rerun on the resulting exact code SHA.

## Explicit unresolved storage-disaster limit

When **all** attempts to persist a marker fail and the durable filesystem
subsequently recovers, the current v1 data model alone cannot reconstruct the
unwritten partial-delivery event after restart. This patch closes the
reviewer's unhandled OSError/False-return path for the *current stop RPC* and
retries a transient write, but it does **not** claim that an unavailable
persistent store can provide future crash-durable knowledge. A stronger
write-ahead stop-intent/confirmation protocol, or equivalent verified durable
mechanism, must be independently considered before anyone certifies complete
failure-after-recovery protection. Do not self-approve this remaining risk or
use this document as deployment permission.

**Disposition: REVIEW_PENDING.** Implementation-owner response, not an
independent verification or production deployment approval. Request exact-SHA
independent review and respond to any remaining material findings.
