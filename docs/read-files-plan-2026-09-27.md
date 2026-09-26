# read_files: design and evaluation plan (2026-09-27)

Status: draft for the owner's review. Nothing here is deployed. The candidate
code lives on `feature/read-files-eval` and is off by default.

## 0. Update: the ceiling is much lower than section 2 says (2026-09-27 08:43)

Measured after the candidates were built: the implementation agent saw it
first, and the manager checked it on the same journal.

- ChatGPT already sends several tool calls in one model step. Counting calls
  that start less than 2 s apart as one step: since 2026-09-14, 26,403
  ChatGPT calls in 20,092 model steps (1.31 calls per step); steps per turn
  median 18, p90 74.
- Of the 2,801 reads of a different file directly after a read, 2,408 (86 %)
  are in the same step as the previous read. The model already batched them,
  as parallel calls. Only 393 start a new step.
- A multi-file read saves model steps, not calls. The realistic ceiling is 393
  steps in two weeks: about 2 % of all steps, about 72 minutes of model time
  at 11 s per step, and only if the model could have known each of those
  paths one step earlier.
- Everything below this section was written before this finding.

Recommendation: do not run Stage 2 and do not merge the candidates. The
branch keeps the tested, off-by-default implementation (commits `b14f49e`
and `15d7209`) in case the model's behavior changes. The owner decides.

## 1. Decisions so far (owner, 2026-09-27)

- Evaluate before anything ships. `read_file` is the second most used tool;
  the model must be proven to handle the change correctly.
- Test three candidate interfaces against today's tool, including the owner's
  variant B3: one tool `read_files` that replaces `read_file`.
- The over-reading risk (a batch returns more content than the task needs) is
  decided by the test results, not by argument.
- Mixed results (some files read, some failed) must be explicit, so that the
  model cannot misread them.
- Out of scope: a git tool (deferred again), changes to `search_text`.

## 2. Evidence and ceiling

Window 2026-09-14 to 2026-09-27, ChatGPT calls only (identified by their turn
id): 671 turns, 26,342 tool calls, 6,267 of them `read_file`.

- 2,801 `read_file` calls came directly after a read of a *different* file:
  10.6 % of all calls. They form 1,058 runs; median 3 files per run, p90 6,
  max 18; 54 % of adjacent pairs are in the same directory.
- 1,234 calls read the same file again; only 114 of them continue exactly
  where the previous slice ended, so paging is not the target.
- Ceiling: if every run became one call, 2,801 calls (10.6 %) disappear. At
  about 11 s of model time per call, that is about 8.5 hours per two weeks.
  For one task that needs *k* files, the best case is *k* calls down to one.
- Not addressable: a read whose target the model learns from the previous
  file's content. No interface can batch that.

## 3. The arms

