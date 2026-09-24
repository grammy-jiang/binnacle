# `run_command` observability implementation plan — 2026-09-24

Status: Phases 1–4 implemented and validated; Phase 5 pending production evidence.

Parent investigation:
`docs/run-command-observability-investigation-2026-09-24.md`.

Working branch/worktree:

- branch: `analysis/run-command-observability-audit`
- worktree: `~/Projects/binnacle-run-command-observability-audit`
- base commit: `77a3f03`

## 0. Implementation progress — 2026-09-24

Phases 1–4 are implemented on this analysis branch. Phase 5 remains intentionally pending
because it is a policy-quality decision that requires representative production evidence
from the new rule/policy hashes.

Completed:

- Phase 1: added a dedicated cross-event `run_command` workflow analyzer and stats model;
  preserved millisecond timestamps; separated policy selection from dispatch outcome;
  joined pre-dispatch errors, lifecycle linkage, automatic-handoff counterfactuals,
  `job_status` follow-up, same-turn correlation, observable intervening tool work, and
  result-collection lag;
- Phase 2: reproduced the frozen production-window aggregates, validated the mixed-version
  deployment-transition window, and passed the stats performance gate;
- Phase 3A: added stable automatic-policy/rule fingerprints without exposing raw regexes;
  implemented independently as `96edff2` and merged via `14ed1cc`;
- Phase 3B: added a pure output-shaping model plus sparse classified shaping telemetry;
  implemented independently as `e35566a` and merged via `d68a52d`; the two Phase-3 lanes
  were merged only after their independent tests and hooks passed;
- Phase 4: added the stable `workdir_not_directory` pre-dispatch error code and verified
  the middleware records it without a dispatch (`ba63114`).

Validation recorded so far:

- Phase-1/2 focused baseline plus new tests: **119 passed**;
- merged Phase-3 combined targeted suite: **151 passed**;
- Phase-4 focused suite: **45 passed**;
- all changed-file pre-commit gates run so far passed, including mypy, deptry, module-size,
  AI-readability, and architecture checks;
- frozen-window `binnacle stats` performance after Phase 1/2: 10.360 / 10.577 / 10.432 s,
  median **10.432 s** versus 9.749 s baseline (+0.683 s, about +7.0%);
- the performance gate (<15% and <1.0 s absolute regression) passed.

Final integrated validation:

- frozen historical production journal remained compatible: core workflow numbers reproduced
  exactly, and **43** old truncated results were reported as `legacy_unclassified` because
  the historical window predates `run_command_output_shaping`;
- supported two-lane full suite, seed 12345:
  - parallel-safe lane: **1186 passed, 3 skipped** in 31.68 s;
  - ordinary-process lane: **2 passed**, 1189 deselected in 2.92 s;
  - total runner elapsed 36.70 s; wrapper wall **36.78 s**;
  - starting one-minute load average was 0.57;
- repository-wide `pre-commit run --all-files`: **PASS** across every configured hook,
  including markdown/yaml/json, secret detection, ruff, bandit, uv-lock, codespell, mypy,
  pip-audit, deptry, module-size, AI-readability, and architecture boundaries;
- Phases 1–4 are therefore closed on this analysis branch with no MCP schema change.

Phase 5 entry condition:

- deploy the Phases 1–4 telemetry first;
- accumulate a representative real-use sample with `policy_hash`/`rule_hash` present;
- then compare per-rule match, warm-up-finish, handoff, follow-up, overlap, and collection
  behavior before changing prefix semantics, warm-up thresholds, or local regexes.

## 1. Goal

Improve `run_command` observability without increasing the MCP schema or flooding the
journal. The work should make `binnacle stats` able to answer the operational questions
that the production audit exposed, then add only the small amount of new runtime telemetry
that cannot be reconstructed from existing records.

The implementation has five phases:

1. stats-only lifecycle/workflow analysis;
2. production and regression validation of that analysis;
3. minimal runtime telemetry for policy identity and output shaping;
4. stable error classification and final stats integration;
5. evidence-driven auto-background policy evaluation/tuning.

Phases 1–4 are repository implementation work. Phase 5 deliberately separates generic
repository semantics from deployment-local preference changes.

## 2. Core design principles

### 2.1 Evidence before instrumentation

Do not add a field merely because it might be useful. First determine whether the fact can
be reconstructed by joining existing `tool_call`, `tool_result`, dispatch, owner, job, and
status records.

### 2.2 Keep model-facing schemas stable

No new `run_command` / `job_status` MCP fields are required for the current objective.
Operational analytics belongs in journal records and `binnacle stats`.

### 2.3 Preserve backward compatibility

`binnacle stats` must continue to read historical journals. New analyzers must tolerate:

