# Phase 3 corpus audit: operational-journal revision 2

This audit independently re-derived the revision-2 operational replay invariants
from the retained Binnacle user journal and compared them with the frozen shard.
It did not invoke or read the corpus extractor implementation. The audit uses the
frozen Step-3.2 journal bounds and the physical `tool_call`,
`job_status_timing`, and `tool_result` records in that retained window.

## Frozen inputs

- Source path / selector:
  `journalctl --user -u binnacle-mcp.service -o short-unix --since '@1789777318.789691' --until '@1790263827.324505' --no-pager | grep -F job_status_timing`
- Source SHA-256 over the exact 4,073 newline-terminated filtered lines:
  `c1a18c4095de00cd68833fb66dabc9db6fbfc2a1122ab6019095f15acd8a1948`
- Shard path:
  `benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/operational-journal.json`
- Shard SHA-256:
  `40186dbf2adde0936a47d0a270c802f71fad5adf8dca9c8a3d9c039590b97cff`
- Frozen inventory path:
  `benchmarks/chat-mode-scheduling-v2/phase3-source-inventory.json`
- Frozen inventory SHA-256:
  `1a147dd0d1632c567d91a4e35e83085ecca062a9f0bcab251b8ccd7a2a62bc9f`

The source selector reproduces the exact frozen source fingerprint recorded in
all revision-2 shard rows. The bounds are `1789777318.789691` through
`1790263827.324505`, inclusive as supplied to `journalctl`.

| Source-window invariant | Expected from retained journal | Shard value | Verdict |
| --- | --- | --- | --- |
| Token-filtered source lines | 4,073 | 4,073 | PASS |
| Oldest bound | `1789777318.789691` | `1789777318.789691` | PASS |
| Newest bound | `1790263827.324505` | `1790263827.324505` | PASS |
| Source SHA-256 | `c1a18c...a1948` | `c1a18c...a1948` | PASS |

The literal source token filter also captures journal payload text that mentions
`job_status_timing`. For semantic reconstruction, the audit therefore anchored
records on real timestamped events and correlated the actual `tool_call` and
`tool_result` for each call ID. That yields 4,043 true timing events, of which
2,968 are positive waits. The shard's `parsed_rows=4045` is an extractor parser
diagnostic rather than one of the frozen replay invariants audited here; it is
not used as a substitute for the actual event correlation.

## Normalized operational slot count

The independent reconstruction groups positive waits by historical base turn.
For the 16 positive calls whose historical records predate turn correlation and
therefore have no `turn` field, each physical call is conservatively retained as
its own singleton using the normalized source key `call:<call-id>`. This avoids
inventing cross-call grouping. The SHA-256-derived normalized IDs for all 16
singletons match the shard IDs.

| Scenario / arm | Expected source slots | Shard rows | Verdict |
| --- | ---: | ---: | --- |
| operational / historical | 278 | 278 | PASS |
| Total | 278 | 278 | PASS |

The shard also records `row_count=278` and `trial_count=278`.

## Positive job-status waits and actual waited seconds

A positive wait is an actual `job_status` timing event with
`wait_requested_s > 0`. Its physical duration comes from the correlated
`tool_result.waited_s` when present, with the timing record's `waited_s` used for
newer records that carry it. Requested duration is retained only as context.

The audit reconstructed all 2,968 positive waits. Comparison keys and values are
`(base_turn, wait_index, job_id_hash, requested_wait_s, waited_s, state)`.
There are zero missing waits, zero extra waits, and zero value mismatches.

| Invariant | Expected from journal | Shard value | Verdict |
| --- | ---: | ---: | --- |
| Positive waits | 2,968 | 2,968 | PASS |
| Missing shard waits | 0 | 0 | PASS |
| Extra shard waits | 0 | 0 | PASS |
| `waited_s` / state value mismatches | 0 | 0 | PASS |

The independently serialized wait-tuple SHA-256 is
`fd48a0c52f987afe32f4513925466b01cab04d04ab690323a80948785ee12e16`
for both source and shard.

## Union blocking wall per turn

For every positive wait, the physical blocking interval starts at the correlated
`tool_call` timestamp. Its end is the earlier of `call_start + waited_s` and the
correlated call-result timestamp: a rounded `waited_s` cannot extend a physical
interval beyond the observed result. Intervals are then merged by normalized
base turn, charging overlap once.

All 278 per-turn union values match the shard exactly to the recorded six-decimal
precision. There are zero missing turns, zero extra turns, and zero union-value
mismatches.