| Arm | Interface |
| --- | --- |
| A | `read_file(path, start_line?, end_line?)`, as today (control) |
| B1 | `read_file(path?, start_line?, end_line?, files?)`: exactly one of `path` and `files` |
| B2 | `read_file` unchanged, plus a new `read_files(files)` |
| B3 | `read_files(files)` only; `read_file` removed (owner's variant) |

B1, B2 and B3 share one implementation, one set of limits and one result
format (section 4), so the arms differ only in the interface the model sees.

## 4. Design

### 4.1 Request

`files` is a list of 1 to `max_files` (8) items. Each item is
`{path, start_line?, end_line?}`: the same meaning as today's parameters.

- Items are read in the order given, and results come back in that order.
- The same path may appear twice (for example, two ranges of one file); each
  item is independent.
- Only a malformed *request* fails the whole call: an empty list, more than
  `max_files` items, or an item without a path. The error names the rule and
  the limit.
- A problem with one *item* never fails the call.

### 4.2 Item status: a closed set of four

| Status | Meaning | What the model does next |
| --- | --- | --- |
| `ok` | The requested range is returned in full (an empty file is `ok` with 0 lines) | Nothing |
| `truncated` | Part of the range is returned; `next_start_line` says where to continue | Continue only if it needs the rest |
| `not_read` | Nothing returned: the call's content budget ran out before this item | Ask for it again (it is in `next_call`) |
| `error` | Nothing returned; `error.code` and a one-sentence `error.message` | Follow the message |

Error codes, also a closed set: `not_found`, `is_directory`, `outside_roots`,
`permission_denied`, `binary` (with the MIME guess and a hint to use
`run_command`), `too_large` (above the file-size guard), `bad_range` (the start
line is past the end of the file). A lossy decode is not an error: the item is
`ok` with `lossy: true`, as today.

### 4.3 Summary and the next call

Every result starts with a summary: `requested`, and counts for `ok`,
`truncated`, `not_read` and `error`, plus `complete` (true only when every item
is `ok`). When anything is `truncated` or `not_read`, `next_call.files` holds
the exact arguments to continue: the continuation ranges first, then the items
not read. The model can send it unchanged. This is the main protection
against confusion when results are mixed.

### 4.4 What the model reads (text content)

One summary sentence, then one header line per item in a fixed shape, then the
item's content. Example:

```text
Read 4 files: 2 complete, 1 truncated, 1 error. To continue, call again with next_call.
=== [1/4] ~/Projects/demo/app.py | lines 1-120 of 120 | ok ===
<content>
=== [2/4] ~/Projects/demo/missing.py | error not_found | No such file; check the path with list_files. ===
=== [3/4] ~/Projects/demo/big.log | lines 1-400 of 950 | truncated (content budget) | continue at start_line 401 ===
<content>
=== [4/4] ~/Projects/demo/util.py | not_read (content budget) | it is in next_call ===
```

The structured result carries the same data (items with status, range,
`total_lines`, content, error, `next_start_line`, plus the summary and
`next_call`) and is validated against the output schema. Content stays
without line numbers, as today, so that A and the B arms are comparable.

### 4.5 Limits and budget

- Per item: the single-read limits of today (24,000 chars, 2,000 lines,
  2,000 chars per line, 20 MB file guard). One item never returns more than
  `read_file` returns today.
- Per call: a content budget of 48,000 chars (twice a single read). Items
  consume it in order; when it runs out, the current item is `truncated` and
  the rest are `not_read`. In-order is predictable and easy to state; a fair
  share would truncate every file and cause more follow-up calls.
- Stage 1 chooses the budget from real batch sizes (criterion R3); Stage 2
  measures whether the batch invites over-reading (criterion P5).

### 4.6 Descriptions (the contract the model reads)

Draft for `read_files` (B2, B3):

> Read one or more text files (up to 8) in one call, each optionally a line
> range (1-based, inclusive). Put every file you already know you need into
> one call. A file within 24k chars comes back whole, so omit the range; for
> a larger file, search_text first and read only that range. Results come
> back in request order, each with a status: ok, truncated (continue at
> next_start_line), not_read (the 48k-char budget of the call ran out) or
> error (code and what to do). One failed file never fails the others. When
> anything is incomplete, next_call holds the exact arguments to continue.
> Binary files return an error with a hint; inspect them with run_command.

B1 uses the same text for `read_file` with "pass either path or files". B2
adds one sentence to `read_file`: "To read several files, use read_files."

### 4.7 Logging

`tool_call` and `tool_result` lines carry `files_requested`, `files_ok`,
`files_truncated`, `files_not_read`, `files_error` (by code),
`content_chars` and `budget_exhausted`, so the evaluation and later reviews
can measure from the journal.

### 4.8 Who gets it

Exposure is per client through `client_tools`. The evaluation concerns
ChatGPT (`openai-mcp`). The other agents (Claude Code, Codex, Copilot) keep
`read_file` unless the owner decides otherwise after the evaluation.

## 5. Evaluation in two stages

The owner proposed (2026-09-27) to test first against the MCP server directly,
with the real `read_file` calls from the production journal, and without
ChatGPT: no tokens, minutes instead of hours. Stage 1 does that. It answers
every question about the implementation and the sizes with real data. It
cannot answer the questions about the model's behavior (does ChatGPT use the
batch, send valid arguments, understand mixed results, read more than it
needs), because no model is in the loop and the journal only shows what the
model did with the old tool. Stage 2 keeps a smaller ChatGPT run for exactly
those questions.

### 5.1 Stage 1: replay and log simulation (no ChatGPT)

Input: every ChatGPT `read_file` call since 2026-09-14 (6,267 calls; path,
range, and the logged result: size, total lines, truncation, kind, error),
grouped by turn. A *batch* is a run of consecutive `read_file` calls on
different files in one turn (1,058 runs). This is the optimistic case in
which the model knew every path in advance.

1. **Log simulation.** From the logged sizes alone: for each batch, the item
   count and the content size, and what a 24,000-, 48,000- or 72,000-char
   budget and an 8-item limit would do (complete, truncated, not_read,
   split). Result: the budget and the limit chosen from data.
2. **Live replay.** Each batch is sent to the candidate implementation
   through the strict in-memory client (output schema validated), and each
   item is also read alone with `read_file` at the same moment. Files that
   changed or disappeared since the original call are simply new test
   cases. Result: equivalence, robustness, and the real frequency of mixed
   results.
3. **Rendering review.** Ten real mixed results (error, truncated and
   not_read items), rendered exactly as the model would see them, are shown
   to the owner before Stage 2.

Stage 1 pass criteria:

- **R1 Equivalence:** every item that both modes read returns identical
  content, range and total lines.
- **R2 Robustness:** zero exceptions; every result is valid against the
  output schema; every per-item error carries a code from the closed set.
- **R3 Budget:** the smallest budget in {24,000; 48,000} chars under which at
  least 90 % of the real batches complete without a `not_read` item becomes
  the Stage-2 budget. If neither does, the design goes back to review.
