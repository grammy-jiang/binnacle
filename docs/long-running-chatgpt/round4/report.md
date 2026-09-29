# Round 4 — endurance and fault test report

Status: **T-GATE PASS, 2026-09-29.** All 16 scenario rows pass the §1 criterion. Code under test: `feature/longrun-v1` @ `8e75196` (contract v1,
`../round2/e4-contract-v1.md`) on the isolated managed staging stack `lrc-stage` (plan: `plan.md`).
Production was never touched: no Round 4 call reached the production server (journal checked), and production
units kept their PIDs.

## 1. Verdict

**The §1 criterion holds.** No supported interruption lost durable state, and the documented reattachment path —
`job_status(job_id, cursor=...)`, resuming from the last cursor a caller received or from `"start"` — reconstructed
the next action in every case without hidden context from the interrupted turn: in the same chat after a turn
ended, in a new chat given only the `job_id`, and in a new chat given a cursor from a dead turn.

## 2. Method

- Subjects: new ChatGPT chats in the worker Project, targeted at the staging app by its plugin hint; each ran a
  numbered fixture (`scripts/longrun_fixture.py`) and followed it with the cursor.
- Evidence: the staging server journal (`event=job_status_cursor` ranges, `tool_call` turn ids, `server_gen`) and
  the staging job store (`meta.json`, `out.log` size). Chat replies are recorded but are not the evidence.
- Coverage checker (`r4_coverage.py`): per job, the union of logged `[delta_start, delta_end)` ranges against the
  final `out.log` size. A logged range proves the server served it, not that the client received it; lost
  responses are therefore identified from the next call's cursor (§4.2).

## 3. Scenario results

| Id | Chat / turn | Job | Result | Evidence |
| --- | --- | --- | --- | --- |
| THIGH | 6abb2a12 / 005b6427 | 7a8f44da7278 | PASS | 217,752 B in 10 calls = 9 × 24,000 + 1,752; `has_more` true→false |
| TQUIET | same | 679817d9a31e | PASS | 60 B in 3 calls; `has_more=false` while silent |
| TFAIL | same | b0e173526dfa | PASS | exit 3; output complete |
| TUTF8 | same | b4a07a9a7e2b | PASS | 1,090 B contiguous; chat saw no U+FFFD |
| TCANCEL | same | 9cffde9c24e6 | PASS | `stop_job` mid-read; drained after stop; signal 15 |
| T10 | 6abb2ada / 93eb0b80 | 9ff5f952382c | PASS | same turn 10.0 min; 0..1,220 in 11 calls; exit 0 |
| T20 | 6abb2a7e / 1dd0e9a0 | 7956f11d35b1 | PASS | same turn 20.0 min; 0..1,630; one response lost in the tunnel restart and re-read from the same cursor |
| T30 | 6abb2af3 / 6596762b | 40fb816378b1 | PASS | same turn 30.0 min; seq 0–59 once; 3 client-side failures during the server restart, recovered by retrying the same cursor |
| T45 | 6abb2b54 / 920bd9ea | eeb3dc4c39ab | PASS | same turn **45.0 min** across both faults; 0..3,680 in 51 calls; seq 0–89 once |
| T60 | 6abb2b6c / f8149b81 | 07beba8e7ec2 | TURN STOPPED (expected outcome class) | turn cut off mid-message after 40.3 min with no error; job continued to exit; recovered by RC |
| TTUNNEL | fault 13:22:09 | — | PASS | staging tunnel restarted; all active turns continued; one in-flight response lost (T20) and recovered |
| TMCP | fault 13:27:40 | — | PASS | staging server restarted (23 s); job survived under the staging manager; `server_gen` changed; all active turns continued |
| TTURN | 6abb333e (TT1) + T60 | ee2cb96dd6a4, 07beba8e7ec2 | PASS | constructed: turn ended after one read, job kept running; natural: T60 stall at 40.3 min |
| TREATTACH-a | 6abb333e (TT2) | ee2cb96dd6a4 | PASS | later turn in the same chat resumed from its own cursor `…:37` to the final 1,358 B |
| TREATTACH-b | 6abb3039 / e4f01157 | 40fb816378b1 | PASS | new chat, only `job_id`: `start` read 0..1,917, then followed live to 2,450, concurrent with the original reader |
| TREATTACH-c | 6abb3a2b (RC) | 07beba8e7ec2 | PASS | new chat given only the dead T60 turn's cursor `v1:07beba8e7ec2:3311`: one call read 3,311..5,098 = final size (exit 0), seq 81–123; byte 3,311 is exactly the start of seq 81, so the dead turn (0–80) and RC (81–123) covered all 124 lines once |

## 4. Findings

1. **A foreground turn can wait 45 minutes — and can also die at 40.** T45's turn completed and resumed after
   45.0 minutes (Round 1's maximum: 33.34). T60's turn was cut off mid-message after 40.3 minutes with no error.
   Both are expected outcomes; the design does not depend on which one occurs.
2. **Lost responses are real and harmless.** A tunnel restart dropped one completed response (T20: served
   1,507..1,589, never received; the next call resumed from 1,507). A server restart failed three client calls
   before they reached the server (T30). In every case the stateless cursor made the retry exact: no loss, no
   duplicate at the client.
3. **A mid-message cut-off can make its own chat unusable.** A resume turn into the stalled T60 chat was refused
   (no send answered 2xx, no new user turn). Recovery from a different chat — by `job_id`, or by a carried cursor —
   is therefore the path that must work, and it does.
4. **Concurrent readers are independent.** T30's job was read by two turns at once (original and RB); each saw a
   contiguous sequence.
5. **`read_chat.py`'s "turn finished" flag is not turn liveness.** It reported the T30 turn finished while the
   journal showed it calling every ~55 s; turn state was judged from the journal thereafter.
6. **Surface cost.** One extra `job_status` argument and four cursor fields (token budget 2,140 → 2,262); tail mode
   is byte-for-byte unchanged.

## 5. Operational notes

- ChatGPT send-path problems during the round (not product defects): HTTP 429 on the conversation listing,
  "Could not load this ChatGPT conversation" on continuations (TT2 needed 3 attempts), and browser-slot
  contention from another orchestrator on the host.
- Test chats and the staging stack are removed at teardown after evidence is copied to
  `~/.local/state/binnacle/long-running-chatgpt/round4-evidence/`.
