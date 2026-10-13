# R6 W3 implementation checkpoint — 2026-10-13

## Source of authority

The approved execution plan and 24-lane task manifest live in the original
binnacle-macos-direct-plan-20261011 planning worktree, respectively named
MACOS-IMPLEMENTATION-PLAN-DIRECT-2026-10-11.md and
MACOS-IMPLEMENTATION-TASKS-2026-10-11.json. Related implementation and test
acceptance designs live in this directory.

The private R3 execution history on the Raspberry Pi is kept under
~/.local/state/binnacle/macos-local-supervisor/r3-20261011-01/:
NEXT-STEPS.md, run.json, ledger.json and events.jsonl. These frozen prior-run
records must not be rewritten or misrepresented. The r6w3 integration base is
f7bdd55f90d5d7fd028937023a388b852ad67b8e (prior CI 7/7 and Mac/Pi
post-merge checks). Production remains on 0a40b064 on both hosts.

## FDW-B1-a3 implementation evidence

- Isolated branch: chatgpt/r6w3-fdwb1a3-20261013.
- Existing FDW-B1-a2 07dbe87 merged into f7bdd55f: a6caebe (signed).
- Source changes: bc7fa2cd8ec55598bc08503e588aec56cc553717 (signed).
- Cross-OS Golden pin: 75d31665934fca1db17ea1563d4eb258ba30f57c
  (signed). The two hosts independently generated matching normalized XOS
  SHA-256: 17e7b3e816427eb66c6ebce76d9e1177d4be33b70f9a266bbea76b8ed8e94cab.
- Work: shared refusal contracts and messages, descriptor-relative socket
  substitution detection, refusal of newly appearing in/out-root symlinks,
  depth-bound descriptor measurements for glob/search, code/test module split,
  and updated read_file documentation.
- Mac affected selectors on Python 3.10/3.11/3.12/3.13/3.14: 292 passed
  per interpreter. Pi: 291 affected cases before Golden pin and 2 XOS
  tests at pinned head. Repeat the entire Pi selector set on final SHA.
- Mac commit hooks and type/lint/security/architecture checks: passed.
- No GitHub push, integration merge or production deployment of this work.

## Next dependency-ordered gates

1. Review FDW-B1-a3 candidate read-only against F1–F6. Address blockers;
   re-run both operating systems and the frozen cross-OS Golden.
2. Independently review E1-a6 8d9142e6c2f4e1761c508c7d153a25ee5bf9aadb
   against 675f3ae23af58f9a4068510f25de81fdda67084c (F1–F4,
   SD-90 criteria 1–5). Do not edit the original worker branch.
3. SEC-FU-14 is read-only analysis only; review the Linux edit/write
   resolve-to-write race, options and threat model. Do not restart its
   previously safeguard-blocked attack demonstration.
4. Integrate accepted changes into a separate R6 W3 integration candidate
   following dependency rules, and run post-merge tests in immutable snapshots.
5. Complete R1D, the J7m-w3 deployment review, SD-97 Darwin Python 3.13
   floor, and remaining relevant Mac/Pi acceptance and exact-SHA CI.
6. Only after required approvals and idle-job safeguards, use the existing
   guarded smoke and deployment process. Never modify the current production
   branch as a shortcut.

## Boundaries

Preserve current production service processes, credentials, user-owned files
and other worktrees. No remaining gate is implicitly satisfied by a successful
targeted test. Do not change the original run ledger to claim that a suspended
session performed this work.

## 2026-10-13 follow-up integration (local only)

- R1D's config-keys doctor warning implementation 212f89c and legacy
  check test af4fcf0 have been integrated as separate signed commits.
- SD-97 Darwin Python 3.13 manager floor and capability-aware native skip
  policy are implemented in the candidate, awaiting final acceptance.
- J7m-W3 uses scripts/mac_w3_deploy_gate.py to extend the pinned reviewed
  J7m-a5 deployment gate with crash-loop exit/status classification and
  an additional startup-record doctor check; source and security review
  gates remain required.
- SEC-FU-14 now has an analysis-only findings document beside this file.
- No production deployment, master merge, or ChatGPT live smoke is claimed.
