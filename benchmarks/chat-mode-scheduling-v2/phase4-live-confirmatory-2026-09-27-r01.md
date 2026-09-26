# Phase 4 live confirmatory report — 2026-09-27 r01

Verdict: **NO_GO_PERFORMANCE**. Phase 5 ready: **false**.

Selected C endpoint remains **C300** at **300 s**. The canonical hard-gate
matrix passes **20/26** required gates; six required gates fail, so the
performance no-go verdict is unchanged.

## Required-gate result

Failed required gates:

- `category_median_regression_within_10_percent`
- `continuation_reduction_ge_80_percent`
- `eligible_overlap_ratio_ge_80_percent`
- `mixed_long_median_ge_20_percent_faster`
- `overall_median_wall_ge_20_percent_faster`
- `read_heavy_median_ge_30_percent_faster`

The diagnostic long-job burden target is also missed. Slot integrity remains
160/160 submitted and 160/160 scorable with zero integrity issues.

## Routing integrity

- A: 1/54 routing misses (1.8519%).
- B: 0/53 routing misses (0%).
- C: 0/53 routing misses (0%).
- H: 0/10 routing misses (0%).

No arm exceeds the 10% evidence-integrity threshold. The R9-r03-A miss remains
a non-owning, non-mutating production isolation incident; its correctly routed
second attempt owns the slot.

## Timing provenance

P4-A6 regenerated 79 changed timing rows from recovered conversation timing.
Five canonical rows remain explicitly poll-observed: `R5-r03-C`, `R6-r01-C`,
`R6-r02-C`, `R7-r02-C`, and reused `R12-r01-C`.

## Historical H comparator

H is **complete**, not pending. Comparator JSON SHA-256 is
`13f1fae101ccf9de63b7c45ed593b4827ba8df4cd7a7943079ec214d812eecb7` and evidence integrity passes. Its nine bounded trials remain
0/9 same-prompt with nine manual continuations, versus selected C300 at 9/9
same-prompt and zero continuations under the corrected analyzer. H remains
diagnostic and does not alter the C gate matrix or Step 4.12 verdict.

## Frozen identities

- Phase-4 source HEAD: `06bc1649c4bad9449470366da971649bb7620020`.
- Canonical schedule SHA-256: `516938320afdf9dade5e03b8262a9e6ef9c95ad5d0330c20d1ce23d0ec68e734`.
- Hard-gate matrix SHA-256: `d4ab68331cf9058e6d0726fc97554a9e6bfbdae94b34681326991e0a53e870b3`.
- Baseline instruction SHA-256:
  `f1c100d0ddb93c29f8f78e5a2d28e297d861ba6e2c7e53712ec886dea06bafa5`.
- V2 instruction SHA-256:
  `b7df6953a3c64bd245b3d5ff13b6f2667e940d5a154e650fec0b10e6a22cf094`.
- Canonical counts: A 53, B 53, C 54, H comparator 10.

## Final validation

- Optimized full suite: **PASS** after isolating the test process from the
  staging connector's inherited `BINNACLE_CONFIG_FILE`. Parallel-safe lane:
  1324 passed, 3 skipped; ordinary-process lane: 2 passed. Tests, seed and
  worker count were unchanged. The first contaminated run produced 55
  job-manager-mode integration failures and is retained as validation evidence.
- Production isolation: **PASS**. Production checkout is clean at
  `cbafe8aff48ac1c0e518b34b6a4f54f62f162864`; services are active; the
  blocking-wall budget key is absent; primary tunnel profile hash is unchanged.
- Endpoint cleanup: **PASS**. A/B/C300/H were stopped using the benchmark cleanup
  path, registry is empty, ports 8110/8111/8113/8115 are closed, and no evidence
  was deleted.
- CI attestation is delegated to the task manager by the assignment procedure,
  which requires a single `--no-wait` push. A red run will be routed to a
  follow-up task; no CI result is fabricated into this report.

## Conclusion

Phase 4 is complete with **NO_GO_PERFORMANCE**. The selected C300/300 s identity
is retained in the handoff, but Phase 5 is not ready because required gates fail.
