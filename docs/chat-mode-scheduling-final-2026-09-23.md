# ChatGPT Chat mode MCP scheduling — final investigation

**Date:** 2026-09-23 (Australia/Sydney)
**Client:** ChatGPT Chat mode / `openai-mcp`
**MCP protocol observed:** `2026-07-28`
**Server:** Binnacle on Raspberry Pi 5
**Status:** investigation complete

This document supersedes the earlier provisional scheduler descriptions in
`chat-mode-async-orchestration-results-2026-09-23.md` and
`chat-mode-scheduling-phase2-2026-09-23.md`.

## Final model

For the tested ChatGPT configuration, one user prompt can sustain many rounds of
MCP work. The effective scheduler is:

```text
one user prompt / one ChatGPT agent turn
        |
        +-- reasoning
        |
        +-- independent read-only work
        |       |
        |       +-- approximately five calls in flight
        |       +-- free slots are refilled while slow calls remain active
        |
        +-- non-read-only work
        |       |
        |       +-- serialized / separated from the read-only lane
        |       +-- idempotentHint does not make it parallel
        |
        +-- long work
        |       |
        |       +-- run_command(background=true) -> job_id quickly
        |       +-- process continues independently
        |
        +-- later reasoning / tools in the same prompt
        |
        +-- true dependency barrier
                |
                +-- job_status
```

The important limitation is **dependent continuation**. An early result from one
tool was not consumed to construct a new dependent tool call while another slow
call from that dependency sequence remained unresolved.

Independent already-known work is different: it can continue filling free
read-only slots while a slow call is outstanding.

## 1. MCP Tasks are not available

The live ChatGPT MCP client reported:

```text
tasks_initialize_capability=false
tasks_request_capability=false
tasks_request_settings=null
protocol_version=2026-07-28
client_name=openai-mcp
```

Therefore Binnacle cannot currently rely on
`io.modelcontextprotocol/tasks` for Chat-mode long-running work.

## 2. Read-only execution is a sliding window of about five calls

The earlier width trials repeatedly produced a five-wide peak:

- six calls: 5 + 1;
- eight calls: 5 + 3;
- repeated six/eight-call controls: same result.

A later unequal-duration control proved that this is a **sliding in-flight
window**, not a rigid batch. A slow `job_status(wait=8)` remained active while
fast reads completed and a later independent read entered the freed slot.

### Model-independent executor control

To separate model planning from the execution path, eight
`job_status(wait=2)` calls were submitted at once from one
`functions.exec` `Promise.all`.

Observed:

```text
8 calls through the ChatGPT connector path:
wall = 6.548 s

job runtime snapshots:
first wave:  7.220, 7.503, 7.487, 7.487, 7.495 s
second wave: 10.485, 10.716, 10.252 s
```

This is again a 5 + 3 shape even though the model did not choose the width.

A second direct control used one six-second wait plus five one-second waits:

```text
wall = 7.054 s

long wait returned at job runtime 24.307 s
sixth short wait returned at job runtime 22.120 s
```

The later short call therefore completed while the long call was still
unresolved. This independently confirms sliding refill.

### Local FastMCP control

The same server was then called directly on
`http://127.0.0.1:8000/mcp`, bypassing the OpenAI connector path:

```text
8 concurrent job_status(wait=2)
wall = 2.229 s
```

So the five-wide limit is **not** a Binnacle application/FastMCP concurrency
limit. It lies upstream of the local server, in the ChatGPT/OpenAI
tool-execution / connector path. The experiment does not distinguish the exact
OpenAI-side sublayer.

## 3. Dependent continuation still has a barrier

The decisive seed/echo experiments remain valid.

In the strongest control:

```text
07:38:46.010  seed starts, with a server-enforced 1 s delay
07:38:46.258  long 12 s wait starts
07:38:47.011  seed returns an unpredictable token
               ~11.25 s opportunity
07:38:58.258  long wait ends
07:38:59.048  dependent echo starts with the exact token
```

The dependent call did not start during the large interval in which its input
was available but the long call remained unresolved.

A production-only control reproduced the same result using
`read_file -> unpredictable token -> dependent search_text` alongside
`job_status(wait=8)`.

Therefore:

- independent known work can refill free slots;
- result-dependent reasoning did not resume across the still-running slow call.

