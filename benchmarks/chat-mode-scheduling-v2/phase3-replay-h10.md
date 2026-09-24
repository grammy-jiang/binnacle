# Phase-3 policy replay

- Algorithm: phase3-replay-v1
- Policy: historical-one-shot
- Budget: 10.0 s
- Corpus SHA-256: 4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d
- Audit status at start: pending
- Provisional: true

## Summary

| Metric | Value |
| --- | ---: |
| turns | 326 |
| turns_with_positive_waits | 291 |
| observed_blocking_wall_s | 83914.599908 |
| candidate_blocking_wall_s | 1821.949 |
| burden_reduction_percent | 97.828806 |
| positive_waits_observed | 3000 |
| waits_clipped | 2458 |
| waits_converted_to_nonblocking | 2709 |
| observed_required_completions | 18 |
| required_completions_preserved | 3 |
| completion_at_risk | 15 |
| completion_preservation_percent | 16.666667 |
| turns_exhausted | 291 |
| exhaustion_percent | 100.0 |

## Per scenario

| Scenario | Turns | Observed wall (s) | Candidate wall (s) | Preserved / observed | Exhausted turns |
| --- | ---: | ---: | ---: | ---: | ---: |
| R1 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R11 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R2 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R3 | 6 | 57.531 | 40.0 | 0 / 4 | 4 |
| R5 | 6 | 92.08 | 40.0 | 0 / 4 | 4 |
| R7 | 6 | 578.992 | 50.0 | 3 / 10 | 5 |
| R8 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| R9 | 6 | 0.0 | 0.0 | 0 / 0 | 0 |
| operational | 278 | 83185.996908 | 1691.949 | 0 / 0 | 278 |
