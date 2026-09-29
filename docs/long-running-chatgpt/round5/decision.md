# Round 5 — production decision

Status: **GO — DEPLOYED AND PRODUCTION UX SMOKE PASSED**
(`planning/longrun-round4-5-prep` @ `dc3b239`, `round5/report-template.md`).

Date: 2026-09-29
Candidate: `feature/longrun-v1` @ `17cc21c0293b183773881331aeefc9af17f77cc5` (9ccfed5 + default durable-job handoff UX; ahead of `master`
`99e89a5`, 0 behind: a fast-forward)
T-GATE evidence: `../round4/report.md`; raw evidence `~/.local/state/binnacle/long-running-chatgpt/round4-evidence/`

## Decision

**GO.**

The candidate adds one optional `job_status` argument (`cursor`) that lets any later turn or conversation
read a job's output completely and in bounded chunks, from the `job_id` alone or from a carried cursor.
Round 4 proved the property that the programme set out to establish: foreground ChatGPT turns are not a
reliable container for long jobs (one completed after 45.0 min, another was cut off after 40.3 min), and
with the cursor neither outcome loses output. Legacy callers are unaffected, and the rollback has been
rehearsed. The fast-path latency could only be measured on a busy host and is not a verdict; the deploy
smoke's budget check re-measures it at deploy time.

The coordinator does not execute the deploy: the repository's deploy flow pushes `master`, which this
session may not do. The exact command is under **Final action**.

## Gate matrix

| Gate | Required | Evidence | Result |
| --- | --- | --- | --- |
| I-GATE | full implementation gate passes | 1,371 tests pass, 3 skipped; branch coverage 96.28% (floor 86.9); coverage policy 0 errors; pre-commit clean (`8e75196`, Python 3.13). CI on `17cc21c`: all jobs green, Python 3.10–3.14; local full suites: py310 1,364 pass / 7 skip and py313 1,369 pass / 3 skip | PASS |
| Cursor completeness | no loss on required scenarios | every job's cursor ranges cover `[0, size)`; overlaps only from retries of lost responses or from concurrent readers | PASS |
| Long normal jobs | T10–T60 evidence | same-turn 10.0 / 20.0 / 30.0 / 45.0 min; T60 turn cut off at 40.3 min, recovered | PASS |
| High/quiet/fail/cancel/UTF-8 | bounded output, correct semantics | 9 × 24,000 + 1,752 chunks; quiet `has_more=false`; exit 3; signal 15 drained; UTF-8 intact | PASS |
| Tunnel restart | later cursor call continues | all active turns continued; one lost response re-read from the same cursor | PASS |
| MCP-server restart | job survives, cursor continues | fixture survived under the staging manager; `server_gen` changed; client-side failures retried exactly | PASS |
| Turn end | foreground turn can end without losing job | constructed (TT1) and natural (T60) | PASS |
| Reattach | same-chat and new-chat recovery from durable ids | same chat from own cursor (TT2); new chat from `job_id` (RB); new chat from a dead turn's cursor (RC) | PASS |
| Production isolation | zero production test calls | 0 Round 4 nonces on the production server; production PIDs unchanged | PASS |
| Legacy compatibility | no-cursor payload unchanged | legacy golden snapshots unchanged; key order pinned by a test; rollback schema check | PASS |
| Fast path | no unacceptable `run_command` regression | busy host (load 6.9–8.4): candidate faster than base in one pass, slower in the other; no code change on the `run_command` path beyond one log field | NOT A VERDICT (re-measured by the deploy smoke) |
| Rollback | rollback + legacy smoke | local rehearsal: cursor merges reverted, hard cap kept, 124 tests pass, stale `cursor` call rejected with "Unexpected keyword argument" | PASS (local; see F2) |
| Cleanup | staging removed, baseline reconciles | staging gone, tunnel 404, connector list = 09:55 baseline | PASS (chats: see F3) |

## F0 — interaction burden (Round 4 jobs, bytes returned to the model)

A legacy `job_status(job_id)` at the same moment returns the last ≤100 lines, capped at 24,000 characters by
the hard cap that ships in both designs.

| Job | Calls | Unique output (B) | Cursor returned (B) | Legacy tail equivalent (B) | Legacy ÷ cursor |
| --- | ---: | ---: | ---: | ---: | ---: |
| T10 `9ff5f952382c` | 11 | 1,220 | 1,220 | 7,487 | 6.1 |
| T20 `7956f11d35b1` | 22 | 1,630 | 1,712 | 19,070 | 11.1 |
| T30 `40fb816378b1` (2 readers) | 42 | 2,450 | 4,982 | 62,576 | 12.6 |
| T45 `eeb3dc4c39ab` | 51 | 3,680 | 3,721 | 99,180 | 26.7 |
| T60 `07beba8e7ec2` (2 turns) | 44 | 5,098 | 5,180 | 77,924 | 15.0 |
| THIGH `7a8f44da7278` | 10 | 217,752 | 217,752 | 240,000 | 1.1 |

Interpretation: for ordinary long jobs, cursor polling returns 6–27× fewer bytes and each byte about once. For
the high-output job both return similar volumes, but every capped legacy call elides the middle of the log, while
the cursor delivers all of it.

## F1 — fast path

Host load 6.8–8.4 throughout (other projects). Two alternating passes of 30 calls per case on throwaway local
servers (`f1_bench.py`), medians in ms:

