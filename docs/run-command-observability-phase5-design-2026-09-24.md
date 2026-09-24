# run_command Phase 5 evidence-driven policy design and implementation plan — 2026-09-24

Status: design complete; implementation intentionally gated on post-deployment production evidence.

Canonical path:

```text
~/Projects/binnacle/docs/run-command-observability-phase5-design-2026-09-24.md
```

Deployment baseline:

- observability Phases 1–4 merged to `master` and `proof-of-concept` at `55e96c3`;
- `binnacle-mcp.service` restarted with the new telemetry at **2026-09-24 23:32 AEST**;
- startup telemetry recorded `auto_background_rules=5` and
  `auto_background_policy_hash=637d1b4f98dc`;
- a one-shot review is scheduled for **2026-10-01 23:32 AEST**, seven days after deployment;
- Phase 5 must not change policy before that review unless a correctness defect appears.

## 0. Phase-5 readiness hardening — 2026-09-25

A live-readiness review after Phases 1–4 exposed four evidence/reporting gaps that are fixed
before Phase 5 policy work begins:

1. detailed per-rule metrics were available only through ad-hoc raw-journal joins;
2. workflow stats did not segment different policy/behavior versions inside one window;
3. full command evidence disappeared rapidly because `tool_call.args` is clipped and the
   per-job spool retains only the newest jobs;
4. `policy_hash` fingerprinted regex configuration but not matching-semantics version or
   automatic warm-up.

The readiness hardening adds no policy change. Matching regexes, prefix semantics, warm-up,
explicit-background behavior, wait limits, durable ownership, and MCP schemas remain
unchanged.

New evidence identity:

```text
policy_hash    = ordered client-prefix/regex configuration
behavior_hash  = policy configuration + semantics_version + actual auto_warmup_s
rule_hash      = one (client_prefix, regex) rule
```

`run_command_auto_background` also records `match_start` / `match_end` scalar offsets.
For qualitative false-positive review, deployments may opt into a private full-command
evidence store. Repository default is disabled; the Phase-5 development host enables a
bounded retention window locally. The evidence store is outside the journal and MCP
response, mode 0700/0600, and records only automatic-policy matches.

`binnacle stats` now renders behavior-level and behavior-scoped rule-level runtime,
counterfactual, follow-up, overlap, and collection-lag metrics, plus marker/dispatch linkage
coverage. Startup `tool_config` records behavior identity even when a behavior receives zero
matches.

Validation before deployment:

- focused readiness suite: **72 passed**;
- supported two-lane full suite: **1200 passed, 3 skipped** plus **2** ordinary-process
  tests, wrapper wall **34.00 s** at seed 12345;
- repository-wide `pre-commit run --all-files`: **PASS**;
- frozen large-window `binnacle stats` median after detailed grouping: **10.508 s**, about
  0.08 s above the prior 10.432 s Phase-1/2 measurement.

After this hardening is deployed, the clean Phase-5 observation window should start at the
hardening service restart, not at the older 2026-09-24 23:32 deployment.

Related documents:

- `docs/run-command-observability-investigation-2026-09-24.md`;
- `docs/run-command-observability-implementation-plan-2026-09-24.md`;
- `docs/logging.md`;
- `docs/tools/run_command.md`.

## 1. Purpose

Phase 5 is not another observability phase. Phases 1–4 established enough evidence to
separate policy selection, runtime outcome, follow-up cost, rule identity, output shaping,
and pre-dispatch failures. Phase 5 uses that evidence to decide whether the automatic
background policy itself should change.

The target is a policy that:

1. returns control early for genuinely long commands;
2. avoids unnecessary background handoff for short commands;
3. avoids false matches where a configured token is merely mentioned rather than executed;
4. keeps explicit `background=true` and `background=false` semantics predictable;
5. keeps deployment-specific preferences outside repository defaults;
6. remains simple enough for an AI agent to reason about without hidden shell heuristics.

The phase is successful only if a change is justified by real post-deployment measurements
and the before/after evidence is preserved.

## 2. Current behavior at Phase 5 entry

### 2.1 Automatic policy matching

`RunCommandSettings` maps client-name prefixes to ordered regex tuples.

Current generic semantics are effectively:

