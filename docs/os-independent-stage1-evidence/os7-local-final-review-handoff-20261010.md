# Stage 1 OS0–OS7 local qualification and independent review handoff

**State: LOCAL_QUALIFIED / INDEPENDENT_REVIEW_PENDING / CI_PENDING.**
Not a Stage 1 acceptance, deployment approval, independent signoff, or
macOS support declaration.

- Task: `BINNACLE-OS-STAGE1-IMPLEMENT-20261009`.
- Production Linux base: v1.0.1, `02f4bab9bc7562668ffc41d622c4274449933768`.
- Approved plan commit: `19a3cf1e43755ed4aee3837c25ea63188058a26e`.
- Executable-source and architecture-test commit under qualification:
  `3797ffc2e044d88e3fc8768e93775a23029ff6ad`.
- Source-only changes end at that SHA. The later local-evidence/documentation
  commit changes no runtime code, tests, packaging or workflows; GitHub CI and
  review must use the actual **final PR HEAD**, never substitute this earlier
  executable-source SHA when evaluating the head itself.
- PR: [Binnacle Stage 1 PR #18](https://github.com/grammy-jiang/binnacle/pull/18).
- Machine: Raspberry Pi Linux, implementation worktree
  `/home/grammy-jiang/Projects/binnacle-os-independent-stage1-impl`.
- Machine-readable exact-source evidence checksums and test markers:
  `os7-final-local-acceptance-20261010.json` (local `.log` outputs remain on
  the Pi; their SHA-256 hashes and the original commands are in the JSON).

## Stages and local checks

| Stage | Evidence/result | Gate |
| --- | --- | --- |
| OS0 | Frozen 4-profile raw Linux/MCP eight-tool behavior; SHA-256 source and unit inventory | Local pass |
| OS1 | Core/platform one-way imports, 21 Import Linter contracts, dynamic and negative architecture probes | Local pass; independent architecture disposition pending |
| OS2 | One host composition selector, pure FastMCP factory and fake-platform contracts; Linux fallback prevented on unsupported hosts | Local pass; review pending |
| OS3 | Native Linux pidfd verified signal leases, reaper compatibility and old/new JSON RPC; P1 and P2 review corrections below | Local pass; security review pending |
| OS4 | systemd provisioner/readiness and deployment semantics retained; no production restart | Local pass; deployment review pending |
| OS5 | Linux-free paths/diagnostics/log processing; existing non-sandbox path TOCTOU explicitly scoped | Local pass; threat-model review pending |
| OS6 | 152 production modules and 49 scripts accounted for; no forbidden reverse dependencies | Local pass; independent source review pending |
| OS7 | Final exact-source suite: 2548 passed, 3 skipped, 0 failed; module branch-coverage gate: 131 production/48 scripts/0 errors; all five tox Python versions 3.10–3.14; one clean packaging smoke; 35 full pre-commit hooks plus pre-push gate passed | Local pass; exact PR-head CI, independent review and live deployment pending |

## Previously actionable code review findings, incorporated

- Codex P1: a single descendant EPERM must not abort signaling of other
  verified descendants. Addressed in `0b296f903dc260011da1bdbf052355eb5613a2fc`.
- Codex P2: after partial native signal delivery, a finished leader must not
  cause later stop RPCs to falsely report success while a descendant may
  remain alive. Persist `stop_signal_partial` under the job store lock before
  reaper wait, and fail subsequent owner/direct-RPC stops explicitly.
  Addressed in `14ea285d0b4778bbed3455205df52efe70118504`, with race,
  legacy metadata, storage errors and real AF_UNIX retry tests.
- The two affected AST-layout tests initially rejected legitimate new
  `job_stop` imports; the narrow generic-owner dependency edges were added
  by `3797ffc2e044d88e3fc8768e93775a23029ff6ad` without allowing Linux
  reverse imports. Architecture test file: 158 passing cases; all final
  gates above completed after that change.
- Previous automated Codex and Copilot review comments do **not** certify
  that the corrected final source has an independent disposition.

## Independent reviewer decision required

Review the original approved plan, all actual diff and relevant evidence,
particularly these six source-bound cells from the preceding
`os7-independent-review-packet.md`:

1. P0 job identity, owner-verification, pidfd lease, TERM/KILL and persistent
   partial-delivery failures (include concurrent reaper and EPERM paths).
2. P0 resource accounting, cgroup scope/recovery and durable RPC/schema parity.
3. P0 single FastMCP root, three native children, providers/transforms,
   middleware, authentication and unchanged four visibility profiles.
4. P0 Linux systemd unit/CLI semantics, quiet-window rules, guarded deployment
   and rollback; no active stable manager restart.
5. P1 file aliases/symlinks, canonical path TOCTOU threat model, log privacy
   and optional Linux services.
6. P1 architecture negative gates, old/new compatibility, wheel/sdist,
   Python matrix, coverage and exact-commit GitHub trusted CI.

Reviewer must identify **reviewer identity, actual reviewed final PR SHA,
individual cell dispositions, actionable findings, and overall APPROVE_DESIGN,
REVISE or BLOCKED_POLICY**. A request from the implementation owner or a
self-authored checklist is not an independent review. Review changes, if any,
require repairs and renewed exact-source checks. Human disposition is still
required for the protected process-safety/deployment policy before production.

## Production boundary and honest residuals

At this snapshot production/master is still v1.0.1, both
`binnacle-mcp.service` and `binnacle-jobs.service` are active, each with
`NRestarts=0`; there are unrelated untracked docs in the production checkout,
which must not be touched or cleaned by this task. No candidate merge,
production restart, upgrade, service deployment or live smoke has occurred.
A prior PR head had passing CI; **new final-head CI is pending**.

Unproven identity of a later-forked, hidden or escaped child is not authority
to signal it. Resource counters never imply signal ownership. The existing
canonical path policy is not a descriptor-level sandbox against a concurrent
same-user filesystem attacker. Three pre-existing script coverage debts are
reported by the successful coverage policy gate, not silently hidden.

Remaining OS7 sequence: push the final evidence-only update through normal
Git hooks, obtain all trusted GitHub CI checks for final PR HEAD, seek genuine
independent re-review, satisfy protected human policy/quiet-window constraints,
then use the existing guarded production deployment workflow and collect
rollback/live smoke/doctor evidence. Do not mark OS7 accepted until completed.
Stage 2 native Darwin work is deliberately **not implemented**; see
`os7-darwin-stage2-backlog-20261010.md`.
