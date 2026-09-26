# Phase 4 confirmatory R1/R2 checkpoint

- Frozen at 2026-09-27T01:19:29+10:00 for task 4.9.1.
- Frozen schedule SHA-256: 516938320afdf9dade5e03b8262a9e6ef9c95ad5d0330c20d1ce23d0ec68e734.
- R1/R2 slot integrity: PASS — 30/30 canonical slots have exactly one owning outcome.
- Pre-submit failures: 1. Pre-submit resubmissions: 1. Reruns: 0. Unscorable-routing slots: 0. All owning state directories are present and all owning rows record host_load_flagged.
- Routing misses: A 0/10 (0.00%), B 0/10 (0.00%), C 0/10 (0.00%). No arm exceeds the >10% evidence-integrity threshold.
- R2-r04-A correction: the original get-instructions harness failure occurred before submission and was reclassified as non-owning pre_submit_failure; the same frozen slot was then resubmitted once.
- R2-r04-A submitted result: the resubmission completed its chat but the harness ended with production invariant changed during benchmark: status. The only production difference was the unrelated untracked docs/lsp-development-intelligence-design-2026-09-27.md disappearing; HEAD, config hash, unit hash, ActiveState and SubState were unchanged. The submitted row owns the slot and was not rerun.
- Analysis: 30/30 same-prompt completion, 0/30 interrupted, 0/30 premature handoff, 1/30 failed trial status, 3/30 host-load flagged.
- Frozen evidence tree: benchmarks/chat-mode-scheduling-v2/phase4-confirmatory-evidence/R1-R2 has 30 deterministic tar.gz archives containing 416 source files; normalized source-manifest SHA-256 b36db72b69392d863401faaa452992077ab3ae45661b8dd3bbb1ef990e0030f1.

## D9 settle-time recovery

No previously poll-observed trial was recomputed during this checkpoint.

Trials that remain explicitly poll-observed:

- R1-r01-C: 68.848 s; read_chat_timeout_30s.
- R1-r03-A: 70.709 s; read_chat_timeout_30s.
- R1-r03-B: 75.802 s; read_chat_timeout_30s.
- R1-r05-A: 51.664 s; read_chat_timeout_30s.
- R1-r05-B: 63.412 s; read_chat_timeout_30s.
- R1-r05-C: 70.931 s; read_chat_timeout_30s.
- R2-r02-B: 25.373 s; read_chat_timeout_30s.
- R2-r02-C: 72.551 s; read_chat_timeout_30s.
- R2-r03-A: 50.09 s; read_chat_timeout_30s.
- R2-r04-A: 54.22 s; read_chat_timeout_30s.

## Canonical slots

- R1-r01-A: live; run r1-20260926T232602-32f8001447; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 23.988 s.
- R1-r01-B: live; run r1-20260926T232325-a02d18845f; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 19.21 s.
- R1-r01-C: live; run r1-20260926T232128-6390f9871b; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 68.848 s.
- R1-r02-A: live; run r1-20260926T181540-4c6b55f9b7; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 24.852 s.
- R1-r02-B: live; run r1-20260926T181103-638dafc31d; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 19.534 s.
- R1-r02-C: live; run r1-20260926T181244-5a91fea402; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 19.55 s.
- R1-r03-A: live; run r1-20260926T203729-8abe9e86ac; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 70.709 s.
- R1-r03-B: live; run r1-20260926T203525-6ee550efc2; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 75.802 s.
- R1-r03-C: live; run r1-20260926T203928-2adb3d836e; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 15.487 s.
- R1-r04-A: live; run r1-20260926T172658-8d6326daf5; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 21.44 s.
- R1-r04-B: live; run r1-20260926T173154-cfb0eea6fe; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 32.748 s.
- R1-r04-C: live; run r1-20260926T172530-312f6bda31; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 25.091 s.
- R1-r05-A: live; run r1-20260926T205656-617f5b0e7c; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 51.664 s.
- R1-r05-B: live; run r1-20260926T205837-a6adfedbc7; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 63.412 s.
- R1-r05-C: live; run r1-20260926T210029-8045d731db; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 70.931 s.
- R2-r01-A: live; run r2-20260926T212055-27314e8b6f; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 18.854 s.
- R2-r01-B: live; run r2-20260926T211857-870de21478; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 15.315 s.
- R2-r01-C: live; run r2-20260926T211734-598a0a3bd3; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 17.572 s.
- R2-r02-A: live; run r2-20260926T205447-826ff2bc35; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 27.442 s.
- R2-r02-B: live; run r2-20260926T205130-8876637d74; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 25.373 s.
- R2-r02-C: live; run r2-20260926T205244-0ba07f1e5d; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 72.551 s.
- R2-r03-A: live; run r2-20260926T221656-22d7f01d6f; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 50.09 s.
- R2-r03-B: live; run r2-20260926T221840-fdfceec144; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 17.201 s.
- R2-r03-C: live; run r2-20260926T221424-29c948f9b9; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 18.58 s.
- R2-r04-A: live; run r2-20260927T003210-7c2132fad3; attempt 1; trial status failed, runner exit 1, same-prompt true, wall 54.22 s.
- R2-r04-B: live; run r2-20260926T171927-121288fa4d; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 19.583 s.
- R2-r04-C: live; run r2-20260926T172128-880ff57c6b; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 15.566 s.
- R2-r05-A: live; run r2-20260926T184241-58bd83c90c; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 20.387 s.
- R2-r05-B: live; run r2-20260926T183917-c7ca125402; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 16.679 s.
- R2-r05-C: live; run r2-20260926T184048-269748114c; attempt 1; trial status completed, runner exit 0, same-prompt true, wall 25.587 s.