- missing newer fields;
- old embedded-owner records;
- windows that start/end in the middle of a call or job;
- mixed server/manager versions during a deployment transition.

Missing in-window counterparts are coverage facts, not automatically errors.

### 2.4 Keep deployment-local policy private

Never log or commit raw local auto-background regexes merely for analysis.
Use short hashes as stable grouping identifiers.

### 2.5 Separate policy selection from execution outcome

Examples:

- auto policy selected + warm-up finished;
- auto policy selected + handed off;
- explicit background selected + warm-up finished;
- foreground selected + wait expired.

These are distinct dimensions and must remain distinct in code and reporting.

### 2.6 Avoid artificial orchestration limits

Implementation tasks form a dependency DAG. An orchestrator may run **all ready independent
steps concurrently**; there is no fixed chat/agent/session cap in this plan. Parallelism is
limited only by real file/branch/test dependencies and shared-state mutation boundaries.

Canonical shared artifacts (the branch history, final plan/status documents, and any single
baseline file) should have one writer at a time; independent implementation/test/review
lanes may run in parallel worktrees/branches and merge through dependency gates.

## 3. Invariants that must not change

The implementation must preserve:

- wait-not-kill semantics;
- maximum foreground wait of 50 s;
- explicit `background=false` overriding auto-background;
- explicit `background=true` using the existing background warm-up;
- durable manager ownership and restart behavior;
- command/output capture semantics;
- head+tail result clipping behavior;
- full output retained on disk;
- `run_command` / `job_status` / `stop_job` MCP response schemas;
- repository default auto-background policy remaining empty;
- local regexes remaining deployment configuration, not repository policy.

## 4. Baselines and acceptance gates

### 4.1 Functional baseline

The focused pre-change baseline is 110 passing tests:

- 20 logstats/job-telemetry tests;
- 42 config/logging tests;
- 48 job-manager/lifecycle tests.

Every phase must preserve its relevant subset. Before merge, the repository's normal full
suite and CI must be green.

### 4.2 Production reference window

Use the frozen aggregate reference from the investigation:

```text
2026-09-22 16:05:45 +10:00
through
2026-09-24 20:57:00 +10:00
```

Do not commit raw journal/command/pattern content. If a baseline artifact is added, store
only aggregate non-sensitive metrics.

### 4.3 Stats performance gate

Baseline `binnacle stats` median wall time over the frozen window: **9.749 s**.

Acceptance target after the stats-only phase:

- median of three identical runs should not regress by more than 15%; and
- any regression above 1.0 s absolute must be explained before proceeding.

A small O(records) lifecycle map is expected to stay well below this threshold.

### 4.4 Journal-volume gate

New per-call telemetry is not allowed unless it is sparse or strictly necessary.
The proposed changes pass this rule because:

- rule/policy IDs extend the already sparse auto-background marker;
- output-shaping telemetry is emitted only when content is actually removed.

## 5. Target reporting contract

After Phases 1–4, `binnacle stats` should include a compact section similar to:

```text
run_command workflow:
  calls/results: calls=... results=... result_errors=...
  dispatch: successful=... owner_errors=... not_dispatched_errors=...
  policy: foreground=... explicit_false=... explicit_background=... auto_background=...
  outcome: synchronous=... warmup_finished=... handed_off=... wait_expired=...
  in-window linkage: dispatch->result=... job_start=... owner_timing=... sync_exit=...

  auto-background:
    matches=... warmup_finished=... handed_off=...
    terminal_observed=...
    would_finish_within_original_wait=...
    would_timeout_anyway=...
    counterfactual_initial_wait_released_s=...
    jobs_with_status=... status_calls=...
    first_status exited=... running=...
    first_status_same_turn=...
    jobs_with_intervening_non_status_tools=...
    terminal_collection_lag_s: n/p50/p90/p95/max

  output shaping:
    tail_lines=... char_limit=... both=... legacy_unclassified=...

  auto rules:
    <rule_hash>: matches=... warmup_finished=... handed_off=...
```

Existing `run_command execution telemetry` owner/latency metrics remain available. Do not
silently rename or remove historical lines in the first implementation.

---

## Phase 1 — Stats-only lifecycle/workflow analyzer

**Objective:** obtain substantially better `run_command` analysis using only telemetry that
already exists today. Runtime logging must remain untouched in this phase.

**Primary files:**

- new: `src/binnacle/logstats_run_command.py`
- `src/binnacle/logstats_models.py`
- `src/binnacle/logstats.py`
- `src/binnacle/logstats_render.py`
- new: `tests/unit/core/test_logstats_run_command.py`
- docs: `docs/logging.md`

### Step 1.1 — Add a dedicated workflow stats model

Target: 20–30 minutes.

