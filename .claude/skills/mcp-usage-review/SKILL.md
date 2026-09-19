---
name: mcp-usage-review
description: Run the evidence-driven improvement loop for an MCP server used by ChatGPT - measure what the model actually called from the server journal, attribute it to ChatGPT, rank tool changes by the calls they would absorb, implement the approved ones with spec and tests, verify them end to end in a real chat, and record a baseline for the next round. Use when asked to analyze tool usage, review whether a tool change reduced calls, propose new tools or parameters from usage data, or "do another round". Local agent on this Raspberry Pi only (needs the journal, the tunnel log, and the chatgpt-mcp-dev skill's browser tools).
---

# MCP usage review loop

One round is: **measure → decide → implement → verify → record**. The first
round (2026-09-03) took the binnacle server from "ChatGPT polls job_status
600 times" to three approved changes verified in a real chat, and it is the
template for every later round. Reference project: `~/Projects/binnacle`;
the loop mechanics (reload, refresh, browser test) come from the
`chatgpt-mcp-dev` skill and are not repeated here.

`mcp-usage-review` is on `PATH` as a symlink into this skill's `scripts/`;
restore it with
`ln -sf ~/Projects/binnacle/.claude/skills/mcp-usage-review/scripts/mcp-usage-review ~/.local/bin/mcp-usage-review`.
The measurement itself is `scripts/usage_breakdown.py` in the repo, so the
numbers are reproducible without the skill.

Read `references/process-lessons.md` before starting: it lists the traps the
first round hit, and each one cost real time.

## Step 1 — Measure

```bash
mcp-usage-review report --since <first real-use day> [--until <day>]
```

This runs the attributed breakdown (`scripts/usage_breakdown.py --json`),
loads the newest baseline from `docs/usage-baselines/`, and writes a draft
`docs/usage-analysis-<today>.md` with the tool mix, job_status polling,
new-parameter uptake, run_command traits, grep split, git subcommands, and
the delta against the baseline. Numbers only; the narrative sections are
left as marked prompts for you to fill from the evidence. It refuses to
overwrite an existing doc unless you pass `--force`; `--stdout` prints
instead of writing; `mcp-usage-review baselines` lists saved baselines.

Rules of evidence:

- **Attribute to ChatGPT** via the tunnel log. Local agents (Codex, Claude
  Code, test clients) share the journal and once made up a whole day's
  traffic. Never report un-attributed totals as ChatGPT behavior.
- **Exclude test traffic**: the script drops nonce-marked commands
  (`e2e-`, `p2-`, ...). Use a nonce in every browser test so this stays true.
- **Payloads are clipped at 500 chars** and wrapped lines rejoin without
  spaces. Count programs and parameters, not tokens; sample raw commands
  before asserting what a category "is".
- For a question the script does not answer, write an ad-hoc pass over the
  parsed records (see the first round's git and grep sections in
  `docs/usage-analysis-2026-09-03.md` for the shape), then fold the useful
  part back into the script so the next round has it.

## Step 2 — Decide

Rank candidates by **calls absorbed**, not by elegance. For each candidate
state: the count it targets, the mechanism (why the model does it the shell
way today), and what it cannot fix. Check the tool's current schema first:
the first round nearly proposed a parameter (`context_lines`) that already
existed — that finding turned the item into a description fix.

Present the ranked list and stop. The user picks; git tools and edit-tool
exposure have been deliberately deferred before, so do not fold them in.

## Step 3 — Implement

Per approved item, in this order, all in one change set:

1. Code in `src/binnacle/tools/<name>.py` (or `jobs.py`); the new
   parameter's description says what shell idiom it replaces ("no need to
   pipe through tail").
2. Spec `docs/tools/<name>.md`: input table, result, behavior, test
   checklist, and a dated line with the usage evidence that motivated it.
3. Tests in `tests/test_<name>.py` mirroring the checklist.
4. `ruff`, `mypy`, the full suite, then `pre-commit run --files <paths>`
   (untracked files need explicit paths; `--all-files` skips them).

Do not hot-edit while the user has a ChatGPT session open on the server:
`uvicorn --reload` restarts on every save and ChatGPT marks the connector
disabled when it hits a dead listener. Batch edits, or use the dev unit.

## Step 4 — Verify end to end

A changed tool surface needs the **full loop**: `test_client.py` shows the
new parameter → `chatgpt-refresh "Raspberry Pi MCP"` → a real message in
the standing test chat with `chatgpt-send`. Listing tools is not a test.
The pass criterion is the nonce in three places: the chat reply, the
journal's `arguments`, and the journal's `job_start`/`tool_result` line.

Design each probe so the feature is actually exercised: ChatGPT takes 5 to
11 s between tool calls, so a blocking wait must be tested against a job
that outlives that gap (40 s, not 8 s). A tool call may block for up to
50 s inside ChatGPT's 60 s cap.

## Step 5 — Record

- Append a "shipped" paragraph to the round's analysis doc with the
  verification evidence.
- `mcp-usage-review report ... --save-baseline` writes the round's JSON to
  `docs/usage-baselines/<today>.json`; the next round's deltas compare to
  it. Save the baseline **before** the change ships if you want a clean
  before/after, or note the boundary date in the doc.
- Memory: one entry naming what shipped, what was deferred, and when the
  user wants the review.

## Reviewing a shipped round

`mcp-usage-review report --since <day after shipping>` and read three
things: the target metric moved (polls per job, hand-tail count, grep on
files), the new parameter's **uptake** is non-zero, and the tool share
shifted. Zero uptake with an unchanged metric means the model never
noticed the parameter — a description problem, fix the wording before
touching code again.
