# Operational journal shard

- Status: `available` (revision 2).
- Frozen inventory SHA-256:
  `1a147dd0d1632c567d91a4e35e83085ecca062a9f0bcab251b8ccd7a2a62bc9f`.
- Frozen source window:
  `1789777318.789691..1790263827.324505` short-unix
  (2026-09-19T10:21:58.789691+10:00 through
  2026-09-25T01:30:27.324505+10:00).
- Window line count: 4,073 token-filtered `job_status_timing` lines.
- Extractor parser records: 4,045; the independent revision-2 audit correlates
  4,043 true timing events.
- Replayable positive waits: 2,968.
- Rows emitted: 278.
- Source SHA-256:
  `c1a18c4095de00cd68833fb66dabc9db6fbfc2a1122ab6019095f15acd8a1948`.
- Shard SHA-256:
  `40186dbf2adde0936a47d0a270c802f71fad5adf8dca9c8a3d9c039590b97cff`.
- Revision 1 was marked unavailable after the extractor compared parsed-event
  count with the frozen token-filtered line count. That extractor defect was
  fixed in worker commit `c7b0b8bf1c308812d3b391c556b8a302d5b8c125`, after
  which the retained window re-extracted deterministically as revision 2.
