# W5: real ChatGPT Desktop operator SOP

Status: **protocol only — no account/UI interaction performed**.

This lane is assigned solely to the installed ChatGPT Desktop application and is the only part of the programme that may interact with a real ChatGPT UI. Its requested operator model/effort is gpt-6-astra/high (subject to verified Desktop support), while the **separate real ChatGPT subject** is explicitly GPT-6/Medium and must stay fixed for all paired trials. Never rely on defaults, inferred desktop equivalence or silent model fallback. W5 returns observation evidence, not application code or an implementation decision.

## 1. Product-surface verification is a mandatory gate

Host inspection on 2026-10-10 found /usr/bin/chatgpt (installed application launcher), resolving to /usr/lib/chatgpt/codex-launcher. Launcher name and app installation are **insufficient** evidence of traditional ChatGPT Chat client behavior. Distinguish:

- **Chat mode:** the traditional ChatGPT conversation tool caller. Primary target of this programme.
- **Codex Desktop:** may have a different runner/tool transport. Can only provide optional separate supplementary observations, never primary Chat mode PASS.
- **ChatGPT Work:** a separate runtime with different MCP/tool integration, also not interchangeable with Chat mode.

At W5 startup:

1. Confirm the opened app's real product/surface and build/version without inspecting passwords, cookies, account tokens, private unrelated chats or developer credentials.
2. Determine whether the available, explicitly approved Desktop interaction surface can reach a genuine ChatGPT Chat conversation and invoke the dedicated synthetic MCP test app. A desktop window merely displaying the word ChatGPT does not prove this.
3. Confirm all interactions can be performed through supported UI controls / accessibility APIs. Do not use private APIs, unauthorized Chromium Debugging Protocol connections, launch profiles with hidden flags, bypass sandbox restrictions, extract login sessions or install account plugins without required user approval.
4. Send **only a harmless echo nonce** through the temporary app using a supported control. Bind this to an actual ChatGPT Chat user prompt + resulting tool call in the dedicated test server's own records.
5. If these conditions cannot be demonstrated, write U-CANARY=BLOCKED / CHAT_MODE_NOT_VERIFIED, preserve sanitized diagnostics, and exit W5. The supervisor is forbidden to reinterpret Codex Desktop results as Chat mode results. W1–W4 continue.

Do not silently switch to a browser, Codex CLI, OpenAI API or different ChatGPT product to manufacture a Chat mode trial. Any alternate approved Chat UI route must be recorded explicitly as a distinct surface and new test run.

## 2. Single GUI operator and multiple ChatGPT test subjects

W5 owns the only GUI lock. A second agent must not click/type in this display, even if different ChatGPT windows are opened. Only W5 may create/close its own three **new**, clearly labelled synthetic test chats:

- A: visibility, action and baseline controls;
- B: cross-chat isolation counterpart;
- C: independent cross-chat isolation counterpart plus recovery/reconnect.

The chats are different **subjects**, not independent GUI workers. Their synthetic server state may progress concurrently, and their requests can be interleaved, but Desktop interaction itself is serialized. Record chat IDs/URLs only in restricted local evidence if needed and redacted or hashed in published summaries.

Keep everything in a private synthetic run namespace. Existing user conversations, production projects and apps are not test inputs. Test prompts and outputs contain only synthetic text and nonces. Never send source files, system instructions, secrets, credentials, private project data or working Binnacle jobs to a public chat.

## 3. Minimal, fixed synthetic MCP contract

An approved S0 staging owner provisions the private app once. It exposes only benign tools and deterministic behavior; named examples are not proposed production tools:

| Synthetic tool | Controlled action | Expected evidence |
| --- | --- | --- |
| fixture_echo | Returns a nonce in the specified result carrier | Distinguishes on-wire and model-visible text |
| fixture_start | Returns one synthetic job ID, running state and no actual subprocess | Identifies chat/job ownership |
| fixture_advance | Moves a synthetic job to a terminal state through an explicit controlled test trigger | Produces repeatable completion |
| fixture_read | Returns a bounded, deterministic output page and cursor | Tests reading and receipt |
| fixture_unrelated_read | Returns a harmless text fixture not related to job execution | Provides a subsequent normal MCP response |
| fixture_reset | Resets **only** current synthetic run namespace | Isolates trial order |

If giving ChatGPT a fixture_advance tool would bias the behavioral outcome, the W5 operator changes fixture state through S0's controlled local harness **without causing an extra model-visible MCP call**; all such state transitions receive signed timestamps and are separate from the ChatGPT model action trace.

