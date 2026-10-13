# R6 W3 E1-a6 delta review and repair — 2026-10-13

## Scope

Source reviewed: signed E1-a6 candidate
8d9142e6c2f4e1761c508c7d153a25ee5bf9aadb, against its parent
675f3ae23af58f9a4068510f25de81fdda67084c. Work was conducted only
in a new isolated review clone; the original E1 worker branch is unchanged.

The first targeted run had 262 passed. Existing tests cover the F1–F4
lifecycle and the five SD-90 rules; they were not weakened.

## Reproducible findings

- E1A6-REVIEW-F2 (diagnostic attribution). The existing frame selector
  picked the innermost third-party exception frame even when the call
  originated inside a Binnacle module. A test-owned synthetic external
  exception produced the external file name instead of the Binnacle
  importer. Fixed by giving Binnacle frames precedence; syntax errors
  retain their own location and a directly imported target may retain
  its own file, otherwise the requested module is reported. No traceback
  or exception message is written to logs.
- E1A6-REVIEW-F4 (record ownership). The candidate wrapped the
  process-global uvicorn.Server.startup and could clear the durable
  Binnacle startup-failure record when another Uvicorn server started
  later in the same process. A negative regression failed on the
  original 8d9142e. Fixed by requiring both an active serving-entry
  mark and the expected Binnacle ASGI app identity before clearing.
  A positive test still clears when the real Binnacle server starts.

Tests in test_r6w3_e1g_f2_frames.py and test_r6w3_e1g_server_scope.py
reproduce the failures; the original serve E2E is aligned with the
actual serving-entry lifetime and retains its bind-failure coverage.

## Required follow-up

- Re-run the complete E1 affected selectors at the final candidate head.
- Run MyPy Linux/Darwin, the generated server-module drift check,
  import/architecture policy and commit hooks.
- Verify the exact source fix on Raspberry Pi (and selected other Python
  interpreters as required), then perform a fresh read-only delta review.
- Merge approved E1 changes only after the accepted FDW stage has a
  dependency-safe integration head. The new Darwin file_io module from
  FDW-B1-a3 must be included by regeneration of the E1 server literal
  during integration; it is not present in the original E1 candidate.
- No GitHub push, production restart or deploy is authorized by this
  evidence file alone.
