# Long-running ChatGPT orchestration — coordinator worklist

Status: **COMPLETE — production `17cc21c`; CI + connector refresh + production UX handoff/status smoke PASS**

This file is the coordinator's progress ledger. Update it after every validated step. Do not mark a step complete from a worker's prose alone; verify its exit criteria and artifacts first.

## Preparation

- [x] P0 — master plan written
- [x] P1 — Lane A plan written
- [x] P2 — Lane B plan written
- [x] P3 — Lane C plan written
- [x] P4 — Lane D plan written
- [x] P5 — Claude Code coordinator prompt written
- [x] P6 — owner explicitly approves execution (coordinator session `binnacle-longrun-coordinator` started by the owner, 2026-09-29 ~09:54)

## Round 1 — four ChatGPT workers in parallel

Frozen base SHA: `99e89a595bdc37cb31e53687d50611eda3463120` (master, docs-only preparation commit; not pushed)
Coordinator start: `2026-09-29T09:54+10:00` (base frozen 09:57:07)
Coordinator state dir: `~/.local/state/binnacle/long-running-chatgpt/`

### Lane A — reliability evidence

Chat URL: `https://chatgpt.com/c/6abb0591-ce8c-83ec-83da-d6bec0a5c020` (Project `g-p-6abb0535b19c81919044ee821c246739`)
Worktree: `~/Projects/binnacle-longrun-a-evidence`
Branch: `investigation/longrun-a-evidence`

- [x] A0 — freeze population and definitions
- [x] A1 — classify population
- [x] A2 — correlate candidate failure drivers
- [x] A3 — recommendations and instrumentation gaps
- [x] A-GATE — `lane-a-report.md` validated and committed

### Lane B — job output safety

Chat URL: `https://chatgpt.com/c/6abb05a5-fed8-83ec-a2e2-0543360c5047` (Project `g-p-6abb0535b19c81919044ee821c246739`)
Worktree: `~/Projects/binnacle-longrun-b-job-output`
Branch: `feature/longrun-b-job-output`

- [x] B0 — reproduce and define hard-cap invariant
- [x] B1 — implement hard cap
- [x] B2 — compatibility/performance validation and focused commit
- [x] B3 — cursor/delta contract proposal
- [x] B4 — final report
- [x] B-GATE — report and hard-cap commit validated; not merged

### Lane C — Responses API reference

Chat URL: `https://chatgpt.com/c/6abb05b9-0eb0-83ec-a0fd-48bcffbf832b` (Project `g-p-6abb0535b19c81919044ee821c246739`)
Worktree: `~/Projects/binnacle-longrun-c-responses`
Branch: `investigation/longrun-c-responses`

- [x] C0 — current Responses lifecycle
- [x] C1 — streaming/cursor/reconnect/cancel semantics
- [x] C2 — map Responses concepts to Binnacle
- [x] C3 — final recommendations
- [x] C-GATE — `lane-c-report.md` validated and committed

### Lane D — MCP capabilities

Chat URL: `https://chatgpt.com/c/6abb05cb-dc04-83ec-8344-7494c44f412e` (Project `g-p-6abb0535b19c81919044ee821c246739`)
Worktree: `~/Projects/binnacle-longrun-d-mcp-capabilities`
Branch: `experiment/longrun-d-mcp-capabilities`

- [x] D0 — static capability inventory
- [x] D1 — isolated live-probe design
- [x] D2 — `input_required` / elicitation live test
- [x] D3 — MCP Tasks/deferred-work live test
- [x] D4 — reconnect/new-turn observations
- [x] D5 — cleanup and final report
- [x] D-GATE — `lane-d-report.md` validated and experimental resources cleaned

## R1 synthesis gate

- [x] R1.0 — all four lane gates complete or documented blocked limitation accepted
- [x] R1.1 — collect exact branch SHAs and reports
- [x] R1.2 — verify no production drift from D experiments
- [x] R1.3 — verify temporary worker chats are tracked and preserved until evidence is committed
- [x] R1.4 — coordinator writes one frozen Round-1 synthesis input set

## Round 2 — contract design

- [x] E0 — synthesize confirmed facts / rejected assumptions / unresolved risks
- [x] E1 — draft minimal lifecycle contract
- [x] E2 — compatibility review
- [x] E3 — fresh adversarial ChatGPT review
- [x] E4 — freeze v1 implementation design

## Round 3 — implementation

Implementation lanes are deliberately `TBD` until E4 freezes ownership and interfaces.

- [x] I0 — freeze implementation lane/file ownership
- [x] I-A — incremental output/cursor implementation
- [x] I-B — public lifecycle/API and compatibility implementation
- [x] I-C — telemetry/recovery/statistics
- [x] I-D — test/docs/harness work that is independent after interface freeze
- [x] I-GATE — integration tests, contract tests, coverage/policy gates

