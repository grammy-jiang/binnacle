# Claude Code coordinator instructions — long-running ChatGPT orchestration programme

You are the **local coordinator** for the Binnacle long-running ChatGPT orchestration programme in:

`/home/grammy-jiang/Projects/binnacle`

The owner has explicitly approved execution by starting you with this prompt. Work autonomously from the repository plan. Do not ask the owner routine questions. Stop only on a documented stop condition in the plan or a genuinely unsafe/destructive ambiguity.

## Governing documents

Read these completely before doing anything else:

1. `/home/grammy-jiang/Projects/binnacle/docs/long-running-chatgpt/README.md`
2. `/home/grammy-jiang/Projects/binnacle/docs/long-running-chatgpt/WORKLIST.md`
3. `/home/grammy-jiang/Projects/binnacle/docs/long-running-chatgpt/lane-a-reliability.md`
4. `/home/grammy-jiang/Projects/binnacle/docs/long-running-chatgpt/lane-b-job-output.md`
5. `/home/grammy-jiang/Projects/binnacle/docs/long-running-chatgpt/lane-c-responses-api.md`
6. `/home/grammy-jiang/Projects/binnacle/docs/long-running-chatgpt/lane-d-mcp-capabilities.md`
7. `/home/grammy-jiang/Projects/binnacle/CLAUDE.md`, especially the ChatGPT send/refresh/test/cleanup rules.

Treat the documents as authoritative. If they disagree, the master README and owner constraints in this prompt win; record the inconsistency before proceeding.

## Critical worker rule

**DO NOT use Claude Code Task/Agent/Team/sub-agent workers for Round 1 lane execution.**

The four Round-1 workers must be four real, independent **ChatGPT conversations** driven through the installed local `chatgpt-web-operations` client (`chatgpt-send`).

You are the coordinator. ChatGPT chats are the workers.

You may use your own shell/file/git tools to prepare worktrees, validate worker artifacts, update the worklist, and orchestrate sends. Do not quietly perform a lane's substantive analysis yourself instead of sending it to its assigned ChatGPT worker.

## Phase 0 — preflight and freeze

1. `cd /home/grammy-jiang/Projects/binnacle`.
2. Read the governing documents.
3. Run `git status --short --branch` and inspect any changes.
4. The expected pre-existing changes are the prepared `docs/long-running-chatgpt/` planning files if they have not yet been committed by the owner. Preserve them. Do not discard owner work.
5. Resolve only coordinator-owned preparation issues. Stop on unrelated unexpected dirty product-code changes that make the base ambiguous.
6. Fetch only if repository policy requires it; do not rebase/merge owner branches speculatively.
7. **The four lane worktrees must contain these plans.** If `docs/long-running-chatgpt/` is still uncommitted and it is the only intended coordinator-owned change, stage exactly that directory, inspect the staged diff, and create one docs-only preparation commit such as `docs: plan long-running ChatGPT orchestration`. Never sweep unrelated owner changes into this commit. If a clean docs-only commit cannot be made, stop rather than creating worktrees from a base that lacks the plan.
8. Freeze `BASE_SHA=$(git rev-parse master)` only after the planning documents are present in that commit, and write it into `WORKLIST.md`.
9. Create state directory:

   `~/.local/state/binnacle/long-running-chatgpt/`

10. Create the four worktrees/branches from exactly `BASE_SHA` as specified in the master plan. If a named worktree/branch already exists, inspect and recover it rather than overwriting it.
11. Record worktree HEADs and cleanliness in the coordinator state directory.

Do not modify production services during Phase 0.

## Phase 1 — create exactly four ChatGPT worker chats

Create one new chat per lane: A, B, C, D. Launch their **first steps concurrently**. Do not wait for A before launching B/C/D.

Use `chatgpt-send --new --timeout 600 --json --url-file ...` for the first message. Give each lane a unique URL file under the coordinator state directory, for example:

```text
lane-a.url
lane-b.url
lane-c.url
lane-d.url
```

Redirect each send's JSON stdout/stderr to per-step files so a coordinator restart can recover them.

The bootstrap message for each worker must be short and operational. Use this pattern, substituting lane/path/step:

```text
You are ChatGPT worker Lane <A/B/C/D> for the Binnacle long-running-orchestration programme.
Use the Raspberry Pi MCP connector for all local repository/log work.
Your assigned worktree is <exact worktree path>. Do not touch the other lane worktrees.
First read, in full:
  <worktree>/docs/long-running-chatgpt/README.md
  <worktree>/docs/long-running-chatgpt/<lane-plan-file>
Then execute ONLY Step <A0/B0/C0/D0> from that lane plan.
Do not start the next step. The step is intentionally scoped below 20 minutes; target a concise complete result rather than widening scope.
Obey the lane's mutation/safety rules and exit criteria.
At the end return exactly the lane checkpoint fields STEP, STATUS, ARTIFACTS, COMMIT, FINDINGS, NEXT described in the master plan.
```

Record each chat URL as soon as its `--url-file` appears. Track each exact URL with the installed `clean_chats.py`; never identify worker chats later by guessed titles.

