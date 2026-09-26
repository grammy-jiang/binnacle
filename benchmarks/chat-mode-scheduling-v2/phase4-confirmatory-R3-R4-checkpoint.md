# Phase 4 confirmatory R3/R4 checkpoint

- Frozen at 2026-09-26T23:40:39+10:00 for task 4.9.2.
- Frozen schedule SHA-256: 516938320afdf9dade5e03b8262a9e6ef9c95ad5d0330c20d1ce23d0ec68e734.
- R3/R4 slot integrity: PASS — 30/30 canonical slots have exactly one owning outcome.
- Pre-submit failures: 1. Reruns: 0. Unscorable-routing slots: 0. All state directories are present and all owning rows record host_load_flagged.
- Routing misses: A 0/10 (0.00%), B 0/10 (0.00%), C 0/10 (0.00%). No arm exceeds the >10% evidence-integrity threshold.
- R3-r04-A: one pre-submit failure did not submit; the subsequent finished submission is the first submitted outcome and owns the slot.
- Analysis: 26/30 same-prompt completion, 0/30 interrupted, 0/30 premature handoff, 0/30 failed trial status, 4/30 host-load flagged.
- Frozen evidence tree: benchmarks/chat-mode-scheduling-v2/phase4-confirmatory-evidence/R3-R4 has 30 deterministic tar.gz archives containing 401 source files; normalized source-manifest SHA-256 3c73d3025bf97e5f477e1a30e11f56ad8bba81a1180293bac0e937ef1fd11ef5.

## D9 settle-time recovery

No previously poll-observed trial was recomputed during this checkpoint.

Trials that remain explicitly poll-observed:

- R3-r02-A: 50.526 s; read_chat_timeout_30s.
- R3-r02-B: 52.603 s; read_chat_human_view_without_raw_conversation_json.
- R3-r03-B: 63.789 s; read_chat_human_view_without_raw_conversation_json.
- R3-r03-C: 52.166 s; read_chat_timeout_30s.
- R3-r04-B: 51.6 s; read_chat_human_view_without_raw_conversation_json.
- R3-r05-A: 75.465 s; read_chat_timeout_30s.
- R4-r01-A: 124.615 s; read_chat_timeout_30s.
- R4-r01-B: 150.05 s; read_chat_timeout_30s.
- R4-r01-C: 339.255 s; read_chat_timeout_30s.
- R4-r02-A: 129.725 s; read_chat_timeout_30s.
- R4-r02-B: 105.805 s; read_chat_timeout_30s.
- R4-r02-C: 113.551 s; read_chat_timeout_30s.
- R4-r03-B: 127.739 s; read_chat_timeout_30s.
- R4-r03-C: 161.673 s; read_chat_timeout_30s.
- R4-r04-A: 174.695 s; read_chat_timeout_30s.
- R4-r04-C: 127.515 s; read_chat_human_view_without_raw_conversation_json.
- R4-r05-A: 122.636 s; read_chat_timeout_30s.
- R4-r05-B: 130.743 s; read_chat_timeout_30s.
- R4-r05-C: 126.057 s; read_chat_timeout_30s.

## Canonical slots

- R3-r01-A: live; run r3-20260926T222915-5bff1ef675; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 45.455 s.
- R3-r01-B: live; run r3-20260926T222600-61eb0f7a08; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 48.67 s.
- R3-r01-C: live; run r3-20260926T223056-d2c8d3851f; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 45.298 s.
- R3-r02-A: live; run r3-20260926T214500-5a03f81a00; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 50.526 s.
- R3-r02-B: live; run r3-20260926T214642-5ebcd84104; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 52.603 s.
- R3-r02-C: live; run r3-20260926T214226-35cd0572d8; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 65.827 s.
- R3-r03-A: live; run r3-20260926T225427-9346ba3c7a; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 46.638 s.
- R3-r03-B: live; run r3-20260926T230442-fe3705276a; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 63.789 s.
- R3-r03-C: live; run r3-20260926T230256-0cc9d192de; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 52.166 s.
- R3-r04-A: live; run r3-20260926T191632-d8b34a7d58; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 45.225 s.
- R3-r04-B: live; run r3-20260926T191952-841fbe993f; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 51.6 s.
- R3-r04-C: live; run r3-20260926T191840-4daa306278; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 42.207 s.
- R3-r05-A: live; run r3-20260926T195201-fefc5ce1bd; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 75.465 s.
- R3-r05-B: live; run r3-20260926T194921-e26dbb24ed; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 47.544 s.
- R3-r05-C: live; run r3-20260926T194305-aa0747ef6e; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 41.37 s.
- R4-r01-A: live; run r4-20260926T174331-52f9ca9835; attempt 1; trial status completed, runner exit 0, same-prompt false, wall 124.615 s.
- R4-r01-B: live; run r4-20260926T173333-32be35d755; attempt 1; trial status completed, runner exit 0, same-prompt false, wall 150.05 s.
- R4-r01-C: live; run r4-20260926T173658-4c0f611091; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 339.255 s.
- R4-r02-A: live; run r4-20260926T220228-61f5d422e3; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 129.725 s.
- R4-r02-B: live; run r4-20260926T215658-b07da72b14; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 105.805 s.
- R4-r02-C: live; run r4-20260926T215940-934717f21a; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 113.551 s.
- R4-r03-A: live; run r4-20260926T224833-1de89fc145; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 107.172 s.
- R4-r03-B: live; run r4-20260926T224526-8d9ea11bf6; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 127.739 s.
- R4-r03-C: live; run r4-20260926T225056-cb4bc539d3; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 161.673 s.
- R4-r04-A: live; run r4-20260926T170143-1203fcbcca; attempt 1; trial status completed, runner exit 0, same-prompt false, wall 174.695 s.
- R4-r04-B: live; run r4-20260926T165203-37ee3d3c77; attempt 1; trial status completed, runner exit 0, same-prompt false, wall 103.045 s.
- R4-r04-C: live; run r4-20260926T165830-b01ee98fd3; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 127.515 s.
- R4-r05-A: live; run r4-20260926T231235-7ff3c866ac; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 122.636 s.
- R4-r05-B: live; run r4-20260926T231827-e372a9e8f8; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 130.743 s.
- R4-r05-C: live; run r4-20260926T231532-bdefeb0234; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 126.057 s.
