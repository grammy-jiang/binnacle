# Phase 3 corpus audit: aggregate

This audit checks the revision-2 Step-3.5M merge at base commit
`b5236ab3742709e19ee37942d574a6496160e66a`. It audits the merged corpus
against the seven frozen JSON shards and canonical Phase-3 progress; it does
not re-audit source extraction semantics.

## Evidence identity

- Source inventory SHA-256:
  `1a147dd0d1632c567d91a4e35e83085ecca062a9f0bcab251b8ccd7a2a62bc9f`.
- Replay corpus SHA-256:
  `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`.
- Replay report SHA-256:
  `f6e46b89b60bb89c918ab4c5d9ab11d0dea5da2b27bf3794c96f1e34ebc440bd`.
- Canonical progress SHA-256:
  `37b0e238c73a7db372cee0002dc4ac7607e25688099cb06a4b2a0301ab83e72a`.
- Canonical progress records replay corpus revision `2` and the same replay
  corpus SHA-256.

## Shard totals and merge membership

| Source | Shard rows | Shard waits | Corpus rows | Corpus waits | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| operational-journal | 278 | 2968 | 278 | 2968 | PASS |
| phase1-step3 | 12 | 0 | 12 | 0 | PASS |
| phase1-step4 | 12 | 8 | 12 | 8 | PASS |
| phase1-step5 | 6 | 0 | 6 | 0 | PASS |
| phase1-step6 | 6 | 0 | 6 | 0 | PASS |
| phase1-step7 | 6 | 0 | 6 | 0 | PASS |
| phase1-step8 | 6 | 24 | 6 | 24 | PASS |
| Total | 326 | 3000 | 326 | 3000 | PASS |

All 326 shard row signatures occur exactly once in the merged corpus. The
`(source_id, trial_id, base_turn)` key is unique for all 326 rows.

## Aggregate invariants

| Invariant | Expected | Actual | Verdict |
| --- | --- | --- | --- |
| JSON shard coverage | One shard for each of 7 inventory sources | 7/7 source ids present; all revision-2 shards available | PASS |
| Exact row membership | Every shard row exactly once | 326/326 signatures matched exactly once | PASS |
| Deterministic ordering | Sort by `source_id`, `trial_id`, `base_turn` | All 326 rows exactly match the sorted shard union | PASS |
| Row totals | Sum of shard rows | 326 = 278 + 12 + 12 + 6 + 6 + 6 + 6 | PASS |
| Wait totals | Sum of shard waits | 3000 = 2968 + 0 + 8 + 0 + 0 + 0 + 24 | PASS |
| Canonical Phase-1 population | 48 submitted slots | 48 distinct canonical trial rows | PASS |
| Canonical arm balance | 24 A + 24 B | 24 A + 24 B | PASS |
| Corpus SHA linkage | Equal `phase3-progress.json.replay_corpus_sha256` | Both are `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d` | PASS |
| Markdown headline counts | JSON rows 326, canonical trials 48, waits 3000 | Report says 326, 48, 3000 | PASS |
| Markdown per-source counts | Match every JSON shard | All 7 source status/row/wait/SHA values match | PASS |
| Privacy/schema | Frozen 12 turn fields, 13 wait fields; no prose/private fields | Exact field whitelists; hashed job ids; normalized operational ids; forbidden prose/private keys absent | PASS |
| Operational window/expiration | Revision-2 retained window and expiration status explicit | 4073 token-filtered lines, 4045 parsed timing records, 2968 replayable waits, 278 rows; 28 non-parsed token-bearing lines explicitly recorded as not an expiration gap | PASS |

## Markdown report consistency

The merged Markdown report is consistent with the JSON corpus:

- replay rows: expected 326, actual 326;
- canonical trials represented: expected 48, actual 48;
- positive wait records: expected 3000, actual 3000;
- corpus SHA-256 and source-inventory SHA-256 both match the files;
- every source-table status, row count, wait count, and source SHA-256 matches
  its JSON shard;
- the report includes the required privacy notes.

The report's operational-journal row records the frozen short-Unix window
`1789777318.789691..1790263827.324505`, 4073 token-filtered lines, and 4045
parsed timing records. Canonical revision-2 progress further records 2968
replayable waits and 278 rows and states that the 28 token-bearing non-timing or
wrapped records are not an expiration gap.

At aggregate-audit execution time, the optional
`phase3-corpus-shards/operational-journal.md` file was still a stale
revision-1 historical note and was not a merge input. Step 3.5A canonical
housekeeping rewrites that note to describe revision 2; the aggregate audit
itself uses the revision-2 JSON shard plus revision-2 canonical progress for
merge consistency.

## Privacy checks

The corpus top-level keys are exactly `schema_version`, `fields`,
`wait_fields`, and `rows`. Every row has exactly the 12 frozen turn fields,
and every wait has exactly the 13 frozen wait fields.

All non-null `job_id_hash` values are 64-character lowercase hexadecimal
SHA-256 digests. Operational `trial_id` and `base_turn` values match the
normalized `operational-<16 hex>` and `turn-<16 hex>` forms. The raw corpus
JSON contains none of the prohibited prose/private key names checked by the
audit, including prompt, conversation, message, content, arguments, raw job id,
or raw job-id fields.

## Independent validation

A standalone Python validator reconstructed the shard union, row signatures,
ordering, counts, arm totals, report table, schema/privacy rules, SHA linkage,
and operational-window assertions without importing the extractor. Result:

```text
AUDIT_STATUS PASS
CHECK_COUNT 96 PASS 96 FAIL 0
ROWS_BY_SOURCE {"operational-journal": 278, "phase1-step3": 12, "phase1-step4": 12, "phase1-step5": 6, "phase1-step6": 6, "phase1-step7": 6, "phase1-step8": 6}
WAITS_BY_SOURCE {"operational-journal": 2968, "phase1-step3": 0, "phase1-step4": 8, "phase1-step5": 0, "phase1-step6": 0, "phase1-step7": 0, "phase1-step8": 24}
PHASE1_ARMS {"A": 24, "B": 24}
ROW_KEYS 326 UNIQUE 326
```

The merge CLI was then run twice into `/tmp`. Both fresh outputs were
byte-identical to each other and to the frozen artifacts:

```text
4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d  corpus run 1
4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d  corpus run 2
4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d  frozen corpus
f6e46b89b60bb89c918ab4c5d9ab11d0dea5da2b27bf3794c96f1e34ebc440bd  report run 1
f6e46b89b60bb89c918ab4c5d9ab11d0dea5da2b27bf3794c96f1e34ebc440bd  report run 2
f6e46b89b60bb89c918ab4c5d9ab11d0dea5da2b27bf3794c96f1e34ebc440bd  frozen report
DETERMINISTIC_MERGE PASS
```

The deterministic rerun began with `nproc=4` and load average
`2.01 1.36 0.96`, so the timing environment had foreign parallel-programme
load; no timing threshold is part of this aggregate audit.

AUDIT aggregate: PASS