```python
for prefix, patterns in auto_background_patterns.items():
    if client.startswith(prefix):
        for pattern in patterns:
            if re.search(pattern, command):
                return match
        return None
```

Important consequences:

- the first matching client prefix wins;
- later, more-specific matching prefixes are ignored;
- regexes run over the entire shell command string;
- explicit `background=false` disables automatic selection;
- explicit `background=true` uses the shared background warm-up;
- automatic matches also use the same shared `jobs.warmup_s` today.

The repository default policy remains empty. The running deployment has local rules in the
user configuration; their raw text is intentionally not copied into this document.

### 2.2 New Phase-3 evidence

Every automatic match records:

```text
policy_hash=<12hex>
behavior_hash=<12hex>
semantics_version=<n>
auto_warmup_s=<seconds>
rule_hash=<12hex>
match_start=<character offset>
match_end=<character offset>
```

The startup `tool_config tool=run_command` additionally records the automatic client/rule
counts, policy hash, behavior hash, semantics version, effective automatic warm-up, and
private evidence-retention configuration.

`policy_hash` identifies the ordered regex configuration. `behavior_hash` is the primary
before/after segmentation key because it also covers semantics version and automatic
warm-up. `rule_hash` remains the per-rule identity. Raw regex text is not logged.

### 2.3 Historical pre-telemetry evidence

The investigation before deployment observed 432 automatic-policy matches with terminal
runtime evidence:

| Current 1 s warm-up outcome | Count |
| --- | ---: |
| finished in warm-up | 172 |
| handed off | 260 |
| handed off but would finish inside original wait | 235 |
| would hit original wait boundary anyway | 25 |

Runtime distribution was approximately:

| Metric | Runtime |
| --- | ---: |
| p50 | 1.52 s |
| p75 | 3.24 s |
| p90 | 17.72 s |
| p95 | 45.71 s |
| max | 203.88 s |

The historical what-if analysis was:

| Auto warm-up | Inline | Handoff | Would finish inside original wait | Would timeout anyway |
| ---: | ---: | ---: | ---: | ---: |
| 1 s | 172 | 260 | 235 | 25 |
| 2 s | 246 | 186 | 161 | 25 |
| 3 s | 317 | 115 | 90 | 25 |
| 5 s | 349 | 83 | 58 | 25 |
| 10 s | 370 | 62 | 37 | 25 |

This table is context, not the Phase-5 decision dataset. It predates `rule_hash` and cannot
reliably distinguish good rule matches from false-positive matches.

## 3. Non-goals

Phase 5 must not:

- add a shell parser merely to decide whether a token is really executed;
- move deployment-local patterns into repository defaults;
- log raw regex text, full command copies, stdin, or command output for analytics;
- change explicit `background=true` behavior while tuning automatic behavior;
- reduce the maximum foreground wait merely to make metrics look better;
- treat one week as automatically sufficient evidence for every rule;
- rank rules using only one metric such as warm-up-finish rate;
- change MCP response schemas for analytics;
- introduce high-frequency sampling or resource accounting;
- interpret a command non-zero exit as a `run_command` tool failure.

## 4. Phase 5 evidence window

### 4.1 Primary observation window

Primary start: **2026-09-24 23:32 AEST**.

Primary first review: **2026-10-01 23:32 AEST**.

The scheduled analysis must query from the deployment start, not “last seven days” relative
to an arbitrary later execution time.

### 4.2 Segmentation key

Never aggregate across different effective policies without identifying the boundary.

Primary segmentation key:

```text
auto_background_behavior_hash
```

Secondary configuration fingerprint:

```text
auto_background_policy_hash
```

Per-rule key is `rule_hash`, scoped by behavior hash. The same rule hash observed under two
behavior hashes is reported as two distinct rule groups.

If the behavior hash changes inside the observation window:

1. split the report by policy hash;
2. record the startup timestamp and policy hash for each behavior hash;
3. never pool outcome metrics across different behavior hashes, even when the rule hash is
   identical;
4. prefer separate before/after rows.

### 4.3 Required raw-event coverage

For a post-deployment Phase-5 dataset to be actionable, it should contain:

