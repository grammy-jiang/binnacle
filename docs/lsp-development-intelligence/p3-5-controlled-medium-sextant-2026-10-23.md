# P3.5 controlled medium synthetic Pyright benchmarks — Sextant Linux ARM64

Date: 2026-10-23. Evidence grade: controlled exploratory measurement; **not** an authoritative performance, security, or production admission decision.

Three native Python 3.13.16 runs used the same SHA-pinned multilspy `08ba0dbe60b6e0a3eff4796cb77ff5c0837bc892`, installed Pyright 1.1.413, and the `p35-python-v1` 131-file synthetic medium corpus. Two runs had two resident instances and concurrency 2, a third had one resident and concurrency 1. Every operation had 100 measured repetitions per instance following three warm-ups. Sextant was checked for low load before running; no real/user repository was ingested.

| Metric | 2 residents run A | 2 residents run B | 1 resident |
| --- | ---: | ---: | ---: |
| Manager definition p95 (ms) | 150.0 | 156.8 | 108.8 |
| Direct definition p95 (ms) | 1.87 | 3.8 | 4.18 |
| References p95 (ms) | 2.07 | 2.3 | 4.21 |
| Hover p95 (ms) | 1.04 | 1.1 | 1.51 |
| Document symbols p95 (ms) | 1.33 | 1.4 | 1.32 |
| Workspace symbols p95 (ms) | 53.37 | 52.8 | 74.63 |
| Sampled process-tree RSS peak (MiB) | 825.2 | 845.2 | 427.9 |

All six gold cases passed all timed calls in all three runs: no request errors, no timeouts, unchanged disposable workspace snapshots and verified process cleanup. Resident reuse was observed. The 100 ms provisional Manager definition p95 target was exceeded in all runs. The 512 MiB provisional RSS target was exceeded in both dual-resident runs, but not in the single-resident run. This is a capacity warning, not a formal resource policy.

Do not subtract direct-protocol and Manager percentiles as if they isolate Binnacle overhead; the measurement paths differ. RSS sums can double-count shared pages, miss short-lived subprocesses and do not impose memory limits. One corpus and these three independent cold runs are not representative production performance; idle CPU, soak, per-platform enforcement, actual project gold and independent evidence review remain open. The embedded JSON `authoritative_timings=false` and P3.3/P3.6 `READ NO-GO` classifications remain unchanged.

Sanitized source evidence files, pinned by SHA-256:

- [Two-resident first run](p3-5-medium-sextant-two-resident-initial-2026-10-23.json) — `fac04666def0ab2bf42340fde971e681fc50c705a32f7d48f62cd75b80171245`
- [Two-resident repeat](p3-5-medium-sextant-two-resident-repeat-2026-10-23.json) — `6614b488300c85984fb14c147e91e30f8be4f5cf62f0cd8c23c2f38220c46ed4`
- [Single-resident comparison](p3-5-medium-sextant-one-resident-2026-10-23.json) — `ffa096463c1db840fe21969eb73462fcc62b84b21552b64bcd613ec34fea96b5`

The source JSON `binnacle_revision` is the base Git commit `66697d2`, not the complete dirty integration worktree identity; the same versioned harness and corpus SHA-256 values are embedded in each record. A single resident can be **provisionally** considered for further controlled private experiments but cannot be promoted to production defaults or `audited_read_eligible` without independent acceptance.
