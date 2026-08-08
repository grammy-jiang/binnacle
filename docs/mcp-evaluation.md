# Binnacle ChatGPT MCP Evaluation and Evidence Contract

- **Status:** Draft empirical compatibility contract
- **Contract version:** `1.1.0`
- **Profile:** `spec/mcp/evaluation-profile.yaml`
- **Frozen cases:** `spec/mcp/evaluation-cases.yaml`
- **Manifest schema:** `schemas/mcp/evaluation-manifest.schema.json`
- **Human profile:** [`mcp-profile.md`](mcp-profile.md)

## 1. Purpose

Binnacle depends on the behaviour of one exact ChatGPT product, plan, account/workspace policy, connection/authentication path, MCP revision, and server build. Documentation, SDK support, or another account cannot be substituted for observed evidence.

The evaluation produces narrow, reproducible conclusions for the tested profile only.

## 2. Profile Identity

A profile comparison uses the exact fields and JSON pointers declared in `evaluation-profile.yaml`, including:

- ChatGPT product/surface, plan, workspace type, and workspace-policy digest;
- connection and authentication profile;
- Binnacle probe release/build and configuration digests;
- MCP SDK and tunnel/gateway agent identities/digests;
- Tool manifest, schema registry, policy bundle, and evaluation-case manifest digests;
- Raspberry Pi model, OS, kernel, architecture, and device profile;
- intended server-supported revision set;
- revision requested/negotiated by the actual ChatGPT connection;
- observed client capabilities.

The dispatcher implementation version is recorded separately from the negotiated MCP revision.

## 3. Canonical Status Vocabulary

Every axis has one of these exact statuses:

```text
observed-supported
observed-limited
declared-unexercised
not-declared
test-failed
host-policy-blocked
server-not-implemented
not-tested
unsupported-by-design
unstable
expired
not-applicable
```

These strings are used by:

- `mcp-profile.md`;
- evaluation manifests;
- `compatibility_report`;
- profile-promotion decisions.

No lossy mapping is permitted.

## 4. Frozen Case Manifest

`evaluation-cases.yaml` is normative and versioned. Each case defines:

- stable case identity and axis;
- prerequisites and fixture readiness;
- exact Tool/protocol request or UI action;
- prohibited effects;
- timeout;
- minimum attempts;
- deterministic oracle or calibrated human grader;
- required evidence artifacts;
- retry/fault policy;
- pass/fail/blocked classification.

An evaluator cannot replace the case manifest while retaining the same evaluation-profile version. The profile records the expected case-manifest digest; a mismatch invalidates promotion.

## 5. Evaluation Axes

The initial axes cover:

- endpoint connection and authentication;
- MCP revision and dispatch;
- discovery, Tool manifest, schemas, annotations, and cache behaviour;
- structured/text results and execution errors;
- read entitlement;
- controlled write/modify entitlement;
- preparation, confirmation, idempotency, retry, reconnect, and cancellation;
- long-running operation/status/result behaviour;
- Resources, MRTR/elicitation, Tasks, notifications, and other optional features;
- owner-only/model-visible boundaries;
- cross-server behaviour;
- latency and context cost.

A conclusion applies only to its axis and exact profile.

## 6. Repetitions and Metrics

Risk classes and minimum attempts are exact:

| Risk class | Minimum attempts |
| --- | ---: |
| `deterministic_protocol_schema` | 1 |
| `tool_selection_and_result_rendering` | 10 |
| `confirmation_and_entitlement` | 5 |
| `write_cancellation_retry_cache_confirmation` | 20 |
| `concurrency_race_reconnect_instability` | 20 |
| `latency_and_context_cost` | 20 |

Metrics include:

- Tool-selection correctness;
- schema-valid request/result rate;
- confirmation shown/bypassed/stale/substituted rate;
- exactly-one-effect rate;
- cancellation verification rate;
- reconnect reconciliation rate;
- p50/p95/p99 latency;
- model-visible Tool metadata/result bytes and tokens where observable;
- host-policy block rate and failure taxonomy.

A single success cannot establish stability.

## 7. Case Results and Conclusions

Each `case_results[]` entry records its axis. Axis conclusions are derived from the cases assigned to that axis and cannot omit a required case silently.

A deterministic case passes only when its oracle passes. A host-policy block is not protocol failure. An unimplemented probe is not evidence of host non-support. A declared capability without behavioural exercise is `declared-unexercised`.

Conflicting valid runs produce `unstable` until the conflict is explained and a fresh profile passes the required repetition threshold.

## 8. Evidence Bundle Without Self-Reference

The evaluation manifest is included inside the evidence directory/archive, but it does not contain the archive's own digest.

The manifest records:

- a file inventory and digest for every evidence file except the detached bundle receipt;
- probe/case/oracle versions;
- sanitized wire/UI observations;
- review and conclusion data.

After the evidence bundle is finalized, a detached receipt records:

```json
{
  "bundle_sha256": "...",
  "manifest_sha256": "...",
  "profile_id": "...",
  "created_at": "..."
}
```

The detached receipt is stored alongside, not inside, the bytes it hashes. This avoids self-reference.

## 9. Human and Automated Evidence

Automated probes collect protocol frames, server observations, schemas, lifecycle, retries, latency, and fault injection.

Real ChatGPT UI observations remain required for:

- Tool selection by the model;
- owner confirmation presentation and bypass behaviour;
- account/workspace entitlement;
- owner-only versus model-visible result handling;
- cross-server behaviour.

Automation cannot fabricate those host facts. Human graders use the calibrated criteria in the case manifest and record screenshots/structured observations with redaction.

## 10. Promotion and Validity

A profile may promote one axis only when:

- every required case for that axis is present;
- attempt thresholds are met;
- evidence is complete and sanitized;
- the expected case-manifest/profile digests match;
- no unresolved contradictory run exists;
- the conclusion is current.

Rerun triggers include:

- ChatGPT product/plan/workspace policy change;
- connection/authentication change;
- negotiated MCP revision or client-capability change;
- Binnacle/SDK/tunnel/manifest/schema/policy/evaluation-case change;
- Raspberry Pi OS/kernel/device-profile change;
- material regression or expiry.

## 11. Invariants

1. Observed support is scoped to one exact profile.
2. Intended and negotiated MCP revisions are separate fields.
3. Frozen cases include executable setup/request/oracle definitions.
4. Every case result identifies its axis.
5. Status strings are identical across profile, manifest, and Tool output.
6. The evidence bundle digest is stored in a detached receipt.
7. Host-owned UI facts require real host observations.
8. A fresh passing report is required after any material profile change.