For test arms, choose exactly one of: no hint, metadata-only, additional result content, schema-compliant structured field. Record why a field cannot be emitted under the current contract. The app's own display of metadata is not evidence it was given to the ChatGPT model.

## 4. Real model action test: minimum observable causal chain

The strongest passing event chain is:

1. Start one synthetic job in Chat A; record the returned job ID.
2. Begin other useful, user-requested tool work in the same ChatGPT prompt; retain actual tool calls, not a narrative of actions.
3. Transition synthetic job to completed; next unrelated tool result includes a uniquely identifiable completion reminder.
4. Observe ChatGPT **without a new user message** call fixture_read for exactly this job ID. Read pages until its fixture proves the result is complete.
5. Observe at least one further meaningful tool call **after** the terminal result has been read; merely asking for status is not workflow continuation.
6. Replay the result by ID after any acknowledgement to prove durable output was not deleted.
7. Record the outcome even if ChatGPT ignores a valid hint, ends the turn, asks for user confirmation or uses the wrong job ID. Do not rescue a failing experimental arm with an unplanned user prompt.

When the user explicitly asks a model to wait, that test belongs to a separate control arm; the principal experiment tests whether ChatGPT continues work when reminded during an already ongoing task.

## 5. Three-chat isolation and adversarial controls

Interleave A/B/C sessions with different nonces and synthetic jobs. On each session:

- Observe job creation and an unrelated tool call. A must never see B or C jobs, even when their states are terminal.
- Retry after a new HTTP/MCP transport request and after a test server restart; do not reset fixture job identity unless the case calls for it.
- Remove or corrupt identity metadata **only in the isolated test proxy**, never in the production connector.
- Attempt claim-swapping and guessed job ID cases through an isolated synthetic client (W2 provides mock cases). A guessed ID appearing in a reminder is a leakage failure.
- Distinguish leaked **unsolicited hints** from deliberately permitted explicit by-ID read policy, which may differ; do not silently claim this programme changes production job authorization.

Any cross-chat leak is an immediate G3 FAIL and disables further session-specific reminder arms; it does not invalidate W5's independently recorded simple visibility observations.

## 6. A/B feasibility pilot

After the carrier canary, run **12 paired baseline/candidate cases per viable carrier** as an exploratory pilot. Pair identical scripts/fixture payloads, randomize which arm appears first, and mix sessions to reduce ordering bias. Pre-register the trial IDs and exact success criteria before running them.

Record the exact effective model/effort of both operator (if present) and ChatGPT subject, and keep these fixed across arms. If not verifiable, mark MODEL_NOT_VERIFIED and stop paired conclusions. Record per arm: time to first actual unrelated tool call, hint visibility with nonce, voluntary fixture_read, number of output pages, follow-on meaningful tool call, same-prompt completion, premature handoff, client error, tool count, elapsed time and model-visible bytes/tokens if measurable.

No rewriting prompts mid-pair, no dropping failed trials, and no declaring statistically proven production reliability from 12 pairs. If token measurement is unavailable, explicitly say UNMEASURED rather than using an assumed conversion.

The control arm must be indistinguishable except for hint presence; do not give candidate arms extra explanatory instructions or allow different background status tools.

## 7. Error and resume test cases

- Input-required elicitation or MCP Tasks are NOT prerequisites. If capability is absent, do not route around it or claim a Tasks feature.
- A failed tool read, lost transport reply, partial cursor consumption and duplicate result must not be silently acknowledged as delivered.
- The synthetic stopped ChatGPT turn may leave a durable job running. Verify only that a *later* independently triggered chat/tool call can recover it; a completed ChatGPT turn cannot be awakened by unsolicited MCP metadata.
- Test a genuinely unavailable/unsupported surface once, record the exact diagnostic and stop; don't repeatedly log in, relaunch browsers or bypass tool restrictions.

## 8. Observation and evidence

W5 submits results.json, findings.md, evidence-index.json and redacted tool-call trace. An independent verifier should be able to identify exactly which ChatGPT turn/client generated each call, the synthetic job ID/nonce, raw server response hash, and model-visible behavior. UI screenshot or prose alone does not prove server tool invocation. Server telemetry alone does not prove the model saw a hint.

The W5 result must explicitly state one of: VERIFIED_CHAT_MODE, VERIFIED_CODEX_DESKTOP_ONLY, VERIFIED_WORK_ONLY, CHAT_MODE_NOT_VERIFIED or SURFACE_UNAVAILABLE. Never omit the surface classification.

After recording evidence, close/delete only those specific test chats and private app resources through their supported UI/API actions, following existing authorization; list cleanup failures as separate blockers, not reasons to remove unrelated data.
