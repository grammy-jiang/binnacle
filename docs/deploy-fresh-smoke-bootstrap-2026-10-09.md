# Deploy-gate target-version Smoke compatibility

Date: 2026-10-09. Scope: the deployment orchestrator only.

## Failure reproduced on first v1.0.0 attempt

The first FastMCP 4.1 candidate passed all seven required GitHub checks.
The guarded deployment correctly rolled it back when only 3 of 12 Journal
correlations were accepted. All twelve MCP tool calls themselves succeeded,
with no runtime tracebacks.

The pre-upgrade deployment CLI had imported the old Smoke code **before**
fast-forwarding the checkout. Python retained that old function in memory
even after Git switched the source tree to the new journaling format.
The old verifier required raw fixture strings in tool-call arguments, whereas
the new privacy policy deliberately removes those strings. The rollback was
correct under the evidence available, not an MCP protocol failure.

An isolated real loopback HTTP probe using the candidate FastMCP 4.1 code
verified that modern and legacy clients successfully propagate validated,
opaque request-metadata Smoke IDs.

## Correction

The controller still runs the same mandatory Smoke program, but launches it
through the **current checkout's own Python and scripts/deploy_smoke.py**
after the fast-forward and after a rollback. A new Python process cannot keep
the previous source tree's imported Smoke callable cached. The subprocess
exit status, overall result and individual check rows must agree. Missing,
ambiguous or inconsistent output returns an ALERT and blocks promotion.

The existing CI, clean-tree requirement, quiet period, fast-forward
restriction, service reload/restart, real MCP call checks, Journal matching,
atomic multi-ref push and rollback rules remain unchanged. The Smoke timeout
is bounded, and there is no escape hatch or bypass.

## Safe two-stage rollout

1. Build and CI-validate a **bridge commit** from the still-deployed base
   containing only this deployment-runner correction plus regressions.
2. Deploy the bridge using the existing (old) guarded controller; it changes
   deployment scripts only, so the pre-existing Smoke schema still matches.
3. Merge the bridge into the FastMCP 4.1 final release candidate, without
   rewriting earlier candidate history or weakening governance.
4. Re-run exact-SHA CI on that final integration commit and deploy from the
   bridge using the corrected fresh-process Smoke.
5. Publish the annotated release tag and GitHub Release only after a
   successful deployment. Confirm the live MCP service restarts; do not
   restart durable Job Manager while it owns running jobs.

Focused tests must prove: valid OK/WARN/ALERT parsing; errors fail closed;
the executable and script paths follow the current checkout; re-executing
after a file change really uses the new script; a failed Smoke still rolls
back and never pushes production refs.
