# `run_command` observability investigation — 2026-09-24

Status: investigation complete; implementation not started.

Branch/worktree:

- branch: `analysis/run-command-observability-audit`
- worktree: `~/Projects/binnacle-run-command-observability-audit`
- base: `77a3f03` (`master` at investigation start)

Companion implementation plan:
`docs/run-command-observability-implementation-plan-2026-09-24.md`.

## 1. Objective

Audit the current `run_command` execution and observability path before changing it.
The investigation asks four separate questions:

1. Is the runtime/job lifecycle itself healthy after the auto-background and durable-owner changes?
2. Does the journal contain enough information to explain what happened to one call?
3. Does `binnacle stats` expose the information that is already present in the journal?
4. Which facts genuinely cannot be reconstructed and therefore justify new telemetry?

The goal is **not** to maximize logging volume. The design rule remains:
log a dedicated low-cardinality fact only when it explains an internal decision,
fallback, lifecycle boundary, or result-shaping decision that generic
`tool_call` / `tool_result` records cannot reconstruct.

## 2. Non-goals

This investigation does not propose:

- adding full command text to more events;
- logging stdin contents;
- adding CPU/RSS/IO sampling;
- changing the MCP `run_command` or `job_status` result schema merely for analytics;
- moving deployment-local auto-background patterns into repository defaults;
- committing local preference regexes into repository documentation;
- changing the local auto-background policy before telemetry can measure it correctly.

## 3. Evidence and methodology

### 3.1 Fixed production window

The primary production window is frozen at:

```text
2026-09-22 16:05:45 +10:00
through
2026-09-24 20:57:00 +10:00
```

The start is immediately after the new durable-manager timing telemetry became live.
The end is immediately before this investigation began. This excludes the investigation's
own probes and avoids mixing the old manager binary with the final telemetry shape.

A window-boundary case remains intentionally visible: one call began just before the
start and returned just after it. That case is useful evidence that an analytics tool
must distinguish in-window linkage coverage from actual logging loss.

### 3.2 Static sources reviewed

The audit followed the complete path through:

- `src/binnacle/config.py`
- `src/binnacle/logging_middleware.py`
- `src/binnacle/run_command_telemetry.py`
- `src/binnacle/tools/run_command.py`
- `src/binnacle/job_owner.py`
- `src/binnacle/job_client.py`
- `src/binnacle/job_manager.py`
- `src/binnacle/jobs.py`
- `src/binnacle/job_store.py`
- `src/binnacle/job_output.py`
- `src/binnacle/logstats.py`
- `src/binnacle/logstats_tools.py`
- `src/binnacle/logstats_jobs.py`
- `src/binnacle/logstats_models.py`
- `src/binnacle/logstats_render.py`
- the associated unit/integration/contract tests;
- `docs/logging.md` and `docs/tools/run_command.md`;
- the relevant history from `e653aba` through `50b6a9f` and the later
  blocking-wall telemetry changes.

### 3.3 Baseline tests

Before any implementation change, the following focused baseline passed:

| Group | Tests | Result |
| --- | ---: | --- |
| logstats core / job telemetry | 20 | pass |
| config + logging middleware | 42 | pass |
| job manager / job lifecycle | 48 | pass |
| **Total** | **110** | **pass** |

This is the minimum regression set for the implementation work; the normal full-suite
and CI gates still apply before integration.

### 3.4 `binnacle stats` performance baseline

The frozen window was rendered three times from the new worktree:

```text
9.858 s
9.709 s
9.749 s
```

Median wall time: **9.749 s**.

Most of this cost is journal retrieval and existing parsing. The proposed lifecycle joins
remain O(records) and should not materially change this baseline.

## 4. Current architecture and correlation chain

The current managed path is:

```text
ToolLoggingMiddleware
  tool_call(call, client, turn, compact args)
       |
       v
run_command_impl
  DispatchPlan.build(...)
  optional run_command_auto_background(call, command_hash)
       |
       v
job_owner.start_and_wait(...)
       |
       +--> job_client --> binnacle-jobs.service
                         job_start(call, job_id, owner_instance, command_hash)
                         wait/reap
                         job_owner_timing(call, job_id, ...)
                         job_exit(job_id, original call, owner_instance, command_hash)
       |
       v
run_command_dispatch(call, job_id, wait policy, handoff reason, state)
       |
       v
output shaping
       |
       v
tool_result(call, job_id, state, background_job, truncated, output_bytes, ...)
       |
       +--> later job_status(call2, job_id)
              job_status_timing(call2, job_id, state/wait/process costs)
```