- `tool_config tool=run_command` with policy hash and rule count;
- `run_command_auto_background` with `rule_hash`;
- `run_command_dispatch`;
- `job_exit` for terminal runtime evidence where applicable;
- `job_status_timing` for follow-up behavior;
- `tool_call` with turn identifiers where available.

If a field is absent because of a mixed-version window, report coverage and exclude that
metric from decision-making rather than synthesizing it.

### 4.4 Private command evidence

Quantitative metrics come from journal telemetry. Qualitative false-positive classification
uses the private evidence store when enabled:

```text
~/.local/state/binnacle/run-command-evidence/YYYY-MM-DD.jsonl
```

Each row contains the full auto-matched command, call/command hash, policy/behavior/rule
identity, semantics version, automatic warm-up, and exact match span. It does not enter the
normal journal or MCP response. Evidence retention is configured by
`run_command.auto_background_evidence_retention_days` and is disabled by repository default.

If private evidence coverage is incomplete, do not infer command-shape classifications from
a clipped `tool_call.args` preview. Mark those samples unavailable.

## 5. Evidence sufficiency model

Sample count alone is not enough, but a minimum sample floor prevents decisions from being
driven by anecdotes.

### 5.1 Per-rule evidence tiers

| Rule sample | Classification | Allowed conclusion |
| ---: | --- | --- |
| 0–4 matches | insufficient | no rule-specific change |
| 5–19 matches | exploratory | identify hypotheses only |
| 20+ matches | actionable candidate | may consider rule change if outcome evidence is coherent |
| 50+ matches | strong operational sample | suitable for before/after policy comparison |

A rule with 20 matches but only one unique command shape is still weak evidence. Workload
diversity matters.

### 5.2 Workload diversity check

For a rule to be considered actionable, inspect a bounded representative sample of local
command shapes and confirm at least two of:

- different repositories/worktrees;
- different command prefixes/wrappers;
- different task types;
- different times/turns;
- both short and long observed outcomes.

Do not commit representative raw commands into the repository. Record only aggregate
classification counts in repository documentation.

### 5.3 Outcome sufficiency

A warm-up threshold decision requires enough handed-off jobs with terminal runtime evidence.

Practical gate:

- at least 20 terminal automatic matches overall;
- at least 10 actual handoffs for any threshold comparison;
- terminal-evidence coverage at least 90% of automatic handoffs, or the missing portion must
  be explained.

If these conditions are not met after seven days, extend observation rather than forcing a
decision.

## 6. Metrics required by the scheduled Phase-5 review

### 6.1 Policy-level metrics

For each `behavior_hash` (including its `policy_hash`, semantics version and warm-up metadata):

- observation start/end;
- startup count;
- automatic match count;
- warm-up-finished count/rate;
- handoff count/rate;
- terminal-evidence coverage;
- runtime p50/p75/p90/p95/max;
- would-finish-within-original-wait count/rate;
- would-timeout-anyway count/rate;
- counterfactual initial foreground wait released;
- automatic jobs with any `job_status`;
- total `job_status` calls;
- first status exited/running;
- same-turn first-status count;
- jobs with intervening non-status tool work;
- terminal collection-lag distribution;
- foreground `wait_expired` count outside automatic policy;
- pre-dispatch error counts/codes;
- owner-dispatch error counts/classes.

### 6.2 Rule-level metrics

For each `rule_hash`:

- matches;
- warm-up finishes;
- handoffs;
- handoff rate;
- terminal-evidence coverage;
- runtime p50/p90/max when sample permits;
- would-finish-inside-original-wait count;
- would-timeout-anyway count;
- first-status already-exited count;
- observable intervening-work count;
- representative command-shape classification performed locally.

### 6.3 Output-shaping metrics

Report:

- `tail_lines` shaping;
- `char_limit` shaping;
- combined shaping;
- `legacy_unclassified`;
- dropped-line total;
- omitted-character total.

After the deployment, new results should become classifiable. Persistent new
`legacy_unclassified` records would indicate a telemetry gap or mixed binary.

## 7. False-positive classification methodology

A high warm-up-finish rate is a signal, not proof of a bad regex.

For selected rule hashes, inspect representative local commands and classify each into one
of these buckets.

### 7.1 Intended execution

