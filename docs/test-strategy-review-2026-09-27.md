# Test strategy review and plan (2026-09-27)

> **Correction, later on 2026-09-27 (owner):** binnacle meets its coverage
> policy in full: 99 of 99 production modules, 0 below target
> (`scripts/check_coverage_policy.py` on the reports measured below), and
> 96.50 % branch coverage for the whole package. The policy in
> `docs/testing.md` is the owner's rule: each core module reaches 95 % from
> the unit suite; each other module reaches 90 % from the full suite. The
> "gaps" in sections 3 and 5 came from two things this review added:
> measuring the other modules with the unit lanes only, and a proposal to
> grow the core list to 27. Both are withdrawn, and so are questions 1 and 2
> in section 7. The policy stays as it is. The ChatGPT client work (the
> browser tools, their copies of the session module, the end-to-end cadence)
> moved to the chatgpt-web-operations skill (`PLAN-2026-09-27.md` there).

Status: plan for the owner's decisions (section 7). Measured on `master`
`4b7cfb4` with `scripts/run_coverage_policy.py` (unit lanes: 376 tests;
non-unit lanes: 846 tests, 3 skipped).

## 1. Why this review

Three breakages in two days passed every test suite:

| Date | What broke | Cause |
| --- | --- | --- |
| 2026-09-26 | `chatgpt-send` (this repo) | ChatGPT's new composer (`div.ProseMirror`); the skill was fixed the same morning, this repo's copy was not |
| 2026-09-27 | `chatgpt-refresh` (this repo) and the skill's session | Chrome held an empty `_dd_s` analytics cookie; the strict cookie decoder exited |
| 2026-09-27 | the new `chatgpt-send` wrapper | an HTTP read before the post starved the post of its time budget under read-path throttling |

The suites did their job for changes to our code. They missed these because:

1. **External drift is invisible to fakes.** The tests use fake pages and
   fake cookie jars that encode yesterday's ChatGPT and yesterday's Chrome.
2. **The broken code is outside the gate.** Coverage measures `src/binnacle`
   only. `scripts/` (4,876 lines) and `.claude/skills/` (2,896 lines) are not
   measured; `chatgpt-send` had 3 tests, none of them touched a page.
3. **The same code exists twice.** This repo's ChatGPT browser tools are an
   old copy of the chatgpt-web-operations skill (a 243-line session module
   here, 1,002 lines in the skill). The skill's fixes did not reach the copy.
4. **A fix covered only some paths, and a test fixed the wrong behavior.**
   The skill's tolerant cookie decoder existed since 2026-09-20 but not on
   the session path; the session tests injected fake decryptors, and one test
   asserted the too-strict behavior.
5. **The live checks run too rarely and too narrowly.** The skill's HTTP check
   runs daily at 05:25; its browser check runs on Fridays only (the UI changed
   on a Saturday). No live check covers this repo's copies. This repo's own
   live smoke (`tests/live/`) runs only by hand.

Also found during the audit: `test_search_text_stream_reduce.py::
test_stream_reducer_property_equivalent_to_materialized` failed once on a
Hypothesis `too_slow` health check while the host was loaded. A test that
fails on load is a defect.

## 2. Principles

From the owner (2026-09-27):

- **P1** Unit tests cover each core module to at least 95 % (branch), each
  module separately; never an average.
- **P2** Unit tests cover each other module to at least 90 % (branch), each
  module separately.
- **P3** More kinds of tests than unit tests, end-to-end included.

Derived from the findings in section 1:

- **P4** Every maintained module is inside the gate. No code that runs in
  production or in the development loop is unmeasured.
- **P5** One implementation per behavior. A copy is deleted, not synced.
- **P6** Every external boundary has a real-path test (real code, realistic
  data, no injected fake at that boundary) and a live canary.
- **P7** A flaky test is a defect: it is fixed or quarantined within a week.

## 3. Current state

The policy already exists: `quality-policy.json` and
`scripts/check_coverage_policy.py` apply a per-module gate in CI (core: 95 %
from the unit lanes; other: 90 % from the full suite). Two differences from
P1/P2, and two scope gaps:

