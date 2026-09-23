# ChatGPT Chat mode MCP scheduling - phase 2 results

**Final synthesis:** see `chat-mode-scheduling-final-2026-09-23.md`. It supersedes provisional scheduler wording in this intermediate report.

> **Refinement after this report:** a later unequal-duration production test
> showed a roughly five-wide **sliding in-flight window**, not a rigid
> five-call batch. Independent calls with already-known arguments may refill
> freed slots while a slow call remains outstanding. The barrier described
> below is specifically for **dependent continuation** that needs an early
> result to construct the next call.

Date: 2026-09-23, Australia/Sydney

Scope: ordinary ChatGPT Chat mode with the real Raspberry Pi MCP connector.

Archived probe chats used GPT-5.6 thinking with thinking_effort=max.

## Executive result

The combined experiments support this effective scheduler model:

    reasoning round
        |
        +-- read-only lane: up to 5 calls concurrently
        |      read_file
        |      list_files
        |      search_text
        |      job_status
        |
        +-- non-read-only lane: serialized / separated
               run_command
               stop_job
               tools with readOnlyHint=false

The next reasoning round begins only after the current dispatched batch
completes. A slow read-only call therefore becomes the long pole for the whole
batch.

Long work can nevertheless remain active across reasoning rounds when a
non-read-only call returns a durable handle quickly:

    run_command(background=true) -> job_id
                  |
                  +------ real process keeps running

    later reasoning rounds:
      reads / searches / decisions

    dependency check:
      job_status(wait_seconds=0)

This gives Chat mode useful asynchronous-like behavior without true inter-round
asynchronous MCP result delivery.

## Parallel width is effectively five

Four independent width trials show the same boundary.

width6-075730-6803:
five four-second waits started between 07:57:44.197 and 07:57:44.763. The sixth
did not start until 07:57:49.007, after the first wave had completed.

Peak concurrency: 5.

width8-075806-16771:
five waits started between 07:58:21.572 and 07:58:21.877. The remaining three
started at 07:58:26.364, 07:58:26.664 and 07:58:26.894, after the first wave.

Peak concurrency: 5.

Independent repeats:

- width8b-081341-4619: peak 5, then 3.
- width6b-081412-5221: peak 5, then 1.

The repeated 5+N shape makes five a strong observed Chat-mode scheduling limit,
not a one-off timing accident. It remains an observed product behavior rather
than a permanent API guarantee.

## Tool annotations materially change scheduling

The ordinary async_probe_wait tool is advertised readOnlyHint=true. Independent
instances overlap and use the five-wide lane.

The async_probe_nondestructive_wait control is physically the same harmless
wait but advertises readOnlyHint=false and destructiveHint=false.

Probe nd3-080303-13950 explicitly requested three calls concurrently:

    08:03:26.898  n1 start
    08:03:30.899  n1 end

    08:03:35.342  n2 start
    08:03:39.342  n2 end

    08:03:42.907  n3 start
    08:03:46.908  n3 end

Peak concurrency: 1.

The host/model serialized them despite the prompt explicitly demanding one
concurrent first round.

A mixed annotation test, mixlane-080937-32439, requested two read-only waits and
one non-read-only/non-destructive wait together:

    08:09:58.242  read-only r1 start
    08:09:58.453  read-only r2 start
    08:10:02.243  r1 end
    08:10:02.454  r2 end

    08:10:06.530  non-read-only m1 start
    08:10:10.530  m1 end

The read-only calls overlapped; the non-read-only call was moved to a separate
serial phase.

A real run_command test, bg3-080017-8942, explicitly requested three
background=true calls concurrently. The calls were serialized rather than
parallelized, and the model re-issued two commands before eventually answering
DONE. This is consistent with run_command being non-read-only/destructive.

Engineering conclusion: readOnlyHint is not cosmetic metadata for this ChatGPT
client. It materially affects scheduling. Binnacle should annotate tools
truthfully and should not expect write-like tools to share the read-only
parallel lane.

## Project instructions strongly improve natural read-only batching

A controlled family of prompts asked for the same three independent operations:
one five-second read-only wait, one read_file, and one search_text.

Natural chat, no scheduling instruction, natural-075848-14411:

    +0.000 s  read_file
    +0.233 s  async_probe_wait
    +26.317s  search_text

Only two of the three calls were dispatched before the wait completed.

A temporary server-instruction hint told ChatGPT to schedule independent
read-only calls concurrently, max five per round.

hint-080625-13877:

    +0.000 s  read_file
    +0.229 s  async_probe_wait
    +15.016s  search_text

Still only two of three were in the early batch.

The test Project then used this workflow instruction:

    With Raspberry Pi MCP, issue independent read-only tool calls concurrently,
    at most five per tool-call round. Do not repeat a completed tool call.
    Keep non-read-only calls separate.

Two independent Project-chat trials produced:

projhint-081204-9133:

    +0.000 s  search_text
    +0.234 s  read_file
    +0.239 s  async_probe_wait

projhint2-081242-1267:

    +0.000 s  async_probe_wait
    +0.462 s  search_text
    +0.471 s  read_file

All three calls were dispatched before the wait completed in both trials.

The natural and Project prompts were otherwise the same apart from probe ids.
The archived conversations confirm the Project trials ran under the test Project
and all relevant chats used the same GPT-5.6 thinking model at max effort.

This is still a small A/B sample, but the 2/2 Project result is materially
stronger than the natural and server-instruction trials. It also matches
Binnacle's existing design principle that workflow policy belongs in Project
instructions rather than tool descriptions.