The rule token corresponds to the actual long-running tool/process being invoked.

Conceptual examples:

- direct command execution;
- wrapper/environment prefix followed by the intended command;
- a composite shell command that genuinely executes the intended tool later.

### 7.2 Path/config mention

The token appears only in a path, cache directory, config filename, or environment data.
This is a likely false positive.

### 7.3 Source/heredoc mention

The token appears only inside source code being written, a heredoc, a generated test, or
quoted content. This is a likely false positive.

### 7.4 Search/inspection mention

The token appears only in search text, process inspection, log analysis, or configuration
inspection. This is a likely false positive.

### 7.5 Ambiguous composite

The command text contains both inspection and eventual execution or is too complex to
classify safely.

Do not fix ambiguous cases with increasingly complex generic shell heuristics. Prefer a
simple local rule or leave the existing behavior.

## 8. Decision matrix

### 8.1 Keep a rule unchanged

Keep a deployment-local rule when:

- sample is sufficient;
- most matches represent intended execution;
- handoff rate is material;
- long-tail runtime exists;
- extra `job_status` burden is acceptable;
- false-positive rate is low.

### 8.2 Narrow a deployment-local rule

Narrow only local configuration when representative review shows path/source/search false
positives and the generic repository semantics are not the cause.

The change belongs only in:

```text
~/.config/binnacle/config.toml
```

It must not be committed.

### 8.3 Remove a deployment-local rule

Consider removal when:

- it has enough samples;
- almost all matches finish inside warm-up;
- representative commands show the rule is mostly incidental mentions;
- intended long use is rare or absent;
- default foreground behavior is acceptable.

### 8.4 Add a new deployment-local rule

A new rule candidate should have:

- repeated foreground `wait_expired` occurrences;
- a recognizable stable command family;
- meaningful blocking duration;
- a clear deployment-local use case.

Prefer local configuration over repository defaults.

### 8.5 Change generic prefix semantics

Preferred repository-level target:

> choose the longest matching client prefix, then evaluate only that prefix’s rules.

This aligns with `JobsSettings.blocking_wall_budget_for_client()`.

### 8.6 Change automatic warm-up

Only consider if post-deployment evidence still shows a large short-job handoff burden.

Do not change shared `jobs.warmup_s`.

If a different threshold is justified, introduce an automatic-policy-specific setting whose
default preserves current behavior.

## 9. Longest-prefix semantic design

### 9.1 Current defect

Current behavior is insertion-order dependent for overlapping prefixes. A broader prefix can
shadow a more-specific prefix even when the broad prefix has no matching rule.

### 9.2 Target behavior

For a client:

1. collect all configured prefixes for which `client.startswith(prefix)`;
2. choose the longest prefix;
3. preserve configured rule order within that prefix;
4. return the first matching rule;
5. do not fall back to a broader prefix when the selected prefix exists but none of its
   rules match.

The no-broad-fallback behavior keeps client-specific configuration authoritative.

### 9.3 Compatibility

Current production has one prefix, so longest-prefix semantics should not change current
production behavior.

### 9.4 Proposed implementation

```python
matches = [prefix for prefix in auto_background_patterns if client.startswith(prefix)]
prefix = max(matches, key=len, default=None)
if prefix is None:
    return None

for pattern in auto_background_patterns[prefix]:
    if re.search(pattern, command):
        return AutoBackgroundMatch(prefix, pattern)
return None
```

Do not alter rule fingerprint construction.

## 10. Automatic warm-up design

### 10.1 Current coupling

`jobs.warmup_s` currently controls both explicit `background=true` and automatic-background
policy matches. The explicit background contract should remain fast-returning.

### 10.2 No-change option

If the 1-second automatic warm-up is acceptable, retain the shared value and add no new
configuration. This is preferred when evidence is inconclusive.

### 10.3 Separate-setting option

Only if evidence justifies it, add:

```toml
[run_command]
auto_background_warmup_s = 1.0
```

The default must be 1.0 so upgrades preserve behavior.

### 10.4 Dispatch behavior with separate setting