Add a dedicated `RunCommandWorkflowStats` rather than overloading
`JobTelemetryStats`.

Recommended initial fields:

```text
tool_calls
tool_results
result_errors
successful_dispatches
dispatch_errors
not_dispatched_errors
policy_modes: Counter
outcomes: Counter
not_dispatched_error_reasons: Counter

link_dispatch_result_num / den
link_dispatch_job_start_num / den
link_dispatch_owner_timing_num / den
link_sync_exit_num / den
boundary_or_legacy counters

auto_matches
auto_warmup_finished
auto_handed_off
auto_terminal_observed
auto_would_finish_within_original_wait
auto_would_timeout_anyway
auto_initial_wait_released_s
auto_jobs_with_status
auto_status_calls
auto_first_status_states: Counter
auto_first_status_same_turn
auto_first_status_different_turn
auto_jobs_with_intervening_non_status_calls
auto_intervening_tools: Counter
auto_terminal_collection_lag_s: list[float]

output_shaping_reasons: Counter          # populated later
auto_rule_matches: Counter              # populated later
auto_rule_handoffs: Counter             # populated later
```

Keep aggregate fields only; do not retain full commands/results in the stats model.

**Acceptance:** model is additive and old stats tests remain green.

### Step 1.2 — Build a single-pass event index

Target: 20–30 minutes.

In `logstats_run_command.py`, scan records once and build small maps:

```text
tool_call by call id
tool_result by call id
run_command_dispatch by call id
run_command_dispatch_error by call id
auto-background marker by call id
job_start by job id
job_owner_timing(start) by job id
job_exit by job id
job_status_timing list by job id
```

Also retain record sequence number so intervening tool calls can be counted without
re-parsing the journal.

Do not depend on command argument JSON for core classification; long commands can clip it.
Use the explicit dispatch fields whenever they exist.

**Acceptance:** synthetic records with clipped args still classify policy/outcome correctly.

### Step 1.3 — Define policy-mode classification

Target: 20 minutes.

Derive a stable enum from `background_arg` + `auto_background`:

```text
auto_background
explicit_background
explicit_foreground_override
foreground_default
unknown_legacy
```

Do not use `handoff_reason` as a policy selector.

Derive outcome separately:

```text
synchronous
warmup_finished
handed_off
wait_expired
owner_error
not_dispatched_error
unknown_legacy
```

Rules:

- auto + exited -> `warmup_finished`;
- auto + running -> `handed_off`;
- explicit background + exited -> `warmup_finished`;
- explicit background + running -> `handed_off`;
- foreground/default or explicit false + exited -> `synchronous`;
- foreground/default or explicit false + running -> `wait_expired`.

Retain the existing handoff-reason aggregation separately for historical compatibility.

**Acceptance:** table-driven unit tests cover every valid combination and unknown/missing
legacy fields.

### Step 1.4 — Join call/result/dispatch and classify non-dispatched errors

Target: 20–30 minutes.

For each in-window `tool_call(tool=run_command)`:

- find its `tool_result`;
- find dispatch or dispatch-error event;
- if result is an error and neither dispatch event exists, count it as
  `not_dispatched_error`;
- aggregate `error_code` when present, else `error_class`;
- never infer an error from a missing counterpart alone.

Track separately:

- result without in-window call;
- dispatch without in-window call;
- call without in-window result.

These are window/legacy/in-flight facts, not necessarily failures.

**Acceptance:** a fixture containing the exact “call before --since, result after --since”
shape does not produce a false logging-loss error.

### Step 1.5 — Add in-window lifecycle linkage coverage

Target: 20–30 minutes.

For successful dispatches report in-window linkage ratios:

```text
dispatch -> tool_result
dispatch -> job_start
dispatch -> owner start timing
synchronous/exited dispatch -> job_exit
```

The renderer must use wording such as `in-window linkage`, not `missing logs`.

For mixed-version fixtures, coverage below 100% is valid.

Use the exact-search telemetry precedent (`dispatches`, `summaries`, `coverage`) as the
style model.

**Acceptance:** old telemetry fixtures and boundary fixtures render without exceptions and
show explicit coverage.

### Step 1.6 — Join automatic handoffs to terminal job evidence

Target: 20–30 minutes.

For `auto_background + state=running` jobs with a terminal `job_exit` in the window:

- record `runtime_s`;
- compare runtime with `bounded_wait_s`;
- classify:
  - would finish within original wait;
  - would reach original wait boundary anyway;
- compute counterfactual initial wait released:

```text
max(0, min(runtime_s, bounded_wait_s) - effective_wait_s)
```

Do not run this calculation when required fields are absent; track analysis coverage.

Label the metric `counterfactual` in code comments and rendered output.