## Round 4 — endurance/fault testing

- [x] T10 — 10-minute normal job
- [ ] T20 — 20-minute normal job
- [x] T30 — 30-minute normal job
- [x] T45 — 45-minute normal job
- [x] T60 — 60+ minute normal job
- [x] THIGH — high-output job
- [x] TQUIET — quiet job
- [x] TFAIL — non-zero exit
- [x] TCANCEL — cancel during run
- [x] TTUNNEL — tunnel reconnect/failover path
- [x] TMCP — MCP service restart while job runs
- [x] TTURN — foreground ChatGPT turn ends while job runs
- [x] TREATTACH — later turn reattaches and continues correctly
- [x] T-GATE — evidence report proves durable state + documented continuation path

## Round 5 — production decision

- [x] F0 — compare model/tool steps and repeated-output/token burden
- [x] F1 — fast `run_command` regression check
- [x] F2 — rollback rehearsal/verification
- [x] F3 — cleanup temporary worktrees/connectors/chats after evidence backup
- [x] F4 — GO / NO-GO decision document
- [x] F5 — merge/deploy only if GO and owner policy permits

## Coordinator event log

Append concise entries here during execution; do not paste huge worker replies.

```text
2026-09-29 09:55 P0   base  preflight: services active, doctor 28 ok/1 warn; plan dir only untracked change
2026-09-29 09:57 P0   base  docs-only commit 99e89a5 on master (plan set, unchanged except 1 trailing blank line); BASE_SHA frozen
2026-09-29 09:58 P0   wt    5 worktrees at 99e89a5, all clean (A/B/C/D + coordinator ledger); Lane B .venv via uv sync --frozen
2026-09-29 09:59 P0   chat  BLOCKED: preflight --browser -> Cloudflare "Verify you are human" on chatgpt.com composer (x2);
                            HTTP reads fine; retry loop every 150 s (preflight-loop.sh, ~40 min budget) before Phase 1 sends
2026-09-29 10:03 P1   chat  fresh browser profile (RP_BROWSER_PROFILE=, set by another local actor in send_step.sh) passes preflight
2026-09-29 10:04 P1   A-D   4 bootstrap sends 10:03:43-10:04:43 (20 s apart): all FAILED "the posted message did not create a
                            conversation"; no POST recorded, no chat created (listing + marker search checked); B also rc=127:
                            send_step.sh edited mid-run by another actor (now runs from a private copy)
2026-09-29 10:15 P1   A     diagnostic resend alone: composer ok, filled, submitted; no f/conversation POST, no /c/ id -> same
                            failure. Shared profile still Cloudflare-challenged (10:22). probe_send_gates: turnstile+pow+so required
2026-09-29 10:22 P1   A     BLOCKED (plan section 16: ChatGPT send unavailable for all workers). Bounded retry: Lane A every
                            600 s, max 6 (retry_bootstrap.sh); B/C/D follow the first send that posts
2026-09-29 10:24 P1   note  another local actor ("MANAGER") stopped the retry loop, noted the proven worker-rounds path
                            (skill references/worker-rounds.md) and created Project g-p-6abb0535... for the workers
2026-09-29 10:25 P1   A-D   MANAGER batch bootstrap (one window, send_prompt.py --project --effort extended --no-wait,
                            fresh profile) posted A 10:25:36, B 10:25:58, C 10:26:16, D 10:26:35 -> canonical workers
2026-09-29 10:27 P1   A     coordinator's own Project-path Lane A send (10:26:39) posted a DUPLICATE (6abb05e4); B/C/D
                            sends stopped before posting. Duplicate made no tool calls; backed up, deleted 10:28:12
2026-09-29 10:29 P1   A-D   coordination protocol (state dir COORDINATION.md: inflight/<lane> markers); coordinator
                            waits on all four turns over HTTP (read_chat.py every 180 s, 20-min boundary)
2026-09-29 10:31 R1   A0    PASS validated: lane-a-report.md @1da932c (report only); 32.56-min case re-checked in journal (33 calls, runtime 1953.751 s). A1 sent 10:30
2026-09-29 10:31 R1   B0    PASS validated: no source change (clean); _tail() confirmed line-count-only; test design + helper strategy stated. B1 sent 10:30 (hard cap only)
2026-09-29 10:31 R1   C0    PASS validated: lane-c-report.md @5388e95 (report only); 4 official developers.openai.com sources, 2026-09-29; polling/cancel claims spot-checked live. C1 sent 10:31
2026-09-29 10:34 R1   D0    PASS validated: lane-d-report.md @824e648 (report only); ChatGPT server/discover 2026-07-28 envelope (visibility + ui ext, no elicitation/tasks) re-checked in journal. D1 sent 10:34 (design only)
2026-09-29 10:36 R1   B1    PASS validated: hard cap in job_output.clip_head_tail_hard + job_status (4 files, uncommitted per plan); diff reviewed (marker counted in budget, converging loop, sparse job_status_output_shaping log); coordinator ran 194 focused tests: pass. B2 sent 10:36
2026-09-29 10:36 R1   C1    PASS validated: report @cad3e24; sequence_number/starting_after cursor, transport vs object lifecycle, 6 documented gaps; 8 official sources. C2 sent 10:37
2026-09-29 10:38 R1   A1    PASS validated: report @085f97d; 734 jobs = 463 resumed + 18 no-followup + 253 stopped; >=5/10/20/30/40/50 min same-turn successes 24/10/3/2/0/0. New 33.34-min success 11023a552209 (2000.2 s) re-checked in journal. PLAN INCONSISTENCY for R1: README section 2 snapshot 23/9/2/1 and '32.56 min' superseded by 24/10/3/2 and 33.34 min in the frozen window. Gap: classifier not committed -> repair folded into A2. A2 sent 10:39
2026-09-29 10:39 R1   D1    PASS validated: report @c922d0b; loopback 2-tool MRTR probe (control_echo, require_choice) under /tmp/binnacle-longrun-d-782414a2, port 18082, onboarding scripts, exact cleanup table; Tasks gated on advertised extension. Confirmed none created. D2 sent 10:40 (live; guardrails: send lock, no UI automation, resource record)
2026-09-29 10:41 R1   C2    PASS validated: report @ca60319; 14-row mapping (copy/adapt/do_not_copy), minimal lifecycle keeps run_command/job_status/stop_job + candidate incremental output position; literal Responses clone rejected. C3 sent 10:42
2026-09-29 10:45 R1   B2    PASS validated: focused commit 136b301 'fix: hard-cap job status log output' (4 files, same as B1 diff), not pushed; coordinator re-ran 194 focused tests on it: pass. Worker: giant line 1,000,000 -> 24,000 chars; full-spool read/decode noted as pre-existing, deferred. NOT MERGED. B3 sent 10:45 (design only)
2026-09-29 10:46 R1   C3    PASS validated: report @4554257 (439 lines, header final, report-only branch, 4 commits). 5 ideas to adopt, 5 not to copy, 4 Lane-D-gated decisions, cursor design tests for Lane B, provisional vocabulary (state/running/exited/unknown, cursor/next_cursor, output_delta)
2026-09-29 10:46 R1   C-GATE PASS: lane-c-report.md validated and committed; branch investigation/longrun-c-responses head 4554257; Lane C chat idle
2026-09-29 10:49 R1   A2    PASS validated: report + lane-a-scripts/lane_a_analysis.py @06f85aa; coordinator re-ran the script (repo .venv python): all A1 tables identical. >=5 min: 24 resumed vs 205 stopped; only 44/205 stopped cases ever polled their job; concurrency correlated only (17/24 vs 180/205); no hard timeout supported; expiry vs handoff not measurable. A3 sent 10:50
2026-09-29 10:50 R1   B3    PASS validated: lane-b-report.md B3 section (uncommitted until B4, per plan); provisional preferred job_status(after=<exclusive byte offset>) -> log_delta/next_after/has_more, fallback job_output(); sequence cursor rejected; UTF-8, invalidation, quiet/terminal, old clients covered. No code change. B4 sent 10:51
2026-09-29 10:53 R1   D2    PASS validated: report @4e0ce9e; LIVE RESULT: control_echo ok end to end; require_choice returned structured input_required (elicitation form), ChatGPT did NOT retry -> 'McpServerError: MCP input requires an elicitation-capable caller' => MRTR elicitation not advertised/rejected. Evidence re-read in /tmp root. Live: tunnel_6abb0957..., asdk_app_6abb0980..., link_6abb098e..., 2 units, probe chats 6abb0a0e/6abb0aa5 (tracked). Production units + connector unchanged. D3 sent 10:54 (gate: Tasks not advertised)
2026-09-29 10:54 R1   A3    PASS validated: report @aa63a07 (412 lines, header final, exec summary, reproducer invocation stated). No wall-clock threshold justified; same-turn success to 33.34 min; 6 telemetry additions (turn_end reason, session generation, context occupancy, server generation, output counters, per-job handoff event); 9 Round-2 constraints
2026-09-29 10:54 R1   A-GATE PASS: lane-a-report.md + lane_a_analysis.py validated and committed; branch investigation/longrun-a-evidence head aa63a07; Lane A chat idle
2026-09-29 10:55 R1   B4    PASS validated: report commit a53774e (docs only; source unchanged since 136b301). Root cause, invariant, synthetic before/after, 188+24 worker tests + 194 coordinator tests, microbenchmarks (no regression), full-spool read limitation, provisional job_status(after=byte offset), Lane C questions answered, Lane D/R1 questions deferred
2026-09-29 10:55 R1   B-GATE PASS: hard-cap 136b301 + report a53774e validated on feature/longrun-b-job-output; NOT MERGED (awaiting R1/coordinator review); Lane B chat idle
2026-09-29 10:58 R1   D3    PASS validated: report @9d554ae; Tasks 'not advertised' (isolated connector envelope = visibility + ui only); no task variant/package/workaround/chat created. D4 sent 10:58 (probe resources only; temp tunnel restart allowed, production never)
2026-09-29 11:06 R1   D4    PASS validated: report @bcb6661; control tool survives later turn, new conversation and temp-tunnel reconnect; FastMCP session_id changes per turn even without reconnect; OpenAI sessionId stable within one conversation only => durable state behind Binnacle-owned ids. Production PIDs/start times = baseline. New probe chat 6abb0de2 tracked. D5 sent 11:07 (evidence first; delete only 3 probe chats by id; never --tracked)
2026-09-29 11:12 R1   D5    PASS validated: evidence af54de1 (sanitized, secret scan clean) then report d276411. Coordinator verified: /tmp root, port 18082, units, profile gone; probe tunnel 404; connectors == baseline; 3 probe chats backed up/deleted/untracked; 4 lane chats intact
2026-09-29 11:12 R1   D-GATE PASS: lane-d-report.md + lane-d-evidence validated; experimental resources cleaned; branch experiment/longrun-d-mcp-capabilities head d276411 (POC, not for merge)
2026-09-29 11:12 R1   GATE  PASS: heads A aa63a07, B a53774e (hard cap 136b301, NOT merged), C 4554257, D d276411; production = baseline (PIDs, connector list, doctor 28 ok/1 warn); master = 99e89a5; 4 worker chats tracked and preserved; r1-synthesis-inputs.md frozen
2026-09-29 11:13 R2   E0    DONE (coordinator): round2/e0-synthesis.md: 12 confirmed facts, 10 rejected assumptions, decisions D-1..D-6, risks R-1..R-8
2026-09-29 11:14 R2   E1    DRAFT (coordinator): round2/e1-contract-draft.md: job_status(after=<exclusive byte offset>) -> log_delta/next_after/has_more, bounded range read, reseed via next_after, no new states; out of scope: tail-mode I/O, create idempotency, elicitation/Tasks; candidate split I-A..I-D
2026-09-29 11:22 R2   E2    DONE (ChatGPT reviewer chat 6abb1118, tracked): round2/e2-compat-review.md: 4 BLOCKER / 8 CHANGE / 5 NOTE. Blockers: tail-mode next_after skips unseen output; unknown-job vs state=unknown; quiet != no unread output; max_output_chars<=0 breaks progress. Coordinator spot-checked config.py:312 and jobs.py state=unknown: confirmed. To be resolved in E4
2026-09-29 11:24 R2   E3    DONE (fresh ChatGPT reviewer chat 6abb113e, tracked): round2/e3-adversarial-review.md: 3 BLOCKER / 6 CHANGE / 5 NOTE (tail reseed loss, UTF-8 loop, cursor not job-bound)
2026-09-29 11:24 R2   E4    FROZEN (coordinator): round2/e4-contract-v1.md: job_status(job_id, cursor='start'|'end'|'v1:<job_id>:<offset>') -> log_delta, delta_start/end, next_cursor, has_more; tail mode byte-identical; UTF-8 pending/flush rules; C=max(4,max_output_chars); all 7 blockers + 14 changes resolved (table §9)
2026-09-29 11:24 R3   I0    FROZEN in E4 §10: integration branch feature/longrun-v1 @a53774e; I-A storage || I-C telemetry, then I-B tool surface, then I-D harness
2026-09-29 12:04 R3   I-A   IA1 sent 3x: two new-chat sends failed HTTP 429 on the pre-send conversation listing (another orchestrator active); IC1 first attempt timed out waiting for a browser slot. Neither posted (Project listing checked). IA1 then sent as a continuation into Lane B's idle chat 6abb05a5 (role change stated); IC1 posted in new chat 6abb1aac (tracked). RP_BROWSER_WAIT_SECONDS 3600 -> 600 (below the 900 s send timeout)
2026-09-29 12:04 R3   IA1   PASS validated: a3ff6ab (job_store/jobs read_log_range + JobGone, open once, fstat); diff matches E4 §10; 40 focused tests pass. IA2 sent 12:05
2026-09-29 12:06 R3   IC1   PASS validated: bedaa51 (SERVER_GEN in shared identity fields, before args=/error=); 62 logging/stats/usage tests pass. IC2 sent 12:07
2026-09-29 12:13 R3   IA2   PASS validated: b1a3608 consume_utf8 (incremental decoder, errors=replace, final only at EOF of a non-running job); 50 unit+property tests pass. IA3 sent 12:13
2026-09-29 12:15 R3   IC2   PASS validated: aff50d8 (cursor_calls counter; job_status_cursor not double-counted); 70 telemetry/usage tests pass
2026-09-29 12:15 R3   I-C   COMPLETE: merged --no-ff into feature/longrun-v1 as a8b44fd (integration worktree ~/Projects/binnacle-longrun-v1)
2026-09-29 12:20 R3   IA3   PASS validated: 2b9fdad (231 unit/core tests; full line+branch coverage of read_log_range and consume_utf8)
2026-09-29 12:20 R3   I-A   COMPLETE: merged --no-ff into feature/longrun-v1 as 558e241; coordinator ran unit/core + jobs + logging + contracts on the integration branch: 357 passed
2026-09-29 12:20 R3   I-B   branch feature/longrun-i-b-cursor @558e241, worktree ~/Projects/binnacle-longrun-i-b-cursor (+.venv); IB1 sent into the I-A chat 6abb05a5 (helper author; new-chat sends were rate-limited)
2026-09-29 12:21 R3   I-D   COORDINATOR AMENDMENT: ID1 (fixture program, scripts/longrun_fixture.py) uses no I-B surface and I-D owns its files (E4 §10), so ID1 runs in parallel with I-B; ID2 (smoke cursor check) still waits for the I-B merge. Branch feature/longrun-i-d-harness @558e241, worktree + .venv; ID1 sent into the idle I-C chat 6abb1aac
2026-09-29 12:30 R3   IB1   PASS validated with repair: a920cd5 cursor semantics match E4 §3-§5 (v1 parse, wrong-job/beyond-end errors, C=max(4,..), final=state!=running, pending suffix excluded from has_more, JobGone -> No job with id, telemetry fields); 152 tests pass. Defect: tail-mode log_tail key moved to payload end (golden compares dicts, cannot see it) -> fix + key-order test folded into IB2 (sent 12:30)
2026-09-29 12:30 R3   ID1   PASS with repair: 06e8dac fixture modes accepted; tests placed in tests/live (reserved for BINNACLE_LIVE opt-in host checks) -> repair step ID1a (move to tests/scripts, coverage policy) sent 12:31
2026-09-29 12:35 R3   ID1a  PASS validated: 6372db8 pure rename tests/live -> tests/scripts/test_longrun_fixture.py; fixture tests pass. Lane I-D idle until I-B merge (ID2)
2026-09-29 12:39 R3   IB2   PASS validated: 41f4d62 public cursor surface (last optional param, §6 texts, cross-field validation, both surface hashes, cursor golden, docs); key order restored and pinned; legacy snapshots unchanged; token budget 2140 -> 2262 recorded; coordinator ran 386 contract/job/unit tests: pass. IB3 sent 12:39
2026-09-29 12:47 R3   IB3   PASS: full coverage pipeline on the lane (worker): 1361+ tests, 96.28% branch vs 86.9 floor, 0 policy errors, pre-commit all files; 3d53f33 is an empty validation marker
2026-09-29 12:47 R3   I-B   COMPLETE: merged --no-ff into feature/longrun-v1 as 5aa74e1; v1 merged into feature/longrun-i-d-harness (a9ff10e); ID2 sent 12:48
2026-09-29 12:52 R3   ID2   PASS validated: ce9bbf2 deploy-smoke cursor drain (short normal fixture, start -> next_cursor until terminal & !has_more, exact seq 0-11 once); legacy smoke checks kept; 27 tests
2026-09-29 12:52 R3   I-D   COMPLETE: merged --no-ff into feature/longrun-v1 as 8e75196. I-GATE started (coverage policy full suite + check + pre-commit all files) on 8e75196
2026-09-29 12:57 R3   I-GATE PASS on feature/longrun-v1 8e75196 (coordinator run): 361 unit + 1008 non-unit + 2 ordinary-process tests passed, 3 skipped, 0 failed; branch coverage 96.28% (2697/2894) vs 86.9 floor; coverage policy 91 modules 0 errors; pre-commit --all-files pass. Not pushed, not merged to master, not deployed
2026-09-29 13:01 R4   stage  lrc-stage up 12:58: manager lrc-stage-jobs (effective_owner=manager), server :18090 (auth 401/200 checked), tunnel_6abb2937..., app asdk_app_6abb295a..., link_6abb296d... (6 tools, job_status has cursor). Local smoke: fixture drained via cursor, 20 lines contiguous once; r4_coverage.py verified (0..930, no gap)
2026-09-29 13:01 R4   send  6 subject chats (TS short suite, T10, T20, T30, T45, T60) in the worker Project with the staging plugin hint; waiter poll 300 s, limit 90 min. Planned faults: TTUNNEL during T45, TMCP during T60 (staging units only)
2026-09-29 13:11 R4   TS    PASS (chat 6abb2a12, one turn 559 s). Journal+store coverage (r4_coverage.py): THIGH 7a8f44da7278 217752 B in 10 calls (9x24000 + 1752, has_more true->false), TQUIET 679817d9a31e 60 B/3 calls, TFAIL b0e173526dfa exit 3, TUTF8 b4a07a9a7e2b 1090 B (chat: no U+FFFD), TCANCEL 9cffde9c24e6 signal 15 drained after stop; all contiguous, 0 gaps, 0 overlaps; 0 Round 4 calls on production
2026-09-29 13:19 R4   T10   PASS (chat 6abb2ada): job 9ff5f952382c 10 min, same turn 93eb0b80 drained 0..1220 B in 11 cursor calls (13:06:05-13:15:07), 0 gaps/overlaps, exit 0; chat: seq 0-29 once
2026-09-29 13:23 R4   TTUNNEL fault 13:22:09: restarted lrc-stage-tunnel only (job eeb3dc4c39ab running). Calls already in flight from turns 920bd9ea (T45) and 1dd0e9a0 (T20) completed and those turns continued; production tunnel untouched
2026-09-29 13:23 R4   TTURN observed on T30 (chat 6abb2af3, turn 6596762b): it issued call 52b60c2b4aaa at 13:22:02 (7 s before the restart); the server completed it at 13:22:52 (bytes 1343..1425) but the ChatGPT turn had already ended ~13:22:26 with 'I'm continuing' text. Durable state intact (job running, spool complete). Finding: a server-logged range is not proof of client receipt; resume must use the last cursor the client received (stateless server = no loss). Coverage checker overstates for such calls; report will adjust
2026-09-29 13:23 R4   TREATTACH on the same job 40fb816378b1: RA = new turn in the T30 chat from its last received cursor; RB = new chat given only the job_id (cursor start); sent 13:27 (MANAGER suggestion adopted)
2026-09-29 13:30 R4   CORRECTION: the 'TTURN observed on T30' entry is WRONG and retracted. T30 turn 6596762b never ended: the journal shows it calling every ~55 s from 13:22:02 through 13:29:52 across both faults. read_chat.py reported 'turn finished' because ChatGPT posted an interim commentary text between tool calls; that heuristic is unreliable during tool loops (the MANAGER note used the same signal). Lesson: judge turn liveness from the staging journal, never from read_chat's finished flag. TTURN box unticked; TTUNNEL stands (all in-flight turns continued)
2026-09-29 13:30 R4   RA send (13:28:12) went into the still-active T30 turn by mistake; stopped at 'submitted; confirming the post'; T30 chat still 49 messages = not posted; T30 turn kept calling (13:28:59, 13:29:52). RA cancelled: T30 is not a reattach case
2026-09-29 13:30 R4   TMCP PASS: lrc-stage-server restarted 13:27:40 (took 23 s, draining in-flight waits); T60 fixture pid 1322087 survived under the staging manager; after restart (server_gen 2cd15887000d -> 040ee44cea22) turns 6596762b (T30), 920bd9ea (T45), f8149b81 (T60) and e4f01157 kept calling without error
2026-09-29 13:36 R4   T20   PASS (chat 6abb2a7e, turn 1dd0e9a0): job 7956f11d35b1 20 min, 0..1630 B in 22 calls, exit 0; chat seq 0-39 once. Lost-response recovery observed: call 13:21:50 spanned the tunnel restart; server answered 1507..1589 at 13:22:40 but ChatGPT evidently never got it; next call 13:23:36 resumed from the same cursor 1507 (1507..1630). No loss, no client duplicate (contract §5.4)
2026-09-29 13:36 R4   TREATTACH-b PASS (new chat 6abb3039, turn e4f01157, given only job_id 40fb816378b1): cursor start read 0..1917 in one call, then followed live to 2450 = final size, last call empty with has_more=false; chat seq 0-59 once; concurrent with the original T30 reader
2026-09-29 13:36 R4   TTURN/TREATTACH-a not yet observed (every turn stayed alive); constructed test sent: new chat starts a 12-min fixture, reads once, ends its turn (TT1); a later turn in the same chat resumes from its own next_cursor (TT2) after the journal shows TT1's turn silent
2026-09-29 13:45 R4   TTURN PASS (constructed, chat 6abb333e): TT1 turn started job ee2cb96dd6a4 (12 min), one cursor call 13:41:01 (0..37, next_cursor v1:ee2cb96dd6a4:37), then ended (journal silent 4 min + STEP: TT1). Job kept running under the staging manager, spool 484 B and growing at 13:45. TT2 (same chat, resume from own next_cursor) sent 13:45
2026-09-29 13:53 R4   TT2 (TREATTACH-a) send failed twice (13:45, 13:51): 'Could not load this ChatGPT conversation' after 6 loads; chat unchanged (10 messages, not posted). Intermittent page-load throttling (RA's second attempt on the T30 chat loaded fine; Lane D continued a hint-created chat). Retry at ~13:59; the job ended ~13:53, so TT2 still tests same-chat resume + drain
2026-09-29 13:54 R4   T60 natural foreground stop: turn f8149b81 (chat 6abb2b6c) last call 13:47:08 -> 13:47:58, silent afterwards while job 07beba8e7ec2 still runs (3803 B, read to 3311); chat shows the turn unfinished with its last text cut off ('...39 lines total,') = platform turn cut-off without error, ~40.4 min after the turn began (13:07:34). Confirming a flat message count before a same-chat resume
2026-09-29 14:03 R4   T60 stall confirmed: chat 6abb2b6c flat at 58 messages, turn unfinished, journal silent since 13:48 (>10 min). T60R same-chat resume (14:00) NOT posted: 'no send request answered 2xx, no new user turn' - the stalled in-progress turn blocks the composer. Finding: after a mid-message platform cut-off the SAME chat may be unusable, so the job_id-only reattach from a different chat (RB, proven) is the path that must work. T60R not retried; TT2 covers same-chat resume after a clean turn end
2026-09-29 14:03 R4   TREATTACH-a PASS (chat 6abb333e): TT2 turn resumed from its own previous next_cursor v1:ee2cb96dd6a4:37 at 13:59:15 and read 37..1358 = final size (job exited 0) in one call; with TT1's 0..37 every seq 0-35 exactly once. TT2 needed 3 send attempts (2 page-load failures)
2026-09-29 14:03 R4   T45 PASS (journal/store; reply pending): job eeb3dc4c39ab 45 min, single turn 920bd9ea read 0..3680 B in 51 calls, exit 0, turn active 13:07-13:52 (~45 min) across BOTH faults (tunnel restart 13:22, server restart 13:27) = longest same-turn completion seen (Round 1 max 33.34 min)
2026-09-29 14:03 R4   T30 job 40fb816378b1 covered 0..2450 by original turn 6596762b and RB turn e4f01157 concurrently (32 overlapping calls = two readers), exit 0; T30 reply pending. T60 job 07beba8e7ec2 still running (4594 B), read to 3311 before the turn stalled
2026-09-29 14:05 R4   T30 PASS (chat 6abb2af3, turn 6596762b 13:05:34-13:35:14 ~30 min same turn): job 40fb816378b1 seq 0-59 once, exit 0. The chat reported 3 transient job_status failures at cursor 1835: they fall exactly in the staging server restart (13:27:40-13:28:03); the server logged no error (requests never reached it); the turn retried the same cursor and read 1835..1917 at 13:28:55 = stateless recovery under TMCP
2026-09-29 14:06 R4   T45 reply confirms: seq 0-89 once, exit 0, has_more=false; turn 920bd9ea tool calls 13:07:09-13:52:03 (44.9 min same turn, across the tunnel and server restarts). RC (new chat given job_id + the stalled T60 turn's last cursor v1:07beba8e7ec2:3311) queued to send when the T60 job exits
2026-09-29 14:14 R4   TREATTACH-c PASS (new chat 6abb3a2b, given only the dead T60 turn's cursor v1:07beba8e7ec2:3311): one call read 3311..5098 = final size, exit 0, seq 81-123; byte 3311 = start of seq 81, so dead turn (0-80) + RC (81-123) covered all 124 lines exactly once
2026-09-29 14:14 R4   T-GATE PASS: round4/report.md - 16/16 rows meet the criterion (no supported interruption lost durable state; reattach by own cursor, by job_id, or by a carried cursor reconstructed the next action). Longest same-turn: 45.0 min (T45, across both faults); natural turn cut-off at 40.3 min (T60) recovered by RC
2026-09-29 14:16 R4   TEARDOWN: staging-down.sh copied evidence (jobs, staging journal, tunnel log; 1.7 MB) to ~/.local/state/binnacle/long-running-chatgpt/round4-evidence, then deleted link/app/tunnel (tunnel 404), stopped both units, removed config/token/state; verified: 0 lrc-stage units, port 18090 free, connectors == 09:55 baseline, production PIDs/start times == baseline
2026-09-29 14:16 R4   CHATS: 9 Round 4 subject chats to back up + delete by exact id; 4 done (6abb2a12, 6abb2ada, 6abb2a7e, 6abb2b6c); 5 skipped on HTTP 429/403 during backup read (nothing deleted without a backup), retry scheduled. Worker chats (lanes, reviewers, I-lanes) kept until the programme ends
2026-09-29 14:23 R5   F0: cursor vs capped legacy tail over Round 4 jobs: 6.1-26.7x fewer bytes for normal long jobs; high-output job similar bytes but legacy elides the middle. F1: busy host (load 6.8-8.4), sign flips between alternating passes = not a verdict; deploy smoke budget check re-measures. F2: local rollback rehearsal PASS (revert 8e75196 + 5aa74e1, hard cap kept, 124 tests, stale cursor call rejected). F3: staging gone; 4/9 Round 4 chats deleted, 5 pending (HTTP 429/403 on backup read; retry later)
2026-09-29 14:23 R5   F4 DECISION: GO (round5/decision.md). F5 not executed by the coordinator: deploy_smoke.py deploy pushes master, which this session may not do. Owner command: .venv/bin/python scripts/deploy_smoke.py deploy 8e75196; chatgpt-refresh "Raspberry Pi MCP"
2026-09-29 14:27 R5   CI on feature/longrun-v1 8e75196 (run 36521428948): FAIL only Tests/Python 3.10: test_wait_parameters_state_that_a_wait_ends_early KeyError 'description' (1 failed, 1360 passed); 3.11-3.14, quality and coverage-policy pass. Reproduced locally with tox py310: on 3.10 the 'str | None' parameter's description sits inside anyOf (job_id has the same shape) -> test defect from IB2, not product. Local I-GATE ran 3.13 only (gap noted). Repair IB4 sent to the I-B chat (test-only fix, prove on py310 + py313)
2026-09-29 14:37 R5   IB4 PASS: 452f036 test-only (parameter_description finds the description at top level or inside anyOf); merged into feature/longrun-v1 as 9ccfed5. Coordinator ran the full suite on Python 3.10 (tox py310): 1365 passed, 8 skipped, 0 failed. Pushed feature/longrun-v1 (not master) -> CI on 9ccfed5 running. Deploy target changes from 8e75196 to 9ccfed5
2026-09-29 14:53 R5   CI PASS on 9ccfed5 (run 36522442246): quality, coverage policy, Python 3.10-3.14 all green. Rollback from 9ccfed5 rehearsed: revert -m 1 9ccfed5 8e75196 5aa74e1 applies cleanly, 122 tests pass, hard cap kept
2026-09-29 14:53 R5   F3 DONE: all 9 Round 4 chats backed up + deleted by exact id (last 4 at 14:52 after 429 back-offs; ledger clear); staging removed; production = baseline. Worker chats (lanes, E2/E3, I-lanes) and worktrees kept for the owner's deploy decision
2026-09-29 14:53 R5   F5 NOT EXECUTED (session may not push master): owner runs .venv/bin/python scripts/deploy_smoke.py deploy 9ccfed5 then chatgpt-refresh "Raspberry Pi MCP"2026-09-29 15:33 R5   UX    PASS: 17cc21c adds default durable-job handoff UX (no schema/lifecycle change); descriptions 681 tokens (<700 guard), py310 full 1364 pass/7 skip, py313 full 1369 pass/3 skip, pre-commit pass, CI 36526411992 all green. F5 target updated from 9ccfed5 to 17cc21c

2026-09-29 15:47 R5   F5 PASS: production master/origin master/origin proof-of-concept at 17cc21c; connector refreshed; production UX smoke chat 6abb4ed0 started durable job a98130cba698, returned control after ~22 s while it ran, then a later Status turn reported exit 0 after ~120 s; smoke chat backed up/deleted.
2026-09-29 17:35 CLOSE cleanup complete: 7 remaining worker/reviewer chats backed up + exact-ID deleted; empty worker Project deleted (HTTP 200, read-back 404); 11 longrun worktrees plus local/remote longrun branches removed; coordinator 4bee5c0b stopped; temporary UX smoke directory removed; durable evidence retained in state archives.
```

