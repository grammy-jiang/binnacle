# Single-job `job_status` command-preview A/B — 2026-09-21

## Scope

This local replay evaluates one change only: use the existing
`jobs.listing_command_preview_chars` head+tail command preview for
`job_status(job_id=...)`, instead of returning the complete launch command on
every status/wait response. Log tails, process details, workdir, paths, polling
semantics and the MCP schema are unchanged.

The candidate branch was created from `proof-of-concept` at `c45164c`.

## A/B populations

Two complementary populations were used.

1. **Exact retained-job replay**: the current 50 durable job records were
   serialized twice with the real `job_status` payload builder shape:
   A = complete command; B = the existing 160-source-character head+tail
   `_command_preview`. Token counts used `tiktoken` `o200k_base`.
2. **Historical validation**: OpenAI MCP journal records from 2026-09-14 onward
   were joined from single-job `job_status` results back to the originating
   `run_command`. This checks whether the retained 50-job sample is atypical.

No production/POC behavior was changed during the replay.

## Exact replay result

There were 50 retained jobs, one running, and no collisions among their
160-character command previews.

At the normal `tail_lines=100`:

| Variant | `o200k_base` tokens |
| --- | ---: |
| A — full command | 68,326 |
| B — 160-char preview | 42,110 |
| **saved** | **26,216 (38.4%)** |

The command saving itself is independent of `tail_lines`; its share of the full
payload naturally falls when a much larger log tail is requested:

| tail lines | A | B | reduction |
| ---: | ---: | ---: | ---: |
| 40 | 59,819 | 33,603 | 43.8% |
| 100 | 68,326 | 42,110 | 38.4% |
| 220 | 76,428 | 50,212 | 34.3% |
| 500 | 94,437 | 68,221 | 27.8% |
| 1,000 | 122,918 | 96,702 | 21.3% |

At 100 lines, the 50 commands had median 1,347.5 source characters, p90 4,946
and maximum 6,282. Commands longer than 2,000 characters accounted for 19,515
of the 26,216 saved tokens. Commands already at or below the preview limit are
effectively unchanged.

## Historical validation

From 2026-09-14 onward, 1,543 single-job OpenAI MCP status calls could be joined
to their originating `run_command`.

Because the journal deliberately clips argument text, exact historical command
content is unavailable for the long cases. A conservative lower bound reserves
220 characters of every `run_command.args_chars` value for JSON keys and
non-command arguments. Even under that deliberately conservative assumption:

- repeated command characters before preview: at least 1,550,244;
- after a 160-character preview: at most 142,725;
- avoidable repeated command characters: at least 1,407,519 (90.8% of the
  command-character component).

The 996 calls whose originating command remained fully visible in telemetry had
median 132 command characters and p90 285, confirming that the retained-job
replay intentionally captures the expensive long-command tail while the
historical population contains many cheap short commands too.

## Decision

The local A/B supports switching the POC single-job result to the existing
preview representation:

- no new MCP parameter or schema field;
- no change to job lifecycle, waiting, process inspection, log tail or workdir;
- short commands remain intact;
- long launch scripts no longer get retransmitted on every poll;
- existing preview code and configuration are reused.

Regression validation after the one-line implementation change:

- focused job integration/lifecycle suite: 61 passed;
- full suite under a hermetic repository-default config: 858 passed, 3 skipped.

A first full-suite attempt inherited the development machine's enabled
`search_text.adaptive_discovery` setting and failed three unrelated legacy
search-budget assertions. Re-running with an empty test config passed; no
`search_text` code was changed for this work.