**Acceptance:** unit tests prove both classifications and formula edges.

### Step 1.7 — Join automatic handoffs to `job_status`

Target: 20–30 minutes.

Use `job_status_timing.job_id` and its `call` field, then join that call back to
`tool_call` to recover the ChatGPT base turn even for older timing-event shapes that did not
carry `turn` directly.

Report:

- auto handoff jobs with any status;
- total status calls;
- first status state;
- same-turn / different-turn first status;
- status state-phase time (`state_ms`) distribution/total;
- `waited_s` only where that field exists, with explicit coverage.

Do not substitute `state_ms` for `waited_s`; they are different metrics.

**Acceptance:** mixed-version fixtures with/without `waited_s` do not synthesize values.

### Step 1.8 — Count observable intervening tool work

Target: 20–30 minutes.

For an auto handoff and its first status call in the same base turn:

- use record sequence numbers;
- count intervening `tool_call` records in that turn;
- separately count non-`job_status` tools;
- aggregate tool type (`run_command`, `search_text`, `read_file`, etc.).

This is a journal-observable overlap proxy, not a claim about hidden model reasoning.

**Acceptance:** tests cover zero/one/multiple intervening calls and another-turn noise.

### Step 1.9 — Preserve sufficient timestamp precision for collection lag

Target: 20–30 minutes.

The investigation used raw ISO timestamps with milliseconds. Current `Record` preserves
only day + whole-second clock.

Preferred implementation:

- add an optional additive timestamp field to `Record` (for example `timestamp_text` or
  parsed local datetime);
- teach the plain-record parser to preserve the fractional ISO timestamp;
- leave rich historical records valid when no millisecond timestamp is available;
- do not change existing day/time fields used by historical reports.

Then compute terminal collection lag only when both `job_exit` and terminal status have
reliable timestamps.

Report precision/coverage explicitly.

**Acceptance:** parser compatibility tests cover old untimestamped plain lines,
second-resolution rich lines, and new millisecond plain lines.

### Step 1.10 — Render the workflow section

Target: 20–30 minutes.

Add a compact renderer in the new module or `logstats_render.py`.

Requirements:

- existing output remains present;
- new section separates policy/outcome;
- all counterfactual metrics are labelled;
- all linkage metrics say `in-window`;
- sections with no compatible data are omitted or shown as zero/unknown without failure;
- avoid printing per-call rows by default.

**Acceptance:** golden/sub-string unit tests validate the section without coupling tests to
irrelevant ordering.

### Step 1.11 — Update documentation

Target: 20 minutes.

Update `docs/logging.md` to describe:

- new stats-only workflow analysis;
- the difference between policy and handoff outcome;
- boundary/mixed-version coverage semantics;
- counterfactual wait-release semantics;
- no runtime event change yet.

### Phase 1 dependency/parallel map

After Step 1.1 model names are fixed:

```text
1.2 event index
 |\
 | +--> 1.4 call/result classification
 | +--> 1.5 linkage coverage
 | +--> 1.6 auto terminal analysis
 | +--> 1.7 status join
 | +--> 1.8 intervening work
 |
 +----> 1.9 timestamp preservation

1.3 policy classifier can proceed in parallel with 1.2.
1.10 renderer waits for the metrics it renders.
1.11 docs waits for the final public names.
```

There is no artificial worker/session cap; all ready nodes may run concurrently.

### Phase 1 stop gate

Do not proceed to runtime telemetry until:

- focused tests are green;
- the new workflow section can reproduce the known frozen-window aggregates within
  documented boundary/precision differences;
- stats performance passes the baseline gate.

---

## Phase 2 — Validate the stats-only model against production evidence

**Objective:** prove that Phase 1 improves understanding without relying on new logging.

### Step 2.1 — Build a sanitized lifecycle fixture

Target: 20–30 minutes.

Create a synthetic journal fixture covering:

- default foreground sync;
- default foreground wait expiry;
- auto warm-up finish;
- auto handoff + terminal exit;
- explicit background warm-up finish;
- explicit background handoff;
- explicit false override;
- pre-dispatch coded error;
- pre-dispatch uncoded error;
- owner dispatch error;
- same-turn status;
- later-turn status;
- intervening independent tool call;
- mixed-version records missing newer fields;
- start/end window boundary orphans.

Use synthetic command/policy names. Do not copy production local regexes or commands.

### Step 2.2 — Reproduce frozen-window production aggregates

Target: 20–30 minutes.

Run the new stats analyzer on the frozen window and compare with the investigation's
aggregate reference:

