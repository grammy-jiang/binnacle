# Chat mode scheduling v2 — metrics contract

Status: Step 0.4 metric/analyzer contract.

Parent plan: `docs/chat-mode-scheduling-v2-ab-plan.md`.

The analyzer deliberately separates three layers:

```text
raw trial evidence
    trial.json
    chat-timing.json
    conversation.json
    journal.log
    fixture-final.json
        |
        v
normalized trace
    trace.json
        |
        v
trial metrics
    metrics.json
```

Raw evidence is retained so a metric can be recomputed after analyzer changes.

## 1. End-to-end wall time

`wall_s` is measured inside `chatgpt-send` from immediately before pressing
Enter to the point where the final assistant text has stopped generating and
remained stable.

It excludes:

- Playwright startup;
- cookie export;
- page navigation before submission;
- fixture setup;
- Project-instruction switching;
- chat backup/deletion;
- fixture cleanup.

On a browser timeout, `chat-timing.json` records the observed wall time and
`status=timeout`; the trial is not silently discarded.

## 2. Correctness versus terminal completion

These are separate concepts.

**Terminal completion** means every logical DAG node reached its completion
condition. A repeatable `job_status` barrier is one logical node even if it
requires several physical calls before `state=exited`.

**Correctness** means all hard scenario oracles pass:

- expected final reply/payload;
- required tool nodes;
- expected job/command outcome;
- final file content;
- hard event relation;
- mutation-scope audit where applicable.

A soft `event_relation` records scheduler behavior but cannot fail
correctness.

A task can therefore reach its terminal DAG state and still fail correctness,
for example by returning the wrong final reply. That is a correctness failure,
not a premature handoff.

## 3. Same-prompt completion

`same_prompt_completion=true` requires all of:

- terminal DAG reached;
- correctness passed;
- final assistant message complete;
- exactly one user message;
- no request/stream interruption.

This is the primary completion/UX outcome.

## 4. Premature versus intentional handoff

`premature_handoff=true` when:

- terminal DAG was not reached;
- the assistant ended normally;
- there was no interruption;
- blocking budget was not exhausted;
- no external user input was required;
- no unrecoverable error was declared.

A blocking-budget exhaustion is tracked separately as
`budget_exhaustion_handoff`.

An interrupted/timeout request is neither type of handoff; it is an
interruption.

## 5. Manual continuation prompts

`manual_continuations_required` is at least:

- the actual number of user messages after the first; or
- one when an incomplete trial ends in premature handoff; or
- one when an incomplete trial intentionally hands off after budget exhaustion.

Bounded normal scenarios are expected to reach median=0 and p90=0. The explicit
budget-exhaustion scenario is evaluated separately.

## 6. Physical versus logical calls

The trace contains **physical MCP calls**. DAG nodes represent **logical work**.

`duplicate_calls` counts extra physical calls assigned to a logical node that
does **not** allow repeats.

A logical `job_status` node with:

```json
{
  "allow_repeats": true,
  "completion_condition": "job_state=exited"
}
```

may legitimately have multiple physical calls and does not increment
`duplicate_calls`.

`redundant_exact_calls` separately counts repeated identical tool+argument
calls, again excluding logical nodes explicitly allowed to repeat.

## 7. Blocking wall time

`blocking_wall_s` is the **union** of actual positive `job_status` blocking
intervals.

For each call, actual blocking duration comes from `waited_s`, not requested
`wait_seconds`.

Example:

```text
status A blocks 0..20 s
status B blocks 5..20 s

blocking_wall_s = 20 s
not 35 s
```

This matches the proposed server-guard accounting model.

## 8. Avoidable idle wall time

`avoidable_idle_wall_s` answers:

> While a positive job-status wait was blocking, for how long was an
> independent read-only DAG node already runnable but not yet started?

The analyzer:

1. reconstructs logical dependency completion times;
2. derives when each independent read-only node became runnable;
3. measures its pending interval from runnable time to physical tool start;
4. intersects the union of pending intervals with positive blocking intervals.

If a read was already submitted and running concurrently with the status wait,
that running time is **not** avoidable idle.

This makes the target operational:

```text
p90 avoidable_idle_wall_s <= 2 s
```

## 9. Read-only concurrency

