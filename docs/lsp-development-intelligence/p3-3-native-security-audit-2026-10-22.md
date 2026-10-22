# P3.3 — Linux ARM64 native Pyright security audit

**Decision: `explicit_trust_only`; untrusted READ and public tools remain NO-GO.**
The confirmed workspace PATH interpreter hijack is fixed at the private launch
boundary. This is not full OS confinement. P3.3 records a concrete trust-only
outcome, not a security release or approval for P4/P5.

## Scope and identity

This audit used an isolated Linux ARM64 Raspberry Pi worktree, CPython 3.13.16,
Node 24.19.0, native Pyright 1.1.413, and the existing multilspy PR #168 adapter.
The probe checks the adjacent package name/version before labeling its result.
This metadata check is not a dependency integrity certificate.
The optional dependency and installed VCS provenance both select
`08ba0dbe60b6e0a3eff4796cb77ff5c0837bc892`. This fork adds the explicit parent
process environment allowlist. Binnacle has no second Pyright adapter.

Only disposable synthetic workspaces, installations, markers, and listeners
were used for executable negative controls. No user project hooks were run.
No service, production checkout, branch, commit, push, or deployment changed.
The other QA worktree's reproduction was read only. This report contains no
credentials, raw syscall/LSP records, or absolute private installation paths.
No Darwin acceptance is inferred from this Linux run.

## Confirmed defect and launch policy

Admission previously checked `pyright-langserver` against every operator root.
Its `#!/usr/bin/env node` shebang still resolved `node` using inherited PATH.
An authenticated writer could place `node` in a second allowed root and gain
execution when that root appeared first in PATH. The environment allowlist
removed secrets but retained that interpreter authority bypass.

The private owner now applies these rules before creating an upstream server:

1. The profile still requires `trusted_absolute`, `explicit_trust_only`, and no
   unreviewed arguments or environment overrides. All operator roots are required.
2. The configured launcher must remain an executable file outside every root.
   Each path component and each intermediate symlink target is checked, including
   canonicalization of double-leading-slash path anchors. A
   launcher alias must still resolve to the target captured by the owner.
3. Only the audited npm launcher format, with the exact env-node shebang, is
   accepted. Arbitrary shell wrappers and other shebang formats fail closed.
4. The operator selects the runtime through a `node` entry beside the configured
   launcher. Both entries may be symlinks to trusted installations elsewhere.
   The Node path receives the same complete root and link checks. Missing,
   non-executable, cyclic, cross-root, and script interpreters are rejected.
   Native ELF/Mach-O signatures reject script chains; they do not authenticate
   executable contents or establish package identity.
5. The owner replaces only upstream `ProcessLaunchInfo` launch arguments and
   environment. The command is absolute Node, absolute Pyright JavaScript, and
   `--stdio`. It never invokes `env` to select an interpreter. The expected
   upstream command/environment contract must match before replacement.
6. Parent PATH, HOME, TMPDIR, Node/Python injection variables, loader variables,
   proxies, credentials, and agent sockets are not inherited. Only `LANG`,
   `LC_ALL`, `LC_CTYPE`, and `TZ` may be inherited. Child PATH contains exactly
   the admitted canonical Node directory. Parent environment state is unchanged.

Operators with a launcher and Node in different directories must select a
trusted directory containing the two aliases. The owner does not discover Node
on service/workspace PATH or fall back to a system interpreter. This can reduce
Python environment discovery, and it intentionally rejects previously accepted
arbitrary wrappers. No new agent-selectable interpreter setting was added.

This is path admission, not an atomic open/exec guarantee. Operator-owned
installation directories and package dependencies must remain trusted. Hardlink
and bind-mount aliases, installation mutation races, dynamically loaded libraries,
and arbitrary writable installed dependencies are not certified by these checks.

## Evidence and limits

| Check | Observed result | Meaning |
| --- | --- | --- |
| Red regression before remediation | Four poisoned PATH variants executed a disposable marker; 11 failures, 1 pass overall | Reproduces the confirmed defect without relying on inherited secrets |
| Real Pyright after remediation | Startup and symbol request succeed with direct, directory-link, node-link, and empty/relative poisoned PATH; no marker | Workspace PATH no longer selects the interpreter |
| Cross-root admission | Missing/interpreter script/non-executable/cyclic files, intermediate links into and out of a second root, and launch-time retargets rejected | Fail-closed path selection across all grants |
| Child environment | Synthetic secret and Node preload hook absent; real definition still succeeds | Credential/injection hygiene at the launch boundary |
| Real definition query | Full synthetic tree manifest unchanged, including ignored entries, modes, sizes, types, and symlink targets | Only the explicitly observed synthetic tree remained unchanged |
| Real syscall trace | 17 provider tasks including threads; 10 failed `python`/`python3` exec attempts; zero sampled children | Periodic sampling misses short-lived subprocess attempts |
| Real syscall trace writes | One write/create open in a provider temporary directory outside the synthetic tree; directory absent after exit | An unchanged workspace manifest does not prove zero filesystem effects |
| Network observation | No traced connect call in this run; periodic socket inspection incomplete | No network-denial proof and no general absence claim |
| Native synthetic launch control | Workspace ignored-file write, external-cache write, loopback connection, and bounded Python child all succeed | The private environment/argv policy does not confine these operations |
| Linux OS primitive control | Bubblewrap read-only workspace denies writes; separate network namespace denies host listener connection; designated cache remains writable | OS primitives work here, but are not integrated into the owner |
| Cleanup | Real owner records clean exit; synthetic child has a deadline and is reaped; existing cancellation/descendant regressions exercised | Observed cleanup only; escaped/unobserved descendants remain a blocker |

