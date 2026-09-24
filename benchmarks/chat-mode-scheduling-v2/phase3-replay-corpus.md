# Phase-3 replay corpus

- Schema version: 1.
- Corpus SHA-256: `4dd1e387c42d6fccd37d60795b00192144f3b4d93c57d9eb54ab527a72e8e94d`.
- Source inventory SHA-256: `1a147dd0d1632c567d91a4e35e83085ecca062a9f0bcab251b8ccd7a2a62bc9f`.
- Replay rows: 326.
- Canonical trials represented: 48.
- Positive wait records: 3000.

## Sources

| Source | Status | Rows | Waits | Source SHA-256 | Window |
| --- | --- | ---: | ---: | --- | --- |
| operational-journal | available | 278 | 2968 | `c1a18c4095de00cd68833fb66dabc9db6fbfc2a1122ab6019095f15acd8a1948` | 1789777318.789691..1790263827.324505 (4073 token-filtered lines, 4045 parsed timing records) |
| phase1-step3 | available | 12 | 0 | `bfb2a31f79a20ac6a292d1ec095a05d7dd462bdf26d22b1922bc2389cb253190` | - |
| phase1-step4 | available | 12 | 8 | `835ad53b639ed53a67bb7731e05cf4075b641449da56d7a5ac267f73b7988d11` | - |
| phase1-step5 | available | 6 | 0 | `1e2257a98e3c13d809f32134483a6ccaf1c1bf8fd81048099230e2b8a28f021d` | - |
| phase1-step6 | available | 6 | 0 | `c6438ce993dd73e495379beeda3a3dea7cb1331a7c5ad678c00481bfed6b576e` | - |
| phase1-step7 | available | 6 | 0 | `8703003bf2bd1c57f098d869e41dd9ed8eaa9bc574cc691af582bd0b6e50909f` | - |
| phase1-step8 | available | 6 | 24 | `98a3744b0deb5b441e892d34d025bb17d45d9e043ca54805a50afe9524e71a6f` | - |

## Exclusions

- None.

## Privacy

- Conversation prose and irrelevant tool arguments are excluded.
- Job identifiers are stored only as SHA-256 hex digests.
- Operational turn identifiers are normalized to truncated SHA-256 labels.