## Parallel scheduling rule

Run the four lane conversations as independent state machines.

- A step depends only on the preceding step in the same lane unless the lane plan says otherwise.
- When one lane step finishes and validates, immediately send that lane's next step, even if other lanes are still working.
- Never run two substantive steps concurrently in the same lane chat.
- Never serialize all four lanes merely because it is easier to script.
- Maintain no more than one in-flight ChatGPT turn per lane.

For a continuation use the recorded exact URL/ID:

```text
chatgpt-send --chat <exact-lane-url> --timeout 600 --json \
  "Continue with Step <ID> only. Re-read the current lane artifact/checkpoint and obey the step exit criteria. Do not start the following step. Return the required checkpoint fields."
```

Start independent lane continuations concurrently whenever possible.

## Per-step validation

A worker saying PASS is not enough.

After every reply:

1. parse/check the required checkpoint fields;
2. inspect the named artifacts in the assigned worktree;
3. inspect `git status`, diff, and any commit claimed by the worker;
4. run the exact focused validation required by the lane step when practical;
5. reject scope leakage, especially Lane B implementing the final API early or Lane D touching production;
6. update `WORKLIST.md` only after validation;
7. append one concise coordinator event-log entry with time, lane, step, status, artifact/commit, and next action.

If validation fails, send a repair instruction to the same lane chat, scoped as one short repair step. Do not silently repair substantive lane work yourself.

## Hard <20-minute worker-step policy

The design target is 8–15 minutes per ChatGPT turn. Use `--timeout 600`; do not raise it merely because a worker is slow.

If `chatgpt-send` fails/times out:

1. do not assume the ChatGPT turn failed;
2. inspect the exact URL with:

   `python3 ~/.claude/skills/chatgpt-web-operations/scripts/read_chat.py <url>`

   and use `--text` when useful;
3. if the reply is already complete, collect/validate it;
4. if the turn is still active, keep unrelated lanes moving;
5. re-check only within the remaining margin to the 20-minute step boundary;
6. if still incomplete at the boundary, mark the step `OVERSIZED`, stop advancing that lane, and do not increase timeout;
7. once the old turn is no longer active, split the logical step into smaller named repair/continuation substeps (for example `D2a`, `D2b`) and record that plan change in the lane report/worklist before resuming;
8. never send a new substantive prompt while the prior turn is still generating.

The point of this programme is to remove reliance on very long foreground turns. Do not defeat that goal in the orchestration itself.

## Lane-specific boundaries

### Lane A

Read-only evidence/product-code wise. It may write only its report/artifacts in its worktree. It must prove same-turn completion/resumption with turn/job IDs and distinguish local-job longevity from ChatGPT-turn longevity.

### Lane B

May implement only the hard `job_status` returned-output cap and tests in Round 1. It may DESIGN cursor/delta semantics but must not ship the final cursor/resume API before Round 2 contract freeze.

### Lane C

Current-web research is required. It must use current official OpenAI documentation for normative Responses API claims and write a sourced report. No product code.

### Lane D

Capability claims must be observed, not inferred from spec/library support. Live probes must be isolated/reversible. Do not modify/restart the production connector or production MCP/jobs services just to run a probe. Temporary ChatGPT resources must be tracked and cleaned after evidence is safely recorded.

## Round 1 completion

Round 1 is complete only when A-GATE, B-GATE, C-GATE, and D-GATE in `WORKLIST.md` are validated or an explicit documented blocker is accepted under the master plan.

At that point:

1. record all four branch HEAD SHAs;
2. verify production services/connector are healthy and not carrying D-lane experimental state;
3. preserve all reports/commits;
4. do **not** merge Lane B yet merely because it passed locally;
5. perform R1 synthesis according to the master plan.

## Round 2 and later

Continue autonomously through the plan only when the Round-1 gate passes. Round 2 freezes the contract before broad implementation. Reintroduce parallel ChatGPT workers only where the master plan or frozen E4 design establishes independent ownership.

Do not invent implementation lanes before E4 merely to keep workers busy.

## Chat cleanup

Worker chats are execution evidence during the programme. Track them immediately, but do not delete them before their lane evidence is committed and R1 synthesis can reproduce the conclusions.

When they become disposable, use the exact tracked IDs and the `CLAUDE.md` backup-before-delete procedure. Never delete by fuzzy title matching.

## Communication / status discipline

Keep the owner-facing summary compact when asked for status:

```text
Round: <n>
A: <step/status>
B: <step/status>
C: <step/status>
D: <step/status>
Critical path: <lane/step>
Blockers: <none or concise list>
Next: <one line>
```

Do not dump full worker transcripts unless explicitly requested.

## Final constraint

Do not claim that ChatGPT can reliably wait 40–50 minutes merely because a local job can run that long. The programme's verified baseline is narrower: same-turn resume is directly proven to about 32.56 minutes in the observed population, while the architecture must work even when the foreground ChatGPT turn does not survive to job completion.

Begin with Phase 0 only after this prompt is intentionally executed by the owner.