`read_only_peak_inflight` is the maximum overlap of physical:

- `read_file`;
- `list_files`;
- `search_text`;
- `job_status`

intervals.

Intervals are half-open: `[start, end)`; one call ending exactly when another
starts is not counted as overlap.

The metric reports observed behavior only. It does not assume that the current
approximately-five-wide product window is permanent.

## 10. Eligible overlap ratio

The denominator is intentionally narrower than "all reads".

Read-only logical nodes are eligible when at least two nodes share the same
dependency frontier: their sorted `depends_on` set is identical and contains
no ordering relation between those peers.

This naturally represents the benchmark fan-out shapes:

- M1: three root reads;
- M2: eight root reads;
- R1: six reads after discovery;
- R11: one cohort after wave-1 search and another after wave-2 search.

A physical call counts as overlapped when its interval intersects at least one
independent eligible peer.

```text
eligible_read_only_overlap_ratio =
    overlapped eligible physical calls / eligible physical calls
```

Calls that are serial because the DAG requires a dependency are excluded from
the denominator.

## 11. Tool/cost metrics

Per trial:

- `tool_calls`;
- `job_status_calls`;
- `positive_job_status_calls`;
- `tool_errors`;
- `tool_result_tokens`;
- `tool_result_bytes`.

Tokens use Binnacle's `tokenizer_tokens` when present. Result bytes are
`content_chars + structured_bytes` from server telemetry.

These metrics measure MCP result cost only; they are not presented as the full
ChatGPT conversation-token bill.

## 12. Interruption classification

A trial is interrupted when:

- browser timing says `status=timeout`; or
- the final conversation text contains a known stream/request interruption
  marker; or
- the harness error records the corresponding timeout/request failure.

Interruption is kept separate from model handoff.

Phase-1 comparison uses interruption **rate**, not an attempt to infer the
undocumented cause of each failure.

## 13. Mutation-journey evidence

Before fixture deletion the harness freezes:

```text
fixture-final.json
    final_files
    file_sha256
    git_status_porcelain   # Git fixture
    git_diff               # Git fixture
```

The analyzer's `no_mutation_outside_scope` audit requires:

- production invariant remained unchanged;
- mutating `run_command` calls used a workdir inside the fixture root;
- absolute paths visible in benchmark shell commands remain under that root
  (with explicit harmless exceptions such as `/dev/null`);
- `stop_job` targets only manifest-owned fixture jobs.

This is an audit guard, not an OS sandbox. Binnacle's unrestricted
`run_command` contract is unchanged.

## 14. Raw journal normalization

Each formal scenario trial freezes the MCP/jobs journal covering the trial
window.

Normalization:

1. parse Binnacle's millisecond ISO `tool_call/tool_result/job_start/job_exit`
   records;
2. keep `openai-mcp` calls whose arguments contain the unique trial root,
   nonce, run id, or fixture job id;
3. identify their base `turn=<base>/<call>`;
4. include all `openai-mcp` calls from that base turn;
5. pair calls/results by Binnacle call id;
6. assign physical calls back to currently-runnable manifest DAG nodes.

This lets a long job-status barrier map several physical calls to one logical
node without relying on title matching or timing guesses.

## 15. Analyzer outputs

For a completed formal trial:

```bash
.venv/bin/python -m scripts.chat_scheduling_analyzer \
  ~/.local/state/binnacle/chat-scheduling-v2/runs/<run_id>
```

writes:

```text
trace.json    # normalized replayable evidence
metrics.json  # stable trial-level metrics
```

and prints the metrics JSON.

Step 0.5 validates this full path with a real short MCP scenario.

## 16. Step 0.4 synthetic acceptance

Synthetic tests cover:

- interval union and half-open peak concurrency;
- five-wide-shaped read fan-out;
- fully serial read fan-out;
- avoidable idle versus promptly submitted reads;
- repeated legitimate dependency waits;
- premature handoff;
- budget-exhaustion handoff;
- timeout/interruption separation;
- correctness failure after terminal completion;
- duplicate/redundant call accounting;
- mutation-journey file oracle;
- real-format journal pairing, trial filtering, DAG assignment, token/byte
  accounting.

Synthetic traces make the metric arithmetic deterministic. A real end-to-end
smoke is intentionally Step 0.5.
