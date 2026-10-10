# Parallel execution: single freeze, five independent lanes

Status: **execution procedure; not executed**. Owner: the ChatGPT supervisor (dispatch and evidence reconciliation only).

## 0. Non-negotiable workflow boundaries

- Every worker uses a **declared model and explicit reasoning effort**, with runtime verification per [MODEL-AND-EFFORT.md](MODEL-AND-EFFORT.md); defaults and silent fallbacks are forbidden.
- Every worker gets one immutable input packet and one exclusive workspace. All source reading is pinned to the **same** baseline SHA, determined when the run begins, not a moving branch name.
- No worker may change the production server, installed Binnacle or its config, systemd user units, live tunnel, primary connector, real job spool, master, existing production branches or another worker's worktree.
- No unsafe local Codex/Claude sub-agent creation: these are separately invoked top-level worker CLI processes, each with an independent checkout and explicit role/permission boundary.
- Prototype MCP servers use separate loopback ports and temporary identity/token/state. Authenticate every exposed endpoint; use a dedicated test tunnel/app only if the allowed supported onboarding route is available and authorized.
- Workers never import actual private job state into synthetic fixtures; use generated nonces, mock job IDs and deterministic logs.
- User-owned sessions, browser tabs, profiles, cookies and other running jobs are not part of the experiment. Neither CLI workers nor the supervisor may inspect credentials or drive the Desktop browser to bypass permission boundaries.
- Worker evidence must include **what was actually exercised**, not a claim inferred from source or a bot reply.
- Any unsupported/blocked UI capability is BLOCKED for W5; it must not stall W1–W4.

## 1. S0: one-time minimal immutable preflight

S0 is a preparation step, not the first implementation wave and not one of the five outcome lanes. Assign to a short Codex CLI setup operator; do not ask the ChatGPT supervisor to implement fixtures. Its sole permissible product is a disposable test harness and the immutable run manifest.

1. Explicitly select Codex gpt-6-sol / medium for S0 and verify actual availability. Reconcile local/remote Git state with read-only inventory; freeze the exact available origin/master SHA that includes both merged PRs. Do not update or reset the original master worktree. Record FastMCP, MCP, Python, Codex, Claude and Desktop launcher versions; record which are *installed* versus which are *verified usable*.
2. Verify available CPU, RAM, disk and active tests. Four CLI workers plus one Desktop operator is the target; if capacity is insufficient, report RESOURCE_BLOCKED and admit only safe subsets. Never kill or interfere with existing jobs.
3. Establish RUN_ID with a unique random suffix, UTC start time and a non-sensitive evidence root, for example ~/Projects/binnacle-job-awareness-results/RUN_ID, chmod 0700.
4. Generate immutable synthetic fixture manifest with unique per-scenario nonce and deterministic job transitions: pending/running/exited/failed/unknown, result pages, stdout sequence hashes and errors. Freeze SHA-256 of fixture and manifest; distribute **read-only copies**, not one writable shared database.
5. Create the minimal synthetic FastMCP adapter and 3-carrier test matrix for W5. It must expose harmless test actions such as open_fixture, get_fixture_status and read_fixture_result, plus unrelated read-only echo. The names are *prototypes* and are not proposals for new production tools. Preserve method and content parity with a baseline no-reminder arm.
6. Provision, if permitted, one private disposable ChatGPT test MCP App using an explicit supported transport and an independent test account/app namespace. Record app surface and actual clientInfo/protocol; never redirect the production connector. If authorization or UI support cannot be established, record Desktop prerequisite blocked while still launching W1–W4.
7. Generate five worker input bundles with identical SOURCE_SHA and FIXTURE_SHA. Establish a results directory for each. Make no change to the shared bundle after dispatch; any correction becomes a new RUN_ID.

S0 must not read any worker results, choose the winning carrier or integrate prototypes. Failure to provision a live test app only blocks W5; no other lane depends on W5's transport.

## 2. Launch all workers after S0

| Lane | Assignment | Interface | Exclusive workspace and result folder | Starts |
| --- | --- | --- | --- | --- |
| W1 | Native FastMCP transport / result-carrier correctness | Codex CLI | worktree W1; results/W1 | Immediately |
| W2 | Session identity, trust and cross-chat attack matrix | Claude Code CLI | worktree W2; results/W2 | Immediately |
| W3 | Job-result receipt state machine, cursor/Drop semantics | Codex CLI | worktree W3; results/W3 | Immediately |
| W4 | Performance, tokens and compatibility benchmarks | Claude Code CLI | worktree W4; results/W4 | Immediately |
| W5 | Actual ChatGPT model visibility, behavior and live isolation | ChatGPT Desktop app | private test GUI/chat sessions and results/W5 | Immediately if Desktop/app canary passes; otherwise BLOCKED |

All five lane assignments include fixed model/effort requests in [worker-manifest.json](worker-manifest.json). Use [prompts/](prompts/) for reproducible worker dispatch. The observed/effective model and effort are evidence fields; an unverified model setting is not an implicit success.

No W1-to-W5 source/code dependency is allowed. All compare the frozen S0 carriers or fixture contract. W1 may conclude a carrier cannot possibly work; W5 still records its own independently observed actual client outcome, not W1's conclusion as a proxy. W2's trust result and W3's receipt result are required **at synthesis**, not before B/GUI experiments start.

W1 and W3 may share the Codex binary but are **independent processes with distinct worktrees**; W2 and W4 similarly share the Claude binary but not process state. These are four CLI workers operating concurrently, not four sequential phases.

