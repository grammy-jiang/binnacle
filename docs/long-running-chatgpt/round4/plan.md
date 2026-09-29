# Round 4 — endurance and fault tests (plan)

Status: **PLAN, 2026-09-29.** Runs after the I-GATE on `feature/longrun-v1`. Tests the frozen contract v1
(`../round2/e4-contract-v1.md`) end to end with real ChatGPT turns, **without deploying to production**.

## 1. Acceptance criterion (from the master plan §13)

No supported interruption loses durable state, and the documented reattachment path (`job_status(job_id,
cursor=...)`) reliably reconstructs the next action without hidden context from the interrupted turn.
"Every single-turn wait succeeds" is **not** the criterion.

## 2. Isolated managed staging stack

Everything below is created by the coordinator, owned by the namespace `lrc-stage`, and removed at the end
(§7). Production units, the production connector and `~/.local/state/binnacle/jobs` are never touched.

| Resource | Value |
| --- | --- |
| Code | worktree `~/Projects/binnacle-longrun-v1` (branch `feature/longrun-v1` after I-GATE), its own `.venv` |
| Config | `~/.config/binnacle/lrc-stage.toml`: own token file, `serve.port = 18090`, `jobs.owner = "manager"`, `jobs.dir` and `jobs.socket_path` under `~/.local/state/binnacle/lrc-stage/` |
| Job manager | transient unit `lrc-stage-jobs.service`: `binnacle-jobs` with `BINNACLE_CONFIG_FILE` set |
| Server | transient unit `lrc-stage-server.service`: `binnacle serve` with the same config |
| Tunnel | a new OpenAI tunnel + profile `lrc-stage` via the onboarding skill's `tunnel-bringup.sh` |
| Connector | a new private app/link `lrc-stage` (`create_connector.py`, `connect_connector.py`) |
| Test chats | new chats in the worker Project, one per scenario, targeted at the staging app, tracked by exact id |

The staging manager owns its jobs, so restarting `lrc-stage-server` exercises the managed-mode guarantee
(contract §5.3) exactly as production would.

## 3. Fixtures

`scripts/longrun_fixture.py` (Lane I-D): every line carries a nonce and a sequence number, so "no line lost,
none duplicated" is checked mechanically from the concatenated `log_delta` text.

## 4. Scenarios

Long fixtures overlap in time; each has its own nonce, job and chat, so evidence stays attributable.

| Id | Scenario | How | Pass condition |
| --- | --- | --- | --- |
| T10 / T20 / T30 | normal job 10 / 20 / 30 min | chat starts the fixture, follows it with `cursor` until drained | every sequence number once; turn outcome recorded (same-turn or reattached) |
| T45 / T60 | normal job 45 / 60+ min | same | as above; a same-turn result is **not** required |
| THIGH | high output incl. one line > cap | drain with `cursor="start"` | all sequence numbers once; every `log_delta` ≤ cap; `has_more` drives progress |
| TQUIET | silent, then one line | poll with cursor | `has_more=false` while silent; final line read once |
| TFAIL | exit code 3 | drain | `state=exited`, `exit_code=3`, output complete |
| TUTF8 | split multi-byte writes with a pause mid-character | drain while running | no U+FFFD for valid text; no loop; pending bytes appear after completion |
| TCANCEL | `stop_job` while draining | stop, then drain | `exited` with signal; output up to the stop complete |
| TTUNNEL | restart `lrc-stage` tunnel unit while a job runs | coordinator restarts the staging tunnel only | later cursor call continues from the held `next_cursor`; no loss |
| TMCP | restart `lrc-stage-server` while a job runs | coordinator restarts the staging server only | job keeps running under the staging manager; cursor continues; no loss |
| TTURN | foreground turn ends while the job runs | a long job whose turn stops observing | durable state intact; recorded with `server_gen`/turn ids |
| TREATTACH | later turn reattaches | (a) same chat, new turn; (b) new chat given only the `job_id` | the later turn drains the rest with `cursor` and continues correctly |

## 5. Evidence

- Staging server journal: `tool_call` / `tool_result` (turn, `server_gen`), `event=job_status_cursor`.
- Staging job store: `meta.json`, `out.log` per fixture job.
- A checker that parses each scenario's collected `log_delta` text (from the chat's tool results or a replay of
  the same cursor sequence against the store) and verifies sequence completeness.
- Chat transcripts are backed up before deletion.

## 6. Ownership

The coordinator creates and tears down the staging stack and performs the fault injections. ChatGPT test chats
are the subjects: each receives one scenario prompt. Validation of each scenario is by the coordinator from the
journal and the store, never from the chat's own claim.

## 7. Teardown and T-GATE

Teardown: stop both transient units, `tunnel-teardown.sh --purge --delete-tunnel` for the exact tunnel/app/link,
remove `~/.config/binnacle/lrc-stage.*` and `~/.local/state/binnacle/lrc-stage/`, back up and delete the test
chats by exact id. Verify production is unchanged (PIDs, connector list, doctor) as in Round 1.

T-GATE: an evidence report (`round4/report.md`) with one row per scenario (pass/fail, ids, evidence) and the
§1 criterion answered.