- 4,019 dispatches;
- policy/outcome distribution;
- zero unknown owner/state in stable telemetry;
- 259 automatic handoffs in the frozen window;
- 234 handoffs that would finish within original wait;
- 25 that would reach the original wait boundary;
- approximately 2,321 s counterfactual initial wait released;
- 254 automatic jobs with status;
- 234 first status exited / 20 running;
- same-turn correlation for all analyzable first status calls;
- observable intervening-work counts;
- collection-lag distributions within timestamp precision.

Minor count changes are not acceptable when the window is exactly frozen; differences must
be explained by parser semantics or corrected.

### Step 2.3 — Verify mixed-version/deployment-transition behavior

Target: 20 minutes.

Run stats across a wider 2026-09-22 deployment-transition window and confirm:

- early records without `job_owner_timing` reduce in-window coverage;
- they do not appear as current runtime failures;
- old owner records remain readable;
- no division-by-zero or missing-key failure occurs.

### Step 2.4 — Benchmark stats

Target: 20 minutes.

Run the same frozen-window command three times, discard no run unless there is a documented
external disturbance, and report median/min/max.

Gate:

```text
median <= 11.211 s  # 9.749 * 1.15
```

Also compare absolute delta against 1.0 s.

If the gate fails, profile analyzer CPU before optimizing; do not weaken the metrics based
on speculation.

### Step 2.5 — Run focused regression tests

Target: 20 minutes.

At minimum rerun the 110-test baseline plus the new workflow tests.

### Phase 2 parallel map

Steps 2.1, 2.2, 2.3, and 2.4 can run independently once Phase 1 is complete.
Step 2.5 runs after their fixes converge.

### Phase 2 stop gate

Runtime telemetry work begins only if:

- production aggregates reproduce;
- boundary behavior is explicitly correct;
- stats performance passes;
- focused regression set is green.

---

## Phase 3 — Add the two genuinely missing runtime telemetry signals

**Objective:** add only policy identity and output-shaping cause.

This phase has two mostly independent lanes and should be parallelized aggressively:

```text
Lane A: policy/rule identity
Lane B: output-shaping telemetry
```

They share only final stats/docs/tests integration.

### Lane A — Auto-background policy/rule identity

#### Step 3A.1 — Introduce a match result without changing semantics

Target: 20–30 minutes.

Add a method such as:

```python
match_auto_background(client, command) -> AutoBackgroundMatch | None
```

The result should contain enough internal information to derive a policy/rule fingerprint,
for example:

```text
client prefix
pattern
prefix index / rule index (optional internal fields)
```

For this step **preserve current first-matching-prefix semantics exactly**. Do not fix
prefix ordering in the same commit as telemetry plumbing.

Keep `should_auto_background()` as a small compatibility wrapper if callers/tests still use
it.

#### Step 3A.2 — Define stable fingerprint helpers

Target: 20 minutes.

Requirements:

- `rule_hash` includes both client prefix and pattern;
- `policy_hash` fingerprints the **ordered** effective mapping because ordering is currently
  semantically meaningful;
- use a short SHA-256 prefix consistent with existing `command_hash` practice;
- use unambiguous separators/canonical serialization;
- empty policy has a deterministic fingerprint;
- raw regex text is never emitted by telemetry.

Document the fingerprint contract so future refactors do not silently change IDs.

#### Step 3A.3 — Extend the sparse auto-background event

Target: 20 minutes.

Current event:

```text
run_command_auto_background call client command_hash
```

Add:

```text
policy_hash
rule_hash
```

Do not add full pattern/prefix text.

The event remains one per automatic-policy match and still occurs before owner dispatch,
so a later owner failure can be associated with the rule decision by `call`.

#### Step 3A.4 — Fingerprint effective startup policy

Target: 20 minutes.

Extend:

```text
tool_config tool=run_command
```

with:

```text
auto_background_rules=<total rule count>
auto_background_policy_hash=<hash>
```

Keep `auto_background_clients` for backward compatibility.

Do not use the general `config` record as the machine-readable fingerprint source.

#### Step 3A.5 — Tests for privacy and stability

Target: 20–30 minutes.

Tests must prove:

- same effective ordered policy -> same hash;
- changing a pattern -> different policy/rule hash;
- changing order -> different policy hash under current semantics;
- same regex under different prefix -> different rule hash;
- raw regex text does not appear in `run_command_auto_background`;
- explicit `background=false` does not emit an auto marker;
- auto policy match followed by dispatch failure still emits one match marker.

### Lane B — Sparse output-shaping telemetry

#### Step 3B.1 — Make shaping result explicit

Target: 20–30 minutes.

Refactor the pure shaping logic to return a small structured result, preferably in
`job_output.py`, while preserving output bytes/text exactly.

Candidate internal model:

```text
output
dropped_lines
char_clipped
selected_chars
returned_chars
omitted_chars
```