This is a good separation of concerns:

- `tool_call` / `tool_result` describe the MCP-facing request and result;
- `run_command_dispatch` describes the execution-policy decision;
- manager/job events describe ownership and lifecycle;
- durable metadata is the source of truth after MCP reloads/restarts.

The investigation does **not** find a reason to redesign this chain.

## 5. Production lifecycle integrity

Within the frozen window:

| Measure | Count |
| --- | ---: |
| `run_command_dispatch` | **4,019** |
| in-window `tool_call(run_command)` | 4,023 |
| in-window `tool_result(run_command)` | 4,024 |
| dispatch with `state=unknown` | **0** |
| dispatch with missing owner instance | **0** |
| owner dispatch error | **0** |
| dispatch without `job_owner_timing` | **0** |
| dispatch without `tool_result` | **0** |
| synchronous dispatch without `job_exit` | **0** |

One dispatch appears without an in-window `job_start`, but the `job_start` is present
1.568 seconds before the window boundary. This is not logging loss.

The difference between 4,023 tool calls and 4,024 results is the same kind of boundary
case: a call began before `--since` and returned inside the window.

### Finding

The **runtime telemetry chain is healthy**. Future stats should expose linkage coverage,
but must label it as *in-window coverage*, not as an error count, because arbitrary
`--since` / `--until` boundaries and mixed-version deployments can legitimately split a
lifecycle.

## 6. Current policy selection versus execution outcome

The existing stats renderer reports only `handoff_reason`. That loses an important
orthogonal dimension: **which policy was selected** versus **what happened during that
policy's wait window**.

Frozen-window dispatches are:

| Selected policy | Outcome | Count |
| --- | --- | ---: |
| automatic background policy | completed during warm-up | **173** |
| automatic background policy | handed off running | **259** |
| explicit `background=true` | completed during warm-up | **16** |
| explicit `background=true` | handed off running | **681** |
| explicit `background=false` | completed synchronously | **49** |
| default foreground | completed synchronously | **2,808** |
| default foreground | normal wait expired | **33** |

The current `handoff reasons` line folds the 173 automatic-policy warm-up completions
and the 16 explicit-background warm-up completions into `synchronous`. The raw telemetry
has enough data to separate these cases; `binnacle stats` simply does not aggregate it.

### Finding

This is a **stats gap, not a logging gap**. No new per-call event is required.

## 7. Auto-background effectiveness: what the current stats cannot show

The 259 automatic-policy handoffs were joined to final `job_exit` records.
All 259 had terminal evidence inside the frozen window.

Using `runtime_s`, `bounded_wait_s`, and the actual 1-second effective warm-up:

| Counterfactual classification | Jobs |
| --- | ---: |
| would have finished inside the original foreground wait | **234** |
| would have reached the original wait boundary anyway | **25** |

This means the dominant purpose of the current auto-background policy is not to avoid a
future wait expiry. It is to **return scheduler control earlier within the same agent turn**.

The estimated initial foreground wait released by the 259 handoffs is approximately
**2,321.2 seconds (38.7 minutes)**.

This is a counterfactual estimate:

```text
max(0, min(runtime_s, bounded_wait_s) - effective_wait_s)
```

It should be labelled as such in stats; it is not equivalent to end-to-end time saved.

### 7.1 Follow-up cost

For those 259 handoffs:

- 254 jobs had at least one `job_status` in the window;
- there were 289 `job_status` calls in total;
- the first status returned `exited` for 234 jobs;
- the first status returned `running` for 20 jobs;
- all 254 first status calls were in the **same ChatGPT base turn** as the originating
  `run_command`;
- median dispatch-to-first-status gap was about 6.1 s;
- p90 was about 39.1 s.

The state/wait phase represented by `job_status_timing.state_ms` totals about 2,788 s.
This is not directly comparable with the counterfactual 2,321 s because the calls overlap
with real job execution and because the model can perform other reasoning/work between
calls. It does prove that reporting only the initial `run_command` latency overstates the
benefit.

### 7.2 Actual intervening tool work

Between automatic handoff and the first status query:

- 254 jobs could be analyzed;
- 229 had **zero** intervening tool calls;
- 25 had at least one intervening tool call;
- 22 had at least one intervening **non-`job_status`** tool call.

