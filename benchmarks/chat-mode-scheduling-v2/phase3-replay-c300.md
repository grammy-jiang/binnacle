# Phase-3 policy replay

- Algorithm: phase3-replay-v1
- Policy: cumulative
- Budget: 300.0 s
- Corpus SHA-256: 4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d
- Audit status at start: pending
- Audit status: pass
- Provisional: false

## Summary

| Metric | Value |
| --- | ---: |
| turns | 326 |
| turns_with_positive_waits | 291 |
| observed_blocking_wall_s | 83914.599908 |
| candidate_blocking_wall_s | 39886.440128 |
| burden_reduction_percent | 52.467818 |
| positive_waits_observed | 3000 |
| waits_clipped | 1310 |
| waits_converted_to_nonblocking | 1109 |
| observed_required_completions | 18 |
| required_completions_preserved | 18 |
| completion_at_risk | 0 |
| completion_preservation_percent | 100.0 |
| turns_exhausted | 85 |
| exhaustion_percent | 29.209622 |

## Per scenario

| Scenario | Turns | Observed wall (s) | Candidate wall (s) | Preserved / observed | Exhausted turns |
| --- | ---: | ---: | ---: | ---: | ---: |
| R1 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R11 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R2 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R3 | 6 | 57.531 | 57.531 | 4 / 4 | 0 |
| R5 | 6 | 92.08 | 92.08 | 4 / 4 | 0 |
| R7 | 6 | 578.992 | 578.989 | 10 / 10 | 0 |
| R8 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R9 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| operational | 278 | 83185.996908 | 39157.840128 | 0 / 0 | 85 |