The trace covered process, network, and selected filesystem syscalls. It was
local supplementary evidence, not a complete filesystem monitor. The provider
PID and its clone descendants were filtered before counting. Raw traces were
not included in the evidence artifact. The temporary artifact was outside the
probe's manifest roots; the CLI explicitly reports that limited scope and
`read_eligibility=NOT_PROVEN`. Expected CLI failures return sanitized failure
JSON with a nonzero status, rather than a path-bearing traceback. The synthetic HOME environment marker does not
redirect Node's passwd-derived home after environment stripping.

The OS primitive test does not launch Pyright inside Bubblewrap. It deliberately
shows that mount/network controls can deny operations that the native owner
allows. It still permits a bounded Python child. A binary merely being present,
or a namespace creation probe returning zero, is not a provider sandbox proof.

## Reproduction

Use the local QA venv, the operator-selected absolute launcher, and an empty
configuration file. Do not use a production configuration or workspace. Set
`BINNACLE_PATCHED_MULTILSPY_QA=1` and `PYRIGHT_LSP_TEST_BIN` explicitly.

```bash
.qa-p33/bin/python -m pytest tests/integration/test_lsp_p33*.py \
  tests/unit/core/test_lsp_p31*.py \
  tests/unit/core/test_lsp_p28_owner_cleanup_branches.py -q
.qa-p33/bin/python -m scripts.lsp_p33_side_effect_probe \
  --binary "$PYRIGHT_LSP_TEST_BIN"
```

The broader regression uses all `tests/unit/core/test_lsp*` and
`tests/integration/test_lsp*` modules plus the existing tool-surface, golden-output,
surface-token, exact-search surface, and plain-pattern contracts. Set
`BINNACLE_LSP_RELEASE_GATE=1` to include the upstream abandoned-request check.
Use seed 12345. This is a focused selection, not a replacement for the managed
full-suite lanes.

For local syscall evidence, run the synthetic probe under `strace -f -qq` with
`-e trace=process,network,openat,mkdir,unlink,rename,chmod`. Keep the raw file in
a private disposable directory, filter the admitted Node process and descendants,
and retain only aggregate results. Never attach a raw trace to an external report.

## Remaining gates

- Integrate and independently review a Linux sandbox policy for the real upstream
  lifecycle. Prove read-only mounts, explicit writable cache/state roots, home
  and credential isolation, network denial, and bounded process-tree cleanup.
- Verify package/runtime/dependency provenance beyond version strings and native
  signatures. Resolve hardlink/mount aliases and mutable-installation races under
  the chosen threat model. Do not promise safety for arbitrary installed code.
- Exercise real Pyright initialization, configuration, semantic requests, direct
  server-side mutation commands, failure/cancellation, and descendant escape
  inside that sandbox. Refusing LSP `workspace/applyEdit` is insufficient.
- Obtain independent source-bound security review and per-OS acceptance. This
  work does not certify Darwin or grant native-signal/process approval.
- Complete repository quality/coverage gates and CI before integration. Public
  READ/tool enablement still requires the later independent product/API gates.

The private configuration remains default-off. No setting is promoted to
`audited_read_eligible`. Existing public six/eight-tool contracts stay unchanged.
See the [running verification ledger](p3-3-running-evidence-2026-10-22.md) for
final command results and environment gate details.

## Final verification and modified paths

The final focused selection passed **80 tests**. The managed full coverage
pipeline passed **8151 tests**, with **307 platform/opt-in skips** and **87
subtests**, across both parallel-safe and ordinary-process lanes. The configured
coverage policy exited zero with 20 below-final-target notices under existing
policy; no thresholds changed. Private owner coverage is **98.31%**. Repository
pre-commit and isolated pre-push checks passed. The supported multi-Python tox
matrix and hosted CI were not run.

| Paths | Purpose |
| --- | --- |
| `src/binnacle/features/development_intelligence/lsp_process_owner.py` | Native interpreter admission and minimal child environment |
| `scripts/lsp_p33_side_effect_probe.py` | Synthetic manifest/observation audit, identity check, sanitized failure output |
| `tests/integration/test_lsp_p33_environment_hygiene.py` | Secret and Node preload stripping with real Pyright |
| `tests/integration/test_lsp_p33_launch_provenance.py` | Real PATH attacks, root/link admission, retarget and launch-contract refusal |
| `tests/integration/test_lsp_p33_os_boundaries.py` | Synthetic side-effect control and Linux namespace enforcement control |
| `tests/integration/test_lsp_p33_side_effect_characterization.py` | Audit CLI and evidence-contract checks |
| `tests/integration/test_lsp_multilspy_patched_upstream.py` | Exact fork provenance pin follows the existing dependency update |
| `tests/unit/core/test_lsp_p28_owner_cleanup_branches.py` | Keep the factory-only unit fixture independent of a native installation |
| `tests/scripts/macos_skip_table.py` | Register the inherently Linux-only namespace control, without claiming Darwin parity |
| `tests/platform/darwin/test_log_e2e_transaction.py` | Bounded completion synchronization for an existing synthetic guardian race found by the full gate; product code unchanged |
| `pyproject.toml`, `uv.lock` | Preserve the original uncommitted fork update |
| `docs/lsp-development-intelligence/implementation-plan.md` | Record the P3.3 trust-only outcome |
| This report and `p3-3-running-evidence-2026-10-22.md` | Reproducible findings, gate results, and explicit remaining blockers |
| `docs/os-independent-stage1-evidence/os6-source-reconciliation.json` | Regenerate the required complete source inventory; includes prior baseline drift |
