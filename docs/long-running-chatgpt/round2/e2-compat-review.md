# E2 — Round 2 compatibility review

Status: **BLOCKED**. Reviewed 2026-09-29 against E0, E1 draft v1, the coordinator checkout's product code (identical to base commit 99e89a5; current HEAD adds coordinator docs only), current contract/integration/script tests, journal/usage parsers, docs/tools/run_command.md, and Lane B hard-cap commit 136b301.

Scope rule observed: review only. No product code, service, branch, or commit was changed.

## 1. E2 answers

### Exact field-set / log_tail dependency

**Tests pin the job_status surface and one exact legacy result; production scripts/parsers do not appear to depend on the exact result key set.**

- The MCP surface hash pins job_status for both ChatGPT and the default profile, and requires exact hash equality: tests/contracts/test_tool_surface.py:43, :53, :67-70.
- Golden outputs compare both the size budget and the entire recorded result for exact equality: tests/contracts/golden_support.py:138-144. The current job_status-wait snapshot contains log_tail and no next_after, with exact size numbers: tests/contracts/snapshots/job_status-wait.json:4-24.
- Legacy compatibility/integration tests directly require log_tail on ordinary single-job calls: tests/contracts/test_job_spool_compat.py:57-66; tests/integration/test_jobs.py:251-254.
- The deployment smoke also checks legacy log_tail, but defensively via .get(): scripts/smoke_checks.py:197-204.
- Journal/stats consumers are additive-field tolerant. plain_fields parses generic key/value fields and treats only args= / error= as terminal free-text tails: src/binnacle/logstats.py:50-53, :95-107. Weekly usage matches tool_call through args= and tool_result through duration_ms, not an exact field list: scripts/weekly_usage.py:73-88. The scheduling journal stores the parsed result-field map rather than validating an exact set: scripts/chat_scheduling_journal.py:138-142.

Therefore additive next_after on legacy single-job calls is compatible with the scripts found, but it requires intentional updates to the pinned surface and golden snapshot. Existing log_tail consumers remain compatible only for calls without after, exactly as E1 promises. No current caller uses cursor mode, so omitting log_tail only when after is supplied has no current caller to break.

### Is tail-mode next_after safe?

**No, not under E1's general “unseen output” wording.** Tail mode intentionally does not prove that all bytes before EOF were shown. Current tail_lines can expose only the last N lines (tests/integration/test_jobs.py:251-254), and Lane B additionally hard-clips the selected tail (136b301:src/binnacle/tools/job_status.py:239-244,269-278). E1 nevertheless returns next_after = EOF from a tail call (docs/long-running-chatgpt/round2/e1-contract-draft.md:42-43,60-62) and tells the model to pass a previous next_after “to read only output you have not seen” (:80-81). Following that cursor can silently skip an unseen middle.

## 2. Findings

### BLOCKER-1 — Tail-mode next_after can silently skip unseen output

E1 defines tail-mode next_after as current EOF and calls it the position to pass next (docs/long-running-chatgpt/round2/e1-contract-draft.md:42-43), reseeds a later turn from that EOF (:60-62), and describes after as reading only output “you have not seen” (:80-81). But ordinary tail mode can omit earlier lines (tests/integration/test_jobs.py:251-254) and Lane B can omit a middle section even after line selection (136b301:src/binnacle/tools/job_status.py:239-244; 136b301:src/binnacle/job_output.py:44-73).

Impact: a caller that follows the advertised next_after can permanently skip bytes it never received. E1 itself asks this question at docs/long-running-chatgpt/round2/e1-contract-draft.md:124-125; the E2 answer is **not safe as currently described**. E4 must resolve the semantic contradiction before the interface freezes.

### BLOCKER-2 — “Unknown job” error conflicts with the existing state="unknown" lifecycle

E1 explicitly says the lifecycle keeps state in running | exited | unknown (docs/long-running-chatgpt/round2/e1-contract-draft.md:18-20) but later says “Unknown or pruned job → the existing unknown-job error” (:67-68).

Current code distinguishes these cases. Missing/unusable metadata returns None and produces the “No job with id” ToolError (src/binnacle/jobs.py:320-324; src/binnacle/tools/job_status.py:203-207). A durable record whose process disappeared is instead returned as state="unknown" (src/binnacle/jobs.py:334-343), and job_status emits a normal unknown-state summary (src/binnacle/tools/job_status.py:285-289). The spool-compat contract pins this behavior (tests/contracts/test_job_spool_compat.py:69-77).

Impact: implementing E1 line 68 literally would break an existing lifecycle state and dated-spool compatibility. The draft must distinguish a missing/pruned job id from a known job whose lifecycle state is unknown.

### BLOCKER-3 — “Quiet” is not equivalent to “no unread output”

