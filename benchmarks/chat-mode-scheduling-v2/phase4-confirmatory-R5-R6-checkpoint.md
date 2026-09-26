# Phase 4 confirmatory R5/R6 checkpoint

- Frozen at 2026-09-27T01:02:43+10:00 for task 4.9.3.
- Frozen schedule SHA-256: 516938320afdf9dade5e03b8262a9e6ef9c95ad5d0330c20d1ce23d0ec68e734.
- R5/R6 slot integrity: PASS — 30/30 canonical slots have exactly one owning outcome.
- Live rows: 24. Reused C300 calibration slots: 6. Reruns: 0. Unscorable-routing slots: 0.
- All state directories are present and all owning rows record `host_load_flagged`.
- Routing misses: A 0/10 (0.00%), B 0/10 (0.00%), C 0/10 (0.00%).
- No arm exceeds the >10% evidence-integrity threshold.
- Analysis: 30/30 same-prompt completion, 0/30 interrupted, 0/30 premature handoff, 0/30 failed trial status, 6/30 host-load flagged.
- Frozen evidence tree: `benchmarks/chat-mode-scheduling-v2/phase4-confirmatory-evidence/R5-R6` has 30 deterministic tar.gz archives containing 413 source files; normalized source-manifest SHA-256 50c4524bf5a9b14df36d6973333cf51882fcade84daac3e3088476b75c7c3a3a.

## D9 settle-time recovery

- 10 slots already used `conversation_final_assistant_timestamp` before this checkpoint.
- 5 additional slots were recomputed from saved raw conversation final-assistant timestamps.
- 15 slots remain explicitly poll-observed after bounded recovery attempts returned no raw conversation JSON.

Recomputed trials:

- R5-r01-C: 39.867 s → 35.378 s.
- R5-r02-A: 187.849 s → 48.802 s.
- R5-r02-B: 70.774 s → 43.491 s.
- R5-r02-C: 73.489 s → 38.046 s.
- R6-r03-C: 136.337 s → 101.081 s.

Trials that remain explicitly poll-observed:

- R5-r01-B: 51.311 s; http_403_cloudflare_no_raw_conversation_json.
- R5-r03-C: 40.268 s; read_chat_timeout_12s.
- R5-r04-A: 63.92 s; read_chat_timeout_12s.
- R5-r04-C: 51.24 s; read_chat_human_view_without_raw_conversation_json.
- R5-r05-A: 50.147 s; read_chat_timeout_12s.
- R6-r01-A: 172.771 s; read_chat_timeout_12s.
- R6-r01-C: 104.552 s; read_chat_timeout_12s.
- R6-r02-A: 129.431 s; read_chat_human_view_without_raw_conversation_json.
- R6-r02-B: 117.778 s; read_chat_timeout_12s.
- R6-r02-C: 108.399 s; read_chat_timeout_12s.
- R6-r03-A: 155.591 s; read_chat_human_view_without_raw_conversation_json.
- R6-r04-B: 173.411 s; read_chat_timeout_12s.
- R6-r04-C: 130.239 s; read_chat_timeout_12s.
- R6-r05-A: 108.206 s; read_chat_timeout_12s.
- R6-r05-B: 114.779 s; read_chat_timeout_12s.

## Canonical slots

- R5-r01-A: live; run r5-20260926T191136-9765afada8; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 42.531 s.
- R5-r01-B: live; run r5-20260926T190946-e6cc605c99; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 51.311 s.
- R5-r01-C: reused C300 calibration; run r5-20260926T011201-fc8affc406; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 35.378 s.
- R5-r02-A: live; run r5-20260926T175528-138523a997; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 48.802 s.
- R5-r02-B: live; run r5-20260926T175329-8d9f86f9de; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 43.491 s.
- R5-r02-C: reused C300 calibration; run r5-20260926T011406-18b15002f6; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 38.046 s.
- R5-r03-A: live; run r5-20260926T212257-56f0ade9c7; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 39.963 s.
- R5-r03-B: live; run r5-20260926T212616-622c32f5b3; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 40.678 s.
- R5-r03-C: reused C300 calibration; run r5-20260926T011904-c834d991d6; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 40.268 s.
- R5-r04-A: live; run r5-20260926T231038-7f1c642969; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 63.92 s.
- R5-r04-B: live; run r5-20260926T230648-9bb083dca0; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 38.039 s.
- R5-r04-C: live; run r5-20260926T230857-d085096042; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 51.24 s.
- R5-r05-A: live; run r5-20260926T193900-f171fb5412; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 50.147 s.
- R5-r05-B: live; run r5-20260926T193640-c87be0bac9; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 38.892 s.
- R5-r05-C: live; run r5-20260926T194035-5382dc8178; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 39.757 s.
- R6-r01-A: live; run r6-20260926T200405-849aff78d2; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 172.771 s.
- R6-r01-B: live; run r6-20260926T195955-51f131baa1; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 110.588 s.
- R6-r01-C: reused C300 calibration; run r6-20260926T012431-17c772cd31; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 104.552 s.
- R6-r02-A: live; run r6-20260926T234127-a2b52ceb93; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 129.431 s.
- R6-r02-B: live; run r6-20260926T233833-69d6ae63c0; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 117.778 s.
- R6-r02-C: reused C300 calibration; run r6-20260926T012946-4ee162a667; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 108.399 s.
- R6-r03-A: live; run r6-20260926T223603-40ca551ab7; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 155.591 s.
- R6-r03-B: live; run r6-20260926T223322-2d61b11b58; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 106.348 s.
- R6-r03-C: reused C300 calibration; run r6-20260926T013453-c54a224925; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 101.081 s.
- R6-r04-A: live; run r6-20260926T193025-cbd78735b5; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 112.976 s.
- R6-r04-B: live; run r6-20260926T193256-156a9d2f3e; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 173.411 s.
- R6-r04-C: live; run r6-20260926T192727-e12075f8c6; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 130.239 s.
- R6-r05-A: live; run r6-20260926T202954-f42c537d09; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 108.206 s.
- R6-r05-B: live; run r6-20260926T203231-0bceaf425e; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 114.779 s.
- R6-r05-C: live; run r6-20260926T202712-a8847460c9; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 104.385 s.