## Future-handle pattern works inside one prompt

Probe future-075233-14534 used one user prompt.

Timeline:

    07:53:23.000  run_command(background=true)
    07:53:24.008  returns job_id=ea646ef4603a, state=running

    07:53:24.497  read_file
    07:53:24.807  search_text

    07:53:29.101  dependent echo using unpredictable token

    07:53:31.615  job_status(wait=0)
    07:53:31.628  state=running, runtime=8.611 s

    07:53:31.935  another read_file

    07:53:35.007  background job finally exits

Therefore the ChatGPT agent executed several later reasoning/tool rounds while
the original shell process was still running. The user did not need to send a
second prompt.

This is the practical asynchronous orchestration primitive available to
Binnacle today: quick handle return + durable background execution + later
non-blocking observation.

The first requested mixed round was not actually mixed in practice:
run_command returned first, then the read-only calls were dispatched. This is
consistent with the annotation-lane result above.

## Blocking job_status is a real reasoning barrier

A production-only control avoided all temporary async-probe tools.

The background job was pre-launched by the test controller. The test Chat was
asked to issue job_status(wait_seconds=8) and read_file concurrently. The file
contained an unpredictable token, and the next call had to use that exact token
as the fixed-string search_text pattern.

Probe barrier4-082451-12200:

    08:25:11.924  read_file call
    08:25:11.927  read_file result; unpredictable token is available

    08:25:12.149  job_status(wait=8) call
                   token is already available while status blocks

    08:25:20.167  job_status result

    08:25:20.978  dependent search_text finally starts

The dependent search did not start during the roughly eight-second window in
which its token was already available and job_status remained unresolved. It
started only after the blocking status call completed.

This independently confirms the batch-barrier result using only production
tools.

## Recommended Chat-mode scheduling policy

For Binnacle and ordinary ChatGPT Chat mode:

1. Parallelize independent read-only calls, at most five per round.
2. Keep non-read-only calls separate. Do not try to co-schedule run_command or
   stop_job with the read-only lane.
3. Make long non-read-only work return a handle quickly. Prefer
   run_command(background=true) or the local auto-background policy.
4. Treat job_id as a Future/Promise-like handle.
5. Use job_status(wait=0) for observation while there is other productive work.
6. A positive job_status wait is a deliberate dependency barrier; use it only
   when the next reasoning round genuinely has nothing useful to do.
7. Do not rely on an early result from one parallel batch to trigger another
   tool round before the slowest member finishes.
8. Put the scheduling rule in Project instructions. The A/B pilot showed much
   stronger compliance there than from the server-level hint.

The compact rule already validated in the test Project is:

    With Raspberry Pi MCP, issue independent read-only tool calls concurrently,
    at most five per tool-call round. Do not repeat a completed tool call.
    Keep non-read-only calls separate.

## Relationship to polling work

The earlier polling problem is more serious under this scheduler model.

A repeated job_status(wait=50) is not merely 50 seconds of idle tool time. It
makes that status call the long pole of the whole read-only batch and prevents
the next reasoning round from starting.

Bad:

    background job
      -> job_status(wait=50)
      -> reasoning-round barrier
      -> repeat

Better:

    background job -> job_id
                    -> parallel read-only rounds
                    -> job_status(wait=0) when useful
                    -> short bounded wait only at a true dependency barrier

The polling fix and scheduling optimization therefore reinforce each other.

## Scope and remaining uncertainty

Strong evidence:

- four width trials all peak at five;
- explicit non-read-only concurrency requests serialize;
- a mixed annotation test split into read-only then non-read-only phases;
- two Project-instruction repetitions fully batched all three read-only calls;
- a production-only blocking-status test exhibited the batch barrier;
- a Future-handle test progressed through several rounds while its job remained
  alive.

Still uncertain:

- whether five is a fixed host cap, a model scheduler policy, or a current
  configuration limit;
- whether other ChatGPT model/effort combinations use exactly the same scheduler;
- whether a future ChatGPT release will negotiate MCP Tasks or true async result
  delivery.

These are empirical ChatGPT product behaviors measured on 2026-09-23. The probe
suite should remain on the isolated analysis branch so the properties can be
re-measured after product changes.

## Sliding-window refinement

Probe widthbarrier-083431-12829 used only production read-only tools. It asked
for one job_status(wait=8) plus five independent read_file calls.

The status call started at 08:34:48.486. Four reads started at
08:34:48.746-08:34:48.772 and completed by 08:34:48.797. The fifth read then
started at 08:34:49.594, while the status call remained unresolved until
08:34:56.503.

This proves that five is best described as an observed maximum number of
read-only calls simultaneously in flight. It is not a hard five-call logical
round. Independent queued work can refill a slot before the slowest call ends.

The Project instruction tested earlier used the phrase "at most five per
tool-call round". That wording was useful for the three-call A/B test but is
overly conservative for larger independent sets. A refined candidate for a
future A/B test is:

    With Raspberry Pi MCP, issue independent read-only tool calls concurrently.
    Keep up to five in flight and continue independent calls as slots free.
    Do not repeat a completed tool call. Keep non-read-only calls separate.

This revised wording is a hypothesis derived from the mechanism test; it has not
yet received the same Project-level A/B validation as the earlier wording.

The distinction that remains important is dependency. A production control
(barrier4-082451-12200) made an unpredictable token available before a blocking
job_status completed, but the search requiring that token did not begin until
after the status call returned. Independent refill works; result-dependent
continuation across the slow call was not observed.