The existing `clip_head_tail()` public/internal compatibility helper may remain unchanged
and delegate to the new implementation.

#### Step 3B.2 — Preserve exact result behavior

Target: 20 minutes.

Before adding logging, add unit tests proving byte/text equivalence for:

- no shaping;
- `tail_lines` no-op;
- `tail_lines` dropping lines;
- char clip only;
- tail drop + char clip;
- empty output;
- one very long line;
- non-ASCII output (char limit versus byte count).

No MCP output change is allowed in this step.

#### Step 3B.3 — Emit one sparse shaping event

Target: 20 minutes.

Emit only when content was removed.

Recommended event:

```text
event=run_command_output_shaping
call=<call>
job_id=<job>
state=running|exited
reason=tail_lines|char_limit|tail_lines+char_limit
tail_lines=<N-or->
dropped_lines=<n>
char_clipped=true|false
selected_chars=<n>
returned_chars=<n>
omitted_chars=<n>
log_bytes=<full durable bytes at result time>
```

Do not include output content.

#### Step 3B.4 — Add stats classification with legacy coverage

Target: 20–30 minutes.

Join shaping events to `tool_result(truncated=true)` by call/job.
Report:

- reason counts;
- dropped-line distribution/total;
- omitted-character distribution/total;
- `legacy_unclassified` truncated results in mixed-version windows;
- classification coverage.

A `tail_lines` argument by itself must **not** be treated as proof of truncation cause.

#### Step 3B.5 — Tests

Target: 20–30 minutes.

Integration tests must prove:

- no shaping event for an unmodified result;
- tail-only event;
- char-only event;
- combined event;
- running/background partial output can also emit the event;
- event contains only scalar facts;
- stats classify each shape correctly.

### Step 3C — Merge the two telemetry lanes

Target: 20 minutes.

After Lane A and Lane B are independently green:

- merge/rebase both into the working integration branch;
- rerun focused tests;
- run `git diff --check`;
- inspect emitted live/in-memory event examples;
- update `docs/logging.md` inventory and field descriptions;
- update `docs/tools/run_command.md` only for behavior/telemetry facts that belong there.

### Phase 3 stop gate

Proceed only if:

- MCP schemas are unchanged;
- no raw regex/command/output duplication was introduced;
- policy hashes are deterministic;
- shaping output is byte/text-equivalent to baseline;
- mixed-version stats still work.

---

## Phase 4 — Stable error classification and final stats integration

**Objective:** make run-command errors interpretable without parsing human strings.

### Step 4.1 — Code the workdir-not-directory failure

Target: 20 minutes.

Replace the plain `ToolError` in the local workdir directory check with
`CodedToolError`, using a stable code such as:

```text
workdir_not_directory
```

Keep the human message compatible.

Do not conflate it with `path_outside_root`; that code already comes from the shared path
guard.

### Step 4.2 — Verify not-dispatched error reporting

Target: 20 minutes.

The Phase 1 lifecycle analyzer should already classify:

- coded pre-dispatch errors;
- uncoded `ToolError`;
- hidden/unavailable tool errors;
- owner dispatch errors separately.

After the new code, confirm the production/synthetic report can distinguish at least:

```text
path_outside_root
workdir_not_directory
ToolError (uncoded/other)
owner dispatch error class
```

Do not fabricate stable codes for errors owned by FastMCP/visibility unless there is a
separate justified project-wide change.

### Step 4.3 — Consider, but do not automatically add, owner-dispatch error codes

Target: 15–20 minutes review.

`run_command_dispatch_error` already retains the underlying manager exception class.
Production audit found zero such errors in the stable window.

Only add a new stable owner error code if tests or production evidence show that
`error_class=JobManagerError` is insufficient. Otherwise keep scope small.

### Step 4.4 — Update error tests

Target: 20–30 minutes.

Add/adjust tests for:

- path outside root;
- workdir nonexistent/not a directory;
- manager unavailable;
- call/result with no dispatch;
- dispatch-error correlation to `tool_result`;
- error code rendering.

### Step 4.5 — Documentation and final stats presentation

Target: 20 minutes.

Ensure documentation explicitly differentiates:

```text
not dispatched / rejected before owner attempt
owner dispatch failure
command successfully started but exits non-zero
command stopped/signalled
```

A command exit code != 0 is a normal command outcome, not a `run_command` tool error.

### Phase 4 stop gate

- focused and full tests green;
- stats error section does not mislabel non-zero command exits as tool errors;
- stable codes appear without parsing human error text.

### Phase 4.5 — Phase-5 evidence readiness hardening (2026-09-25)

A live review before Phase 5 found four non-policy gaps. The hardening keeps execution
semantics unchanged while adding:

