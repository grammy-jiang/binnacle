# Stage 1 OS7 mandatory independent review packet

Task: BINNACLE-OS-STAGE1-IMPLEMENT-20261009.

**REVIEW NOT YET RECEIVED.** The implementation owner prepared this
source-bound dossier. An automated hook or the author's own local tests
cannot count as independent reviewer approval. The reviewed candidate must
be identified by its actual Git SHA; compare the reviewed SHA with current
`git rev-parse HEAD` before accepting results.

## Authoritative inputs

- Approved implementation plan: `docs/os-independent-stage1-implementation-plan-2026-10-09.md`
- Baseline: `v1.0.1` commit `02f4bab9bc7562668ffc41d622c4274449933768`
- Plan commit: `19a3cf1e43755ed4aee3837c25ea63188058a26e`
- Local source SHA tested before this report: `02879e8e34215515500209f80ba24aaa7438aadc`
- Exact OS0 reference: `docs/os-independent-stage1-evidence/os0-raw-mcp-surface.json`,
  `os0-host-baseline.json`, `os0-manifest.sha256`
- Source inventory: `os6-source-reconciliation.json`, 152 production modules,
  49 Python scripts, explicit KEEP/BOUNDARY/LINUX decisions
- Local gates: `os7-local-acceptance.json` with checksums of six actual
  test/lint/coverage/matrix/package logs
- Current working branch:
  `refactor/os-independent-stage1-implementation-20261009`

## Independent review cells required

| Area | Specific acceptance questions | Disposition |
| --- | --- | --- |
| Process identity and safety (P0) | Can Linux pidfd lease prove ownership without unintended signals after boot/PID reuse, ancestor reparenting, leader exit, signal/grace escalation? Are legacy records handled safely without breaking old managers? | REVIEW_PENDING |
| Resource containment and accounting (P0) | Are cgroup capture, scope lifecycle, finalizer, restart, cleanup and no-accounting behavior compatible with v1.0.1? Is resource counter ownership never mistaken for signal authority? | REVIEW_PENDING |
| Native FastMCP composition (P0) | Exactly one MCP root, three native children/eight public tools, middleware/transform/auth/visibility unchanged, no second framework/registry or FastMCP Tasks for durable jobs? | REVIEW_PENDING |
| Linux services/deployment (P0) | Unit bytes/markers, CLI outcomes, diagnostics, safe quiet and rollback gates, no active stable manager restart? Is the generic contract free of systemd/procfs? | REVIEW_PENDING |
| Files, Search, telemetry (P1) | Are aliases, directory escapes and root retargeting correct without exposing private paths? Is the documented TOCTOU limitation acceptable for the existing non-sandbox threat model? | REVIEW_PENDING |
| Infrastructure and packaging (P1) | Is every module classified; do import/negative gates prevent return paths; do full two-lane, Python 3.10–3.14, coverage/CI and wheels authentically pass? | REVIEW_PENDING |

Reviewer must respond `APPROVE_DESIGN`, `REVISE` or `BLOCKED_POLICY`,
give individual cell findings, reviewer identity, source SHA, and evidence
paths. A `REVISE` requires actual source corrections and a new review on
the resulting SHA. Review must not downgrade process-signal safety or
declared public compatibility to obtain PASS.

## Known limits and production boundary

The native lease pins processes observed at acquisition; it cannot prove
membership of children forked after enumeration, escaped/reparented tasks
that cannot be observed, or atomic group-wide termination. Older records
without identity metadata remain readable but do not authorize unverified
signals. Binnacle's canonical path guard is not a descriptor-level
filesystem sandbox against concurrent local same-user mutation; this
threat-model difference must be explicit in the review disposition.

Local hooks, coverage, 5-version tox and package acceptance have passed;
GitHub exact-SHA CI and independent reviews have not yet been completed.
No production checkout mutation, GitHub branch merge or service restart
is authorized *by this document*. The pre-existing guarded deployment
workflow and active jobs safety controls remain mandatory.
