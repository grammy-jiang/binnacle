# Errata to Darwin interface 1.1.0

This note corrects the frozen interface 1.1.0 documents without changing
them. `api-contract.json` stays byte-identical to the frozen revision
(SHA-256 `4fdb04d66c501b3dcbd3ad3970515088393e956d4501e6e9d9e563e73a9cefb0`)
so its hash pins stay valid. Where this note and the frozen text disagree,
this note wins. The CR0 owner approved adding it.

## E-1: `descendants_unverified` is summary text, not a schema field

**Superseded text.** In `api-contract.json` 1.1.0:

- `foreground_execution.wire_mapping.darwin` says CR0-04 adds
  `descendants_unverified` (boolean const `true`, required on every successful
  Darwin `run_command` output) to the Darwin-only output schema and payload.
- `wire_policy.darwin` says output schemas are preserved "except the CR0-04
  Darwin-only run_command descendants_unverified=true field".

**Binding decision.** CR1a (`CR1A-SUPERVISOR-REVIEW.json`, SHA-256
`e80abd0dd4c8f0731b97fbb9de75c0ca313a827b16d847a8dc49e39bb7f8adf8`, condition
R1D-B0-05) replaced this. Interface 1.1.0 keeps the argument and output schemas
unchanged, so the Linux surface hashes stay pinned. The Darwin `run_command`
therefore reports the limit like this:

- The human-readable result summary contains `descendants_unverified=true`.
  The structured output has no `descendants_unverified` key.
- Controlled error text contains `descendants_unverified=true` when a child was
  spawned.
- The Darwin `run_command` description states that results disclose
  `descendants_unverified=true`, and that new sessions and process groups are
  not tracked or terminated.

The internal `ForegroundResult.descendants_unverified: Literal[True]`
declaration in `modules[3]` stays as written. It is an in-process value and
never appears on the wire. Adding a schema field still needs a new CR0
revision.

**Unaffected.** Every other 1.1.0 statement about leader-only completion,
escaped descendants and the foreground limits still applies.
