# Search-text structured-result budget — usage analysis, 2026-09-19

## Scope

This review addresses only `search_text` result size. The journal retained by
`binnacle-mcp` begins 2026-08-26; per-call `structured_bytes` telemetry is
usable for `search_text` from 2026-09-14 onward. No production behavior was
changed during the measurement phase.

## Evidence

682 successful sized `search_text` results were observed from 2026-09-14
through the analysis. Result-size distribution by the existing chars/4 estimate:

- p50 1,611 tokens; p75 3,938; p90 8,875; p95 15,473; p99 38,733.
- 135 results (19.8%) exceeded 5k estimated tokens.
- 62 (9.1%) exceeded 10k; 23 (3.4%) exceeded 20k; 2 exceeded 50k.
- the largest result was 655,605 structured bytes, logged as 162,398 estimated
  tokens. A replay with `o200k_base` measured the current equivalent at about
  170k tokens, so chars/4 is useful for ranking but not a hard tokenizer bound.

The long tail is concentrated in explicit-context searches. `names_only`,
`context_lines=0`, and auto-context produced no >64 KiB results in this window.
The implementation duplicates overlapping context per match; replaying large
queries found 9–50% of context characters could be removed by perfect overlap
de-duplication, but even that would leave the largest searches far too large.
A total result budget is therefore the primary control; context representation
changes remain deferred.

## Budget sensitivity

Using the observed structured-byte sizes:

| budget | calls affected | share | total search bytes removed |
| ---: | ---: | ---: | ---: |
| 48 KiB | 55 | 8.05% | 25.24% |
| 56 KiB | 44 | 6.44% | 21.55% |
| **64 KiB** | **39** | **5.71%** | **18.58%** |
| 72 KiB | 32 | 4.69% | 15.88% |
| 80 KiB | 25 | 3.66% | 13.76% |
| 88 KiB | 17 | 2.49% | 12.24% |
| 96 KiB | 15 | 2.20% | 11.10% |

On surviving historical worktrees, prefix replay showed 48 KiB was materially
more aggressive for cross-file discovery. At 64 KiB no replayed affected case
retained fewer than one quarter of its entries; median file coverage was about
83%. 96 KiB retained more, but exact-token replay of representative payloads
put 96 KiB at ~21.8k–24.6k model tokens, versus ~14.6k–16.7k at 64 KiB.

Behavior also supports bounding the broad result: of the 39 historical results
above 64 KiB, 35 (about 90%) were followed within four tool calls by another
`search_text` or `read_file`; 15 immediately narrowed the search path. The
broad result is primarily a discovery step rather than a corpus dump.

## Decision

Use **65,536 UTF-8 bytes** as the default maximum compact structured result.
The setting is server configuration (`search_text.result_max_bytes`), not an
MCP input parameter, so the public input schema and its standing token cost do
not change. `max_results` remains independent: it limits count; the byte budget
limits payload size.

When the byte budget binds, preserve order and return the largest complete
prefix of entries that fits together with the narrowing note. Keep the full
match count, set `truncated=true`, and direct the model to narrow pattern/path/
glob, reduce context, or use `names_only`. If the first contextual entry alone
cannot fit, retain its match identity without context and point to `read_file`.

The implementation logs a separate `event=search_budget_hit` with the correlated `call` id, final bytes, configured
budget, returned entry count, total match count and mode.
This adds no fields to the MCP response. A future usage review should measure
hit rate, follow-up calls and whether 64 KiB causes repeated narrowing loops.

## Explicit non-goals

- No new MCP tool or input parameter.
- No global reduction of `max_results`.
- No context-region schema redesign or overlap de-duplication in this change.
- The result budget limits what the model receives; it does not claim to cap
  the internal rg event/context working set. No real log showed an internal
  memory problem, so that larger refactor is not justified by current evidence.

## Implementation validation

The implementation was developed in an isolated filesystem snapshot of the live
repository because the production checkout currently tracks only nine bootstrap
files in Git; `src/`, `tests/`, `docs/` and the rest of the running server are
untracked there. No production server file was changed during this work.

