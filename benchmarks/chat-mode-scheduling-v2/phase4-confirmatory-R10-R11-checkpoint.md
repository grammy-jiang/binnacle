# Phase 4 confirmatory R10/R11 checkpoint

- Frozen at 2026-09-27T01:33:15+10:00 for task 4.9.6.
- Frozen schedule SHA-256: 516938320afdf9dade5e03b8262a9e6ef9c95ad5d0330c20d1ce23d0ec68e734.
- R10/R11 slot integrity: PASS — 30/30 canonical slots have exactly one owning outcome.
- Pre-submit failures: 0. Reruns: 0. Unscorable-routing slots: 0. All owning state directories are present and all owning rows record host_load_flagged.
- Routing misses: A 0/10 (0.00%), B 0/10 (0.00%), C 0/10 (0.00%). No arm exceeds the >10% evidence-integrity threshold.
- Analysis: 30/30 same-prompt completion, 0/30 interrupted, 0/30 premature handoff, 0/30 failed trial status, 5/30 host-load flagged.
- Frozen evidence tree: benchmarks/chat-mode-scheduling-v2/phase4-confirmatory-evidence/R10-R11 has 30 deterministic tar.gz archives containing 415 source files; normalized source-manifest SHA-256 4d626494f71b0465e797adf13ccfeeba7eed5a82ff74d72d116961abb006e6d2.

## D9 settle-time recovery

No previously poll-observed trial was recomputed during this checkpoint.

Trials that remain explicitly poll-observed:

- R10-r01-A: 130.823 s; read_chat_timeout_30s.
- R10-r01-B: 131.224 s; read_chat_human_view_without_raw_conversation_json.
- R10-r01-C: 128.197 s; read_chat_timeout_30s.
- R10-r02-A: 110.064 s; read_chat_timeout_30s.
- R10-r02-B: 115.15 s; read_chat_human_view_without_raw_conversation_json.
- R10-r02-C: 116.765 s; read_chat_timeout_30s.
- R10-r04-A: 172.378 s; read_chat_timeout_30s.
- R10-r04-B: 104.774 s; read_chat_human_view_without_raw_conversation_json.
- R10-r04-C: 156.978 s; read_chat_timeout_30s.
- R11-r01-B: 51.781 s; read_chat_timeout_30s.
- R11-r05-A: 70.239 s; read_chat_timeout_30s.
- R11-r05-B: 73.622 s; read_chat_timeout_30s.
- R11-r05-C: 70.806 s; read_chat_human_view_without_raw_conversation_json.

## Canonical slots

- R10-r01-A: live; run r10-20260926T210827-42f18f9d43; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 130.823 s.
- R10-r01-B: live; run r10-20260926T210229-269635dd8d; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 131.224 s.
- R10-r01-C: live; run r10-20260926T210529-fcd281e693; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 128.197 s.
- R10-r02-A: live; run r10-20260926T220537-4a16a7a653; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 110.064 s.
- R10-r02-B: live; run r10-20260926T221136-cc88039020; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 115.15 s.
- R10-r02-C: live; run r10-20260926T220841-c79ce8945b; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 116.765 s.
- R10-r03-A: live; run r10-20260926T164952-f59d38d564; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 102.002 s.
- R10-r03-B: live; run r10-20260926T164735-eb78f3969c; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 105.56 s.
- R10-r03-C: live; run r10-20260926T164524-2715ab58c3; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 102.1 s.
- R10-r04-A: live; run r10-20260926T233046-eab06ceb13; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 172.378 s.
- R10-r04-B: live; run r10-20260926T232759-d4a5465607; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 104.774 s.
- R10-r04-C: live; run r10-20260926T233448-cd6f149f35; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 156.978 s.
- R10-r05-A: live; run r10-20260926T184450-3e14540efc; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 105.704 s.
- R10-r05-B: live; run r10-20260926T184730-c1acf01c64; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 103.223 s.
- R10-r05-C: live; run r10-20260926T185034-d02890429e; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 105.783 s.
- R11-r01-A: live; run r11-20260926T222439-e382f957d3; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 31.238 s.
- R11-r01-B: live; run r11-20260926T222300-e24c838366; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 51.781 s.
- R11-r01-C: live; run r11-20260926T222118-571e2b65ac; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 30.623 s.
- R11-r02-A: live; run r11-20260926T170534-6bce184f9a; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 28.943 s.
- R11-r02-B: live; run r11-20260926T170931-dff2e37086; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 25.675 s.
- R11-r02-C: live; run r11-20260926T170729-b57adfc725; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 34.024 s.
- R11-r03-A: live; run r11-20260926T195728-268911e217; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 41.939 s.
- R11-r03-B: live; run r11-20260926T195635-2c0166e428; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 30.586 s.
- R11-r03-C: live; run r11-20260926T195427-2a0778fd41; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 26.918 s.
- R11-r04-A: live; run r11-20260926T190347-48edc10393; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 48.889 s.
- R11-r04-B: live; run r11-20260926T190541-9d5be3f217; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 66.523 s.
- R11-r04-C: live; run r11-20260926T190147-860ea2fa3e; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 33.233 s.
- R11-r05-A: live; run r11-20260926T211127-0d064f8436; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 70.239 s.
- R11-r05-B: live; run r11-20260926T211524-0f5885a101; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 73.622 s.
- R11-r05-C: live; run r11-20260926T211327-11e5aba83b; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 70.806 s.