| Case | base-1 | cand-1 | base-2 | cand-2 |
| --- | ---: | ---: | ---: | ---: |
| `run_command true` | 28.1 | 19.6 | 29.5 | 51.0 |
| `run_command` small output | 31.6 | 20.9 | 28.0 | 49.4 |
| legacy `job_status` | 21.9 | 15.5 | 21.3 | 36.4 |
| cursor `job_status` | — | 16.1 | — | 34.9 |

The sign flips between passes, so the variance is the host, not the change. Not a verdict. The deploy smoke's
budget check (`scripts/smoke_checks.py`) measures production after the deploy; a quiet re-run of `f1_run.sh` is
recommended if a latency number is wanted before it.

## F2 — rollback rehearsal

- Cursor rollback boundary: revert merge `8e75196` (I-D) and `5aa74e1` (I-B) with `-m 1`; I-A helpers and I-C
  telemetry stay (unused/additive).
- Hard cap retained: `clip_head_tail_hard` still in `job_status.py`.
- Tests on the rolled-back tree: 124 contract/job/smoke/telemetry tests pass.
- Live check on a throwaway server (`rollback_rehearsal.py`): schema `job_id, tail_lines, wait_seconds`; legacy
  `job_status` returns `log_tail`; a stale `cursor` call is rejected ("Unexpected keyword argument"), never served
  wrongly; server stopped, port closed.
- Not rehearsed: the ChatGPT connector refresh on rollback (the staging connector was already removed). It is the
  same `chatgpt-refresh` step every surface change uses.

## F3 — cleanup

- Staging: link, app and tunnel deleted (tunnel 404); both units stopped; config, token and state removed;
  evidence kept (1.7 MB).
- Production: connector inventory matched the pre-test baseline throughout the isolated test programme.
- Round 4 chats: all 9 subject chats were backed up and deleted by exact ID.
- The remaining 7 distinct Round-1/2/3 worker/reviewer chats were later backed up and deleted by exact ID; repeated
  HTTP 429/403 responses were handled by low-frequency retries and no chat was deleted before its backup succeeded.
- Worker Project `g-p-6abb0535b19c81919044ee821c246739` was verified empty, deleted with HTTP 200, and read back as 404.
- All 11 `binnacle-longrun-*` worktrees, their local branches, and the remaining remote longrun branches were removed
  after final reports/evidence were archived to `master` or the local final-evidence store.
- Coordinator `4bee5c0b` was stopped and `/tmp/binnacle-ux-handoff-smoke` was removed after its evidence backup.
- Durable local evidence remains under `~/.local/state/binnacle/long-running-chatgpt/{round4-evidence,round5-evidence,final-evidence}`.

## Residual risks / deferred work

- Tail mode still reads the whole spool per call (returned size is capped).
- `run_command` create idempotency is out of scope (a turn lost before seeing `job_id` can only use the listing).
- Retention does not pin jobs with outstanding cursors.
- MCP Tasks, elicitation and SSE remain non-dependencies (ChatGPT does not support them today).
- A turn cut off mid-message may leave its chat unusable; recovery must happen in another chat (it works).
- `read_chat.py`'s "turn finished" flag is not turn liveness; orchestration must read the server journal.

## UX handoff amendment — 2026-09-29

After the original GO decision, the owner selected the default long-job handoff UX. Candidate
`17cc21c` adds no lifecycle or result-schema field: it changes the model-visible
`run_command` / `job_status` guidance and running-result text so a durable running job is
normally handed back to the user with its `job_id` and current progress instead of keeping
the current ChatGPT turn open with repeated positive waits. An explicit user request to wait
for completion overrides the default. Immediately available cursor chunks are drained before
handoff; cursor remains internal unless requested.

The description set remains under its existing 700-token guard (681 by the repository's
contract estimator). Local full suites pass on Python 3.10 and 3.13, pre-commit passes, and
CI run 36526411992 is green for quality, coverage policy, and Python 3.10–3.14.

## Final action — completed

Production deployment completed on 2026-09-29 at `17cc21c`:

- `master`, `origin/master`, `feature/longrun-v1`, and `origin/proof-of-concept` all reached `17cc21c`;
- CI run `36526411992` passed code quality, coverage policy, and Python 3.10–3.14;
- `chatgpt-refresh "Raspberry Pi MCP"` ran after the tool-surface change;
- production services remained healthy;
- the deployed tool surface was exercised from a fresh ChatGPT conversation.

### Production UX smoke

Smoke chat `6abb4ed0-f268-83ec-93e9-db409f943aeb` was given a harmless two-minute command and was **not** asked to keep the turn open. It started durable job `a98130cba698`, observed the `START` line, and ended the first turn after about 22 seconds with a user-facing response containing the job ID/current status and explaining that the job would continue after the turn ended. No repeated long polling occurred in that turn.

A later user message containing only `Status` reattached to the same durable job and reported exit code 0 after about 120 seconds with the `DONE` output. The chat was backed up to the Round-5 evidence directory and deleted by exact ID. This validates the intended production UX in addition to the Round-4 durability contract.

### Rollback

If the UX policy alone must be removed, revert ordinary commit `17cc21c`. For a full cursor rollback, use the already-rehearsed merge rollback from `9ccfed5`: `git revert -m 1 9ccfed5 8e75196 5aa74e1` (newest first), deploy the rollback result, and run `chatgpt-refresh "Raspberry Pi MCP"`. The rehearsal passed 122 contract/job/smoke tests, kept the 24,000-character hard cap, and removed `cursor`.
