# Phase-3 candidate shortlist

- Corpus SHA-256: 4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d
- Verdict: NO_LIVE_CANDIDATE
- Production budget declared: false

## Candidate gates

| Candidate | Budget (s) | Completion % | Exhaustion % | Early exhaustions | Burden reduction % | Evidence complete | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| C120 | 120.0 | 88.888889 | 47.766323 | 0 | 75.123692 | True | REJECT |
| C300 | 300.0 | 100.0 | 29.209622 | 0 | 52.467818 | True | REJECT |
| C600 | 600.0 | 100.0 | 17.869416 | 0 | 29.565116 | True | REJECT |

## Rejected candidates

- C120 (120.0 s): gate_1_completion_preservation, gate_2_exhaustion
- C300 (300.0 s): gate_2_exhaustion, gate_4_repeated_wait_burden_reduction
- C600 (600.0 s): gate_2_exhaustion, gate_4_repeated_wait_burden_reduction

## Live candidates

- Live candidates: none
- Preferred live candidate: none

## Open evidence limitations

- None.

## Phase-4 targeted calibration requirements

- Do not start Phase-4 targeted calibration: no C120/C300/C600 candidate passed every Phase-3 offline gate.
