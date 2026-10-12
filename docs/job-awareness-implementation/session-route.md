# Job Awareness E2 session route (lab only)

Status: E2 S1-S5 implemented on a lab branch (2026-10-12). Default off.
`PRODUCT_ENABLE_GO = false`.
Design: E2-DESIGN-20261012 revision g4 (review g4 PASS). Code baseline:
`32cbe56`.

## What it is

The E2 lab routes a synthetic job-completion hint to the chat that started
the job. The route key is the platform-asserted pair `X-OpenAI-Session` /
`X-OpenAI-Subject`, which must equal `params._meta["openai/session"]` and
`params._meta["openai/subject"]` of the same `tools/call`. The value is a
conversation correlation key. It is not authentication.

## Threat model scope

- In scope: the model in any chat (T1), a user in another chat of the same
  account (T2) and content or prompt injection (T3). These actors set only
  tool arguments and chat text.
- Conditional: another ChatGPT subject (T4) is synthetic only, because one
  account exists.
- Out of scope, conditional on the account-level disconnect of every
  command, HTTP or file capable connector for each phase (design §1.3):
  bearer or tunnel-path holders (T5), same-UID local processes (T6) and the
  network path (T8). The scripted replay N5 shows that a T5 actor who holds a
  live value gets the hint.
- Private items per chat: the handle, the incarnation, the `alloc_tag`, the
  page canaries, the hint text and the allocation state. The frozen template
  bytes are public, and their secrecy is never claimed.

## Modules

| Module | Role |
| --- | --- |
| `features/commands/job_awareness/session_route.py` | Parser, HMAC keyer, `RouteOutcome`, `SessionRoute` |
| `features/commands/job_awareness/session_binding.py` | Lab ledger DDL and SQL, exclusive directory layout, binding table |
| `features/commands/job_awareness/session_lab.py` | Cold start and the allocation protocol |
| `features/commands/job_awareness/session_serving.py` | Owner-scoped selectors, pages, echo, seal, retire, suspend |
| `features/commands/job_awareness/session_emission.py` | Once-only reserve/emit under the per-key fence |
| `features/commands/job_awareness/session_snapshot.py`, `session_fence.py` | Allocation snapshot; per-key `asyncio` fence |
| `mcp/job_awareness_session.py` | Same-request header and `_meta` extraction; digest-only log fields |
| `mcp/job_awareness_hint.py` | CA-2 `adapt_routed` and `RoutedOutcome` |

## Flags

- `HintAdapter.enabled` defaults to `False`. The control arm of an A/B pair
  uses the same route with the adapter off.
- `LabConfig.ttl_ms` is explicit: 3600000 for TC sub-phases, 1800000 for
  A/B arms.
- `LabConfig.deferred_seal` (S5) defaults to `False`. When it is `True`, a
  new allocation is not hint-eligible until the controller calls
  `session_serving.seal` at the job's terminal point. The §4.4 sub-phases and
  the §4.5 arm lifecycle use it. The flag is memory only, and a restart
  denies every allocation anyway.
- `ja_lab_marker=scripted` is a harness-only log label for N5. It grants
  nothing.

## No production path

- No production module imports a lab module. The import-linter contract
  `job-awareness-lab-not-in-production` forbids all of them from
  `binnacle.server`, `binnacle.application` and `binnacle.cli`.
- A fresh interpreter that imports the production entry points loads no Job
  Awareness module, and the production server lists exactly the eight public
  tools (`tests/contracts/job_awareness/test_e2_no_path.py`).
- The E2 lab server, tunnel and connector are separate (S7). The production
  units, connector and `job_status` are unchanged.

## In-process evidence (S5)

- `tests/contracts/job_awareness/e2_composition.py`: the real `SessionLab`,
  the real `adapt_routed` and the S3 extraction on a native FastMCP app over
  streamable HTTP, with synthetic chats.
- `e2_subphases.py` runs TC-1 to TC-5 with 180 s between sends. Every
  negative check records a pending proof (sealed, `PENDING`, `AUTHORIZED`,
  `LIVE`).
- `e2_scoring.py` applies scoring rules (a) to (f), the exact-seed rule and
  the TC-4 inherited-history rule. Negative controls show that each rule
  catches its violation.