- behavior identity (`policy_hash + semantics_version + auto_warmup_s`);
- detailed behavior/per-rule workflow stats and marker/dispatch coverage;
- optional private full-command evidence for auto matches, repository-default disabled;
- match-span offsets and best-effort evidence persistence.

This phase exists so the scheduled Phase-5 review can perform both quantitative analysis
and representative false-positive classification without relying on the short per-job
retention window.

Validation: focused readiness tests **72 passed**; full suite **1200 passed, 3 skipped** plus
**2** ordinary-process tests; repository-wide pre-commit **PASS**.

Detailed Phase-5 design remains:
`docs/run-command-observability-phase5-design-2026-09-24.md`.

---

## Phase 5 — Evidence-driven policy evaluation and tuning

Detailed Phase-5 design and cold-start execution plan:
`docs/run-command-observability-phase5-design-2026-09-24.md`.

**Objective:** use the now-correct telemetry to decide whether policy behavior should
change. This phase must not be bundled blindly into the observability implementation.

### Step 5.1 — Gather post-telemetry rule-level evidence

No background/automatic work is implied by this plan. When this phase is executed later,
run `binnacle stats` over a representative real-use window after rule hashes have been
present long enough to produce useful samples.

For each rule hash, collect:

- matches;
- warm-up finishes;
- handoffs;
- terminal runtime distribution;
- would-finish-within-original-wait count;
- would-timeout-anyway count;
- status follow-up count;
- first-status state;
- observable intervening tool work;
- collection lag where available.

Do not require a fixed calendar duration; use sufficient sample size and workload diversity.
A rule with very few matches should be marked insufficient evidence rather than ranked.

### Step 5.2 — Review false-positive candidates

Use high warm-up-finish rates and very short runtime distributions as **signals**, not proof.
Then inspect representative local commands outside committed repository artifacts.

Classify causes such as:

- real execution of the intended long tool;
- token only in path/config text;
- token only inside heredoc/source content;
- token only in a search/process-inspection expression;
- composite command where the long tool really is executed later.

Do not commit local regexes or command samples containing deployment-specific preferences.

### Step 5.3 — Fix client-prefix semantics explicitly

The preferred generic policy is to align with blocking-wall configuration:

> choose the **longest matching client prefix**, then evaluate only that prefix's rules.

Before changing:

- add tests capturing current overlapping-prefix behavior;
- add tests for the desired longest-prefix behavior;
- document that a more-specific prefix overrides a broad prefix;
- confirm current single-prefix production configuration is behaviorally unchanged.

This should be a distinct commit from the Phase 3 telemetry refactor so behavior change is
reviewable.

### Step 5.4 — Evaluate warm-up thresholds without changing explicit background

Use runtime evidence to compare candidate automatic warm-up thresholds.
The investigation's historical what-if showed that 1/2/3/5/10 s produce materially
different handoff rates.

Important invariant:

- `jobs.warmup_s` is currently shared by explicit background and auto-background.

Therefore **do not** change that shared value based only on auto-policy evidence.

Decision options:

1. retain the shared 1-second warm-up; or
2. if data strongly justifies it, introduce a separate
   `run_command.auto_background_warmup_s` whose default preserves current behavior.

A new setting requires its own config/startup telemetry/tests/docs and must not be added
speculatively.

### Step 5.5 — Tune deployment-local regexes outside the repository

If per-rule evidence identifies false positives, update only the deployment's local
configuration. Repository defaults remain empty.

Validation after a local rule change:

- config loads successfully;
- server effective config logs a changed policy hash;
- intended command shapes still match;
- known false-positive command shapes no longer match;
- explicit `background=false` still overrides;
- no repository file records the private local pattern text.

### Step 5.6 — Compare before/after policy behavior

Use policy hash as the segmentation key. Compare:

- match rate;
- warm-up-finish rate;
- handoff rate;
- counterfactual original-wait classification;
- status-call burden;
- observable intervening work;
- collection lag;
- wait-expired foreground calls.

Do not report a policy as “better” based on a single metric. The decision should balance:

- scheduler control;
- extra tool calls;
- time to final result;
- false-positive rate;
- simplicity/maintainability.

### Phase 5 completion gate

The phase is complete only when the selected policy behavior is documented with before/after
aggregate evidence and local preference changes remain outside repository defaults.

---

## 6. Detailed file-change map

### Phase 1 likely changes

```text
src/binnacle/logstats_models.py
src/binnacle/logstats.py
src/binnacle/logstats_render.py
src/binnacle/logstats_run_command.py        # new
src/binnacle/logstats.py parser timestamp preservation (if chosen)
tests/unit/core/test_logstats_run_command.py # new
tests/unit/core/test_logstats.py
docs/logging.md
```

### Phase 3 Lane A likely changes

