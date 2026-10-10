# R1 → R2 evidence handoff and frozen execution provenance

**Status:** R1 retrospective report completed; R2-0 frozen and R2 CLI experiments started under the *original*, immutable R2 plan revision.

## Authoritative R1 report

The complete prior investigation is in the R1 research branch:

[R1 final investigation results](https://github.com/grammy-jiang/binnacle/blob/50cca28695dce8b2f11810b92aa792179b0e9eb4/docs/job-awareness-feasibility/R1-INVESTIGATION-RESULTS.md)

- R1 report commit: 50cca28695dce8b2f11810b92aa792179b0e9eb4 (documentation-only retrospective).
- R1 original research plan commit: 62a677b83f5b3a34dddc7fd23595f00ffe89159a.
- R1 tested product source: d61761356ee0fce8ea6d73b0c3043b4881c5645e.
- R1 fixture SHA-256: e1c35bda430a2e8e3794d51032cf827afec7bfa451887731918b7fd529970d41.
- R1 run evidence root: /home/grammy-jiang/Projects/binnacle-job-awareness-results/JA-20261010-174301-ead99b0c.
- R1 authorized Codex reassignment snapshot: revisions/codex-reassignment-v2.
- R1 W1–W4 worker reports and index hashes are recorded in the R1 retrospective, which was independently verified.
- R1 W5 had **no real ChatGPT Chat trials**. Do not present R1 as successful model visibility or per-chat ownership proof.

## Critical results carried into R2

| R1 conclusion | Classification | R2 follow-up |
| --- | --- | --- |
| Metadata and added text are possible native FastMCP result carriers in local ASGI tests | Positive but incomplete | A/D full transport and genuine E1 Chat mode visibility |
| Real authenticated ChatGPT conversation identity is **not demonstrated** | Security gate unresolved | B trusted identity / fail-closed alternatives, E2 gate |
| Existing server fetch and public cursor cannot reliably confirm client receipt | **Refuted design assumption** | C new authenticated receipt or later-call opaque proof |
| Synthetic render hints are small and fast but full-call/token cost unmeasured | Inconclusive | D full local transport and measured cost |
| Same-turn automatic model continuation was not tested | Blocked | E1/E2 genuine Chat mode tests after client permission and B/C gate |

All R2 workers must consume these original R1 results read-only. No R1 result can be rewritten to create a more favorable technical verdict.

## Frozen R2 execution identity

**Important provenance rule:** The R2 operational run was intentionally frozen before this explanatory handoff was appended to Git. Its exact plan revision remains cc386613a20f14cd466f19d0fbd3e38ec6ce9927. Subsequent report/README-only commits do **not** silently change the source SHA, R2 plan SHA, worker input packets, fixture SHA or per-worker model/effort selection.

- R2 run ID: R2-20261010-191506-889bdb8e.
- R2 runtime result root: /home/grammy-jiang/Projects/binnacle-job-awareness-r2-results/R2-20261010-191506-889bdb8e.
- Pinned product source SHA: d61761356ee0fce8ea6d73b0c3043b4881c5645e.
- **Frozen R2 plan SHA: cc386613a20f14cd466f19d0fbd3e38ec6ce9927.**
- Frozen R2 fixture SHA-256: 74c97e6d1b35f86be8484560d4cbb3f7a56090ceaa87da4303a206771016847e.
- R2-0 completed PARTIAL (local source/fixture/packet validation passed, genuine Chat mode client authorization not verified).
- Five frozen worker packets in inputs/A.input.json, B.input.json, C.input.json, D.input.json, E0.input.json have SHA-256 hashes recorded in run-manifest.json. The five worker checkouts use only the unchanged product source commit.
- A/B/C/D were dispatched after R2-0. E0 offline trial preparation reached PASS. E1/E2 true ChatGPT trials require account/UI/plugin gates and have not run as of handoff writing.

The separate reporting-only documentation may mention later source evidence but cannot retroactively modify already sealed workers' inputs. If an operational testing requirement genuinely changes, create a separate explicitly versioned new run/manifest instead of secretly relabeling the old one.

## Next gate and evidence discipline

R2-A may prove a local synthetic MCP app and identify official connection procedures, but **new ChatGPT app/plugin installation and account connection are not automatically authorized**. The supported user-facing connection step must be explicit and auditable. A native HTTP response is not a ChatGPT model-use event. Do not use Codex Desktop or Work as a substitute for Chat mode.

B must show authenticated per-chat identity, or fail closed without unsolicited per-chat reminders. C must show actual consumer proof separate from server fetch and preserve retained output. D must measure full local HTTP plus middleware cost rather than quoting only R1 rendering cost.

Supervisor only checks terminal worker evidence and writes the R2 results report; it does not manufacture E1/E2 data or mark G0–G7 passed because CLI workers finished.

See [R2 execution status and results](R2-RESULTS.md) and the original [R2 execution plan](README.md).