- **R4 Item limit:** `max_files` covers at least 95 % of the real batches.
- **R5 Review:** the owner accepts the rendered mixed results.

### 5.2 Stage 2: ChatGPT, behavior only

Environment as before: four isolated endpoints (A, B1, B2, B3) on ports
8141-8144, allowed roots limited to the fixture, own tokens, tunnels,
connectors and `rp-test-rf-*` Projects, nonce routing check with the P4-A2
rerun rule, and everything deleted afterwards. The fixture is a small
synthetic repository with unique answer tokens (hash frozen before the run).

Scenarios, reduced to the behavior questions:

| Id | Task | Behavior tested |
| --- | --- | --- |
| S1 | One function in one module (control) | No regression; B3 single-file use |
| S2 | Test versus module edge case (2 files) | Batching |
| S3 | One key in three config files, paths given | Batching with known paths |
| S5 | Function names in three given line ranges | Ranges in a batch (argument shape) |
| S6 | Four paths, one missing | Mixed result: error |
| S7 | Text, binary and empty file | Mixed result: binary, empty |
| S8 | Three paths, one outside the allowed roots | Mixed result: guard |
| S9 | End of a 60,000-char file plus two small files | Budget: truncated, not_read, next_call |
| S11 | Find a symbol's definition and read its callers | Batching when paths are discovered |

S4 (five files) and S10 (twelve files) are dropped: Stage 1 measures sizes and
limits with real data, and a batch above the limit is rare (R4).

Procedure:

1. Freeze the candidate commit, the Stage-1 budget and limit, the fixture
   hash, the prompts, the four configurations and this plan's commit.
2. Harness check: one trial per scenario on B3 only (9 chats). Only harness
   and oracle defects may be fixed after it; these trials are not scored.
3. Main run: two trials per scenario per arm (72 chats). Each block is one
   scenario across the four arms in random order; sends serialized at least
   15 s apart; a new chat with a nonce per trial.
4. Evidence per trial: the conversation JSON, the arm's journal lines and the
   oracle's verdict; the chat is deleted after its evidence is saved. Settle
   time comes from the conversation's own timestamps.

Metrics per trial: correct (oracle); tool calls by tool; read calls; batch use
(a read call with two or more items); argument errors; mixed-result handling
(S6-S9: every problem file named with its cause, and the other files used);
content chars and tokens returned; wall time.

Stage 2 pass criteria, fixed before the harness check (a variant passes only
if all hold):

- **P1 Correctness:** overall at least A's rate, and 100 % on S1, S6, S7 and
  S8.
- **P2 Argument errors:** at most 2 % of the variant's read calls, and none
  on S1.
- **P3 Adoption:** the batch form in at least 70 % of the trials of S2, S3
  and S5.
- **P4 Round trips:** in S2, S3 and S5, the median read calls per trial at
  most 60 % of A's.
- **P5 Result size:** in S2-S9, the median content chars per trial at most
  120 % of A's.

Decision rule, fixed before the harness check: among the variants that pass,
the simplest interface wins: B3, then B1, then B2. If none passes, nothing
ships. The report states every criterion for every arm.

## 6. Rollout after a pass

1. Save a usage baseline before the change.
2. Merge the chosen variant and enable it for `openai-mcp` through the
   configuration.
3. Full loop: `scripts/mcp_client.py`, then `chatgpt-refresh`, then a nonce
   test in the standing test chat, checked in the journal.
4. Review after one week: batch uptake, read calls per turn, result sizes,
   argument errors.
5. Rollback: switch the configuration back to A and refresh ChatGPT.

## 7. Risks and how the plan covers them

| Risk | Covered by |
| --- | --- |
| Over-reading fills the context | R3 (budget from real sizes), P5 |
| The model misreads mixed results | The status set, `next_call`, S6-S9, P1 |
| B1's optional `path` confuses the model | P2, S1 |
| The model never discovers `read_files` (B2) | P3 |
| B3 makes single-file reads clumsier | S1, P1, P2 |
| Routing to the wrong connector | Nonce in the arm's journal, rerun rule |
| ChatGPT read-path throttling | The skill's retry, timing from the conversation |
| A ChatGPT change during the run | The pilot; stop and report if the harness breaks |

## 8. Cost

Stage 1: about one hour to align the candidate code with section 4, then
minutes to run (no ChatGPT). Stage 2: 81 chats instead of 176 (9 for the
harness check, 72 for the main run), about two hours, plus 30 minutes for the
environment and 30 minutes for the report.

## 9. Open questions for the owner

1. Which model and effort should the trials use: the one you use for binnacle
   work in ChatGPT?
2. Are 8 files per call and a 48,000-char budget acceptable as the starting
   values?
3. Should Claude Code, Codex and Copilot keep `read_file` whatever the result?