| Case | Effective wait source |
| --- | --- |
| explicit `background=true` | `jobs.warmup_s` |
| automatic rule matched | `run_command.auto_background_warmup_s` |
| explicit `background=false` | normal bounded foreground wait |
| no automatic match | normal bounded foreground wait |

### 10.5 Startup telemetry

If introduced, `tool_config tool=run_command` must record
`auto_background_warmup_s=<value>`. The jobs config continues to report `warmup_s` for
explicit background.

## 11. Warm-up candidate evaluation

Replay candidate thresholds from the post-deployment runtime sample without changing
production:

```text
1 s
2 s
3 s
5 s
```

For each threshold compute:

- predicted inline count;
- predicted handoff count;
- predicted would-finish-inside-original-wait handoffs;
- predicted would-timeout-anyway count;
- predicted initial foreground wait released;
- handoff reduction relative to current;
- extra foreground waiting relative to current.

A threshold is not preferred merely because it minimizes handoffs.

## 12. Warm-up decision criteria

Use this order:

1. correctness and explicit-background isolation;
2. false-positive rule quality;
3. reduction in unnecessary handoffs;
4. extra foreground wait introduced;
5. observable independent work lost by waiting longer;
6. simplicity.

Rule cleanup should happen before warm-up tuning when false positives materially explain
short runtimes.

## 13. Foreground wait-expired candidate analysis

Review commands that remain default foreground and hit `wait_expired`.

For each recurring family:

- count occurrences;
- runtime distribution;
- repositories/contexts;
- whether the family is stable enough to identify locally;
- whether an existing auto rule should already have matched;
- whether it represents a new local rule candidate.

Do not use first shell word alone when wrappers hide the real command family.

## 14. Repository versus deployment boundaries

### 14.1 Repository-owned behavior

May include:

- longest-prefix semantics;
- optional separate automatic warm-up setting;
- generic config validation;
- telemetry fields;
- stats/analysis support;
- tests and public documentation.

### 14.2 Deployment-owned behavior

Must remain local:

- actual automatic regex text;
- selected command families;
- local threshold override if eventually supported.

### 14.3 Evidence artifacts

Repository docs may record policy hashes, rule hashes, aggregate counts/rates/distributions,
and anonymized classification totals. Do not record raw local regexes or sensitive command
text.

## 15. Phase 5 implementation worktree strategy

When the scheduled evidence review permits implementation:

1. update local `master` and `proof-of-concept`;
2. create `~/Projects/binnacle-run-command-phase5`;
3. create `feature/run-command-policy-phase5`;
4. append the evidence summary to this document before source changes;
5. split independent changes into worktrees where useful.

Recommended independent lanes:

```text
Lane A: longest-prefix semantics
Lane B: automatic warm-up setting, only if approved by evidence
Lane C: stats/reporting refinements found by the seven-day review
```

Local regex tuning is not a repository lane.

## 16. Implementation steps

Each step is scoped to roughly 20–30 minutes for a cold-start AI agent.

### Step 5.0 — Freeze the evidence window

1. query startup records at/after 2026-09-24 23:32 AEST;
2. identify every policy hash;
3. confirm review end timestamp;
4. save aggregate evidence, not raw commands.

Stop if telemetry coverage is broken or the expected build was not active.

### Step 5.1 — Produce policy-level report

Compute Section 6.1 and reconcile `binnacle stats` with raw journal counts for:

- `run_command_auto_background`;
- `run_command_dispatch`;
- startup `tool_config`.

Any boundary mismatch must be explained.

### Step 5.2 — Produce per-rule report

For every `rule_hash` calculate match/handoff/runtime/follow-up metrics and classify its
evidence tier from Section 5.

Do not change policy yet.

### Step 5.3 — Inspect representative local command shapes

For actionable/high-interest behavior-scoped rule groups:

1. load bounded private evidence rows for that behavior/rule;
2. use `match_start` / `match_end` to locate the trigger inside the full command;
3. classify using Section 7;
4. record aggregate category counts only;
5. identify candidate false-positive rules.

Do not commit raw commands or local regex text. If private evidence is unavailable for a
sample, mark it unavailable rather than reconstructing it from clipped journal arguments.

### Step 5.4 — Review foreground wait-expired families

Find recurring non-auto commands that hit the foreground wait limit and produce candidate
local rule families, if any.

