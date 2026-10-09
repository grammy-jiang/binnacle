# FastMCP 4.1 adoption and MCP journal privacy — 2026-10-09

## Decision and scope

Adopt FastMCP 4.1.0 without rewriting the existing native-composition architecture.
Keep the public eight-tool surface and six-tool ChatGPT presentation, exact tool
metadata, command/job behavior, backend, platform boundaries, client identity
policy, and HTTP authentication contract. Treat P3 multi-principal authorization
and P4 middleware redesign as independent follow-up design decisions.

The reference baseline is production `master` at
`dfbce25e25076594806769ac284d3c3226b1e403`. The production checkout has
uncommitted user-owned files. All changes are made in the isolated worktree
`/home/grammy-jiang/Projects/binnacle-fastmcp41-security-20261009` on
`upgrade/fastmcp41-security-20261009`. Neither the live service nor the
production checkout is changed by P0/P1/P2 development.

## Verified upstream facts

- FastMCP 4.1.0 was released 2026-10-08, following the security-fix 4.0.11.
- The tagged 4.1.0 sources still support `mount`, native Providers, Transforms,
  `Visibility`, `LoggingMiddleware`, `StaticTokenVerifier`, `AuthMiddleware`,
  `Depends`, and native Lifespan.
- `Visibility` and `LoggingMiddleware` have identical source blobs in
  tags v4.0.10 and v4.1.0. FastMCP 4.1.0 does change some HTTP/session and
  authorization implementation paths, so behavior must be retested.
- The SDK labels `StaticTokenVerifier` as a test/development mechanism. Our
  existing single-token model is a *trusted workstation* policy, not a verified
  per-client privilege boundary. Client-announced names remain presentation
  labels, not authority.
- A separate installed 4.1.0 environment passed native mount/visibility/call
  probes, three client-profile smoke checks, and 38 contract/dependency tests.
  This does not constitute production acceptance.

Official code reference:
[FastMCP 4.1.0 tagged implementation](https://github.com/PrefectHQ/fastmcp/tree/v4.1.0/fastmcp_slim/fastmcp)

## Implementation gates

**P0 — frozen baseline**: Source at the SHA above; four-profile tool schema
pins and client visibility, middleware order, current 4.0.10 auth and logging
probes; immutable production worktree inventory. No new application framework
abstractions.

**P1 — dependency upgrade**: Update only `fastmcp==4.1.0` and `uv.lock`,
retaining MCP 2.1.1 / MCP-types 2.1.1 and the supported Python 3.10–3.14
matrix. Review the new lockfile's Python 3.15-only beartype prerelease branch:
it is not selected on any supported CI interpreter. Run targeted native,
contract, HTTP, session, and auth tests before moving to P2. Candidate commit:
`b0b6870`.

**P2 — journal input minimization**: Keep the `request_*`, `tool_call`,
`tool_result`, and `job_start` event names and correlation identifiers.
Replace user-supplied command/content/pattern/glob/unknown parameter values,
untrusted tool names, client names, and errors with safe diagnostic
representations. Preserve safe numeric/bool knobs and valid job IDs. Paths are
`pathhash:<12-hex>[.file]` — never raw. Preserve the full *size* of original
argument JSON (`args_chars`) but serialize only scrubbed argument *values*
(`args`). Native `LoggingMiddleware.payload_serializer` is fail-closed
because the upstream middleware falls back to the default raw serializer if
the custom serializer raises. `job_start` no longer prints raw commands.
The original execution payload and MCP results must remain unchanged.

### Journal boundaries and intentional trade-offs

- Current request/job telemetry must not contain free-form arguments, command
  text, stdin, file bodies, search patterns, or exception messages. Synthetic
  sentinels are tested end to end. The journal still contains event metadata,
  output lengths, job IDs, short hashes, known client labels and a validated
  tunnel-generated turn reference.
- The anonymized path marker preserves anonymous same-path correlation for
  `binnacle stats` adaptive discovery by reusing the historical normalized
  path digest. It preserves whether an input *looks* file-scoped without
  revealing a file extension.
- Historical analysis of command *text* (command families/traits, test traffic
  inferred from a command substring) necessarily becomes unavailable for
  newly redacted journal records. Tools still report concrete timing, usage,
  exit state and size; analytics must treat redacted command categories as
  unknown rather than inventing command labels. Old logs still parse.
- The durable job store intentionally retains executable command and optional
  stdin, and the per-job output can itself contain user data. The deployed
  jobs directory and its parent were observed as mode 0700. This phase does
  not rewrite the persistent spool format, stored historical data, tunnel
  companion logs or contents of commands' stdout.
- Existing historical journald records may still contain secrets from before
  this patch. There is no silent deletion/rewriting of these records. A
  separate retention or incident response procedure would be needed.
- Structured tool results returned to MCP clients intentionally remain
  unchanged; redaction applies to journal representations only.

### Verification and release policy

Perform focused tests on changed code after each step; never repeatedly run
the entire suite to investigate a single failure. Freeze a final candidate,
run pre-commit and pre-push, one full seeded two-lane suite, coverage policy,
packaging and supported-Python GitHub CI. Confirm exact-SHA mandatory checks
and existing master governance before normal guarded integration/deployment.
Live release requires doctor, HTTP/Tunnel/Watchdog/Job smoke, exact MCP wire
parity and a real read-only client acceptance proof. Never weaken gates, use
force pushes or bypass tool safety refusals. Roll back to the validated
pre-upgrade SHA on any behavior change.

## Evidence recorded during development

- The new isolated worktree was created with the canonical development helper
  and passed bootstrap/doctor with hooks installed.
- P1 `fastmcp==4.1.0` lock and sync succeeded; MCP/MCP-types remained 2.1.1.
- 82 focused P1 tests passed before adding P2.
- 63 focused P2 tests passed after initial redaction change; 7 added
  fail-closed serializer tests passed at their latest run.
- Targeted Ruff and mypy: pass. Final full gates and release status must be
  separately recorded after the candidate is frozen.
