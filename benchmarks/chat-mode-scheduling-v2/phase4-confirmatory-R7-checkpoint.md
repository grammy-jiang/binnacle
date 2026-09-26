# Phase 4 confirmatory R7 checkpoint

- Frozen at 2026-09-26T20:43:38+10:00 for task 4.9.4.
- Frozen schedule SHA-256:
  516938320afdf9dade5e03b8262a9e6ef9c95ad5d0330c20d1ce23d0ec68e734.
- R7 slot integrity: PASS — 9/9 canonical slots have exactly one owning
  outcome (6 live A/B slots plus 3 reused C300 calibration slots).
- Reruns: 0. Unscorable-routing slots: 0. All state directories are
  present and all owning rows record host_load_flagged.
- Routing misses: A 0/3 (0%), B 0/3 (0%), C 0/3 (0%). Reused C300 routing
  uses the already-resolved D6 retained-log recovery.
- R7-r02-B exited 1 after submission and is deliberately retained as the
  first correctly routed submitted outcome; it was not rerun.
- Analysis: 8/9 same-prompt completion,
  1/9 interrupted, and
  0/9 host-load flagged.
- D9 timing recovery recomputed R7-r01-C (158.269 s -> 154.656 s) and
  R7-r03-C (160.772 s -> 157.100 s) from saved conversation final-assistant
  timestamps.
- R7-r01-A, R7-r01-B, and R7-r02-C remain poll-observed after bounded
  read_chat.py recovery attempts produced no conversation payload.
- Frozen evidence tree:
  benchmarks/chat-mode-scheduling-v2/phase4-confirmatory-evidence/R7 has nine
  deterministic tar.gz archives containing 126 source files; tree SHA-256
  e64ba86062d91863653bfed02946b9e0fb95ed0285009af8c9bdfb4d82a5ecf6.

## Canonical slots

- R7-r01-A: live; run r7-20260926T181657-83b81b3556;
  trial status completed, runner exit 0,
  same-prompt true, wall
  168.054 s.
- R7-r01-B: live; run r7-20260926T182033-09141708b5;
  trial status completed, runner exit 0,
  same-prompt true, wall
  186.229 s.
- R7-r01-C: reused C300 calibration; run r7-20260926T014111-06c1b6225d;
  trial status completed, runner exit 0,
  same-prompt true, wall
  154.656 s.
- R7-r02-A: live; run r7-20260926T202240-bf043fc386;
  trial status completed, runner exit 0,
  same-prompt true, wall
  161.881 s.
- R7-r02-B: live; run r7-20260926T200743-e7db9a34ac;
  trial status failed, runner exit 1,
  same-prompt false, wall
  152.812 s.
- R7-r02-C: reused C300 calibration; run r7-20260926T014904-e32fdb3f45;
  trial status completed, runner exit 0,
  same-prompt true, wall
  155.16 s.
- R7-r03-A: live; run r7-20260926T175936-2605f95749;
  trial status completed, runner exit 0,
  same-prompt true, wall
  163.661 s.
- R7-r03-B: live; run r7-20260926T180753-639dc8ecc9;
  trial status completed, runner exit 0,
  same-prompt true, wall
  158.313 s.
- R7-r03-C: reused C300 calibration; run r7-20260926T015728-011a38e147;
  trial status completed, runner exit 0,
  same-prompt true, wall
  157.1 s.