Do not add rules yet.

### Step 5.5 — Decide longest-prefix change

Confirm:

- production still has one prefix;
- current overlapping-prefix behavior;
- blocking-wall longest-prefix precedent.

Expected decision is to implement longest-prefix unless evidence reveals a compatibility
concern.

### Step 5.6 — Implement longest-prefix semantics

Likely files:

```text
src/binnacle/config.py
tests/unit/core/test_config_loading.py
tests/unit/core/test_run_command_telemetry.py
docs/tools/run_command.md
docs/logging.md
```

Implementation must increment `AUTO_BACKGROUND_SEMANTICS_VERSION` because longest-prefix
selection changes generic matching semantics even when the regex mapping is unchanged.

Tests must cover:

- no client / no prefix;
- broad-only behavior;
- broad + specific -> specific wins;
- specific exists but rule does not match -> no broad fallback;
- order reversal does not change result;
- current single-prefix deployment unchanged.

Commit separately.

### Step 5.7 — Decide whether separate auto warm-up is justified

Possible outcomes:

1. **KEEP CURRENT**;
2. **EXTEND OBSERVATION**;
3. **IMPLEMENT** separate setting.

Do not alter shared `jobs.warmup_s`.

### Step 5.8 — Add automatic warm-up setting if approved

Likely files:

```text
src/binnacle/config.py
src/binnacle/run_command_telemetry.py
src/binnacle/server.py
tests/unit/core/test_config_loading.py
tests/unit/core/test_run_command_telemetry.py
tests/integration/test_run_command_policy_telemetry.py
docs/tools/run_command.md
docs/logging.md
```

Requirements:

- default 1.0 s;
- explicit background still uses `jobs.warmup_s`;
- automatic policy uses the new setting;
- explicit false still overrides;
- startup config logs both values;
- old config files remain valid;
- no MCP schema change.

### Step 5.9 — Validate automatic warm-up implementation

Test matrix:

| Background arg | Rule match | Expected wait source |
| --- | --- | --- |
| omitted | no | foreground bounded wait |
| omitted | yes | auto-specific warm-up |
| false | yes | foreground bounded wait |
| true | yes/no | explicit `jobs.warmup_s` |

Also test manager/embedded owner, fast/slow command, dispatch failure, and config bounds.

### Step 5.10 — Tune local regexes, if justified

Outside repository history:

1. back up `~/.config/binnacle/config.toml`;
2. edit only the relevant pattern;
3. validate config loading;
4. restart `binnacle-mcp.service`;
5. confirm new policy hash;
6. probe intended matches;
7. probe known false positives;
8. preserve explicit false override;
9. do not restart `binnacle-jobs.service` unless independently required.

### Step 5.11 — Add new local rule candidates, if justified

Only add a recurring `wait_expired` family when evidence is repeated, the family is stable,
and the rule can remain simple and deployment-local.

### Step 5.12 — Full regression

```bash
uv run python scripts/run_test_suite.py --workers 4 --seed 12345
uv run pre-commit run --all-files
```

Any failure blocks deployment.

### Step 5.13 — Deploy repository behavior changes

Merge approved changes to `master` and `proof-of-concept`, push both refs, and restart only
`binnacle-mcp.service` unless the job-manager binary independently requires a restart and no
active jobs exist.

Verify active service, expected revision, startup config, expected policy hash, and no
unexpected manager restart.

### Step 5.14 — Post-change observation

Collect a second representative window under the new policy hash. Do not declare success
immediately after deployment.

## 17. Before/after comparison contract

| Metric | Before | After | Interpretation |
| --- | ---: | ---: | --- |
| auto matches | | | workload-normalized context required |
| warm-up finish rate | | | lower may mean fewer short matches |
| handoff rate | | | neither inherently good nor bad |
| would-finish-inside-original-wait rate | | | short-handoff burden |
| would-timeout-anyway count | | | genuinely long work |
| status calls / handed-off job | | | follow-up burden |
| first status already exited rate | | | handoff may be too early |
| intervening-work rate | | | observable scheduling value |
| collection lag p50/p90 | | | result availability cost |
| foreground wait-expired count | | | uncovered long commands |
| pre-dispatch errors | | | should not regress |
| owner dispatch errors | | | should remain near zero |

