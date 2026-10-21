# P1.9 initial independent reliability review — 2026-10-21

**Evidence class:** Independent read-only code audit of committed baseline `3327531`. Reviewer: new ephemeral Codex session, medium effort, read-only sandbox. Reproductions used in-memory synthetic inputs without live providers. The output below preserves the initial four-blocker REWORK verdict, with source links rebased for this repository.

**P1.9 verdict: REWORK — four concrete blockers.**

Reviewed HEAD `3327531214d10740dee6766541a6016bbd4eb8eb`, both requested documents, and the scoped fixture/unit/integration files. Reproductions used read-only, in-memory executions with bytecode writes disabled. No files were edited, no network or real providers were used, and no services were touched. The full native suite was not rerun.

1. **High — Benchmark admits malformed LSP framing as correct evidence.**
   Location: [process_observer.py:123](../../tests/fixtures/lsp/process_observer.py#L123).

   `ProcessObserver.receive()` treats everything after the first colon as the body length without checking that the header is `Content-Length`. This is the reader actually used by the benchmark; the adversarial framing tests exercise the different `LspPeer.receive()` implementation.

   **Reproduced:** supplied `Wrong-Header: <length>\r\n\r\n` followed by the pinned gold JSON response. `bench.semantic()` returned `correct=True` and admitted a latency sample. Thus a framing regression can generate apparently correct benchmark evidence while the framing test suite remains green.

   **Minimal fix:** share one bounded, strict incremental decoder between both peers, retaining the observer’s separate stderr-draining behavior. Require exactly one valid `Content-Length` and an object payload.

   **Missing test:** run the malformed-frame corpus through `ProcessObserver` and the benchmark admission path. Wrong-header, duplicate-length, negative-length and non-object responses must never become admitted samples; completed failure artifacts must remain `valid=false`.

2. **High — Constructor failures bypass process cleanup.**
   Locations: [lsp_peer.py:19](../../tests/fixtures/lsp/lsp_peer.py#L19), [process_observer.py:70](../../tests/fixtures/lsp/process_observer.py#L70).

   Both constructors can successfully spawn a process and then fail while creating/registering the selector or configuring the pipe. Those operations lack complete rollback. Because construction failed, the context manager’s `__exit__` never runs. `ProcessObserver` also allocates its control pipe before the protected block.

   **Reproduced:** injected `OSError` from selector registration after a mocked successful `Popen`. Both constructors made **zero kill, wait or selector-close calls**. The observer closed the trace descriptor and control reader but left the control writer open. With real children, this path can leave a blocked fake parent and delay cooperative descendant shutdown, contaminating later tests and resource observations.

   **Minimal fix:** protect the complete acquisition sequence with explicit rollback: close the control writer, terminate and reap any spawned parent, and close all acquired pipes/selectors. Handle partial initialization without relying on `__exit__`.

   **Missing test:** inject failures at selector creation, each registration and `set_blocking`; assert every acquired resource is released. Add a native synthetic-child constructor-failure test with bounded disappearance verification.

3. **High — Python 3.10 cannot import the shared fixture peer.**
   Location: [lsp_peer.py:12](../../tests/fixtures/lsp/lsp_peer.py#L12).

   `from typing import Any, Self` requires Python 3.11+, while the repository supports 3.10–3.14. Postponed annotations do not postpone imports. The dependency propagates through `ProcessObserver`, analyzer auditing and benchmarking, preventing collection of the affected tests.

   **Reproduced on installed Python 3.10.22:** importing `LspPeer` raised `ImportError: cannot import name 'Self' from 'typing'`. The recorded native matrix uses Python 3.13 only and therefore cannot detect this.

   **Minimal fix:** remove the runtime `Self` import and use a compatible return annotation, or an already-approved compatibility import.

   **Missing test:** import/collect the complete scoped fixture suite under Python 3.10, then run the supported interpreter matrix.

4. **Medium — Mid-body timeout permanently loses framing state.**
   Location: [lsp_peer.py:51](../../tests/fixtures/lsp/lsp_peer.py#L51), particularly header removal at line 70.

   The pending body length is local to `receive()`, but parsing removes the header from the persistent buffer. A timeout after header parsing discards the length while retaining the partial body. Retrying interprets that body as a new header.

   **Reproduced:** buffered a valid header plus five body bytes, forced a timeout, then appended the entire remaining body. The next `receive()` still raised `TimeoutError`, despite a complete valid response being available.

   Existing split tests establish emitter write boundaries, not deterministic reader boundaries across a timeout; the late-response test times out before any frame arrives.

   **Minimal fix:** persist pending length across calls, or retain the header until the whole frame can be consumed.

   **Missing test:** deterministically pause at every header/body split, including inside UTF-8 bytes; timeout, resume, and verify exactly one decoded response followed by successful decoding of a coalesced next frame.

These are defects in the **P1 synthetic foundation**, not demands to implement P2 production behavior. Final-state manifests cannot exclude reverted writes; periodic sampling cannot observe every short-lived child; cooperative descendant cleanup does not establish general containment. Those limitations are explicitly documented and are not additional blockers here. Production cancellation/future ownership remains a P2 concern.

**GO requires closing these four blockers and rerunning the affected synthetic tests, including Python 3.10 and native Linux/macOS validation.**
