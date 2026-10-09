# Indexed `@context` development pilot

Status: **removed on 2026-09-28** (see "Closing: benchmark and removal" at the
end). The sections before it describe the pilot as it ran from 2026-09-19 to
2026-09-28. The code is kept by the tag `archive/indexed-context-pilot-2026-09-28`.

## Purpose

The pilot tests whether explicit repository-indexed discovery reduces real ChatGPT
search/read chains without degrading investigation quality. It is **not** automatic
routing: the indexed path is used only when `pattern` begins with `@context` followed by a space and
`fixed_strings=false`.

The final offline/agent research that motivated the pilot is in the separate
`binnacle-indexed-retrieval-poc` repository. The strongest manually curated A/B kept
quality at 8/8 vs 8/8 while reducing tool-result tokens ~24%, logical model input
~42%, reported Claude cost ~25%, API time ~17%, calls ~13%, and turns ~12%.

## Public behavior

Exact search is unchanged:

```text
search_text(pattern="CompletionBudget", path="~/Projects/voice-input")
```

Indexed discovery is explicit:

```text
search_text(
  pattern="@context where is the stop-to-delivery completion deadline enforced?",
  path="~/Projects/voice-input",
)
```

During this pilot, `path` must resolve to the Git worktree root. Indexed mode rejects
`glob`, `names_only`, and non-zero `context_lines`; use normal regex search when those
controls are required. `fixed_strings=true` always forces literal behavior, so a
literal string beginning with `@context` followed by a space remains searchable.

The result reuses the existing `search_text` schema. Entries are absolute file paths
with line, symbol/kind/provenance label, and bounded excerpt. The internal package is
bounded by configuration (default 8.5 KiB before the normal search-surface mapping).

## Configuration

Repository defaults keep the feature off. This development machine enables it in
`~/.config/binnacle/config.toml`:

```toml
[indexed_context]
enabled = true
reconcile_on_query = true
max_open_indexes = 2
```

Other settings live in `IndexedContextSettings`:

- `index_dir`: persistent per-worktree SQLite DB directory;
- `relation_items`: related/provenance item budget (default 8);
- `lexical_items`: direct lexical item budget (default 2);
- `snippet_chars`: excerpt cap per item (default 700);
- `package_max_bytes`: internal context package cap (default 8,500 bytes);
- `max_open_indexes`: LRU open SQLite connections (default 2);
- `reconcile_on_query`: verify the persistent index against the live worktree before
  each indexed query.

## Freshness and storage

Each Git worktree has a persistent SQLite/FTS5 index under the configured index
directory, keyed by a SHA-256 prefix of its canonical root. Opening an existing DB is
cheap; the service holds only a small LRU of open connections.

For the development pilot, every `@context` query performs a correctness
reconciliation before retrieval. This intentionally favors correctness and clean
measurement over the later watcher fast path. The journal records reconciliation
cost separately, so we can decide whether watcher integration is worth enabling.

## Telemetry

Every `search_text` call emits:

```text
event=search_dispatch call=<id> mode=exact|indexed path_hash=<12hex> pattern_chars=<n>
```

A successful indexed call additionally emits one `event=index_context` line with:

- correlation: `call`, `root_hash`, `query_hash`;
- source state: `head`, `generation`;
- open/freshness: `cold_open`, `open_ms`, `reconcile_ms`, `freshness_ms`,
  `changed_files`, `deleted_files`, `hashed_files`;
- retrieval latency: `query_ms`, `surface_ms`, `total_ms`;
- index scale: `files`, `nodes`, `edges`, `db_bytes`;
- response shape: `related_items`, `direct_items`, `package_items`, `package_bytes`,
  `package_est_tokens`;
- `evidence_hashes`: hashes of returned absolute file paths, allowing later
  `read_file`/file-scoped exact-search calls to be matched without logging query or
  source content.

Failure emits `event=index_context_error` with `call`, `root_hash`, `phase`,
`error_class`, clipped `error`, and `total_ms`. There is no silent fallback to regex;
a failed indexed call remains visible as a failed indexed call.

The existing middleware still emits `tool_call` and `tool_result` with `turn=`,
`structured_bytes`, estimated result tokens, outcome, and duration. This is what lets
one indexed first hop be joined to later searches/reads in the same ChatGPT turn.

## Review commands

The normal operational entry point is the existing stats subcommand:

```bash
binnacle stats --since "7 days ago"
```

When the selected journal window contains indexed calls, `binnacle stats`
automatically appends an `indexed context pilot` section. Windows without indexed
data keep the old stats output unchanged.

For per-call rows or machine-readable review, use the detailed front end (it shares
the same `binnacle.observability.logstats` analysis implementation; it is not a second stats
engine):

```bash
scripts/analyze_indexed_pilot.py --since '7 days ago'
scripts/analyze_indexed_pilot.py --since '2026-09-20' --json > /tmp/indexed-review.json
```

The indexed section/analyzer reports:

- indexed successes/errors and error phase;
- cold opens and changed-file count;
- result tokens/package bytes;
- total/reconcile/query latency distributions;
- follow-up calls/exact searches/reads and their result-token cost;
- evidence-open conversion: fraction of indexed calls where a later `read_file` or
  file-scoped exact search actually uses a file returned by the indexed package.

## What a useful improvement should look like

The pilot is promising when real usage shows all of the following directions:

1. **Reliability:** indexed errors are rare and explainable; no stale-index incidents.
2. **Bounded response:** package/result sizes remain close to the measured ~2.5k-token
   target rather than broad-search 10k+ token payloads.
3. **Follow-up economy:** conceptual investigations need fewer follow-up exact searches
   and reads than the historical repository-orientation pattern.