Do not compare raw counts across materially different workload volumes without explaining the
difference.

## 18. Decision examples

### Example A — Short false-positive rule

Evidence: 40 matches, 35 finish inside 1 s, representative review shows many search/path
mentions, and almost no long-tail runtime.

Decision: narrow local regex first; do not lengthen global automatic warm-up to hide it.

### Example B — Real long-running rule

Evidence: 50 matches, 45 hand off, p90 runtime 40 s, and follow-up often occurs after
intervening work.

Decision: keep rule; 1 s warm-up may be valuable.

### Example C — Mostly 1–3 s intended jobs

Evidence: genuine matches, many handoffs at 1 s, first status often already exited, and
little intervening work.

Decision: consider a longer auto-specific warm-up; do not alter explicit background.

### Example D — Rare rule

Evidence: 3 matches in seven days.

Decision: insufficient evidence; leave unchanged.

## 19. Error and safety gates

Stop policy deployment if any of these appear:

- owner-dispatch errors begin appearing;
- automatic rules affect explicit `background=false` unexpectedly;
- explicit background latency changes unintentionally;
- raw regex text leaks into telemetry;
- MCP result schema changes unintentionally;
- deployment would interrupt current running jobs;
- stable-window linkage coverage drops unexpectedly;
- policy hash changes without intentional config/source change.

## 20. Rollback plan

### 20.1 Longest-prefix change

Revert the dedicated semantics commit and restart MCP. Policy configuration need not change.

### 20.2 Separate auto warm-up

Set local auto warm-up back to 1.0 s or revert the setting implementation. Explicit
background remains isolated.

### 20.3 Local regex change

Restore backed-up local config, restart MCP, and verify the previous policy hash returns.

## 21. Documentation requirements

After implementation update:

- `docs/tools/run_command.md`;
- `docs/logging.md`;
- this Phase-5 document with evidence and decisions;
- parent implementation-plan status.

Do not overwrite pre-change evidence; append dated before/after sections.

## 22. Commit strategy

Preferred sequence when applicable:

```text
policy: make run-command client prefix selection longest-match
policy: add separate automatic-background warm-up
docs: record Phase 5 policy evidence
```

Local regex tuning produces no repository commit.

## 23. Phase 5 completion criteria

Phase 5 is complete only when:

1. the post-deployment window has been analyzed by policy and rule hash;
2. every changed rule/setting has enough evidence or is explicitly marked insufficient;
3. false positives were classified using representative local commands;
4. longest-prefix semantics is explicitly decided and documented;
5. any automatic warm-up change is isolated from explicit background behavior;
6. local regex preferences remain outside repository history;
7. full suite passes;
8. repository-wide pre-commit passes;
9. both `master` and `proof-of-concept` contain approved repository changes;
10. MCP service is restarted and verified;
11. a post-change policy-hash window is collected;
12. before/after aggregate evidence is recorded;
13. no MCP schema, durable ownership, or explicit background contract regressed.

If the seven-day sample is insufficient, the correct state is **EXTEND OBSERVATION**, not a
forced policy change.

## 24. First scheduled review checklist

The review scheduled for 2026-10-01 23:32 AEST should answer, in order:

1. Did the expected behavior hash remain active, and which policy hash did it map to?
2. How many matches did each rule hash receive?
3. Which rules have at least 20 matches?
4. Which rules show high warm-up-finish / first-status-already-exited behavior?
5. Which rules have representative false positives?
6. How many handoffs would have completed within the original foreground wait?
7. How often did handoff create observable independent tool work?
8. What was collection lag?
9. Did foreground command families repeatedly hit `wait_expired`?
10. Did new pre-dispatch or owner-dispatch errors appear?
11. Is there enough evidence to implement longest-prefix semantics?
12. Is there enough evidence to justify a separate auto warm-up?
13. Which local regex changes are justified?
14. Which decisions remain under-sampled?

The review must end with one explicit state for each candidate change:

```text
IMPLEMENT
KEEP CURRENT
EXTEND OBSERVATION
LOCAL CONFIG ONLY
```

No Phase-5 policy source change should begin without that decision record.