So only about **8.7%** of queried automatic handoffs show directly observable independent
tool work before the first status call. The intervening work included other command calls,
searches, and reads.

This does not measure hidden model reasoning, but it is the strongest journal-observable
signal of actual tool-level overlap.

### 7.3 Result collection lag for jobs that would have finished inline

For 229 automatic handoffs that:

1. would have completed within their original foreground wait, and
2. have an observed terminal status collection,

the lag from `job_exit` to the terminal `job_status` record is:

| Metric | Lag |
| --- | ---: |
| p50 | **2.54 s** |
| p90 | **7.04 s** |
| p95 | **8.78 s** |
| max | **18.75 s** |
| aggregate | **717.1 s** |

208 of these 229 had no intervening non-status tool call. Their aggregate collection lag
was about 590.5 s.

### Finding

The policy has real scheduler-control value, but its benefit is workload-dependent. The
new stats should report both the early-handoff benefit and the follow-up/collection cost.
No policy parameter should be changed using only `handoff count` or only initial call
latency.

## 8. Warm-up what-if analysis

There were 432 automatic-policy matches with terminal runtime evidence in the frozen
window. Their runtime distribution was approximately:

- p50: 1.52 s
- p75: 3.24 s
- p90: 17.72 s
- p95: 45.71 s
- max: 203.88 s

A runtime-only counterfactual gives:

| Warm-up | Finish inline | Handoff | Handoff but would finish inside original wait | Would time out anyway | Estimated initial foreground wait released |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 s | 172 | 260 | 235 | 25 | 2,321.2 s |
| 2 s | 246 | 186 | 161 | 25 | 2,103.0 s |
| 3 s | 317 | 115 | 90 | 25 | 1,950.4 s |
| 5 s | 349 | 83 | 58 | 25 | 1,757.2 s |
| 10 s | 370 | 62 | 37 | 25 | 1,395.3 s |

This table is **not** a recommendation to change the warm-up. It omits the value of
returning scheduler control earlier. It demonstrates that the current 1-second threshold
creates many handoffs for short jobs, so Phase 5 needs evidence-driven evaluation rather
than an arbitrary parameter change.

### 8.1 The warm-up is currently shared with explicit background

The effective warm-up comes from `jobs.warmup_s` / `jobs.WARMUP_S`. The same value is
used for both:

- explicit `background=true`; and
- deployment-local automatic background matches.

Therefore a future auto-policy tuning decision must **not** simply change the shared
`jobs.warmup_s` using automatic-policy evidence. That would also delay explicitly requested
background calls and change an existing tool contract.

If Phase 5 eventually proves that automatic matching needs a different threshold, it must
choose explicitly between:

1. keeping the shared 1-second warm-up; or
2. adding a separate `run_command.auto_background_warmup_s` setting whose default preserves
   current behavior.

No separate setting should be added before the data justifies it.

## 9. Automatic-policy rule identity is genuinely missing

`RunCommandSettings.should_auto_background()` currently returns only `bool`.
`DispatchPlan` therefore knows only `auto_background=true/false`.

The existing sparse event:

```text
run_command_auto_background(call, client, command_hash)
```

records that a policy matched but not:

- which client prefix selected the policy;
- which configured rule caused the match;
- which policy version was active.

Historical `tool_call.args` cannot reliably reconstruct this because arguments are clipped
after 500 characters. In the production audit a material subset of automatic matches could
not be classified back to a specific configured rule from the clipped command text.

### Finding

This is a **real telemetry gap**. Add stable, non-reversible identifiers, not pattern text:

- `policy_hash`: fingerprint of the ordered effective policy;
- `rule_hash`: fingerprint of `(client_prefix, pattern)` for the rule that caused the
  decision.

The raw regex and local preference text must not be copied into repository telemetry or
repository documentation.

## 10. Client-prefix semantics are order-sensitive

Current implementation:

```python
for prefix, patterns in auto_background_patterns.items():
    if client.startswith(prefix):
        return any(pattern matches command for pattern in patterns)
```

So the **first matching prefix wins even when none of its patterns match**.
A synthetic test confirmed that merely reversing two overlapping prefix entries reverses
which commands are eligible.

In the same repository, `JobsSettings.blocking_wall_budget_for_client()` already uses a
more deterministic rule: choose the **longest matching prefix**.

Current production has only one auto-background prefix, so this has not caused a production
failure in the audited window.

### Finding

This is a latent policy-semantics defect, not an observability failure. Do not silently
change it while adding telemetry. Phase 5 should make the rule explicit and test it;
longest-prefix semantics is the preferred consistency target.