- `test_e2_capacity.py` runs the 72 frozen A/B arm slots, one carrier per
  phase, and all TC sub-phases in one phase, with the real `Limits`.

## Amendment g5: TEXT-U and the canonical-key selector

Design §9.2 S-2 (TEXT-U) and the selector extension are implemented. The
STRUCT carrier (§9.2 S-1) is not implemented; it waits for CV (c′).

- **TEXT-U bind rule.** In routed mode (bindings with a `route_type`), a
  native tool without an output schema binds the `NO_STRUCTURE` sentinel.
  Only the TEXT carrier may bind it. TEXT on a tool that declares an output
  schema raises `ValueError` at bind time (H-SC: the client drops a second
  text block when `structuredContent` is present).
- **TEXT-U render rule.** `adapt_routed` inserts the reminder as a second
  text block only when the result has no `structuredContent` at all.
  Otherwise the hint is suppressed and the jobs are reset, as for any other
  suppression.
- **Unchanged.** `adapt()` never hints a `NO_STRUCTURE` tool, so the
  non-routed path is byte-identical to the pre-g5 baseline. The META path,
  every tool with an output schema and every adapter-off result keep their
  bytes. The master wire-byte golden values are unchanged.
- **Lab tool v2-U.** The in-process composition registers
  `fixture_unrelated_read` without an output schema when `structured=False`.
  It returns one text block, `Synthetic reference note.`.
- **Canonical-key selector.** Lab selectors also accept the canonical key that
  the reminder prints (`^ja1_[0-9a-f]{32}:[0-9a-f]{12}:g1_[0-9a-f]{32}$`).
  The grammar is disjoint from the handle and slot grammars. It is an exact
  match inside the caller key's own allocations, before any global read.
  Foreign, guessed, malformed and retired keys return the uniform `DENIED`.
- **Evidence.** TC-1 to TC-5 pass on v2-U, alone and in one shared phase.
  The capacity dry run covers all 72 frozen slots on v2-U (the TEXT block,
  and the META and STRUCT blocks relabeled). Raw-value scans of wire results,
  log rows, argument logs and lab files find no raw platform value.

## Amendment g6 D0: negatives, lab manifests and the c′ fixture

- **G-U1..G-U5** (`test_hint_routed_textu_negatives.py`): a value-equal
  second schema-less Tool, forged, reused, other-result, `None` and
  non-`Execution` receipts, a name or version change after bind, a Tool
  subclass, the adapter off, and non-routed bindings with a schema-less tool.
  Each returns the original result object and leaves every lab emit row
  `PENDING`. No code change was needed.
- **Lab manifests** (`fixtures/e2_cv/lab-manifests.json`, lab-only). The
  hash rule is the frozen E2-RUN rule. The in-process composition reproduces
  the frozen E2-RUN hashes:

  | Manifest | sha256 |
  | --- | --- |
  | v1 (`fixture_unrelated_read` with the closed `{note}` schema) | `ca4563c3ba00fdeb1b9cee2932a33c7ea110eeb05d20e5781c5b20dccfc77e04` |
  | v2-U (no output schema on `fixture_unrelated_read`) | `4aab8ee00b24d5c4759b8b55e875e59fae6c9b6d28fc1aa33dde830bdf087721` |
  | c′ (declared optional `job_awareness_hint`, ≤ 512, no description) | `a995405136191de89fb9657ecccf8de14ae9ee011d98eddce365845481627828` |

- **c′ fixture** (`e2_cprime.py`): the schema and result rule mirror the
  E2-RUN CV variant `e`. The result is schema-valid with and without the hint,
  a hint over 512 characters is dropped, the wire bytes are pinned, and the
  `tools/list` hash is the same for the control and candidate arms. The STRUCT
  carrier is still not implemented.

## Code review of the TEXT-U branch: fixes

- **TEXTU-01.** The routed carrier rule is checked on every call, not only
  at bind time. The adapter records the carrier that the routed bind rules
  accepted (`routed_carrier`). Both routed admission and `_render` require
  META for a schema-backed binding and TEXT for a `NO_STRUCTURE` binding,
  and require the current carrier to equal the recorded one. A carrier
  reassigned after bind returns the original result, consumes no receipt,
  and the lab resets the reservation (`PENDING`).
