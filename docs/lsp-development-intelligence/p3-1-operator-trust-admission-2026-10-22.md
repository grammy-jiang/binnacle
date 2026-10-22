# P3.1 — Operator-trusted provider profile admission

Date: 2026-10-22, Australia/Sydney. Base Binnacle commit
`d17424836bd9c8de99cee901a967fb60276ab100` (P2.8 GitHub-hosted CI
7/7 SUCCESS). This is a **private provider policy** milestone, **not** a
public `inspect_symbol` release or certification of Pyright READ confinement.

## Responsibility boundary

- New, pure `lsp_profile_assessment.py` implements the P3.1 classification,
  separately from FastMCP, startup and process management. It accepts only
  Pydantic-validated operator settings. It never searches the service PATH,
  touches a workspace or executable, loads multilspy, starts a provider or
  performs network I/O. Its verdict exposes only provider label, source type,
  a conservative classification and sanitized reason; no executable path,
  environment value or deterministic hash of private configuration is returned.
- `lsp_preview_server.validate_private_profile` now uses this policy to
  check the code-gated P2.7 private FastMCP child. The P2.6
  `PrivateProviderManager.definition` uses the same assessment *before* any
  source snapshot/Provider creation, and separately retains the P2.5
  workspace admission. Actual execution is still owned by P2.4, which
  checks host-selected binary existence, absolute paths, workspace exclusion
  and process lifecycle; it now also rejects a declared Pyright profile
  listing only non-Python languages. The **full snapshot of all host-granted
  roots is a mandatory owner argument**: a binary located in *any* root
  writable through the authenticated MCP must not be executed as the provider,
  including aliases or symlinks crossing between otherwise distinct projects.
- Classification never overrides P2.8's disabled-by-default installation,
  never adds a public MCP tool, and never changes the existing eight/six tool
  schemas. `scripts/gate_a_manifest.py` has an exact owner entry for the
  module; the generated startup inventory contains only its inert import.

## Classifications and conservative proof rules

| Operator configuration | Classification | Private P2.4 launch grant | Untrusted READ |
| --- | --- | --- | --- |
| Feature/profile off or missing | `not_audited` | No | No |
| Enabled bare executable from `service_path`, `benchmark_only` | `benchmark_only` | No: discovery is not authorization | No |
| Enabled service PATH mislabeled `explicit_trust_only`, malformed or extra argv/env | `not_audited` | No | No |
| Enabled `trusted_absolute`, `explicit_trust_only`, no unreviewed argv/env, correct Python declaration | `explicit_trust_only` | Conditional: **only** for Pyright; P2.4 independently rechecks host executable | No |
| Any other language server with an operator-supplied trusted absolute path | `explicit_trust_only` (declared trust only) | No: native provider owner/adapter not admitted yet | No |
| `audited_read_eligible` | Reserved P3.3 security verdict, not derivable from configuration | No admission based solely on this status | **Not granted** |

The verdict deliberately has **no profile fingerprint**: the independently
reviewed SHA-256 fingerprint of full settings would be vulnerable to offline
guesses about executable paths or environment values if exported to MCP or
logs. P2.6 keeps its original profile identity hash only inside its private,
per-generation registry, never as an agent-visible diagnostic. Neither it nor
a launcher hash is a Node.js package or dependency identity certificate.
Filesystem behavior and process-tree observations, absent OS-enforced
containment, do not independently authorize READ. Client-supplied executable
paths or `package.json` scripts never enter the trust evaluation.

## P3.1 proof and native QA

Thirty focused deterministic P3.1 profile-classification tests verify all
classification states, all eight non-Pyright names, mismatched Pyright
languages, empty/malformed profiles, unchecked process options, verdict
stability, no executable/path discovery and pre-filesystem refusal. A further
**ten P3.1 operator-root safety tests** verify binaries inside a second
writable authorized root, symlinks into/out of that root, empty/missing roots,
root containment, direct-owner mandatory root arguments, P2.5 and P2.6 root
propagation, a real FastMCP end-to-end rejection of cross-root executable
launch, and fail-closed process stop. Tests monkeypatch file probes,
process spawning and PATH discovery, so no unexpected operation can pass.

