# ChatGPT Chat mode asynchronous MCP orchestration — results

**Final synthesis:** see `chat-mode-scheduling-final-2026-09-23.md`. It supersedes provisional scheduler wording in this intermediate report.

> **Later refinement:** phase-2 production controls showed that the read-only
> scheduler is not a rigid whole-batch barrier. It maintains roughly five
> independent calls in flight and may refill a freed slot while another slow
> call remains outstanding. The negative async result in this report applies to
> **dependent continuation**: a later call that must consume an early result was
> not started across a still-running slow call.

**Date:** 2026-09-23 (Australia/Sydney)
**Client under test:** ChatGPT Chat mode, real chatgpt.com browser session
**MCP client name:** `openai-mcp`
**MCP protocol:** `2026-07-28`
**Server:** Binnacle experiment branch `analysis/chat-async-probe`

## Executive result

ChatGPT Chat mode supports both:

1. multiple MCP tool-call rounds inside one user prompt / agent turn; and
2. concurrent MCP calls **within one tool-call round**.

It did **not** demonstrate asynchronous continuation from an early tool result
while another tool from the same round remained outstanding.

The observed scheduling model is therefore:

```text
reasoning round
    |
    +-- tool A -----+
    +-- tool B -----+  concurrent
    +-- tool C -----+
                    |
              wait for whole batch
                    |
             next reasoning round
```

not:

```text
tool A -----------------------------+
tool B -> result                     |
          |                          |
          +-> reasoning -> tool C    |  (not observed)
                                     |
tool A result -----------------------+
```

For Binnacle, the practical way to obtain asynchronous-like development flow in
one Chat prompt is still to make long operations return a durable handle
quickly, then let later reasoning rounds continue. A truly outstanding MCP call
must not be allowed to become the round's long pole.

## T0 — MCP Tasks extension

Live ChatGPT result:

```text
tasks_initialize_capability=false
tasks_request_capability=false
tasks_request_settings=null
protocol_version=2026-07-28
client_name=openai-mcp
```

**Result:** MCP Tasks (`io.modelcontextprotocol/tasks`) are not negotiated by
this ChatGPT Chat client. Binnacle cannot currently rely on standards-native
MCP Tasks for long-running Chat-mode work.

## T1 — parallel MCP dispatch

Probe: `par-002600-4135`

Three independent eight-second waits were requested in the first tool-call
round.

```text
00:26:16.227  p2 start
00:26:16.549  p1 start
00:26:16.774  p3 start
00:26:24.228  p2 end
00:26:24.550  p1 end
00:26:24.774  p3 end
```

All three calls have the same ChatGPT base turn:

```text
25625f80-bc08-421f-bb21-e9ffcbf6b11e
```

The start spread was about **0.55 s**, and the calls overlapped for almost their
entire eight-second duration.

**Result: PASS — ChatGPT Chat mode parallel-dispatches independent MCP calls.**

## T2 — dependent continuation while another call is outstanding

### Trial A

Probe: `async-002647-6676`

The long wait started first; the unpredictable seed returned 14.77 seconds
before the long wait ended.

```text
00:27:09.823  long wait start
00:27:10.055  seed start/end -> 0865...
               [14.77 s opportunity for dependent echo]
00:27:24.824  long wait end
00:27:25.627  echo start/end, exact seed token
```

All calls share base turn:

```text
6a62734b-d8ad-4735-b66e-ecddcefe9d64
```

The exact seed reached echo, proving echo was genuinely dependent on the seed
result. But echo started only **after** the long call ended.

Deterministic classifier:

```text
classification=parallel_batch_barrier
seed_token_matches_echo=true
seed_finished_while_wait_running=true
echo_started_before_wait_end=false
```

### Trial B — stronger delayed-seed control

Probe: `async4-073820-28338`

This trial removed the scheduling-order ambiguity. Seed itself waited one second
before returning. The long call lasted 12 seconds.

