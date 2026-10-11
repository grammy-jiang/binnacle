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
