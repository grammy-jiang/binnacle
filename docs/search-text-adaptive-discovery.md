# search_text adaptive discovery

Status: implementation prototype for a development-machine pilot.

## Goal

Reduce the first-hop token cost of broad ordinary search_text calls without losing
the files an agent is likely to inspect next. The existing 64 KiB structured-result
budget remains the final safety boundary.

The offline A/B on 31 production budget-hit queries found that a file-oriented
response can reduce mean first-hop result tokens by about 79% while increasing
observed evidence-file recall. The raw production dataset remains local and is not
part of the repository.

## Public contract

The MCP input schema and output schema do not change.

Small and ordinary results are unchanged. Adaptive discovery is considered only
when all of these are true:

1. adaptive discovery is enabled by server configuration;
2. this is an ordinary content search, not names_only and not @context;
3. the result assembled by the existing behavior would exceed
   search_text.result_max_bytes.

The response continues to use:

    {path, pattern, entries, count, truncated, note?}

The existing entry schema already requires only file and permits line, text and
count. Adaptive results therefore use two existing entry shapes in one ranked list:

- detailed representatives: {file, line, text, count}
- tail file summaries: {file, count}

For a detailed representative, count is the total number of matches in that file.
text remains an actual matching source line and never includes synthetic ranking
text. Tail entries are not matches; they are compact file summaries. The top-level
count remains the total number of matching lines observed.

max_results continues to cap returned detailed match entries. Tail file summaries
do not consume that match-entry allowance. This preserves the parameter's existing
meaning while allowing broad discovery to expose more files than a prefix of match
lines can.

Adaptive responses set truncated=true because they deliberately summarize rather
than return every matching line/context block. The note explains the representation
and directs the agent to narrow path/glob or use read_file.

No new MCP parameter or top-level response field is added, so connector discovery
does not need a schema refresh.

## Default prototype policy

Repository defaults keep the behavior disabled.

When enabled, the prototype uses:

- detailed files: 30
- representative matches per detailed file: 2
- representative text: 180 characters maximum
- ranked candidate files: up to 200
- final structured-result budget: the existing 65,536 bytes

Ranking favors:

1. files that add coverage of top-level regex alternatives;
2. files covering more alternatives overall;
3. query alternatives appearing in the file path;
4. match density, capped so one very dense file cannot dominate;
5. deterministic path tie-breaking.

If the query cannot be conservatively interpreted with Python's regex engine, the
prototype falls back to deterministic density/path ordering; ripgrep remains the
authority for matching.

## Telemetry

Each adaptive result emits one search_adaptive_discovery event correlated by call id
with:

- pre-adaptive structured bytes;
- total matches and matching files;
- detailed files and candidate files;
- representative and tail entry counts;
- final result bytes and configured byte budget;
- whether the adaptive response itself needed final budget trimming.

The normal tool_result telemetry continues to report duration, structured bytes and
estimated tokens.

## Safety and rollback

The existing result byte budget remains authoritative. Adaptive construction must
fit under it or trim the ranked entry prefix with an adaptive-specific truthful note.

Rollback is configuration-only:

    [search_text]
    adaptive_discovery_enabled = false

and a service restart. Ordinary search behavior is independent of the prototype.

## Validation gate before pilot

Before enabling on the development machine:

- small-result payloads remain byte-for-byte unchanged;
- existing search_text unit/contract/integration tests pass;
- new ranking, mixed-entry, max_results and hard-budget tests pass;
- the historical broad-query replay keeps at least 70% mean first-hop token
  reduction and at least 95% observed evidence-file recall;
- the full per-module coverage policy and Python compatibility gates pass;
- pre-commit quality gates pass.

Only after these gates pass may the development machine enable the configuration.

## Pilot review telemetry

The adaptive journal event also records comma-separated 12-hex SHA-256 prefixes for
the returned candidate files and for the detailed-front files. Only hashes are
logged; source paths and query text are not added to the event.

The existing binnacle stats command joins those hashes to read_file and file-scoped
exact search_text calls in the next ten calls of the same ChatGPT turn. When
adaptive data is present it reports candidate/detailed open conversion, result and
trigger sizes, follow-up calls, follow-up tokens, and whole-investigation result
tokens. Windows without adaptive calls keep the old stats output unchanged.
