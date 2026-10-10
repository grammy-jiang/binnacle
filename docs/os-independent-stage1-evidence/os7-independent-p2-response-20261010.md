# Stage 1 PR #18 — independent Codex P2 correction submission

Task: BINNACLE-OS-STAGE1-IMPLEMENT-20261009.

## Reviewer and finding

- Reviewer: chatgpt-codex-connector[bot] on GitHub PR #18.
- Exact reviewed SHA: ae1232bb2ccb66f8ccdadaa945a58e8492f479bc.
- Review ID: 5473022114; inline finding ID: 4232561690.
- Finding: P2, Persist partial signal failures for later stop calls.
- Original behavior: Linux pidfd partial signal delivery was reported only in
  the current stop RPC. A leader could exit while an EPERM child survived;
  later stops short-circuited on the durable exited state and falsely
  reported success.

## Implementation changes to verify independently

1. job_store.mark_signal_delivery_partial atomically writes the optional
   stop_signal_partial=true marker under the same lock as the durable
   reaper, retaining schema, output cursors, native identity and exit status.
2. job_stop.stop_embedded calls the injected on_partial callback as soon
   as partial TERM or KILL delivery is detected, before waiting for the reaper.
3. jobs.stop_job_embedded also persists any partial delivery exception in its
   outer handler and fails closed if metadata cannot be written.
4. Both job_owner.stop_job and direct JobManager._stop RPC check the marker,
   including when the recorded leader has already exited. Subsequent
   stops return explicit partial-delivery failure, not success.
5. Older records without this marker and the public v1 RPC contract remain
   compatible, with no golden rewriting.

## Evidence

- Expanded relevant post-P2 run: 134 passing cases (seed 12345).
- Final affected regression subset: 14 passing cases (seed 12345).
- Explicit regressions: in-process reaper race, true AF_UNIX manager RPC
  retries, old metadata, writer error, late record_exit and no suppressed
  descendant errors.
- Ruff, mypy (152 sources), Import Linter (21 contracts), architecture,
  and module-size checks pass.

**Disposition: REVIEW_PENDING.** This is an implementation-owner submission,
not a second independent review or approval. The new exact pushed commit SHA
requires CI and independent assessment before any merge or deployment.
