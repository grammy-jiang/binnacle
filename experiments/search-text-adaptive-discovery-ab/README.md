# search_text adaptive-discovery A/B

Status: offline experiment only. No production search_text behavior is changed.

## Question

For broad searches that currently hit the 64 KiB structured-result budget, can a
file-oriented discovery response reduce first-hop result tokens without hiding
files the agent later proves useful by opening or searching them?

## Arms

### A — current behavior

Replay the historical query through the current search_text_impl. The existing
64 KiB structured-result budget remains unchanged, so A is the production prefix
behavior on the same current filesystem snapshot used by B.

### B — adaptive discovery

Rank every matching file by keyword-branch coverage, diversity, path hits, and
match density. Return:

- 30 detailed files;
- two representative matches per detailed file;
- representative text clipped to 180 characters;
- ranked file name + match count only for the remaining tail;
- 150 total candidate files in the primary B arm.

The 64 KiB hard budget is not removed by this experiment; B is testing a better
representation before that final safety boundary.

## Dataset and weak ground truth

The replay uses production search_budget_hit queries from 2026-09-19 09:57 AEST
onward. For each original ChatGPT turn, files opened by read_file or by a
file-scoped search_text within the next 10 tool calls are treated as weak relevance
evidence. An evidence file counts only when it still belongs to the replayed query's
current match set.

This is behavioral evidence, not human relevance annotation.

The final run contained:

- 31 historical budget-hit queries;
- 31 successful current-state replays;
- 17 queries with matched observed evidence;
- 39 matched observed evidence files.

A replay is close to the historical production observation: mean token drift is
1.1%, with 0.3% median absolute drift.

## Result

| Metric | A: 64 KiB prefix | B: adaptive discovery |
| --- | ---: | ---: |
| Estimated tokens, mean | 15,957 | 3,277 |
| Estimated tokens, p50 | 16,284 | 2,923 |
| Estimated tokens, p90 | 16,406 | 6,085 |
| Observed evidence-file recall | 41.0% | 97.4% |
| Queries recalling all observed evidence | 35.3% | 94.1% |

Mean first-hop token reduction is **79.4%**.

At the observed median result cost of later search_text/read_file calls, B would
need roughly **10.4 additional follow-up calls per broad query** to consume the mean
first-hop token saving.

The first 30 detailed files alone contain 84.6% of observed evidence files. The
count-only tail is therefore doing useful work rather than merely inflating the
candidate list.

## Why A loses recall

A returns many match entries but relatively few distinct files:

- A entries: 77.9 mean;
- A distinct candidate files: 12.5 mean, 11 p50;
- current matching files: 64.4 mean, 40 p50.

The 64 KiB prefix is often consumed by repeated/contextual matches from a small
number of high-density files. B spends far fewer tokens while exposing a much wider
file set.

## Tail sensitivity

The detailed front stays at 30 files.

| Total candidates | Mean estimated tokens | Evidence-file recall | Queries recalling all evidence |
| ---: | ---: | ---: | ---: |
| 100 | 3,013 | 94.9% | 88.2% |
| 150 | 3,277 | 97.4% | 94.1% |
| 200 | 3,505 | 100.0% | 100.0% |

The only observed evidence file missed by the primary 150-candidate B arm ranked
175th. It had one match, covered one query branch, and had no path hit. Expanding
the count-only tail from 150 to 200 recovered it for about 228 additional mean
estimated tokens in this sample.

This makes **30 detailed + up to 200 total candidates** the safer candidate for a
future production prototype, subject to more data.

## Interpretation thresholds

For this offline feasibility test, a useful B arm should:

- reduce mean first-hop tokens by at least 70%;
- retain at least 95% of observed evidence files;
- recall all observed evidence for at least 90% of comparable queries;
- leave enough first-hop saving to tolerate at least five extra normal follow-up
  search/read results.

The primary 150-candidate B arm clears all four thresholds. The 200-candidate
sensitivity arm improves observed recall further at low marginal token cost.

## Limitations

- Relevance is inferred from later agent behavior, not human annotation.
- Queries are replayed on the current filesystem, not exact historical snapshots.
- Other project worktrees can continue changing while the experiment is rerun.
- Only 17 queries currently provide usable observed-evidence recall measurements.
- Branch coverage ranking conservatively approximates top-level regex alternatives
  with Python regexes while the real search engine is ripgrep/Rust regex.
- File recall does not prove that the two representative snippets are always the
  best snippets for reasoning.

The result is strong enough to justify a controlled implementation prototype, but
not enough to remove the existing 64 KiB safety budget or automatically route
ordinary searches through a new behavior without another production validation.

## Re-run

From the Binnacle repository, run:

    uv run python scripts/search_text_discovery_ab.py \
      --since "2026-09-19 09:57:00" \
      --detailed 30 \
      --total 150 \
      --representatives 2 \
      --snippet-chars 180 \
      --json-out /tmp/search-text-ab.json \
      --markdown-out /tmp/search-text-ab.md

Use --total 200 to replay the safer tail sensitivity arm.

The experiment uses the same token estimate as Binnacle telemetry:

    (content_chars + compact_structured_json_chars) // 4