| Invariant | Expected from journal | Shard value | Verdict |
| --- | ---: | ---: | --- |
| Turns with union wall | 278 | 278 | PASS |
| Union-wall mismatches | 0 | 0 | PASS |

The independently serialized per-turn union SHA-256 is
`dc6092c16411da6b5c025fae22255d99f5835a987dbb30f8859ca38dbd027f1d`
for both source and shard.

## Observed required completions

The operational journal records physical job completion state but carries no
Phase-1 DAG/node requirement annotation. Therefore no operational completion can
be independently classified as a *required* completion; the conservative
expected count is zero. The shard likewise marks every one of its 2,968 waits
`required_completion=false` and every one of its 278 rows
`observed_required_completions=0`.

| Invariant | Expected from journal evidence | Shard value | Verdict |
| --- | ---: | ---: | --- |
| Observed required completions | 0 | 0 | PASS |
| Rows with non-zero required completions | 0 | 0 | PASS |
| Waits marked required | 0 | 0 | PASS |

## Terminal states

Terminal state for an operational slot is the state returned by its final
positive status call in the retained turn. The independently reconstructed
distribution is 218 `exited` and 60 `running`; every normalized turn matches the
shard.

| Terminal invariant | Expected from journal | Shard value | Verdict |
| --- | --- | --- | --- |
| `exited` slots | 218 | 218 | PASS |
| `running` slots | 60 | 60 | PASS |
| Per-slot terminal mismatches | 0 | 0 | PASS |

The independently serialized terminal-state SHA-256 is
`92c94ed457ae638779634c13674be83561938fe87f8ae54d9ec74cb93d936530`
for both source and shard.

## Exact commands used

Lineage and frozen input hashes:

```bash
git status --short --branch
git log -5 --oneline
sha256sum \
  /tmp/p36-manager/assignments/p3-audit-operational-journal-r2--a1.json \
  /home/grammy-jiang/Projects/binnacle-chat-scheduling-phase3-6-plan/docs/chat-mode-scheduling-v2-phase3-execution-plan.md \
  benchmarks/chat-mode-scheduling-v2/phase3-source-inventory.json \
  benchmarks/chat-mode-scheduling-v2/phase3-corpus-shards/operational-journal.json
```

Exact frozen-source fingerprint materialization:

```bash
set -o pipefail
journalctl --user -u binnacle-mcp.service -o short-unix \
  --since '@1789777318.789691' --until '@1790263827.324505' --no-pager |
  grep -F job_status_timing |
  tee /tmp/p36-opjournal-r2-token-lines.txt |
  sha256sum
wc -l /tmp/p36-opjournal-r2-token-lines.txt
```

The independent semantic validator uses the following journal event selector,
then correlates records by `call` without invoking extractor code:

```bash
journalctl --user -u binnacle-mcp.service -o short-unix \
  --since '@1789777318.789691' --until '@1790263827.324505' --no-pager \
  --grep='event=(tool_call|tool_result|job_status_timing)'
python3 /tmp/p36-opjournal-r2-validate.py
```

Focused validation output:

```text
PASS source_token_lines=4073 source_sha256=c1a18c4095de00cd68833fb66dabc9db6fbfc2a1122ab6019095f15acd8a1948 true_timing_events=4043 positive_waits=2968 operational_rows=278 no_turn_singletons=16 wait_mismatches=0 union_mismatches=0 required_completion_mismatches=0 terminal_mismatches=0 terminals=exited:218,running:60
```

File-scoped pre-commit command:

```bash
uv run pre-commit run --files \
  benchmarks/chat-mode-scheduling-v2/phase3-corpus-audits/operational-journal.md
```

Two exploratory compound command texts were rejected by the platform safety
filter. The audit used equivalent small-helper/Python comparisons instead; no
source, shard, or invariant was skipped because of those command-text rejections.

## Overall verdict

All requested revision-2 operational-journal source/shard invariants match.

## Canonical corpus binding (Step 3.5A)

- Canonical revision-2 replay corpus SHA-256:
  `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`.
- Canonical integrated shard SHA-256:
  `40186dbf2adde0936a47d0a270c802f71fad5adf8dca9c8a3d9c039590b97cff`.
- The Step 3.5A fan-in binds this independent source/shard PASS to the
  aggregate revision-2 PASS. The shard hash above matches the integrated
  shard bytes and the aggregate audit confirms exact membership in the
  frozen corpus.

AUDIT operational-journal: PASS
