# Phase-3 candidate shortlist

- Corpus SHA-256: 4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d
- Verdict: LIVE_CANDIDATES_AVAILABLE
- Production budget declared: false

## Candidate gates

| Candidate | Budget (s) | Completion % | Exhaustion % | Early exhaustions | Def. (a) reduction % (non-gating) | Def. (b) repeated-wait reduction % | Evidence complete | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| C120 | 120.0 | 88.888889 | 15.384615 | 0 | 75.772057 | 87.325603 | True | REJECT |
| C300 | 300.0 | 100.0 | 0.0 | 0 | 52.927366 | 63.448499 | True | PASS |
| C600 | 600.0 | 100.0 | 0.0 | 0 | 29.824066 | 36.593805 | True | REJECT |

## Gate 4 burden definitions

- Definition (a), non-gating continuity column: total per-turn positive-wait union.
- Definition (b), gating: per `(turn, job)`, union of the second and later positive waits.
- Gate 4 minimum definition-(b) reduction: 60.0%.

## Gate populations

### C120

- gate_1_completion_preservation: canonical_phase1_observed_valid_completion; canonical_turns=48, turns_with_observed_required_completions=13
- gate_2_exhaustion: canonical_phase1_positive_wait_turns; turns=13
- gate_3_no_early_exhaustion: canonical_phase1_turns; turns=48
- gate_4_repeated_wait_burden_reduction: operational_journal; turns=278, fallback_used=False
- gate_5_evidence_completeness: canonical_phase1_positive_wait_turns; turns=13

### C300

- gate_1_completion_preservation: canonical_phase1_observed_valid_completion; canonical_turns=48, turns_with_observed_required_completions=13
- gate_2_exhaustion: canonical_phase1_positive_wait_turns; turns=13
- gate_3_no_early_exhaustion: canonical_phase1_turns; turns=48
- gate_4_repeated_wait_burden_reduction: operational_journal; turns=278, fallback_used=False
- gate_5_evidence_completeness: canonical_phase1_positive_wait_turns; turns=13

### C600

- gate_1_completion_preservation: canonical_phase1_observed_valid_completion; canonical_turns=48, turns_with_observed_required_completions=13
- gate_2_exhaustion: canonical_phase1_positive_wait_turns; turns=13
- gate_3_no_early_exhaustion: canonical_phase1_turns; turns=48
- gate_4_repeated_wait_burden_reduction: operational_journal; turns=278, fallback_used=False
- gate_5_evidence_completeness: canonical_phase1_positive_wait_turns; turns=13

## Population correction before/after

| Candidate | Gate | Metric | Before | After | Before population | After population |
| --- | --- | --- | ---: | ---: | --- | --- |
| C120 | gate_1_completion_preservation | value_percent | 88.888889 | 88.888889 | canonical_plus_operational_required_completions | canonical_phase1_observed_valid_completion |
| C120 | gate_2_exhaustion | value_percent | 47.766323 | 15.384615 | canonical_plus_operational_positive_wait_turns | canonical_phase1_positive_wait_turns |
| C120 | gate_3_no_early_exhaustion | early_exhaustion_turns | 0 | 0 | canonical_plus_operational_turns | canonical_phase1_turns |
| C120 | gate_4_repeated_wait_burden_reduction | repeated_wait_burden_reduction_percent | 87.162212 | 87.325603 | canonical_plus_operational_turns | operational_journal |
| C120 | gate_5_evidence_completeness | missing_evidence_count | 0 | 0 | canonical_plus_operational_positive_wait_turns | canonical_phase1_positive_wait_turns |
| C300 | gate_1_completion_preservation | value_percent | 100.0 | 100.0 | canonical_plus_operational_required_completions | canonical_phase1_observed_valid_completion |
| C300 | gate_2_exhaustion | value_percent | 29.209622 | 0.0 | canonical_plus_operational_positive_wait_turns | canonical_phase1_positive_wait_turns |
| C300 | gate_3_no_early_exhaustion | early_exhaustion_turns | 0 | 0 | canonical_plus_operational_turns | canonical_phase1_turns |
| C300 | gate_4_repeated_wait_burden_reduction | repeated_wait_burden_reduction_percent | 63.319406 | 63.448499 | canonical_plus_operational_turns | operational_journal |
| C300 | gate_5_evidence_completeness | missing_evidence_count | 0 | 0 | canonical_plus_operational_positive_wait_turns | canonical_phase1_positive_wait_turns |
| C600 | gate_1_completion_preservation | value_percent | 100.0 | 100.0 | canonical_plus_operational_required_completions | canonical_phase1_observed_valid_completion |
| C600 | gate_2_exhaustion | value_percent | 17.869416 | 0.0 | canonical_plus_operational_positive_wait_turns | canonical_phase1_positive_wait_turns |
| C600 | gate_3_no_early_exhaustion | early_exhaustion_turns | 0 | 0 | canonical_plus_operational_turns | canonical_phase1_turns |
| C600 | gate_4_repeated_wait_burden_reduction | repeated_wait_burden_reduction_percent | 36.51935 | 36.593805 | canonical_plus_operational_turns | operational_journal |
| C600 | gate_5_evidence_completeness | missing_evidence_count | 0 | 0 | canonical_plus_operational_positive_wait_turns | canonical_phase1_positive_wait_turns |

## Exhaustion diagnostics

| Candidate | Operational exhausted / positive | Operational % | Combined exhausted / positive | Combined % |
| --- | ---: | ---: | ---: | ---: |
| C120 | 137 / 278 | 49.280576 | 139 / 291 | 47.766323 |
| C300 | 85 / 278 | 30.57554 | 85 / 291 | 29.209622 |
| C600 | 52 / 278 | 18.705036 | 52 / 291 | 17.869416 |

## Rejected candidates

- C120 (120.0 s): gate_1_completion_preservation, gate_2_exhaustion
- C600 (600.0 s): gate_4_repeated_wait_burden_reduction

## Live candidates

- Live candidates: C300
- Preferred live candidate: C300

## Open evidence limitations

- None.

## Phase-4 targeted calibration requirements

- Exercise every live C candidate during targeted live calibration; do not collapse the shortlist to the preferred candidate.
- Exercise the R12 budget-edge runtime for each live C budget while preserving the canonical A/B/C/H arm vocabulary.
- Treat preferred_live_candidate as the smallest offline-passing budget, not as a declared production budget.
