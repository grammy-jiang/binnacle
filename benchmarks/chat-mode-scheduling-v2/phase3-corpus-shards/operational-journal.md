# Operational journal shard

- Status: `unavailable`.
- Frozen inventory SHA-256: `1a147dd0d1632c567d91a4e35e83085ecca062a9f0bcab251b8ccd7a2a62bc9f`.
- Frozen window: 2026-09-19T10:21:58.789691+10:00 through 2026-09-25T01:30:27.324505+10:00.
- Expected `job_status_timing` lines: 4,073.
- Observed frozen-window timing lines at extraction: 4,045.
- Rows emitted: 0.
- Source SHA-256: unavailable because the frozen journal window no longer matches the frozen line count.
- Exclusion reason: `frozen_window_line_count_mismatch_4073_4045`.
- The shard is explicit rather than synthesizing or substituting historical rows.