The policy module's targeted statement/**branch** coverage is **100%**.
MacBook Pro Python 3.13 tested P2.4–P2.7 with actual Pyright and the reviewed
P3.1 changes: **183 cases passed**. The profile-classifier-only branch
coverage remains **100%**. Linux/Darwin full repository mypy checks **901
Python files** with zero errors; Ruff, module-size, wheel contents, G6
ownership, startup manifest and default installation without multilspy pass.
Both Linux ARM64 hosts (Raspberry Pi and Sextant) ran the **identical
SHA-256-verified reviewed P2.4–P3.1 real-Pyright selection: each 183 passed**
under Python 3.13, using fixed multilspy commit `9203732e4e5f65cc1374b109110f7b6354d3d43b`.
Mac Python 3.10, 3.11, 3.12 and 3.14 also each passed **39/39** of the P3.1
profile/operator negative cases before adding the final E2E FastMCP refusal;
the last E2E rejection was then run separately on both Linux hosts and Mac.
The reviewed module continues to report 100% branch coverage; the private
P2.4 owner reported 97.80% branch coverage in the native Mac owner selection.

## Independent security review and corrections

An independent **read-only Claude Fable review** identified the critical
multi-root executable-bypass condition: validating only the *current*
workspace misses executable files that an MCP user can edit inside a second
host-granted root. P2.4 now **requires `operator_allowed_roots`**, checks that
the requested workspace belongs to those roots, rejects any binary or
resolved symlink target inside any of them, and refuses missing roots. P2.6
and P2.5 pass the complete canonical host-root snapshot; direct P2.4
private callers must supply it explicitly. No agent-provided root is trusted.

The review also found that a failed explicit `aclose()` could leave a
misleadingly clean `last_exit` if a second stop succeeded later. The owner
now sets its poison state on failed/timeout stop and carries it into final
`cleanup_unverified` evidence. An additional negative test discovered this
evidence mismatch and verified the fix before candidate approval.

The deterministic SHA-256 of private profile settings was removed from the
classification verdict, which now returns no executable path, environment
values or predictable private-settings digest. P2.6 retains its internal
per-generation fingerprint solely for provider-instance identity. Rejecting
misconfigured enabled discovery by aborting child creation is intentional
fail-closed behavior. No test or policy asserts a complete OS sandbox.

**Independent read-only follow-up reviewer verdict: private trust admission
GO.** It verified the mandatory entire-root propagation, both symlink
directions, non-executable authorized roots, evidence poisoning after explicit
stop failure and absence of exported profile hashes. This verdict is limited
to operator `explicit_trust_only` configuration. It explicitly excludes
hardlink/bind-mount alias proof, OS sandboxing, and the upstream Pyright
subprocess environment (which may inherit sensitive Binnacle environment
variables). Those issues remain P3.3 conditions before any READ/public GO.

## Security observations and unfinished P3 items

- **P3.2 functional only:** the upstream multilspy Pyright Adapter and fixed
  `pyright-langserver 1.1.413` previously passed LSP feature tests. Upstream
  Microsoft PR #168 remains unmerged. A launcher hash or language capability
  cannot certify Node package identity, environment or side-effect safety.
- **P3.3 not passed:** earlier Linux test runs left two process-tree *fixture*
  children alive beyond their intended scenario. The specific orphaned test
  PIDs were independently verified as owner-created QA subprocesses (UID,
  executable command line, PID and birth time) and explicitly terminated
  individually, without signaling another process group or live Binnacle.
  This observation is not evidence of any leaked production Pyright process,
  but demonstrates why clean process exit and OS confinement are distinct.
  The test fixture, escaped process handling, on-disk/network side effects,
  independent package identity and both-OS containment all require P3.3
  review. In particular, suppressing `workspace/applyEdit` does not prevent
  a Pyright command from writing to the workspace directly.
- **P3.4–P3.6 not passed:** other language adapters, side-effect audit and
  realistic latency/RSS budgets have not been assessed under this branch.
- **P4/P5 still NO-GO:** no public tool registration or READ annotation is
  authorized. Continue to use upstream multilspy rather than fork a second
  Pyright protocol adapter in Binnacle.