| Area | Modules | Meets the owner's rule | Does not |
| --- | --- | --- | --- |
| Core list today (95 %, unit) | 14 | 14 | 0 |
| Proposed core additions (95 %, unit) | 13 | 4 | 9 |
| Other modules (90 %, unit only) | 72 | 23 | 49 |
| Other modules (90 %, full suite, today's rule) | 72 | 72 | 0 |
| `scripts/` and `.claude/skills/` code | not measured | - | - |

The 9 proposed core modules below 95 % by unit tests are the request path:
`tools/job_status.py` 13.9 %, `jobs.py` 21.3 %, `tools/run_command.py`
32.1 %, `logging_middleware.py` 35.6 %, `tools/stop_job.py` 66.7 %,
`job_manager.py` 66.8 %, `tools/edit_file.py` 89.8 %, `tools/write_file.py`
90.6 %, `tools/search_text.py` 94.9 %. Integration tests cover them (93.7 %
to 100 % in the full suite), but a regression shows up only as a failure of a
slow, broad test.

Of the 49 other modules below 90 % by unit tests, 36 (the watchdog, doctor,
uplink and tunnel modules) have 0 % in the unit lanes because their tests live
in `tests/system/`. Those tests run in-process against fake NetworkManager,
systemd and probes; they do not touch the host. The rest: 5 job modules
(`job_owner`, `job_store`, `job_process`, `job_client`, `indexed_context`),
4 assembly modules (`server`, `cli`, `visibility`, `search_text_register`)
and 4 statistics modules.

## 4. Test types: target set

| # | Type | Catches | Runs | Today |
| --- | --- | --- | --- | --- |
| 1 | Unit (isolated, per-module gate) | logic regressions, with a precise failure | pre-commit subset, CI | exists; definition, core list and scope change (section 5) |
| 2 | Property-based | edge cases no example lists | CI | 4 areas; add journal parsing, config compatibility, cookie decoding |
| 3 | Contract (surfaces, schemas, descriptions) | a client-visible change made by accident | CI | exists; pin every tool's surface as run_command's is pinned |
| 4 | Integration (HTTP with auth, CLI, jobs, config) | components that do not fit together | CI | exists |
| 5 | System with fakes (watchdog, doctor, uplink) | host-behavior logic | CI | exists |
| 6 | Real-path boundary tests | a fake that hides the real path (the cookie case) | CI | new rule: one per external boundary |
| 7 | Recorded external fixtures | drift in ChatGPT pages and API shapes, journal lines | CI; refreshed by the canaries | new |
| 8 | Post-deploy smoke | a deploy that breaks the live server | after every master fast-forward | manual today; make it part of the deploy step |
| 9 | Live read-only checks (`tests/live/`) | a live server that stopped working | daily | exists, never scheduled |
| 10 | End-to-end through ChatGPT | the full chain: refresh, send, tool call, journal, reply | required for every tool-surface change; weekly | manual today; script it |
| 11 | External canaries | ChatGPT UI, cookies, session, tunnel | daily (browser included) | HTTP daily; browser weekly (to change) |
| 12 | Mutation testing | tests that execute code but assert nothing | weekly, core modules, one module per run | on demand today |
| 13 | Performance budgets | slower tools or a slower suite | CI (suite time); weekly (tool p95 from the journal) | suite timing exists; tool budgets new |
| 14 | Fault-injection drills | recovery paths that only run in a real fault | after watchdog changes; quarterly | done by hand on 2026-09-14 |
| 15 | Client compatibility | a change that breaks Claude Code, Codex or Copilot | monthly; after surface changes | the conformance probe exists; not scheduled |

## 5. Decisions the plan proposes

- **What counts as a unit test.** Proposal: a test that runs in-process with
  no real network, no running server, no real subprocess of the product and
  no host mutation, whatever its directory. The fake-based `tests/system/`
  tests then count toward P2; tests that start the HTTP stack or a real
  subprocess do not. The unit lanes select by marker, not by directory.
  Alternative: only `tests/unit/` counts; then the 36 watchdog, doctor and
  tunnel modules need new or moved tests.
- **Core list, 14 to 27 modules:** add the request path: the 8 tools, `jobs.py`,
  `job_manager.py`, `logging_middleware.py`, `search_text_stream.py` and
  `search_text_adaptive.py`.
- **Scope:** `scripts/` enters the gate at 90 %. The ChatGPT browser tools
  leave this repo's copy and call the skill (P5), which has its own 95/90
  per-module gate; the remaining `.claude/skills/` scripts enter the gate at
  90 % or move into `scripts/`.
- **Other modules:** measured by the unit lanes (P2), not by the full suite.
  Temporary floors hold every module at today's value until it reaches its
  target, and only rise.

## 6. Work plan

| Phase | Work | Exit criterion |
| --- | --- | --- |
| 0, now | `chatgpt-send` on the skill's sender (in progress); daily browser canary; real-path cookie tests in the skill; fix the flaky property test | a real send passes; the canary runs daily; no flaky failure in 20 loaded runs |
| 1, 1 day | policy: the unit marker and lanes, the 27-module core list, `scripts/` in scope, temporary floors; `docs/testing.md` and `docs/quality-gates.md` updated | CI enforces the new policy with floors |
| 2, 1-2 weeks | unit tests for the 9 request-path core modules to 95 %; the other modules to 90 % in the unit lanes; `scripts/` to 90 %; the remaining ChatGPT tools (`chatgpt-refresh`, `chatgpt-chats`, `chatgpt-project`) on the skill, and this repo's `chatgpt_session.py` deleted | no temporary floors left |
| 3, about 3 days | post-deploy smoke in the deploy step; daily `tests/live/` through `cron-report`; a scripted ChatGPT end-to-end check (refresh, nonce send, journal assert) required for surface changes and run weekly; recorded ChatGPT fixtures refreshed by the canary | each check runs on its schedule and mails on failure |
| 4, ongoing | weekly mutation runs on core modules (kill rate at least 80 %); weekly tool p95 budgets; a quarterly fault-injection drill; a monthly client-compatibility probe | results recorded in `docs/` |

## 7. Questions for the owner

1. Which definition of a unit test (section 5): by isolation (proposed) or by
   directory?
2. Is the 27-module core list right?
3. May the ChatGPT browser tools leave this repo for the skill (P5)?
4. How often may the ChatGPT end-to-end check run (it uses your ChatGPT
   quota): weekly and on surface changes, as proposed?