## 11. Rule false-positive risk is real

The auto-background policy applies regexes to the **entire shell command string**.
Therefore a configured token can match when it is merely:

- present in a filename or cache directory;
- present in a heredoc being written to a source/test file;
- present in a grep/search expression;
- printed as configuration text;
- referenced by a process-inspection command rather than executed.

The production journal contains concrete examples of these shapes. Correctness is not
broken—the command still runs normally—but the call can receive an unnecessary 1-second
handoff policy and extra `job_status` round trip.

### Finding

Do not solve this by hard-coding shell parsing into the server during the observability
work. First record `rule_hash` and measure each rule's:

- match count;
- warm-up completion rate;
- handoff rate;
- runtime distribution;
- follow-up status behavior.

Deployment-local pattern tuning remains outside the repository and should follow that
evidence.

## 12. Effective policy configuration is not fingerprinted

Current machine-readable startup telemetry says only:

```text
tool_config tool=run_command
  wait_default_s=...
  wait_max_s=...
  auto_background_clients=<count>
```

It cannot distinguish:

- one client with 1 rule from one client with 20 rules;
- one set of rules from a completely different set with the same count;
- policy ordering changes that matter under current prefix semantics.

The general `config` record includes Python dict representations for fields such as
`client_tools` and `auto_background`. Those contain spaces, while `plain_fields()` parses
whitespace-free `key=value` tokens. The audit confirmed that only a partial token such as
`{'prefix':` is recovered. It is human-readable but unsuitable as the historical policy
fingerprint.

### Finding

Use `tool_config tool=run_command` as the machine-readable source of truth and add:

- total rule count;
- ordered policy hash.

Do not depend on the general `config` line for this analysis.

## 13. Output truncation currently conflates two causes

`run_command._shaped_output()` performs:

1. optional `tail_lines` reduction;
2. 24k-character head/tail clipping.

It then returns only `(output, truncated)`.

In the frozen window:

- 1,992 calls requested `tail_lines`;
- 43 results had `truncated=true`;
- 32 truncated results also requested `tail_lines`;
- 11 truncated results did not request `tail_lines`.

The current journal cannot prove whether an individual truncated result was caused by:

- line dropping only;
- character clipping only;
- both.

`tail_lines` is usually visible in `tool_call.args`, but that proves only that it was
requested, not that any lines were dropped.

### Finding

This is a **real telemetry gap**, but it is sparse. Emit a dedicated output-shaping event
only when shaping actually removes content. Candidate fields:

```text
call
job_id
reason=tail_lines|char_limit|tail_lines+char_limit
tail_lines=<requested-or->
dropped_lines=<n>
char_clipped=true|false
selected_chars=<chars after line selection, before char clipping>
returned_chars=<final output chars>
log_bytes=<full durable output bytes>
```

No output content is duplicated.

## 14. Pre-dispatch errors are hidden from the execution-telemetry section

The frozen window contains five `run_command` calls that did not produce a dispatch.
They are normal errors/rejections such as invalid workdir/path or client visibility.
Generic `tool_result` logging records them, but the `run_command execution telemetry`
section reports only owner dispatch errors and therefore shows `dispatch_errors=0`.

Both statements are technically true, but a reader can incorrectly interpret the latter
as “run_command had zero errors.”

### Finding

This is primarily a **stats join gap**. Join `tool_call(run_command)` to `tool_result` and
to dispatch events and report separately:

- tool calls observed in the window;
- not-dispatched error/rejection calls;
- owner dispatch attempts;
- owner dispatch errors;
- successful dispatches;
- in-window unpaired/boundary records.

The existing path guard already produces stable codes. The local `workdir is not a
directory` branch still raises a plain `ToolError`; give it a stable
`workdir_not_directory` code in a later small hardening step.

## 15. `binnacle stats` currently underuses existing telemetry

`JobTelemetryStats` aggregates distributions but does not construct a lifecycle join.
It therefore cannot currently answer:

- policy selected versus final handoff outcome;
- run-command calls that failed before owner dispatch;
- linkage coverage across tool/dispatch/job events;
- automatic-policy matches that finished during warm-up;
- automatic handoff jobs that would have finished inside the original wait;
- automatic handoff follow-up `job_status` count/state/cost;
- same-turn versus later-turn collection;
- observable intervening tool work;
- result collection lag;
- output-shaping cause;
- per-rule behavior after rule IDs exist.

