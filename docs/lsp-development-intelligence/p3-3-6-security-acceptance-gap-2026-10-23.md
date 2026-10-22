# P3.3–P3.6 independent-acceptance gap ledger (2026-10-23)

This is direct implementation review, NOT a third-party security audit or release certificate. Baseline GitHub-green commit: 1393494b87b211f677558ad8ad489d457a39d798. New local acceptance candidate is not merged or deployed.

## Controls exercised

- Linux ARM64: actual Pyright under rootless Bubblewrap, private Process Owner, explicit experimental mode, real initialize/documentSymbol, stable process-group cleanup. Five repeated 13-test cycles plus one poisoned-parent-environment fixture passed.
- Sandbox selected synthetic read-only workspace rejects write; unmounted synthetic sibling secret is inaccessible; host listener (positive host connectivity control) is inaccessible in sandbox network namespace.
- macOS ARM64: synthetic process tests and unchanged default baseline run; Seatbelt broad-read proof is NOT READ isolation and the stricter attempted read allowlist failed Node launch.
- P3.6: verified Ed25519 detached signature over canonical, domain-separated stage/reviewer/producer/target/evidence/artifact digests. A caller-supplied key/fingerprint validates the signature, NOT the reviewer trust chain. Signed GO claim always yields admission REWORK and READ NO-GO.
- First-party quality: G6 and generated module membership, opt-in native P3.3 fixtures, static and managed unit/full/coverage/prepush gates are independent stages; results must be linked to the exact new commit.

## Unresolved security certification gates

| Gate | Observation | Required remaining proof |
| --- | --- | --- |
| Executable supply chain | Selected absolute Node ELF and Pyright package work for trusted install | Immutable/signed package source and atomic inode/path identity; hardlink, mount and symlink TOCTOU |
| File access | Read-only synthetic workspace and private HOME; /usr still mounted read-only | Complete mount topology, inherited FDs, /proc and symlink read-escape controls |
| IPC / network | Host loopback denies in Linux test | Other IPC, PID and namespace escape controls on each target OS |
| Resource enforcement | Synthetic memory/latency observed; cgroup v2 delegation exists on Sextant | Hard CPU/memory/PID ceilings, safe ownership, pressure/cancellation/soak/TTL tests |
| Process lifecycle | Two observed Node children reaped, no observed escape in native proof | Deliberate setsid, double-fork, surprise death, inherited FD, group reassignment and all cancellation paths |
| macOS parity | Limited Seatbelt can run Pyright and block selected writes/network | Strict system read allowlist with no blanket file-read or mach-lookup, audited Mac process cleanup |
| Reviewer trust | Ed25519 proof verifies under a key provided by its caller | Authenticated out-of-band reviewer registry, rotation/revocation, independent key provenance |
| Evidence chain | P3.4/P3.5 self-reported source hashes and signed-claim type exist | Independently witnessed exact Pyright method and OS/security evidence, linked to all binary/source identities |
| Dependencies | Default branch has open Critical development dependency alert for uv | Separate tested dependency upgrade, no baseline weakening |

## Admission determination

- P3.3 private Linux synthetic experiment: eligible only for further sandbox testing, under operator trust and explicit opt-in.
- P3.6 Ed25519 verifier: valid proof-of-signature primitive, not a full reviewer trust service.
- Untrusted READ, agent-facing LSP MCP tools, production rollout, default-on, P4 private deployment: NO-GO.
- Current source review is not an independent third-party acceptance. Do not turn these local observations into trusted certification.

## Next safety items

1. Protect selected Node/Pyright/Bubblewrap identities atomically and implement narrow OS filesystem/process/network/FD policy.
2. Bind delegated hard cgroup resource limits and prove cleanup on cancellation, escapes and pressure.
3. Establish independent operator-controlled reviewer public-key registry with signed chain, revocation and exact immutable artifact bindings.
4. Complete Darwin strict Seatbelt negative-controls and independent review; only then reconsider P3.6 policy GO.
