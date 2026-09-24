# Phase-3 policy replay

- Algorithm: phase3-replay-v1
- Policy: cumulative
- Budget: 120.0 s
- Corpus SHA-256: 4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d

## Summary

| Metric | Value |
| --- | ---: |
| turns | 326 |
| turns_with_positive_waits | 291 |
| observed_blocking_wall_s | 83914.599908 |
| candidate_blocking_wall_s | 20874.85417 |
| burden_reduction_percent | 75.123692 |
| positive_waits_observed | 3000 |
| waits_clipped | 1765 |
| waits_converted_to_nonblocking | 1712 |
| observed_required_completions | 18 |
| required_completions_preserved | 16 |
| completion_at_risk | 2 |
| completion_preservation_percent | 88.888889 |
| turns_exhausted | 139 |
| exhaustion_percent | 47.766323 |

## Per scenario

| Scenario | Turns | Observed wall (s) | Candidate wall (s) | Preserved / observed | Exhausted turns |
| --- | ---: | ---: | ---: | ---: | ---: |
| R1 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R11 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R2 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R3 | 6 | 57.531 | 57.531 | 4 / 4 | 0 |
| R5 | 6 | 92.08 | 92.08 | 4 / 4 | 0 |
| R7 | 6 | 578.992 | 570.987 | 8 / 10 | 2 |
| R8 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R9 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| operational | 278 | 83185.996908 | 20154.25617 | 0 / 0 | 137 |