Five replayable historical large searches were run through the 64 KiB build:

| historical call | old structured bytes | old estimated tokens | new bytes | exact new `o200k_base` tokens | returned / total |
| --- | ---: | ---: | ---: | ---: | ---: |
| `7298006c3d4a` | 655,605 | 162,398 | 64,837 | 15,052 | 56 / 3,304 |
| `c6c5b736ea6e` | 193,886 | 48,421 | 65,273 | 16,408 | 168 / 5,013 |
| `7dcd26e0773b` | 134,043 | 33,523 | 64,534 | 14,957 | 55 / 199 |
| `9b9414c78640` | 105,269 | 26,347 | 65,293 | 16,582 | 122 / 789 |
| `96c5d2446cf9` | 111,262 | 27,835 | 65,449 | 15,752 | 81 / 152 |

Every replay stayed below 65,536 bytes and retained the full match count plus a
narrowing note. A normal small search was run once with the pre-change snapshot
and once with the new implementation; the compact structured payloads were
byte-for-byte identical (502 bytes).

Targeted `search_text` tests cover UTF-8 byte accounting, normal-result identity,
entry ordering, `max_results` interaction, names-only results, a context block
larger than the budget, metadata that cannot fit, and correlated budget-hit
logging. The final targeted gate is **26/26 on every Python 3.10 through 3.14**.
On Python 3.13 the final full suite is **549 passed**, project branch coverage is
**88.22%** against the 86.9% gate, and `search_text.py` branch coverage is
**92.74%**.

The all-project Python 3.14 run exposed one pre-existing differential-test
defect: `paths.full_match('a', '[^]')` raises `ValueError` while Python 3.14's
`PurePath.full_match` supplies the reference behavior. The exact failure was
reproduced against the pre-change snapshot, so it is not caused by this change
and is intentionally left for a separate maintenance round. A concurrent-stop
test also failed once in the noisy matrix run but passed immediately when rerun
in isolation. Neither issue touches the `search_text` budget path.

## Production integration

The verified implementation was copied to the live `binnacle` tree on
2026-09-19 after a byte-for-byte drift check confirmed that every existing
target file still matched the research snapshot baseline. A rollback copy was
created under `/tmp/binnacle-before-search-budget-20260919T095705`. WatchFiles
reloaded the server once and the replacement process reported a normal startup.
The live targeted suite passed 26/26. The MCP public tool signature and
description did not change, so no connector schema refresh was required.

Two live broad-search checkpoints used the historical Topic 01 query that had
previously produced a 655,605-byte result. The local MCP client returned 3,304
matches / 58 entries at `structured_bytes=63024`. A real ChatGPT `openai-mcp`
call then returned 3,304 matches / 59 entries at `structured_bytes=63243`; both
set `truncated=true` and emitted the narrowing note. The ChatGPT call journal
record was correlated as `call=592ba7dad6f3`, with the matching
`search_budget_hit` event carrying the same id. This closes the production gate.

## Deferred follow-up: indexed repository retrieval

During this review the user proposed a separate repository-aware retrieval tool:
pre-build a path/worktree-scoped index combining BM25/full-text relevance with
code structure and dependency/call relationships, so an agent can retrieve a
small related-context package in one call instead of doing a broad grep followed
by several narrowing searches. This is deliberately **not** part of the current
`search_text` result-budget change.

If revisited, evaluate it offline first against real `binnacle` history: use broad
`search_text` calls as queries and the files/symbols subsequently searched or read
as relevance evidence. Start with SQLite FTS5/BM25 plus Python AST symbol/import/
call relationships; measure Recall@K/MRR, payload bytes, first-hop usefulness,
index build/update cost, worktree freshness and downstream tool-call reduction.
Only expose a new MCP tool (tentative role: `retrieve_context`) if it clearly
reduces total calls/context enough to justify the permanent tool-schema cost.
