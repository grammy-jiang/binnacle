# ChatGPT MCP Compatibility Profile

- **Status:** Draft — no live Binnacle-to-ChatGPT report recorded yet
- **Contract version:** `1.1.0`
- **Target host:** ChatGPT web
- **Initial account plan:** Pro
- **Server revision contract:** [`mcp-revision-support.md`](mcp-revision-support.md)
- **Evaluation contract:** [`mcp-evaluation.md`](mcp-evaluation.md)

## 1. Purpose

This document is the human-readable record of what the actual ChatGPT connection has demonstrated. It is not a list of every feature supported by the MCP specification or SDK.

The governing rule is:

> Binnacle may depend only on behaviour observed for the exact tested ChatGPT product, plan, workspace policy, connection/authentication path, server build, MCP revision, and capability profile.

## 2. Initial Unknown Profile

Until the first real connection is tested:

| Field | Value |
| --- | --- |
| ChatGPT product/surface | ChatGPT web |
| Plan | Pro |
| Workspace type/policy | Unknown |
| Connection method | Secure/private tunnel candidate; unvalidated |
| Authentication profile | Unknown |
| Binnacle build/configuration | Not implemented |
| MCP SDK/tunnel agent | Not selected |
| Server-supported revisions | `2026-07-28`, `2025-11-25`, `2025-06-18`, `2025-03-26` |
| Revision requested/negotiated by ChatGPT | Unknown |
| Client capabilities | Unknown |
| Tool discovery and refresh | Unknown |
| Structured/text result handling | Unknown |
| Read entitlement | Unknown |
| Write/modify entitlement | Unknown; live test required |
| Host confirmation behaviour | Unknown |
| Idempotency/retry/reconnect/cancellation | Unknown |
| Resources, MRTR/elicitation, Tasks | Unknown |
| Owner-only/model-visible boundary | Unknown |
| Result-size, latency, context cost | Unknown |

No unknown value is treated as support.

## 3. Canonical Status Vocabulary

Every axis uses exactly one status:

| Status | Meaning |
| --- | --- |
| `observed-supported` | Required attempts passed the frozen oracle for this exact profile. |
| `observed-limited` | The feature passed only under recorded limits or degraded semantics. |
| `declared-unexercised` | The client declared the feature, but behavioural cases did not pass. |
| `not-declared` | The feature was absent from the relevant declaration. |
| `test-failed` | A valid probe reached the intended layer and failed its oracle. |
| `host-policy-blocked` | Account, plan, workspace, or host policy prevented the test independently of wire compatibility. |
| `server-not-implemented` | Binnacle did not implement the required probe. |
| `not-tested` | No reliable test conclusion exists. |
| `unsupported-by-design` | Binnacle V1 intentionally excludes the feature. |
| `unstable` | Valid repeated runs conflict or fail the stability threshold. |
| `expired` | The evidence passed its validity period or a rerun trigger occurred. |
| `not-applicable` | The optional feature/case is outside the selected profile or not promoted. |

These strings are identical in evaluation manifests and `compatibility_report`.

## 4. Revision Observation

Binnacle records separately:

- its intended supported revision set;
- the version requested by the client;
- the version negotiated for a legacy session;
- the dispatcher implementation version;
- observed client capabilities.

The target revision `2026-07-28` is not reported as the ChatGPT revision unless the actual connection requests it.

## 5. Fundamental Bootstrap Dependencies

The bootstrap implementation requires only:

- authenticated remote/tunnel connection;
- one supported MCP revision;
- Tool discovery/listing;
- Tool invocation;
- JSON Schema inputs;
- bounded text and structured results;
- protocol and Tool execution errors.

It does not depend on:

- Tasks;
- Resources;
- Prompts;
- MRTR/elicitation;
- progress or list-change notifications;
- custom UI;
- Sampling or Roots.

Optional features may be probed without becoming dependencies.

## 6. Bootstrap Tool Phases

`compatibility-core` exposes:

- `binnacle_probe`;
- `system_inspect`;
- `probe_result_formats`;
- `probe_error`;
- `compatibility_report`.

`compatibility-write-probe` additionally exposes:

- `probe_workspace_prepare`;
- `probe_workspace_write`;
- `probe_workspace_cleanup`.

The write/cleanup Tools remain unsupported for a HOST profile unless the actual account/workspace permits their calls and the host-confirmation cases pass.

## 7. Evidence and Sanitization

The server records protocol facts but never stores or returns:

- bearer tokens, cookies, full authorization headers, private keys, or raw secrets;
- raw owner-private data unrelated to the test;
- reusable authority material;
- unbounded prompt or response content.

Evidence uses sanitized wire frames, schema reports, audit references, bounded UI observations, and detached bundle receipts.

## 8. Evaluation Source of Truth

The executable cases and quantitative thresholds are defined in:

- `spec/mcp/evaluation-cases.yaml`;
- `spec/mcp/evaluation-profile.yaml`;
- `schemas/mcp/evaluation-manifest.schema.json`.

A prose update here cannot promote a feature without a fresh passing manifest and evidence bundle.

## 9. Promotion Rules

A profile axis may become `observed-supported` or `observed-limited` only when:

- the exact profile dimensions are complete;
- required frozen cases and attempts pass;
- the negotiated/requested revision is recorded;
- evidence is complete and sanitized;
- no conflicting valid run remains unresolved;
- the report is within its validity period;
- material server/SDK/tunnel/manifest/schema/policy/host changes have not occurred.

## 10. V1 Intentional Exclusions

These remain `unsupported-by-design` unless a future product decision changes V1:

- MCP Sampling;
- Roots;
- custom UI/MCP Apps;
- server-side planning or model generation;
- an Owner-control Companion or separate approval issuer.

## 11. First Live Evaluation

The first Raspberry Pi deployment should execute the frozen cases in this order:

1. connection/authentication;
2. protocol revision and dispatch;
3. Tool discovery/manifest/schema;
4. read-only Tools and result/error handling;
5. controlled write entitlement and host confirmation;
6. idempotency, retry, cancellation, reconnect, and concurrency;
7. optional Resources, MRTR, and Tasks probes;
8. information boundary, cross-server observation, latency, and context cost.

The resulting manifest populates this profile. Until then, the validation state remains `not-tested` or `server-not-implemented` as applicable.