4. **Candidate usefulness:** a meaningful fraction of indexed calls later open/search
   one of the returned evidence files.
5. **Latency:** warm query time stays in the low tens of milliseconds; reconciliation
   does not create user-visible delay in normal repositories.
6. **Quality:** no recurring pattern where indexed evidence anchors the agent on a
   plausible but wrong implementation. Exact search remains available for
   verification/same-name disambiguation.

Do not judge success from one easy query. Review at least a week of normal work and,
preferably, 1–2 weeks before deciding whether to automate routing or broaden rollout.

## Rollback

Set:

```toml
[indexed_context]
enabled = false
```

and restart the service. Normal `search_text` remains independent of the persistent
index. The SQLite index files are cache artifacts and may be removed/rebuilt without
changing repository contents.

## Closing: benchmark and removal (2026-09-28)

**Decision: the owner approved the removal on 2026-09-28**, after the offline
benchmark failed the rule that was set before it ran. The code is kept by the
tag `archive/indexed-context-pilot-2026-09-28` (on master 9b7d6d3, pushed
before anything was deleted).

### Benchmark evidence

The benchmark ran offline on 2026-09-28 against master 45f12b6, in process,
with the production defaults. It used no ChatGPT and did not change the live
index files (it worked on copies). Two question sets:

- **Real queries:** the 35 `@context` calls ChatGPT made from 2026-09-19 to
  2026-09-27, from the `binnacle-mcp` journal. 29 remained after the
  exclusions. The answer file is the file the model read most in the next
  20 calls of the same turn. The index was built for the tree the query
  saw, as closely as git allows.
- **Labelled questions:** 26 questions on binnacle, voice-input and
  research-pipeline. Every answer location was verified by reading the
  code. 20 describe behavior, 6 name an identifier.

The rule: recall@3 of at least 70 % on both sets, and a clear step saving
against exact search.

| Condition | Required | Measured | Result |
| --- | --- | --- | --- |
| recall@3, real queries | >= 70 % | 4/29 = **14 %** (95 % CI 5–31 %) | fail |
| recall@3, labelled questions | >= 70 % | 13/26 = **50 %** (95 % CI 32–68 %) | fail |
| Step saving against exact search | a clear saving | −0.7 steps per labelled question, −1.5 per real query (conservative model) | fail |

- Both upper confidence bounds are below 70 %, so the sample size does not
  change the decision.
- Calling `@context` first and reading its top 3 files **costs** steps. The
  optimistic step model (the model skips the reads when the excerpts look
  wrong) still gives −0.2 and −0.7.
- Speed and size were not the problem: a warm call took 25–50 ms at p50
  in process (481 ms end to end in production), and a result was about
  2,050 tokens.

Where it failed:

1. **Behavior questions.** Identifier questions: recall@3 6/6. Behavior
   questions: 7/20. The retriever is BM25 (SQLite FTS5) plus one hop over
   a code graph, with no embeddings. A question whose words are not in the
   answer's code cannot reach it. This pilot was indexed search, not
   semantic search, so it did not test semantic search.
2. **Hub bias.** The graph hop favors files with many edges:
   `tools/job_status.py` was in the top 3 for 10 of the 55 questions,
   `tools/run_command.py` for 9. On binnacle, real recall@3 was 1/14.
3. **Tests and docs ahead of the code** for 7 of 26 labelled questions.
4. **Real answers are often not code:** 17 of 29 were code (recall@3 2/17),
   6 docs, 4 tests and 2 JSON files (JSON was not indexed).
5. **The excerpt missed the answer lines** in 11 of 17 labelled cases where
   the answer file was in the package.

Better exposure does not help: direct entries first, BM25 without the graph
hop and a larger package all stay far below the bar. The whole package (up
to 10 files) held the answer for 38 % of the real queries and 77 % of the
labelled questions.

The bar for any future retriever, from the step model: recall@3 of about
45 % on real queries and 73 % on labelled questions for a net saving
(conservative model), or 29 % and 58 % (optimistic). A perfect top 3 would
save about 2.4 steps per real query and 0.7 per labelled question.

### What was removed

- The pilot modules `indexed_context`, `indexed_parse`, `indexed_query`,
  `indexed_refresh`, `indexed_retrieval`, `indexed_store` and
  `indexed_surface`, `scripts/analyze_indexed_pilot.py`, and their tests.
- The `@context` path of `search_text`: its sentence in the tool
  description, its clause in the `pattern` parameter, and the
  `indexed_args_invalid` error. A pattern that starts with `@context` and a
  space is an ordinary regex or literal pattern again. Every other
  `search_text` result is byte-identical to master 9b7d6d3; the tests
  `tests/contracts/test_search_text_surface.py` and
  `tests/unit/tools/test_search_text_plain_patterns.py` prove it.
- The `index_context` and `index_context_error` records, `mode=indexed` on
  `search_dispatch`, the `indexed_*` fields of the startup `config` record,
  and the "indexed context pilot" section of `binnacle stats`
  (`docs/logging.md` §13).

An old `[indexed_context]` section in the host configuration keeps loading.
It is ignored, and one startup WARNING names it:

```text
event=config_warning section=indexed_context reason=removed action=ignored
```

The server does not delete the index files. On this host they are in
`~/.cache/binnacle/indexes`: 681 MiB on 2026-09-28, 13 indexes in 31 files
(314 MB of it WAL and shared-memory files). 4 of the 13 indexes (128 MB)
belong to worktrees that no longer exist. Deleting the directory is a host
operation.

### The LSP design branch

The owner's LSP design branch `design/lsp-development-intelligence-2026-09-27`
planned to route LSP queries through this `@context` path. That path no
longer exists, so the LSP work must add its own entry point.