All but the final two groups can be computed from **existing** logs.

`search_text` provides a useful precedent: its stats explicitly report dispatch count,
summary count, and coverage while remaining compatible with mixed-version windows.

## 16. Recommended analytics architecture

Do not overload `logstats_jobs.py` with a large second responsibility.
Recommended structure:

```text
logstats.py
  -> existing analyze_tool_*()
  -> existing analyze_job_telemetry()       # owner/job/status performance
  -> new analyze_run_command_workflow()      # cross-event lifecycle/policy join
```

Add a dedicated model, for example `RunCommandWorkflowStats`, and a small module such as
`logstats_run_command.py`.

Reasons:

- preserves current owner-performance metrics and output for compatibility;
- keeps the lifecycle join independently testable;
- avoids pushing `logstats_jobs.py` toward a large mixed-responsibility module;
- mirrors the existing dedicated exact-search analyzer;
- allows mixed-version/window-boundary semantics to be documented in one place.

The first implementation phase should add this analyzer **without changing runtime
telemetry**.

## 17. What should be added to `binnacle stats`

The new report should be concise enough for normal use but answer the core questions.
Suggested shape:

```text
run_command workflow:
  calls/results: calls=N results=N not_dispatched_errors=N dispatch_errors=N
  policy: foreground=... explicit_false=... explicit_background=... auto_background=...
  outcomes: synchronous=... warmup_finished=... handed_off=... wait_expired=...
  in-window linkage: dispatch->result ... job_start ... owner_timing ... sync_exit ...

  auto-background:
    matches=... warmup_finished=... handed_off=...
    terminal_observed=...
    would_finish_within_original_wait=...
    would_timeout_anyway=...
    counterfactual_initial_wait_released_s=...
    jobs_with_status=... status_calls=...
    first_status: exited=... running=...
    first_status_same_turn=...
    jobs_with_intervening_non_status_tools=...
    terminal_collection_lag_s: n/p50/p90/p95/max

  output shaping:                  # after new sparse event exists
    tail_lines=... char_limit=... both=... unclassified_legacy=...

  auto rules:                      # after rule hashes exist
    <rule_hash>: matches=... warmup_finished=... handed_off=...
```

Use explicit labels such as `counterfactual` and `in-window` to prevent overclaiming.

## 18. What should *not* be added to the MCP response

No evidence from this audit justifies expanding `job_status` or `run_command` structured
MCP responses with policy hashes, rule IDs, analytics counters, or output-shaping internals.

The current model-facing response already contains the operational facts it needs:

- state / exit code / signal;
- output or log tail;
- runtime;
- background-job status;
- quiet/process state for `job_status`;
- wait/blocking policy facts where operationally relevant.

The proposed additions are operational analytics. Keeping them journal/stats-only avoids
schema/token growth on every tool call.

## 19. Log-volume and privacy impact of the proposed telemetry

The two proposed runtime additions are intentionally low-volume:

1. matched-rule/policy hashes are added to the **existing sparse auto-background event**;
2. output-shaping events are emitted only when content is actually removed.

The frozen window had hundreds of auto-policy matches but only 43 truncated results,
versus more than four thousand dispatches. This keeps incremental journal volume small.

Privacy constraints:

- no regex text in per-call telemetry;
- no full command duplication;
- no stdin values;
- no returned output content;
- fingerprints are short SHA-256 prefixes used only as stable grouping IDs.

## 20. Key conclusions

1. **The durable `run_command` execution path is healthy.** No redesign is justified.
2. **The raw journal is substantially better than the current stats report.** Most next
   value comes from joining existing events.
3. **Policy selection and execution outcome must be reported separately.**
4. **Auto-background has measurable scheduler-control value but also measurable follow-up
   and collection cost.** Both must be shown.
5. **Matched rule identity and policy version are genuinely missing.** Add hashes, not
   pattern text.
6. **Output truncation cause is genuinely missing.** Add one sparse shaping event.
7. **Pre-dispatch errors are already logged but absent from the run-command stats section.**
8. **Current client-prefix policy selection is order-sensitive and inconsistent with the
   repository's longest-prefix blocking-wall policy.** Treat this as a later behavior
   decision, not an accidental side effect of telemetry work.
9. **Do not expand the MCP `job_status` schema for these analytics.**
10. **Do not tune deployment-local regexes in the repository.** First obtain per-rule
    evidence, then change local policy separately.
