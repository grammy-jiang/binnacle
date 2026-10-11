# Job Awareness hint producer provenance

Status: accepted for the inert, default-off hint adapter (2026-10-11).
Scope: `src/binnacle/mcp/job_awareness_hint.py` and
`src/binnacle/mcp/job_awareness_hint_identity.py`.
Findings: ADV-G4-01, ADV-G4-04 (L4 Q0 g4 review) and
CHATGPT-ADV-G4-01-R1, R2 and R3 (independent review of `60bd87c`).

## Decision

- `HintAdapter.adapt(original, *, execution)` has no `tool` or name
  parameter. A controller cannot pass a Tool that it looked up by name,
  version or registry.
- The controller runs each dispatch through
  `witnessed_call(call_next, context)`. It returns the result and an
  `Execution` receipt, or `None`.
- `witnessed_call` issues a receipt only when all of these are true:
  - Exactly one `witnessed_tool` body returned normally during the dispatch.
  - That body ran on the dispatching FastMCP server, not on a mounted child.
  - That body ran outside a tool transform.
  - The dispatch itself returned. If it raised or was cancelled, the
    exception propagates and no receipt exists.
- The receipt names the Tool object whose body completed and the exact
  `ToolResult` object that the dispatch returned.
- `adapt()` validates the receipt first and consumes it only after it passes.
  The receipt must be issued, not yet consumed, and bound to the same
  `original` object (identity, not equality). Any failure returns `original`
  unchanged, with no worker admission, observation read or receipt query.
- The Tool in the receipt must then be the bound registered Tool object, with
  an exact native type and the bound name, version and canonical output
  schema.

## Threat model

- All Python code in the server interpreter is trusted. This includes
  middleware, composition code, controllers and tests.
- The receipt protects against accidental mis-wiring by a controller:
  - the wrong tool (a looked-up, rerouted, injected, mounted, transformed or
    value-equal Tool);
  - the wrong result (the result of another call, or an equal but different
    object);
  - a body that raised, was cancelled or completed after its dispatch
    returned;
  - a reused or hand-built receipt.
- The receipt is not a security boundary against hostile code in the same
  interpreter. Such code can reach every object through introspection
  (`object.__new__`, `object.__setattr__`, `__globals__`, closure cells). It
  can build a receipt, add it to the issued set or record a witness without
  running the body. Findings R1 and R2 are in this class. They are accepted
  under this threat model and are not claimed as blocked.
- Precondition: no middleware inside `witnessed_call` replaces the result
  object after the witnessed body completed.

## Consequences

- The feature stays default off. A production controller must use
  `witnessed_call` and register hint-eligible tools with `witnessed_tool`.
- Tests that call `adapt()` directly register a receipt with a test fixture.
  That fixture is trusted in-process code, not a bypass that the adapter
  defends against.
