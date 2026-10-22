# P3.3 Experimental Linux Bubblewrap integration — private Pyright Process Owner

**Date:** 2026-10-23, Sextant Linux ARM64. **Status:** experiment verified
against real Pyright 1.1.413, not production-qualified.

The owner now has a private, explicit constructor option
`sandbox_mode="linux_bwrap_experimental"`. Its default remains `"none"`,
so existing P2.4/P2.6 profiles, production startup, MCP tool inventory and
published binaries are unchanged. There is no configurable public profile
switch for this mode. It requires the existing **enabled** provider profile,
an explicitly admitted absolute Pyright launcher and the existing
`explicit_trust_only` authority checks.

## Implementation

- A separate module
  `src/binnacle/features/development_intelligence/lsp_linux_bwrap.py`
  builds a deterministic argv for the fixed `/usr/bin/bwrap` executable.
  There are no shell strings, user-specified extra mount arguments, PATH
  discovery or arbitrary process commands.
- Rootless Bubblewrap creates private user, PID and network namespaces,
  a read-only `/usr` system tree, a single read-only admitted Node
  executable, the reviewed read-only Pyright package tree, a read-only
  **original-URI** synthetic workspace, private `/tmp`, `/proc` and
  minimal `/dev`.
- Package and workspace mount parents are **empty directory placeholders**;
  the caller's HOME and sibling project directories are not bound
  into the sandbox. A package/workspace mount overlap, symlink alias,
  unrecognized system alias, noncanonical root, missing Bubblewrap or
  non-Linux host fails closed.
- Unlike the earlier independent PoC, this path runs through the actual
  `PrivatePyrightProcessOwner.session()` and upstream
  `multilspy` `PyrightServer` lifetime.
- The upstream process launcher already creates an independent POSIX
  session. A second Bubblewrap `--new-session` produced different-PGID
  children, which Binnacle correctly classified as escaped and refused
  to cleanly admit. The integration retains the **upstream** session
  and omits only Bubblewrap's redundant second session. Child cleanup
  continues to use PID, birth-time and PGID verification.

## Verified on disposable fixtures

- Pyright initialized and answered `documentSymbol` from actual synthetic
  source files, then exited with no pending requests or reader tasks.
- The Process Owner observed its separate Node descendants. It verified
  `parent_exited=true`, `cleanup_unverified=false`, no escaping or lingering
  descendants in these runs, and an unchanged synthetic workspace.
- A direct OS negative-control test checked that an otherwise writable
  synthetic workspace became read-only (`EROFS`); a synthetic neighboring
  non-mounted file could not be read; access to a host loopback listener
  (proved reachable from the host) was denied.
- **Five independent local native cycles** of the combined owner and
  argument-selection tests passed **13/13 tests each (65 total)**. The
  CI-default native test remains explicit opt-in and is not presented
  as if the generic unit suite had run native Bubblewrap.
- An additional native regression poisons inherited NODE_OPTIONS, NODE_PATH
  and HOME with synthetic values before launch; the experimental owner
  still initializes Pyright, does not execute the synthetic preload, and
  verifies clean descendant shutdown. Its 14-test combined run passed.
- Static unit checks reject wrong paths, package layout and unsupported
  platform/mode with no provider execution.

## Remaining acceptance gaps

**READ and public MCP tools remain NO-GO.** The
`ProviderExitEvidence.containment_verified` field is deliberately still
`false` even after a clean experimental launch. The test proves only
observable local lifecycle and selected read/write/network behavior.
Before any untrusted project is admitted, independent review is needed for
trusted Node/JS tree immutability and complete npm package dependency
resolution, mount/TOCTOU/hardlink races, inherited descriptors, compiler
and subprocess effects, escaped children, cgroup memory/CPU limits,
long soak/TTL/capacity checks, syscall restrictions and other IPC routes.

The parallel macOS Seatbelt experiment still uses broad file-read rules
and is **not** an equivalent sandbox, so Darwin is intentionally rejected
by this mode. The P3.6 evidence importer must not infer a safety stage GO
from these positive fixture results.

## Branch coverage and candidate quality gate (2026-10-23)

The first full managed Linux suite passed **8,341 parallel-safe tests** and
**98 ordinary-process tests**, with 357 skips and 87 subtests. Its generated
branch-coverage policy check then reported one real shortfall:
`lsp_linux_bwrap.py` at **89.47%** against the unchanged **90%** requirement.
Four additional synthetic **negative-control tests** now exercise refusal for
a workspace that is not a directory, a Node executable located inside that
workspace, an unexpected host system symlink, and a non-symlink system
directory read-only bind.

The 14-case policy-builder unit suite now reports **100% branch+statement
coverage** for `lsp_linux_bwrap.py`. The retained existing full-suite coverage
SQLite data was combined with the separately measured 14-case targeted
coverage SQLite data **without modifying any implementation source**.
The normal `scripts/check_coverage_policy.py` gate on this union returned
**zero errors, 257 production modules, 77 top-level script modules**.
Twenty existing, explicitly acknowledged final-target debts remain unchanged.

This is an incremental combined-coverage check; the full managed coverage
pipeline and hosted CI must still be run on the exact new test-source
commit before publishing any final quality acceptance.
