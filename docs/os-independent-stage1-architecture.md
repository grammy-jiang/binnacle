# Binnacle Stage 1 OS-independent core and Linux platform adapters

This describes the **candidate architecture**, not a completed release or an
approval. The accepted plan is
`docs/os-independent-stage1-implementation-plan-2026-10-09.md`. The durable
`docs/os-independent-stage1-evidence/ledger.json`, exact-SHA CI and independent
reviews are authoritative for qualification and deployment.

## FastMCP, Core and platform responsibility

| Owner | Responsibilities | Must not own |
| --- | --- | --- |
| FastMCP 4.1.0 | Native root, three child Servers, Providers, Transforms, Middleware, auth, request DI and MCP lifespan | Durable jobs, host process/service lifecycle, FeatureRegistry |
| Binnacle Core | Files, Search, Commands, durable job/RPC/cursor policy, configuration validation and reporting | procfs, systemd, cgroup v2, killpg or host selection |
| Platform adapters | Linux launch/identity/signals, accounting, runtime paths, systemd provisioning, journald acquisition | MCP registries, tool contracts, business logic |

Pure composition is
`binnacle.application.create_application(settings=..., token=..., backend=...)`;
its explicit long-lived Commands dependency is a plain domain backend, not an
MCP Provider. Production `binnacle.server.create_server()` remains the Linux
bootstrap and preserves existing auth, middleware/transform order, all eight
tools, existing mounts and compatibility exports.

`binnacle.platform.composition` selects **Linux only** in Stage 1; an
unsupported OS raises `UnsupportedHostOS`. `Settings()` does not construct a
Linux adapter, while `get_settings()` resolves native socket defaults on the
actual host. No Darwin, Fedora or RHEL adapter has been implemented.

## Durable process ownership

Binnacle retains Job Manager RPC version 1, historical `pid`/`pgid`/`starttime`
fields, spool records, stdout/stderr combined log, byte cursors, recovery and
the existing independent owner process. It does **not** use FastMCP Tasks.
The generic `job_stop` policy accepts an opaque `JobProcessIdentity` and uses a
validated native `JobSignalLease` for both TERM and KILL. Only the Linux
adapter knows pidfd, boot ID, /proc and process group details; generic status
uses a job ID rather than a Linux PGID.

The Linux backend pins signal targets with pidfds and checks the leader birth,
boot, group and descendant ancestry before any signal. Unverifiable targets
are refused; a legacy record without `starttime` remains readable but cannot
automatically authorize unsafe destructive action. This does **not** claim
atomic group signaling or ownership of a child that forks after enumeration
or escaped and reparented before observation. Mandatory independent safety
review remains a separate gate.

Optional cgroup v2 accounting is separate from signal authority and durable
records. `NoResourceAccounting` and failed containment must retain their
existing best-effort/error semantics; counters are not proof of ownership.

## Deployment, diagnostics and observability

`deployment.units` retains pure marker rendering, provenance, plan/diff and
adopt/refuse/backup policy. Linux unit ExecStart, procfs property interpretation
and CLI/systemd provisioning are delegated to Linux-specific implementations.
`UnitProvisioner` is a narrow typed application interface, not a new platform
framework. Existing CLI names and options, service unit text, quiet restart,
rollback and read-only doctors remain Linux compatibility contracts.

`diagnostics.linux_checks` owns host-specific systemd/linger/journal hints;
portable rendering and analytics do not import Linux collection code.
`logstats.fetch_journal` remains a deferred Linux-only compatibility accessor.
Log redaction is unchanged; relative-path hashes use captured configured roots,
preserving their prior default `~/Projects` representation.

## Files/Search and roots

Paths and configured root aliases are canonicalized consistently. The allowed
canonical root set is captured for each application generation, so changing a
symlink's target alone does not silently extend an existing authorization.
Relative, absolute, nonexistent and escaping-symlink inputs preserve intentional
tool errors. Search continues to use external ripgrep, not a new OS adapter.

Pathlib authorization is **not a descriptor-level sandbox** against concurrent
local filesystem replacement: replacing the canonical ancestor after the
root check and before file open is still a potential time-of-check/time-of-use
race. Stage 1 does not claim race-free access or Darwin filesystem security;
eliminating that threat needs a separately reviewed OS-specific file descriptor
access mechanism. The server also exposes the intentionally open-world shell
`run_command` tool, so the allowed-roots layer must not be represented as a
hostile local-user security perimeter.

## Companion and infrastructure policy

Watchdog, Tunnel, resource monitor, weekly resource benchmark/host scripts
and historical migration tools remain Linux/Raspberry Pi companions or host
utilities. Core cannot depend on those companions. Generic subprocess calls
for Git, Python tests and ripgrep are portable, not a reason to manufacture
Linux adapters.

The full source/scripts ownership reconciliation is generated with:

```bash
uv run python -m scripts.os_stage1_inventory
uv run python -m scripts.os_stage1_inventory --check
uv run python scripts/check_architecture.py
uv run lint-imports --no-logo
```

Original v1.0.1 golden/wire captures and archived Git history are immutable.
Source changes must be reconciled before OS6 completion.

## Required acceptance

- OI-01–OI-05: dependency/static/dynamic gates, fake-platform composition and
  transparent unknown-host error.
- OI-06–OI-07: verified process ownership, native stop races, durable records,
  restart/cursors/cgroups and both directions of v1.0.1 RPC interoperability.
- OI-08–OI-12: safe root aliases, service/log/mock separation, companion
  direction and exact Linux behavior, unit and CLI parity.
- FM-01–FM-08: original native FastMCP root and three children, one owner per
  public tool, unchanged Middleware, Transforms, auth and four client profiles.
- OS7: normal hooks, complete two-lane suite, per-module coverage, Python
  3.10–3.14 matrix, sdist/wheel+clean install, trusted exact-SHA CI, truly
  independent reviews and the official guarded Linux deployment workflow.

No amount of self-testing counts as an independent review, and a running stable
Job Manager must not be restarted to satisfy the deployment milestone.

## Stage 2 Darwin backlog (not implemented)

1. Design native Darwin process launch, identity, signal containment and
   verifiable descendants, with independent safety tests.
2. Replace Linux cgroup containment/accounting with explicit macOS capability
   reporting, without pretending the guarantees are equivalent.
3. Implement `launchd` service provisioning, startup readiness, quiet checks,
   process identity, retention, diagnostics and safe rollback.
4. Implement runtime/config/token/socket/state directories with appropriate
   Darwin permissions, account ownership and cleanup semantics.
5. Implement Darwin system logs and service health facts, separate from
   Linux-only watchdog and tunnel companions.
6. Verify real macOS case sensitivity, symlink and concurrent filesystem
   behavior and define native descriptor access where needed.
7. Freeze Darwin-specific reference metadata/fixtures; preserve Linux public
   MCP, job records, RPC, and service behavior in parallel.
8. Add macOS CI, installation and deployment qualification with independent
   review; do not advertise macOS support based on Stage 1.