```text
07:38:46.010  seed start (server-enforced 1 s delay)
07:38:46.258  long wait start
07:38:47.011  seed end -> 0a95...
               [11.25 s opportunity for dependent echo]
07:38:58.258  long wait end
07:38:59.048  echo start/end, exact seed token
```

All calls share base turn:

```text
b88241b7-6f93-42d1-af5e-f976d1597fc9
```

Again the seed definitely completed while the long MCP call was unresolved, and
again the dependent echo did not start until after the long call ended.

Deterministic classifier:

```text
classification=parallel_batch_barrier
seed_token_matches_echo=true
seed_finished_while_wait_running=true
echo_started_before_wait_end=false
```

This is the decisive control because the server, not the model, creates the
early-result window.

## Additional trials

Two additional scheduling trials were useful as controls but are not counted as
decisive evidence:

- `async2-002807-2611` contained a repeated wait/seed attempt under the same
  probe id, so it is intentionally excluded from the binary verdict.
- `async3-002950-23611` dispatched seed before the long wait started, so it did
  not establish the required "seed returned while long was outstanding"
  condition. Echo still occurred after the wait.

Neither contradicts the two decisive barrier trials.

## What is proven vs inferred

### Proven for the tested Chat mode configuration

- One prompt can produce several rounds of MCP calls.
- One round can contain multiple concurrent MCP calls.
- FastMCP/Binnacle itself handles concurrent calls; a local control completed
  three 0.6-second waits in about 0.95 seconds.
- ChatGPT did not negotiate MCP Tasks.
- In two decisive trials, a dependent second-round call was not dispatched
  during a still-running first-round call, despite an explicit prompt and a
  large 11–15 second opportunity window.

### Not proven

The experiment cannot distinguish whether the batch barrier lives in:

- the ChatGPT host/orchestrator, which may withhold partial batch results from
  the model; or
- model/tool scheduling policy, which may receive an early result but decline
  to continue until the batch completes.

For Binnacle this distinction does not change the engineering consequence: the
**effective Chat-mode behavior is batch-barrier scheduling**.

This result is a capability measurement for the tested ChatGPT configuration on
2026-09-23, not a permanent product guarantee. It should be re-run if ChatGPT's
MCP host or model orchestration changes.

## Engineering consequence for Binnacle

Do not design a Chat-mode workflow that leaves a long MCP call unresolved while
expecting the model to consume another call's early result and start the next
round.

Instead:

```text
round N:
  run_command(background=true) -> job_id quickly
  read/search calls             -> results quickly

round N+1:
  reason with those results
  start more independent work

later dependency barrier:
  job_status(wait_seconds=0 or short bounded wait)
```

Independent long jobs can also be launched in parallel, because parallel MCP
dispatch is confirmed. The important rule is that every call in a round should
return quickly unless the entire next reasoning round is allowed to wait for it.

This strengthens, rather than weakens, the value of:

- auto-backgrounding known long developer commands;
- eliminating repeated blocking `job_status` waits;
- using job ids as future/promise-like handles;
- parallelizing independent read/search/short-execution calls;
- keeping ChatGPT in one prompt/turn where possible without making any MCP call
  the long synchronous barrier.

A full durable workflow engine is not required by this finding.

## Later scheduling correction

Subsequent production-only testing refined two statements in this report.

First, five is an observed in-flight width for independent read-only calls, not
a rigid per-round call count. In probe widthbarrier-083431-12829, one
job_status(wait=8) and four fast reads occupied the first five slots. After the
fast reads completed, a sixth independent read started while the slow status
call still had about seven seconds left. Independent known work can therefore
refill free slots.

Second, real run_command calls are non-read-only and were observed to serialize
rather than share the read-only parallel lane. Multiple long jobs can still run
concurrently after successive quick background launches return their job ids.

These refinements do not change the core negative result: calls that require an
early result to construct a dependent next action did not start while another
slow call in the same dependency sequence remained unresolved.
