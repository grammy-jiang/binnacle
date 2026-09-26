# Phase 4 confirmatory R8/R9 checkpoint

- Frozen at 2026-09-26T23:08:47+10:00 for task 4.9.5.
- Frozen schedule SHA-256: 516938320afdf9dade5e03b8262a9e6ef9c95ad5d0330c20d1ce23d0ec68e734.
- R8/R9 slot integrity: PASS — 30/30 canonical slots have exactly one owning outcome.
- Reruns: 0. Unscorable-routing slots: 0. All state directories are present and all owning rows record host_load_flagged.
- Routing misses: A 1/11 (9.09%), B 0/10 (0.00%), C 0/10 (0.00%). No arm exceeds the >10% evidence-integrity threshold.
- R9-r03-A: one pre-submit failure did not submit; the next attempt was a production routing miss with 8 production calls and did not own the slot; attempt 2 was the first correctly routed submission and owns the slot.
- Analysis: 30/30 same-prompt completion, 0/30 interrupted, 0/30 premature handoff, 0/30 failed trial status, 0/30 host-load flagged.
- Frozen evidence tree: benchmarks/chat-mode-scheduling-v2/phase4-confirmatory-evidence/R8-R9 has 30 deterministic tar.gz archives containing 397 source files; normalized source-manifest SHA-256 e86cf96dd2b58c9402d9b7d4adf0440189c369da79dddd000ac6528108c844f7.

## D9 settle-time recovery

No previously poll-observed trial was recomputed during this checkpoint.

Trials that remain explicitly poll-observed:

- R8-r01-A: 53.014 s; read_chat_human_view_without_raw_conversation_json.
- R8-r01-B: 69.297 s; read_chat_timeout_30s.
- R8-r02-B: 61.271 s; read_chat_timeout_30s.
- R8-r02-C: 54.012 s; read_chat_timeout_30s.
- R8-r03-C: 190.069 s; read_chat_human_view_without_raw_conversation_json.
- R8-r04-A: 65.032 s; read_chat_timeout_30s.
- R8-r04-B: 68.53 s; read_chat_timeout_30s.
- R8-r04-C: 65.486 s; read_chat_human_view_without_raw_conversation_json.
- R8-r05-A: 61.632 s; read_chat_timeout_30s.
- R8-r05-B: 51.18 s; read_chat_timeout_30s.
- R8-r05-C: 64.08 s; read_chat_human_view_without_raw_conversation_json.
- R9-r01-A: 63.91 s; read_chat_timeout_30s.
- R9-r01-B: 175.869 s; read_chat_timeout_30s.
- R9-r01-C: 62.845 s; read_chat_timeout_30s.
- R9-r02-A: 51.972 s; read_chat_timeout_30s.
- R9-r02-C: 64.861 s; read_chat_human_view_without_raw_conversation_json.
- R9-r03-B: 122.803 s; read_chat_timeout_30s.
- R9-r03-C: 70.738 s; read_chat_human_view_without_raw_conversation_json.
- R9-r04-A: 124.946 s; read_chat_timeout_30s.
- R9-r04-B: 101.649 s; read_chat_timeout_30s.
- R9-r04-C: 75.257 s; read_chat_timeout_30s.
- R9-r05-A: 51.208 s; read_chat_human_view_without_raw_conversation_json.
- R9-r05-C: 62.079 s; read_chat_timeout_30s.

## Canonical slots

- R8-r01-A: live; run r8-20260926T185958-f1a56adbf8; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 53.014 s.
- R8-r01-B: live; run r8-20260926T185329-13bfd189f0; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 69.297 s.
- R8-r01-C: live; run r8-20260926T185527-680c45b76d; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 35.572 s.
- R8-r02-A: live; run r8-20260926T174625-a6a7388a51; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 59.261 s.
- R8-r02-B: live; run r8-20260926T175139-e7cc4d893c; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 61.271 s.
- R8-r02-C: live; run r8-20260926T174957-87a5d299a2; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 54.012 s.
- R8-r03-A: live; run r8-20260926T215240-6712dc83ac; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 40.643 s.
- R8-r03-B: live; run r8-20260926T215506-3fd04faca2; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 33.87 s.
- R8-r03-C: live; run r8-20260926T214825-e33a94540d; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 190.069 s.
- R8-r04-A: live; run r8-20260926T224126-3ebfc36216; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 65.032 s.
- R8-r04-B: live; run r8-20260926T223928-5398cde99e; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 68.53 s.
- R8-r04-C: live; run r8-20260926T224330-e5a3d07fae; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 65.486 s.
- R8-r05-A: live; run r8-20260926T213243-6fc24b6480; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 61.632 s.
- R8-r05-B: live; run r8-20260926T212856-d9857d7de6; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 51.18 s.
- R8-r05-C: live; run r8-20260926T213042-5e27c27b63; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 64.08 s.
- R9-r01-A: live; run r9-20260926T214029-bcbe900b68; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 63.91 s.
- R9-r01-B: live; run r9-20260926T213639-3066107040; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 175.869 s.
- R9-r01-C: live; run r9-20260926T213444-7a34f53da1; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 62.845 s.
- R9-r02-A: live; run r9-20260926T192358-44dc6afbc0; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 51.972 s.
- R9-r02-B: live; run r9-20260926T192138-06177be375; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 53.378 s.
- R9-r02-C: live; run r9-20260926T192535-b9bb574f29; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 64.861 s.
- R9-r03-A: live; run r9-20260926T183433-10ee9b73b4; attempt 2; trial status completed, runner exit 0, same-prompt true, wall 70.553 s.
- R9-r03-B: live; run r9-20260926T182633-da25215d9d; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 122.803 s.
- R9-r03-C: live; run r9-20260926T182427-ca17fa57f2; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 70.738 s.
- R9-r04-A: live; run r9-20260926T171433-61c8f2f318; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 124.946 s.
- R9-r04-B: live; run r9-20260926T171156-9e2d3b4f55; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 101.649 s.
- R9-r04-C: live; run r9-20260926T171726-80b4d2f934; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 75.257 s.
- R9-r05-A: live; run r9-20260926T204735-b4486903fa; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 51.208 s.
- R9-r05-B: live; run r9-20260926T204156-5de980ddc8; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 62.434 s.
- R9-r05-C: live; run r9-20260926T204936-bd0aa28852; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 62.079 s.
