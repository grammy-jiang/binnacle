# S0 immutable fixtures and independent comparison contract

Status: **specification only, no fixture server created**. This document is the single source for per-lane synthetic inputs, so W1–W5 can start in parallel after one short S0 preparation.

## 1. Golden envelope and carrier choices

S0 creates one canonical no-reminder response for each synthetic tool (echo/status/result) and three alternative outputs that differ **only** in carrier placement:

| Arm | Hint placement | Expected interpretation |
| --- | --- | --- |
| CONTROL | No reminder anywhere | Baseline schema/text |
| META | Native MCP result metadata only, where supported | Test app/framework data; must NOT assume model visibility |
| TEXT | Additional short text content block | Candidate model-visible reminder if accepted and displayed |
| STRUCT | Additive property in structured result if schema explicitly admits it | Fail/mark unavailable if schema would have to change |

All reminders use identical semantics: bounded synthetic job ID and either running or finished_unfetched, with no process command, workdir, stdout or secret. All variants include the same nonce and fixed output length bounds. W1 checks legitimate MCP/FastMCP encoding, W4 measures all technically encodable arms, W5 independently observes visibility.

An example candidate user-visible hint is:

~~~text
Pending jobs:
- ja-RUN-001: running
- ja-RUN-002: exited, result not fetched
~~~

This is illustrative content, **not** a new production wire/schema field or a promise that the model receives it. The real synthetically generated IDs are run-scoped and short.

## 2. Fixture inventory

| Fixture | Seeded lifecycle/output | Intended checks |
| --- | --- | --- |
| J-OK | running → exited/exit 0; two bounded result pages | Completion, multi-page delivery, acknowledgement, replay |
| J-FAIL | running → exited/exit 3; diagnostic output | Failure semantics, no false success |
| J-QUIET | running with no new output; later terminal | Repeated running hints without busy polling |
| J-UTF8 | valid UTF-8 split across page boundaries | Cursor integrity, no data loss or replacement |
| J-BIG | synthetic output above single response cap | Bounded hint, incremental pagination |
| J-UNKNOWN | unexpected owner disappearance, durable unknown | No false terminal-success acknowledgement |
| J-LOSS | output served by server, response intentionally dropped by isolated test transport | Distinguish serving from client receipt |
| J-EXPIRED | fixture removed/pruned under controlled test | Retention error and no fabricated success |
| J-CROSS | distinct A/B/C chat-scoped IDs with same timing | Leakage and spoofed identity negatives |
| J-RESTART | state retained under test server restart | Recovery and manager-neutral continuation |

Each fixture must have a unique nonce, job_id, owner-chat label in the S0 **test model only**, deterministic state-transition action, stdout SHA-256 and number of expected bytes/pages. Generated test data must contain no real user projects or credentials.

## 3. Required synthetic state API semantics

The test harness supplies:

- start: returns job ID, running state, no subprocess;
- status: reads a deterministic immutable snapshot; can optionally show short hint;
- advance: the staging owner/test controller triggers a timestamped transition (never a signal to real processes);
- unrelated read: returns unchanged harmless text and may carry a reminder;
- result read: returns one output page, byte start/end, opaque cursor, has_more and lifecycle state;
- reset: isolates only one trial namespace, with a fresh nonce; cannot alter other trials.

This API may be named fixture_start/fixture_read/fixture_unrelated_read in the staging app. It is a disposable probe surface and must not be installed in production.

Use a read-only or explicitly scoped synthetic result backend. Receipt state, if modeled, is independent from JobStore and must never delete the result payload. Do not silently infer delivery from an unacknowledged server result.

## 4. Candidate message generation and eligibility

For each test call:

1. Resolve synthetic authenticated/verified chat label **if one is demonstrably available**. If not, record UNTRUSTED_IDENTITY, output no chat-specific hint and stop any security-sensitive arm.
2. Enumerate only the current chat's running and finished-unfetched fixtures. Order finished-unfetched first, then running, by stable job ID; deterministic selection matters for A/B comparison.
3. Truncate by bounded job count and total 512-byte proposed limit; do not emit stdout, command or path. Record number omitted so W4 can detect starvation.
4. Keep running hints eligible on subsequent unrelated tool calls regardless of status changes. A finished result is only suppressed according to the exact, experimentally defensible receipt mechanism under test.
5. No hint on failed authentication, visibility denial, tool validation failure or an explicitly unsupported carrier.

Do not use the same mock backend state for multiple workers: each receives an immutable seeded copy. W5 alone owns the GUI-visible mock app's data.

## 5. Experiment trial schedule

S0 pre-registers trial indices 01–12, pair ordering, condition assignment, target chat, fixture ID, nonce and expected successful independent-work step. The order seed is recorded and is not chosen after seeing outcomes.

W5 explicitly selects and holds ChatGPT Chat GPT-6/Medium for the entire experimental cohort; if this cannot be verified in Chat UI, paired tests are BLOCKED pending a newly approved fixed model/effort. W5 runs the same 12 paired tasks for each technically promising carrier. A single pair differs only in reminder presence, not instruction wording, task complexity, tool schema, or synthetic data. Record every attempt, including errors, user handoffs and timeouts.

Suggested invariant task:

> Use the synthetic fixture service to start task J-OK, then independently read and compare two harmless reference fixtures. When a job result becomes available, collect all pages and then perform one further fixture read that checks the original user objective. Complete within the current user prompt if possible; do not fabricate completion or ask for an extra Status message.

That task is intentionally non-sensitive and can be reproduced without browser secrets or repository writes.

## 6. Run manifest fields

S0's immutable run manifest includes RUN_ID, SOURCE_SHA, lockfile digest, FastMCP/MCP/runtime versions, FIXTURE_SHA, full fixture nonce/owner map (restricted), seeded A/B schedule, carrier envelope hashes, named test app/port/transport, separate worker evidence roots and exact cleanup ownership.

Raw owner/chat labels can be used only inside the private staging fixture backend; evidence destined for Git/GitHub uses opaque run-scoped pseudonyms and no bearer/token values.

The fixture manifest is immutable during fan-out. If W1 finds a protocol carrier invalid, it returns FAIL. It must not delete the carrier from W5's matrix or mutate the signed fixture snapshot. If a fixture is broken, the S0 owner declares a new RUN_ID rather than modifying input to only one lane.