The Desktop display, keyboard, pointer, ChatGPT app and connector profile are single-owner resources. W5 is the **only** GUI operator and owns all three synthetic ChatGPT test sessions. Within W5 it interleaves B-visibility and C-live-isolation trials across A/B/C chat IDs. No second GUI agent, Codex CLI or Claude Code worker can seize the Desktop while W5 is in control. Running background fixture jobs remain concurrent even though physical GUI clicks are serialized.

A supported multi-desktop isolation feature could change this constraint in a future, separately verified run; simply opening extra windows does not confer independent GUI ownership.

## 3. Worker process contract

For each W1–W4, the dispatch record contains: worker ID, tool binary/version, exact process/session ID, immutable base SHA, worktree path, fixture SHA, output directory, allowed file paths, test brief, start timestamp, and resource limits.

Each CLI worker must:

- Read its own brief from [WORKER-BRIEFS.md](WORKER-BRIEFS.md) and signed/frozen input manifest. Never reinterpret the other lanes as its own tasks.
- Write only disposable test code **inside its worktree or isolated /tmp root** and evidence **inside its assigned results directory**.
- Run its own smallest appropriate targeted probes/tests. Do not run whole-repository gates five times; no production-code changes are permitted.
- Output a complete scenario-by-scenario machine-readable report, concise Markdown findings, hashes of reproducible evidence, and exit status. If blocked, output the actual failed step and missing prerequisite.
- After its final report is durable, exit. Do not begin integration, alter another worker's artifacts, post a GitHub review, merge or deploy.

W5 follows [DESKTOP-OPERATOR.md](DESKTOP-OPERATOR.md) instead; it must not write production source or launch a parallel CLI coder. It submits exactly the same machine-readable evidence contract. A model statement of success is not a successful test.

No worker is allowed to silently turn a missing metric into zero, infer ChatGPT receipt from a server log, or report a transport/session gap as a FastMCP failure without attribution.

## 4. Supervisor lifecycle: coordination only

The ChatGPT supervisor does exactly five things:

1. Confirm S0 manifest, five assignments, exclusive ownership, and prerequisites; launch/request launch of independent workers according to the available approved entry points.
2. Record each worker process/session identity, terminal status and evidence location; leave healthy workers uninterrupted.
3. When a worker completes, verify immutable SHA bindings, schema validity and presence of raw evidence **without rerunning its experiments**.
4. Mark any missing, contradictory or security-unsafe evidence as INCONCLUSIVE/BLOCKED and ask the *same assigned worker* for one bounded correction, rather than rewriting code itself.
5. After all workers are terminal (PASS/FAIL/INCONCLUSIVE/BLOCKED), produce one user-visible synthesis from [MANAGER-SUMMARY-TEMPLATE.md](MANAGER-SUMMARY-TEMPLATE.md); state unanswered questions and Go/No-Go. Archive the results. Do not merge any prototype.

The supervisor does not write implementations or tests, drive ChatGPT Desktop, approve a production deployment, or publish a PASS merely because an agent reports it. It can inspect read-only metadata and evidence only.

## 5. Concurrency controls and resource admission

- One immutable source snapshot, one fixture hash, **five independent writable namespaces**, one Desktop GUI owner.
- No shared Python virtual environment modifications after S0. Different worktrees may read shared immutable package caches, but do not concurrently run package upgrades or synchronization that mutate common environments.
- Separate port/token/socket/spool/app namespace for each server, with a registry of owning lane. Never expose a private mock endpoint on 0.0.0.0.
- GUI lock lives only in the W5 operator's process context. With no verified cross-process lock, W5 uses exclusive ownership by contract; other workers never touch the GUI.
- At kickoff measure available RAM, CPU load, open files, swap and ongoing real work. Preserve a safety margin for the Binnacle manager and unrelated active projects; if a resource limit is crossed, launch what is safe and record an admission delay rather than overloading the Pi.
- Failures must remain isolated: a W5 app-auth failure cannot cancel W1; a W1 malformed carrier cannot modify W3's fixture; W4's benchmark does not run while staging setup mutates shared state.
- No synthetic stop/fault test may signal a real process. All cancellation/restart tests target disposable test workers and their own namespaces.

## 6. Readiness, observation and completion stages

S0 **PREPARED** means fixture/manifest frozen and approved temporary resources identified. It is not equivalent to a ChatGPT Chat surface PASS.

L0 **FIVE-WAY FANOUT** begins when W1–W5 receive the immutable packet, with W5 allowed to report its client prerequisite BLOCKED; other workers remain concurrent.

L1 **INDEPENDENT RESULT COLLECTION** accepts a worker's terminal report even if another lane remains running. Do not poll fast or repeatedly rerun unchanged tests.

L2 **READ-ONLY INTEGRATION GATE** occurs after all workers are terminal. It reconciles contradictions (e.g., raw carrier visible but model cannot see it; server fetch success but client never received it) and decides which narrower follow-ups are necessary.

L3 **FINAL SYNTHESIS** is a report only. It can recommend implementation, additional testing or NO-GO; there is no automatic new PR, master merge, deploy or background monitoring.

Every lane must return a terminal evidence report or explicit BLOCKED state. Silence and a still-running process are **not** PASS.

## 7. Teardown and retention

The worker that created each disposable resource tears down only that exact resource after evidence capture. Private test App/connector cleanup follows its own supported management flow; no deleting other user apps. Retain redacted logs, input manifests, test transcripts (only synthetic content), and hashes under the run evidence root. Record teardown PASS/FAIL separately. Cleanup failure is not permission to edit production resources.

The supervisor keeps the final report plus links to each worker's immutable artifact; it does not own teardown scripts. If W5's authenticated UI session cannot be safely cleaned up through supported controls, record CLEANUP_BLOCKED with its exact resource identifiers for deliberate review.