E1 says “Quiet and empty jobs” return log_delta="", next_after=after, has_more=false (docs/long-running-chatgpt/round2/e1-contract-draft.md:63-64). Current quiet means only that a running job's last output is at least QUIET_AFTER_S old (src/binnacle/tools/job_status.py:242-245); it says nothing about whether the caller's cursor is behind existing output. A quiet job can therefore have unread historical output.

Impact: if “quiet” is implemented as an output-empty condition, cursor mode can discard unread data. E4 must make the draft unambiguous that output availability is determined by cursor/spool position, not the existing quiet flag.

### BLOCKER-4 — Current valid jobs.max_output_chars <= 0 settings violate cursor progress

E1 reuses jobs.max_output_chars as the cursor byte cap and guarantees that has_more=true returns at least one character (docs/long-running-chatgpt/round2/e1-contract-draft.md:53-57). Current configuration has no lower bound on max_output_chars: src/binnacle/config.py:312. Lane B's hard-cap helper explicitly supports limit <= 0 by returning an empty string (136b301:src/binnacle/job_output.py:44-49), confirming that zero is not currently rejected.

Impact: with a nonempty spool and cap 0, cursor mode cannot advance: log_delta="", next_after=after, and has_more=true would loop forever. A negative cap is also incompatible with a bounded range-read size. E4 needs an explicit compatibility decision/migration for existing non-positive settings before the progress guarantee can be frozen.

### CHANGE-1 — Lane B hard cap is a prerequisite, not present in the base product code

E1 treats the 24,000-character job_status.log_tail cap as unchanged behavior from 136b301 (docs/long-running-chatgpt/round2/e1-contract-draft.md:16-18). Base code still reads the whole log and returns the selected tail directly: src/binnacle/tools/job_status.py:239-240,259-260. Lane B changes that path to clip_head_tail_hard(..., RUN_MAX_OUTPUT_CHARS): 136b301:src/binnacle/tools/job_status.py:239-258,269-278.

Migration: integrate the hard-cap change before or atomically with the cursor surface, while keeping it separable for rollback. Cursor implementation/tests must be based on the hard-cap version, not the current base function body.

### CHANGE-2 — Both pinned job_status surface hashes must change

The optional after input, three output properties, and description sentence all change the hashed surface. job_status is pinned independently for ChatGPT and default profiles at tests/contracts/test_tool_surface.py:43 and :53; exact equality is enforced at :67-70.

Migration: update both intentional pins in the same change as the schema/description and record the reason, as the test's own update rule requires (tests/contracts/test_tool_surface.py:19-22). Tool counts do not change.

### CHANGE-3 — Exact golden job_status-wait snapshot and size budget must change; cursor cases need coverage

Golden checking requires exact size equality and exact payload equality (tests/contracts/golden_support.py:138-144). The current legacy wait snapshot ends at wait_effective_s and has fixed structured-byte/token counts (tests/contracts/snapshots/job_status-wait.json:12-24). E1 adds next_after to every single-job legacy result (docs/long-running-chatgpt/round2/e1-contract-draft.md:42-43,101-103).

Migration: update the legacy wait snapshot/size and add contract coverage for cursor-mode presence/absence rules (log_delta, next_after, has_more, omitted log_tail). The listing snapshot should remain unchanged because E1 does not add next_after without job_id.

### CHANGE-4 — Preserve or deliberately migrate the positional job_status_impl helper signature

Current internal helper signature is job_status_impl(job_id, tail_lines, wait_seconds=0): src/binnacle/tools/job_status.py:191-193. Tests call it positionally, including tests/integration/job_test_support.py:23-25, tests/integration/test_jobs.py:215, and tests/integration/test_jobs_lifecycle.py:128-130.

Migration: do not insert after between tail_lines and wait_seconds without updating these callers; doing so would silently reinterpret existing wait values as cursors.

### CHANGE-5 — after without job_id needs explicit cross-field validation and tests

E1 requires after to have a job_id and calls the combination without one an input error (docs/long-running-chatgpt/round2/e1-contract-draft.md:33-36). Current schema validation covers independent numeric bounds such as tail_lines >= 1 and wait_seconds <= 50 (tests/contracts/test_input_validation.py:81-85), while current job_status immediately enters listing mode when job_id is None (src/binnacle/tools/job_status.py:191-198).

Migration: add explicit cross-field rejection before listing and pin it in contract tests; Field(ge=0) on after alone cannot enforce the dependency.

### CHANGE-6 — Published job-status documentation must migrate with the schema

Current docs publish only job_id, tail_lines, and wait_seconds as inputs (docs/tools/run_command.md:173-179) and publish log_tail as part of every single-job result (:180-184).

Migration: update this section in the same surface change, including legacy/cursor field-presence distinction and cursor error semantics. This matches E1's proposed I-B ownership but is a required compatibility artifact.

### CHANGE-7 — server_gen must be placed before existing free-text tail fields

