# Chat mode scheduling v2 — safe benchmark harness

Status: Step 0.3 implementation. This layer owns trial lifecycle and safety; it
does not score benchmark performance.

## Commands

Run one manifest-defined trial:

```bash
.venv/bin/python -m scripts.chat_scheduling_harness trial M1 --arm A
.venv/bin/python -m scripts.chat_scheduling_harness trial M1 --arm B
```

Safety probes:

```bash
.venv/bin/python -m scripts.chat_scheduling_harness restore-probe
.venv/bin/python -m scripts.chat_scheduling_harness chat-smoke
```

A test-only failure injection exercises the real trial cleanup path without
opening a chat:

```bash
.venv/bin/python -m scripts.chat_scheduling_harness trial M1 --arm B \
  --inject-failure-after-instructions
```

That command is expected to exit 1; the pass condition is exact instruction
restore, fixture removal, and unchanged production invariants in `trial.json`.

## Safety model

Each trial follows this lifecycle:

```text
capture production invariant
        |
create unique run_id + 32-char nonce
        |
create disposable fixture under /tmp/binnacle-chat-scheduling-v2
        |
prelaunch fixture jobs through LOCAL FastMCP only when manifest requires them
        |
capture exact Project instructions
        |
apply A or B instruction lease
        |
start project chat
        |         |  +-> chatgpt-send writes conversation URL to url-file ASAP
        |      so timeout/error still leaves an exact cleanup id
        |
track exact test chat id
        |
instruction lease exits -> exact restore, with retry/read-back
        |
backup/delete exact chat id; copy conversation JSON into run state
        |
stop any still-running jobs whose workdir is inside fixture root
        |
remove fixture root
        |
capture production invariant again and compare
        |
write final trial.json
```

The instruction restore happens **before** chat deletion and fixture teardown.
A chat cleanup failure therefore cannot strand the benchmark Project on the
wrong instruction variant.

The ChatGPT terminal helpers may occasionally see transient 403/session
authentication failures even while the browser-backed chat itself is healthy.
For this reason:

- Project get/set operations have a bounded outer retry around the helper's own
  session-level retry;
- exact UUID chat deletion has the same bounded outer retry;
- retries never broaden selectors or fall back to title matching;
- if retries are exhausted, the trial fails and the exact tracked chat remains
  in the ledger for explicit recovery.

These retries are lifecycle hardening only. Chat wall-time metrics are measured
inside the submitted conversation and exclude setup/restore/cleanup time.

## A/B instruction sources

Arm A is read from the exact backend string stored in:

```text
benchmarks/chat-mode-scheduling-v2/baseline-2026-09-23.json
  -> benchmark_project.live_instructions
```

JSON is used deliberately because it preserves the backend's trailing newlines
without an EOF formatter rewriting them.

Arm B:

```text
.claude/skills/chatgpt-mcp-dev/references/
  project-instructions-chat-scheduling-v2.txt
```

Step 0.1 originally froze `chatgpt-project get-instructions` stdout. That CLI
uses `print()`, adding one newline after the backend value. Step 0.3 corrected
the machine-readable baseline to the exact backend bytes while retaining the
original CLI stdout/hash for provenance.

## Fixture isolation

Fixture roots must resolve below:

```text
/tmp/binnacle-chat-scheduling-v2
```

The harness refuses a root outside this base. Fixture files are already
schema-validated against absolute paths and `..` escapes.

For an `ephemeral_git_repo`, the harness initializes Git and commits the
fixture baseline before the model sees the task.

During cleanup, the local MCP recent-job list is inspected. A running job is
eligible for automatic stop only when its reported `workdir` resolves inside
the trial fixture root. Jobs from unrelated development work are never stopped
by the harness.

## Production invariant

The harness captures and compares:

- production Git HEAD;
- production working-tree porcelain status;
- `~/.config/binnacle/config.toml` SHA-256;
- `binnacle-mcp.service` unit-file SHA-256;
- MCP service active/sub state.

A difference fails the trial.

The harness never refreshes the production connector and never changes
`client_tools`, server annotations, or the production checkout.

## Test-chat recovery

The benchmark uses the branch-local `chatgpt-send` with `--url-file`.
As soon as the browser is on a `/c/<uuid>` URL, that exact URL is persisted.
Therefore a later browser timeout does not make the test chat anonymous.

Deletion is by exact UUID only. `chatgpt-chats` backs the conversation up
before hiding it; the harness copies that JSON to the trial state directory and
then removes the UUID from the tracked-test ledger.

If backup/delete fails, the trial fails and the tracked UUID remains visible in
the ledger for explicit cleanup. The harness never falls back to title matching.

## Persistent trial evidence

State is outside the repository:

```text
~/.local/state/binnacle/chat-scheduling-v2/runs/<run_id>/
    trial.json
    chat-url.txt         # conversation id recovery
    chat-timing.json     # Enter -> settled/timeout wall time
    conversation.json    # exact backup after test-chat deletion
    journal.log          # frozen MCP/jobs trial window
    fixture-final.json   # final fixture contents/hash/diff before cleanup
    trace.json           # Step 0.4 normalized evidence, after analysis
    metrics.json         # Step 0.4 trial metrics, after analysis
```

`trial.json` is written atomically and records the current stage, error,
instruction restore result, fixture cleanup, chat cleanup, and production
invariant.

The raw evidence files remain immutable inputs to the Step 0.4 analyzer.
Metric definitions are in `benchmarks/chat-mode-scheduling-v2/METRICS.md`.

## Step 0.3 validation

Unit tests cover:

- unique run ids/nonces;
- placeholder rendering;
- restore on normal exit and exception;
- restore failure preserving the original trial error;
- disposable Git fixture creation/removal;
- fixture-job prelaunch;
- production-invariant change detection;
- exact chat-id delete plus copied backup;
- URL-file chat-id recovery;
- restore-probe behavior;
- full trial failure injection cleanup.

Live controls performed during Step 0.3:

1. **Restore probe:** temporary sentinel instructions were applied, an
   intentional failure was raised, and the exact before/after SHA-256 was the
   same.
2. **Chat smoke:** one non-MCP Project chat returned the expected nonce, was
   tracked, backed up, deleted by exact UUID, and untracked.
3. **Real trial failure injection:** M1/arm-B created a fixture, applied B,
   intentionally failed before chat creation, restored A exactly, removed the
   fixture, and reported production unchanged.

Formal MCP benchmark execution remains deferred to Step 0.5 / Phase 1.
