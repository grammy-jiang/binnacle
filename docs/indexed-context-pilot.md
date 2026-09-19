# Indexed `@context` development pilot

Status: development-machine pilot. Normal `search_text` regex/literal behavior remains the default.

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
the same `binnacle.logstats` analysis implementation; it is not a second stats
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