## 4. Non-read-only tools are serialized

The annotation controls showed:

- `readOnlyHint=true` no-op waits overlap;
- physically identical `readOnlyHint=false` no-op waits serialize;
- mixed read-only/non-read-only workloads split into separate phases;
- real `run_command(background=true)` calls are scheduled serially by ChatGPT.

### idempotentHint does not open the parallel lane

Production `stop_job` is annotated:

```text
readOnlyHint=false
destructiveHint=true
idempotentHint=true
openWorldHint=false
```

Three dedicated dummy jobs ignored SIGTERM, forcing each `stop_job` to block
for about five seconds until SIGKILL. The three calls were submitted together
through one executor `Promise.all`.

Observed:

```text
09:51:09.399 -> 09:51:14.453  stop #1
09:51:16.863 -> 09:51:21.911  stop #2
09:51:24.218 -> 09:51:29.266  stop #3

wall = 22.042 s
```

They were strictly serialized.

Conclusion: for this client, `idempotentHint=true` does not make a
`readOnlyHint=false` tool eligible for the parallel read-only lane.

## 5. Future/Promise-style background execution works in one prompt

The successful future-handle trial showed:

```text
run_command(background=true)
    -> job_id in about 1 s

while the process is still running:
    read_file
    search_text
    dependent reasoning
    another read_file
    job_status(wait=0)

background process exits later
```

All of this occurred inside one user prompt.

This is the practical asynchronous primitive available to Binnacle today:
**quick durable handle return + background process + later observation**.

No generic workflow engine is required.

## 6. Project instruction result

Earlier controlled trials with three independent read-only operations showed:

```text
natural chat:        34.64 s
server instruction: 25.36 s
Project rule #1:    17.27 s
Project rule #2:    15.25 s
```

The Project rule materially improved the model's tendency to batch known
independent reads.

The first rule said "at most five per tool-call round". Later mechanism tests
showed this wording is unnecessarily restrictive because the platform itself
enforces/refills the approximately five-wide window.

### Refined rule validation

A baseline and two refined-Project trials each asked for one
`job_status(wait=5)` plus five independent reads.

Baseline, no scheduling rule:

```text
09:52:28.222  status starts
09:52:28.444  read
09:52:28.457  read
09:52:28.687  read
09:52:28.707  read
09:52:29.332  fifth read refills
09:52:33.240  status ends
```

Refined trial 1:

```text
09:53:38.921  read
09:53:39.223  read
09:53:39.232  status starts
09:53:39.452  read
09:53:39.460  read
09:53:39.730  fifth read refills
09:53:44.249  status ends
```

Refined trial 2:

```text
09:54:35.171  read
09:54:35.431  read
09:54:35.437  read
09:54:35.450  status starts
09:54:35.637  read
09:54:36.014  fifth read refills
09:54:40.611  status ends
```

The refined rule did not create artificial five-call logical batches. All
already-known independent work was submitted and the platform handled the
sliding window.

The final recommended wording is:

```text
With Raspberry Pi MCP, submit all currently-known independent read-only tool
calls without waiting for other independent results. Do not manually split
them into groups of five; the platform currently keeps about five calls in
flight and refills slots as calls finish. Do not repeat completed calls. Keep
non-read-only calls separate.
```

The "about five" statement is empirical behavior, not an API contract.

## 7. Real development workload impact

In the measured 8.5-hour development window:

- 731 `read_file` / `list_files` / `search_text` calls;
- 43 turns contained at least two such calls;
- about half of those turns were fully serial;
- strict discovery-follow-up analysis found 29 high-confidence clusters with
  95 independent `read_file` calls;
- cluster size: p50 = 3, p90 = 5, max = 6;
- high-confidence wall-clock recovery estimate = **212.7 s / 3.5 min**;
- a broader estimate, including repeated paths, was about **355.9 s**.

The p90 cluster size being five is a useful fit with the observed execution
window. A new bulk `read_files([...])` tool is not justified by this evidence;
the existing simple tools already map well to the host scheduler.

## 8. job_status: final policy evidence

Across the expanded measurement window:

```text
first-status jobs with known start+exit: 408+
running at first status:                 ~275-279

residual runtime when still running:
p10  ~3 s
p25  ~9 s
p50  32.5 s
p75  74.1 s
p90 174.6 s
max  >2300 s
```