E1 adds a server-generation id to every tool_call / tool_result line (docs/long-running-chatgpt/round2/e1-contract-draft.md:85-89). Current logging constructs shared identity fields in _who (src/binnacle/logging_middleware.py:299-306) and appends args= last on tool calls (:316-320); error results explicitly keep error= final for historical parsers (:343-348). plain_fields treats args= and error= as terminal free-text tails (src/binnacle/logstats.py:50-53,95-107).

Migration: emit server_gen before args= / error= and add parser/logging tests. Appending it after either tail would make existing parsers absorb it into free text rather than expose it as a field.

### CHANGE-8 — Rollback requires reverse schema refresh and must not undo the hard cap

E1 says ChatGPT caches the schema and rollout needs reload/client/refresh/new-chat cleanup (docs/long-running-chatgpt/round2/e1-contract-draft.md:104-105) but describes rollback only as “revert the commit; callers that never pass after are unaffected” (:106).

Migration/rollback issue: after cursor use begins, a cached client may continue sending after to a rolled-back server, where the old tool has no such parameter (src/binnacle/tools/job_status.py:332-350). Rollback therefore needs the same schema-refresh discipline in reverse. Also, because D-5 keeps Lane B's hard cap, the cursor rollback boundary must not remove 136b301; hard-cap integration and cursor change need separable rollback semantics.

### NOTE-1 — No production script found that requires an exact result key set

The smoke uses .get("log_tail", "") on a legacy call (scripts/smoke_checks.py:197-204). Scheduling journal parsing stores arbitrary result fields (scripts/chat_scheduling_journal.py:138-142). Weekly usage regexes tolerate added fields between fixed anchors (scripts/weekly_usage.py:73-88). Core plain_fields is generic apart from terminal free-text fields (src/binnacle/logstats.py:95-107).

This supports E1's additive-schema direction once the pinned contract tests are intentionally migrated.

### NOTE-2 — client_tools needs no change for this placement

The ChatGPT profile already includes job_status (src/binnacle/config.py:362-371), and matching is by client-name prefix (:374-380; tests/contracts/test_visibility.py:74-78). Because E1 adds an argument to the existing tool rather than a new tool, every client that already sees job_status receives the new schema automatically. E1's “no changes to client_tools” statement is compatible with current visibility behavior.

### NOTE-3 — Existing OpenAI/ChatGPT attribution already uses prefix matching

Scheduling evidence selects calls with call.client.startswith("openai-mcp"): scripts/chat_scheduling_evidence.py:86-90. Visibility likewise pins both openai-mcp and openai-mcp(ChatGPT) to the same profile: tests/contracts/test_visibility.py:46-51,74-78. E1's prefix-attribution requirement is compatible with current behavior.

### NOTE-4 — New job_status_cursor records are additive to current stats parsing

Current job-status performance stats count event=job_status_timing specifically (src/binnacle/logstats_jobs.py:61-72); unknown event types are not treated as job_status calls. Adding a separate job_status_cursor event therefore does not double-count existing timing stats unless I-C explicitly adds new accounting. This is compatible, but new telemetry should have dedicated tests.

### NOTE-5 — run_command and stop_job have no direct surface migration from the cursor placement

E1 keeps run_command and stop_job unchanged (docs/long-running-chatgpt/round2/e1-contract-draft.md:16-20). Lane B 136b301 changes job_output plus job_status and tests, not either public run_command or stop_job surface. Shared job-output changes must still preserve existing run_command shaping semantics; Lane B does so by adding a separate hard-clip helper (136b301:src/binnacle/job_output.py:44-79,82-110).

## 3. Migration / rollback checklist implied by compatibility review

1. Resolve BLOCKER-1 through BLOCKER-4 in E4 before freezing the contract.
2. Land/retain Lane B hard cap 136b301 independently of cursor rollback.
3. Add range-read/UTF-8 helper tests, then tool-level cursor tests including after=0, multi-chunk drain, after at EOF, beyond EOF, missing/pruned id, known state="unknown", quiet-with-unread-output, and non-positive configured cap behavior.
4. Update both job_status surface hashes and the legacy golden snapshot; add cursor golden/contract cases.
5. Preserve the positional helper contract or migrate every direct caller.
6. Add explicit after-without-job_id validation.
7. Update docs/tools/run_command.md with exact field-presence/error rules.
8. Add server_gen before args=/error= and test current journal/usage parsers against the additive field plus job_status_cursor.
9. Treat rollback as a schema transition: revert only cursor/telemetry changes, keep the hard cap, refresh the MCP schema/client/new chat, and clean up the test chat.

## 4. Compatibility conclusion

E1 is implementable on the current architecture: job storage is durable and byte-addressable, existing parsers are mostly additive-field tolerant, client visibility already uses prefix matching, and no new tool is required. It is **not ready to freeze unchanged** because four draft semantics can violate existing lifecycle/output guarantees or the stated progress guarantee.

Finding counts: **4 BLOCKER / 8 CHANGE / 5 NOTE**.
