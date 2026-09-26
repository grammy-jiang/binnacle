# Chat-mode scheduling v2: retrospective (2026-09-27)

## Result

The programme is closed. Phase 4 ended with the verdict `NO_GO_PERFORMANCE`
on 2026-09-27 04:24. The selected candidate C300 (300 s blocking budget) is
correct and safe, but it is not fast enough for the pre-registered gates.
Nothing from v2 is deployed; production still runs `master`.

| Phase | Outcome |
| --- | --- |
| 0-1 | Baseline frozen, pilots done (2026-09-23) |
| 2 | Blocking-wall guard built on `feature/chat-mode-blocking-wall-guard`, not merged |
| 3 | Closed 2026-09-25 11:48 (r02, Amendment A1): C300 is the sole live candidate |
| 4 | Closed 2026-09-27 04:24: `NO_GO_PERFORMANCE`, 20 of 26 required gates pass |
| 5 | Speculative preparation discarded under Amendment P5-A1 (2026-09-27 04:26-04:27) |
| 6 | Not started |

## What the confirmatory run measured

160 canonical slots (A 53, B 53, C 54), all submitted and scorable, plus the
historical comparator H (10). Routing misses: A 1/54, B 0/53, C 0/53, H 0/10.

C passes every correctness and safety gate: 100 % correctness, no premature
handoff, 53/53 same-prompt completions. The six failed gates:

| Gate | Required | C/A measured |
| --- | --- | --- |
| Overall median wall | <= 0.80 | 0.933 |
| Read-heavy (R1/R2/R11) median wall | <= 0.70 | 0.803 |
| Mixed-long (R3/R4) median wall | <= 0.80 | 1.141 |
| Category regression | <= 10 % slower | R3/R4 exceed it |
| Eligible read-only overlap | >= 80 % | 53.5 % |
| Manual-continuation reduction | >= 80 % | undefined: A needs none |

The paired C/A bootstrap (53 pairs, 10 000 samples) gives a median ratio of
0.980 with a 95 % interval of [0.936, 0.997]. C is faster, but by a few
percent.

| Scenario | A median (s) | C median (s) | C/A |
| --- | --- | --- | --- |
| R1 | 24.0 | 19.6 | 0.81 |
| R2 | 20.4 | 17.6 | 0.86 |
| R3 | 45.2 | 45.3 | 1.00 |
| R4 | 107.2 | 106.8 | 1.00 |
| R5 | 40.0 | 38.4 | 0.96 |
| R6 | 103.9 | 105.0 | 1.01 |
| R8 | 31.5 | 33.2 | 1.05 |
| R9 | 52.5 | 55.0 | 1.05 |
| R10 | 104.9 | 104.1 | 0.99 |
| R11 | 31.2 | 30.6 | 0.98 |

## Why the performance gates failed

- **The addressable part is small.** For A, the median trial takes 45.2 s:
  14.6 s of tool activity and 28.9 s of model time, network and page
  overhead. A server-side scheduler can only change the tool part. A 20 %
  overall gain needs about 9 s, which is most of the tool time.
- **Fixed-duration jobs bound the long scenarios.** R4, R6 and R10 take
  about 105 s because their fixture jobs run for a fixed time. No schedule
  shortens them.
- **Overlap depends on the client.** The server can only overlap calls that
  ChatGPT sends together. Only 53.5 % of eligible read-only calls overlapped.
- **The big gain was already taken.** The historical build H needed a manual
  continuation in 9 of 9 bounded trials. The current build A needs none. The
  earlier chat-mode work delivered that; v2 had only speed left to win.

The gates were set before anyone measured this ceiling. That is the main
lesson.

## Lessons

1. **Measure the ceiling first.** Before a performance gate is fixed, split
   the baseline wall time into the part the change can affect and the rest.
2. **Rehearse the frozen analysis.** Run the confirmatory analyzer end to end
   on a qualification population before the confirmatory run. Defects D7
   (argument matching, P4-A3) and D10 (population, status, timing, P4-A6)
   were found only after the data was in.
3. **The ChatGPT platform is part of the test system.** Plan for read-path
   throttling (HTTP 403/429), UI changes (2026-09-26 composer and turn
   markup), routing that the system hint prefers but does not force (P4-A2),
   and turns cut off after about 40-45 minutes.
4. **Take timing from the conversation.** Use the final assistant message's
   own timestamp (P4-A5). When a timing is recovered later, regenerate every
   file derived from it (D10c).
5. **Take the send gate before the fixture starts.** The harness started the
   fixture jobs and then queued for the send gate; a queued M3 micro was
   invalid because its 300 s job had ended.
6. **Run live trials through one runner.** A chat that ran the harness
   directly lacked the runner's environment and failed before submission.
7. **Name the connector on every send.** A chat whose brief talked about
   staging used the staging connector (Step 4.13).

## What remains, and where

- Branches, not merged: `planning/chat-mode-scheduling-v2-phase3-6`
  (plans and amendments), `feature/chat-mode-scheduling-v2-phase4` (Phase-4
  code, evidence and reports, final head `0b5b593`),
  `feature/chat-mode-blocking-wall-guard` (Phase 2),
  `design/chat-mode-scheduling-v2` (test-suite performance work). Phase-5
  preparation is archived by the tags
  `archive/chat-mode-scheduling-v2-phase5-instructions-2026-09-27` and
  `archive/chat-mode-scheduling-v2-phase5-operational-2026-09-27`.
- Phase-4 report:
  `benchmarks/chat-mode-scheduling-v2/phase4-live-confirmatory-2026-09-27-r01.md`
  and `phase4-hard-gate-matrix.json` on the Phase-4 branch.
- Trial evidence: `~/.local/state/binnacle/chat-scheduling-v2/` (runs, run
  requests, completions, checkpoints).
- Removed: the staging server, its connector and tunnel (P5-A1, record in
  `phase5/discard-p5a1-20260927/`), and the four Phase-4 lane connectors and
  tunnels A/B/C300/H (owner request, record in
  `phase4/discard-lanes-20260927/`).
- Still present in ChatGPT: the lane Projects `rp-sched-A`, `rp-sched-B`,
  `rp-sched-C300` and `rp-sched-H`, and the manager Projects that hold the
  development chats.

## Next

Model time is about two thirds of a typical trial. The next work reduces the
number of model round trips per task instead of the tool wall time, through
the `mcp-usage-review` loop: measure calls per task from the journal, rank
tool changes by the calls they absorb, implement, verify in a real chat, and
record a baseline.