Age at first status did not produce a stable enough hazard difference to
justify an age-based adaptive policy.

For jobs still running at first status:

| Wait cap | Finish within cap | Mean actual blocked time |
| ---: | ---: | ---: |
| 2 s | 7.3% | 1.9 s |
| 5 s | 16.4% | 4.6 s |
| 10 s | 26.2-26.5% | 8.5 s |
| 20 s | 36.6-37.1% | 15.4 s |
| 30 s | 48.0-48.4% | 21.2 s |
| 50 s | 65.2-65.8% | 29.6 s |
| 120 s | 86.4% | 46.2 s |
| 180 s | 88.9% | 53.3 s |
| 300 s | 93.9% | 63.4 s |

The historical problem was not one legitimate dependency wait. It was repeated
blocking waits:

```text
positive job_status waits: 700+ calls
turns containing them:      ~64
requested wait / turn:
  p50  210 s
  p75  500 s
  p90 1000 s
  max 2150 s
```

This changes the conclusion from the earlier polling prototype.

### Do not deploy the old "one 10 s wait, then force zero" rule unchanged

That rule bounds latency well, but it is too restrictive for the user's primary
goal: complete long development workflows inside one prompt.

The better separation is:

1. **Scheduling policy** prevents unnecessary blocking:
   - launch long commands early in the background;
   - submit all known independent read-only work;
   - while useful independent work exists, use `job_status(wait=0)` only
     when a status observation is actually needed;
   - a positive wait is reserved for a true dependency barrier.

2. **Server guard** is a catastrophe ceiling, not the normal scheduler:
   - bound cumulative blocking wall time for an agent turn rather than
     suppressing every repeated wait after the first;
   - overlapping read-only waits should charge wall time once, not sum their
     requested durations;
   - once the wall budget is exhausted, further positive waits become
     non-blocking and telemetry must say so.

A five-minute / 300 s wall ceiling is a reasonable next implementation
candidate, not because ChatGPT has a documented five-minute limit, but because
this sample shows it would cover about **93.9%** of residual job runtimes while
still preventing the multi-hundred-to-multi-thousand-second repeated-wait
patterns seen in real turns.

The exact ceiling should be validated in a live A/B before production rollout.

## 9. Recommended Binnacle Chat-mode workflow

```text
1. Identify dependencies.

2. Submit every currently-known independent read-only call.
   Do not manually batch at five.

3. Start long non-read-only commands early.
   run_command(background=true) -> job_id

4. Continue reasoning and independent reads/searches while jobs run.

5. Treat job_id as a Future/Promise handle.

6. Do not use a positive job_status wait while productive independent work
   remains.

7. At a real dependency barrier, wait deliberately.

8. Do not blind-poll the same job. A server wall-budget guard should bound
   pathological repeated waiting without forbidding legitimate same-prompt
   completion.
```

## 10. What is proven and what remains product-dependent

Proven for the tested ChatGPT configuration on 2026-09-23:

- one prompt can execute many MCP rounds;
- independent read-only calls overlap;
- the connector path exposes an approximately five-wide sliding window;
- the five-wide limit is upstream of local Binnacle/FastMCP;
- independent queued work refills free slots while a slow read-only call runs;
- dependent continuation across that slow call was not observed;
- non-read-only calls serialize;
- `idempotentHint=true` does not change that;
- background `job_id` handles enable useful same-prompt asynchronous work;
- MCP Tasks were not negotiated.

Not proven as a permanent product guarantee:

- that the width will always be five;
- which exact OpenAI-side component owns the width;
- that other models/effort levels use identical scheduling;
- that MCP Tasks will remain unavailable.

The probe suite should therefore stay isolated and be re-run after meaningful
ChatGPT MCP/runtime changes.

## 11. Experiment safety lesson

During phase 2, a temporary `client_tools` allowlist experiment removed
`run_command` and `stop_job` from the active production connector. Recovery
required restoring the pre-experiment config/unit backups and refreshing the
connector.

The resulting rule is:

> Never mutate the only active production connector's control surface for a
> schema/annotation experiment.

Future schema-changing experiments need either a separate Lab connector or a
test that can be expressed using already-existing production tools. The final
`idempotentHint` control deliberately used production `stop_job` dummy jobs, so
no second schema mutation was required.