- **TEXTU-02.** The capacity dry run checks the lifecycle of every arm again
  (`arm_failures`). A negative control proves that a bad non-final arm fails.
- **ADV-TU-02.** The raw-value scan covers the synthetic argument log. A
  negative control plants a raw-looking value in a tool argument and the
  scan reports it.

## Speculative D1-S: the STRUCT carrier (g6 §9.2 S-1)

This section describes the branch `impl/job-awareness-e2-struct-20261012`.
It is speculative: the CV-F decision (W4) is still pending, and the branch
is not merged until the Supervisor says so. The feature stays default off.

- **Carrier.** `HintCarrier.STRUCT` and `HintBindings.struct` (default
  `None`). Only routed bindings can bind STRUCT; a non-routed STRUCT bind
  raises `ValueError`.
- **Bind rule** (`job_awareness_hint_struct.bind_struct`). The bound tool's
  closed output schema (`type` `"object"`, `additionalProperties` `false`)
  must declare `job_awareness_hint` exactly as
  `{"type": "string", "maxLength": 512}`: not required, no description, no
  other keyword. Anything else fails the bind. The binding is snapshotted
  (`struct_bound`, and `routed_carrier` = STRUCT). The TEXTU-01 per-call
  rule extends to STRUCT: a STRUCT binding stays STRUCT, and a schema-backed
  binding without the snapshot stays META. A carrier change after bind
  (STRUCT to META or META to STRUCT), a schema, name or version change, or a
  cleared snapshot suppresses.
- **Render.** The hint is inserted into the private copy of
  `structuredContent`, then re-validated with the metered `Schema`. A field
  that is already present, invalid structured content, or a failed
  re-validation suppresses.
- **Mirror rule.** Text blocks are classified against the original
  structured content. An exact JSON mirror (`json.dumps` defaults, or compact
  with non-ASCII kept) is re-serialized in its own format. Two mirrors, or a
  JSON object text equal to the structured content in another format,
  suppress. Plain tool text is never rewritten.
- **Caps.** The hint is at most 512 UTF-8 bytes. Growth (field plus mirror)
  is at most 1024 bytes. The wire byte limit is unchanged.
- **Unchanged.** `adapt()` never hints a STRUCT binding. META, TEXT-U, off
  and `adapt()` golden bytes are unchanged; their tests run with bindings
  that name the STRUCT member.
- **Lab tool v2-S** (`e2_cprime.v2s_server`). It is the c′ tool with the
  routed STRUCT carrier. Its `tools/list` equals the frozen c′ manifest
  (`a995405136191de89fb9657ecccf8de14ae9ee011d98eddce365845481627828`) for
  both arms. Its routed legacy wire bytes equal the frozen c′ hinted bytes.
  No product tool declares the field.
- **Evidence (in process).** TC-1 to TC-5 pass on v2-S, alone and in one
  shared phase. The capacity dry run covers all 72 frozen slots on v2-S. The
  hint never reaches another chat. The canonical key reads for its owner
  only. Raw-value scans find no raw platform value.

## What is NOT claimed

- No authentication, no authenticated per-chat authorization and no replay
  resistance. R3-B stays correct.
- No cross-subject isolation. One subject exists.
- No uniqueness of the session value beyond the observed sample. The
  bijection check is a fail-stop check only.
- No secrecy of the frozen template bytes.
- No privacy of aggregate resource use across chats. Caps and quota errors
  are global per phase.
- No ACK. `EMITTED` means the server committed the hint for return to the
  transport. Client receipt and model use are separate evidence rungs.
- No timing equality between `DENIED` cases. Only the bytes are identical.
- In-process results are synthetic. They do not replace the live S8 phases,
  the S6 code review or the S7 disconnect proof.
- Under concurrent calls of different keys, a busy worker or receipt store can
  return the original result (no hint). This is fail-closed: it never sends a
  wrong hint, and the job stays `PENDING`.
- Product automatic per-chat hints stay NO-GO.
