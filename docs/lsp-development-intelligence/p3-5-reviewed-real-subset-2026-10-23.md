# P3.5 reviewed Binnacle source-subset measurements — 2026-10-23

This is **trusted, disposable source-subset exploration**, not full-repository indexing, production capacity proof or P3.6 authenticated GO evidence. Original files were only copied after the manifest's per-file SHA-256 checks; Pyright ran against temporary copies and no project code was deliberately executed.

The [exact 18-source manifest](p3-5-reviewed-real-subset-manifest-2026-10-23.json) identifies selected `src/binnacle/features/development_intelligence/*.py` files from the integrated code and five independently checked symbol gold cases. The `revision` is operator-declared `ae545d1`; it is **not** proof of complete source-tree identity. The provider was Pyright 1.1.413, `multilspy` commit `08ba0dbe`, Sextant Linux ARM64, Python 3.13.16. Each instance had three startup warmups and 30 instrumented measured calls for each of the five operations, after a bounded gold-checked index-readiness preflight.

| Post-review metric | One resident, 30 calls/method | Two residents, 60 calls/method |
| --- | ---: | ---: |
| Manager definition p95 | 76.72 ms | 151.24 ms |
| Direct definition p95 | 0.57 ms | 1.19 ms |
| Hover p95 | 1.39 ms | 1.74 ms |
| Document symbols p95 | 1.76 ms | 5.24 ms |
| Workspace symbols p95 | 30.59 ms | 46.03 ms |
| Sampled process-tree RSS peak | 257.6 MiB | 522.4 MiB |
| Errors or timeouts | 0 | 0 |
| Gold correctness | 100% of sampled operations | 100% of sampled operations |
| Workspace snapshot and cleanup | Verified | Verified |

The reports were taken **after** the independent review fixes for actual Node provenance, cold-start gold validation and resource/operation validity. Each report has `valid=true`, `cleanup_verified=true`, `snapshot_unchanged=true` and `resident_reuse_verified=true`. The benchmark `valid` field is only a functional envelope check; `authoritative_timings=false`, and `READ` still remains NO-GO.

Evidence artifacts (sanitized source output, matching unchanged SHA-256 transfers):

- [One-resident report](p3-5-real-subset-18-single-reviewfix-2026-10-23.json) — SHA-256 `48aaa19891530d36b26f20843b8a793ac78c6bcf5f107d0bb493ee5470b01cbf`
- [Two-resident report](p3-5-real-subset-18-dual-reviewfix-2026-10-23.json) — SHA-256 `94c3a76e456e09d819759002d3e55e417a3e3b8d1b5a16d8f2d1a1bf3ac28ec0`
- [18-source manifest](p3-5-reviewed-real-subset-manifest-2026-10-23.json) — SHA-256 `dd1863a0c32aada2349d90c9ecf3ff6968b4df2938a076bfe19d1824fe993403`

## Interpretation and remaining work

The second resident increases RSS above the provisional 512 MiB cap on this workload, and Manager definition p95 exceeds the provisional 100 ms target at two residents; the one-resident sample stays within both provisional values here. These results support **testing one resident first**, not updating production defaults or approving a resource guarantee. The independent review identified that `manager_definition` travels through the private Manager but other calls go directly to the upstream LSP session, so their timings are not comparable as pure Manager overhead. Real-world project indexing, idle CPU, TTL/capacity eviction, sustained load, network isolation, comprehensive package identity and source-bound external review are outstanding.