### Coordinator decisions (recorded under the owner's standing instruction)

1. The plan files carry "do not execute before approval" banners. The owner approved by launching the
   coordinator; the base keeps the owner's text unchanged, and each bootstrap message states the approval.
2. The live ledger is this file on branch `coordination/longrun-chatgpt` (worktree
   `~/Projects/binnacle-longrun-coordinator`), so that `master` stays exactly at `BASE_SHA`.
3. "Launch the first steps concurrently" and the standing owner rule "never send to several chats at the
   same moment" (last set to a 15 s gap, 2026-09-25) are both kept: the four bootstrap sends start about
   20 s apart and then run concurrently; the skill's `new_chat_lock` also serializes new-chat creation.
4. Coordinator state (URLs, send JSON/stdout/stderr, timing, helper scripts) lives in
   `~/.local/state/binnacle/long-running-chatgpt/`.
5. Sends use the skill's proven worker-rounds path instead of `chatgpt-send --new` (which could not post on
   2026-09-29 10:03-10:23): `send_prompt.py --project g-p-6abb0535... --effort extended --no-wait` with a fresh
   browser profile, a `TASK_ID` first line, and collection over HTTP (`read_chat.py`). Same installed client,
   same 20-minute step boundary; only the transport of the wait changed (HTTP polling, no held browser).