```text
src/binnacle/config.py
src/binnacle/run_command_telemetry.py
src/binnacle/server.py
src/binnacle/tools/run_command.py
 tests/unit/core/test_config_loading.py
 tests/integration/test_logging.py
 tests/unit/core/test_logstats_run_command.py
 docs/logging.md
 docs/tools/run_command.md
```

### Phase 3 Lane B likely changes

```text
src/binnacle/job_output.py
src/binnacle/tools/run_command.py
src/binnacle/logstats_run_command.py
 tests/integration/test_jobs.py
 tests/integration/test_logging.py
 tests/unit/core/test_logstats_run_command.py
 docs/logging.md
```

### Phase 4 likely changes

```text
src/binnacle/tools/run_command.py
src/binnacle/logstats_run_command.py
 tests/integration/test_jobs.py
 tests/integration/test_logging.py
 tests/unit/tools/test_telemetry_error_codes.py
 tests/unit/core/test_logstats_run_command.py
 docs/logging.md
```

### Phase 5 likely repository changes

Only if evidence justifies behavior changes:

```text
src/binnacle/config.py
possibly src/binnacle/run_command_telemetry.py
possibly src/binnacle/server.py
 tests/unit/core/test_config_loading.py
 tests/integration/test_logging.py
 docs/tools/run_command.md
 docs/logging.md
```

Deployment-local regex changes are **not** repository file changes.

## 7. Test strategy by layer

### Pure/unit tests

Cover:

- policy-mode classifier;
- outcome classifier;
- rule/policy fingerprint determinism;
- longest-prefix semantics (Phase 5 only);
- output-shaping result model;
- counterfactual wait formula;
- percentile/coverage behavior;
- old/missing fields;
- parser timestamp preservation.

### Integration tests

Cover:

- middleware client identity -> auto policy decision;
- explicit false override;
- manager-backed sync/handoff;
- dispatch error;
- event correlation IDs;
- sparse shaping events;
- stable workdir error code;
- no raw pattern/output leakage.

### Production-data validation

Use aggregate-only comparison against the frozen window. Do not build tests that depend on
the live host journal.

### Full validation

Before merge:

```text
focused telemetry/config/job tests
full pytest suite
pre-commit / repository quality gates
GitHub CI
```

## 8. Documentation strategy

Update documentation in the same phase as the behavior it describes.

`docs/logging.md` is authoritative for:

- event inventory;
- fields;
- correlation chain;
- stats interpretation;
- mixed-version behavior.

`docs/tools/run_command.md` is authoritative for:

- user-visible tool contract;
- wait/background semantics;
- deployment-local policy semantics;
- durable ownership behavior.

The new investigation and plan documents remain historical rationale/evidence and should not
replace the operational docs.

## 9. Rollback strategy

Each phase should be independently revertible.

- Phase 1/2: stats-only; rollback has no runtime effect.
- Phase 3A: hashes are additive log fields; old readers ignore them.
- Phase 3B: sparse event is additive; output behavior must remain unchanged.
- Phase 4: coded error is still a `ToolError` subclass; client behavior/message remains
  compatible.
- Phase 5: prefix/warm-up/pattern behavior changes must be separate commits so they can be
  reverted without removing observability.

Do not combine all five phases into one large commit.

## 10. Recommended commit structure

A reasonable sequence is:

```text
1. stats: add run_command workflow lifecycle analysis
2. stats: validate run_command production workflow metrics
3. telemetry: fingerprint auto-background policy matches
4. telemetry: classify run_command output shaping
5. telemetry: code run_command workdir failures
6. policy: make auto-background client prefix selection deterministic   # Phase 5, if approved
7. docs: record final run_command observability validation              # or fold docs per phase
```

The exact number can vary, but behavior changes must not be hidden inside analytics commits.

## 11. Completion definition

The observability project (Phases 1–4) is done when:

1. `binnacle stats` separates policy selection from execution outcome;
2. it reports run-command call/dispatch/error/linkage coverage without false boundary alarms;
3. it quantifies automatic handoff benefit and follow-up cost from existing logs;
4. it correlates automatic handoffs to status calls and observable same-turn work;
5. startup telemetry fingerprints the effective automatic policy without exposing regexes;
6. each automatic match records a stable rule/policy ID;
7. truncated run-command results have a sparse, classified shaping event;
8. local invalid-workdir failures have a stable error code;
9. MCP schemas remain unchanged;
10. historical/mixed-version journals still parse;
11. stats performance stays within the gate;
12. focused/full tests and CI pass;
13. operational docs match the shipped implementation.

Phase 5 is intentionally a separate policy-quality project gate. Observability should be
finished first so any later tuning is based on evidence rather than guesswork.
