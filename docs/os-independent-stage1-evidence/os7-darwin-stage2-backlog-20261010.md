# Binnacle Stage 2 Darwin adapter backlog (not implemented)

Task: BINNACLE-OS-STAGE1-IMPLEMENT-20261009.
This is a design handoff only. Stage 1 implements and qualifies Linux; neither
this file nor the Stage 1 branch claims macOS support. Stage 2 must reuse the
single FastMCP root, three native children, eight public tool contracts and
the Stage 1 platform Protocols. Do not create a second MCP framework.

## Source-bound starting point

- First inspect `platform/composition.py`, the five files under
  `platform/contracts/`, and Linux implementations under `platform/linux/`.
- Review the OS0 raw four-profile MCP wire snapshot and OS6 complete module
  inventory before selecting Darwin mechanisms or changing packaging claims.
- Preserve the Linux implementation and retain a host-independent fake backend
  suite as the contract authority, not a Darwin implementation imported on Linux.

## Ordered adapter work and acceptance evidence

1. **Capability and risk study, no implementation.** Build a macOS-version and
   Apple Silicon/x86 compatibility table for launchd, process identity, resource
   accounting, local sockets, process group control and unified logging. Prove
   APIs and fallbacks with disposable local probes; explicitly classify
   guarantees that macOS cannot provide. Review any unprovable stop safety
   before implementation.
2. **Explicit host composition.** Extend the one platform-selection boundary
   with `Darwin` and its native factories. Tests on both systems must reject
   unsupported hosts, prohibit Linux fallback, prove that generic imports do
   not load either native backend, and preserve the fake-platform path.
3. **Durable job identity and signals.** Implement `ProcessBackend` on Darwin
   only after proving an owner-verified process identity and race-safe
   TERM/wait/KILL escalation against PID reuse, leader exit, descendants and
   reparenting. macOS has no Linux pidfd/cgroup-v2 substitute by assumption.
   If a descendant/target cannot be safely verified, fail closed rather than
   calling numeric-PID or process-group kill optimistically. Exercise actual
   privilege errors and partial-delivery persistence across retries.
4. **Resource accounting.** Implement or truthfully mark unavailable
   `ResourceAccounting` semantics using verified Darwin primitives (for
   example, Mach/libproc if appropriate). Do not synthesize cgroup counters or
   misrepresent a sampled process tree as complete containment. Preserve
   historical schema, finalizer/reaper behavior and optional accounting.
5. **Runtime paths and RPC.** Implement `RuntimePaths` for native user runtime
   directories and permission-safe socket placement. Confirm AF_UNIX path
   length, atomic metadata/spool writes, old record readers, cursor retention,
   restart/recovery and symlink escape protections with real macOS tests.
6. **Managed services and provisioning.** Implement service inspection,
   readiness and optional service control using user launchd agents and
   native backup/adopt/rollback. Keep Linux systemd unit bytes untouched.
   Guard manager upgrades against active durable jobs and provide an observed
   quiet window before any live restart.
7. **Diagnostics and service logs.** Map native service/linger expectations
   into neutral diagnostic contracts. Implement a Darwin `ServiceLogSource`
   using macOS unified logs if safe and sufficiently supported; preserve
   privacy redaction, bound retrieval, timeouts and pure log analytics.
8. **CLI, security and packaging.** Wire Darwin-native setup/doctor/log
   hints without teaching generic commands about launchctl/systemctl. Verify
   external ripgrep availability and uv/Python/third-party wheel compatibility
   on supported macOS releases; declare accurate support classifiers only
   after package and host tests pass.
9. **Cross-platform acceptance.** Re-run OI-01 through OI-12 and FM-01 through
   FM-08, raw four-profile MCP wire parity, v1 job metadata/RPC cross-version
   suites, stop race probes and service rollback. Add macOS CI/signed source
   review plus live smoke on a designated host; keep existing Raspberry Pi
   Linux CI and production gates intact.
10. **Companions and exclusions.** Treat Raspberry Pi watchdog, Webmin history,
    Linux tunnel service units and host-maintenance scripts as optional
    Linux-only integrations. Port only with separately specified requirements,
    explicit user approval and independent tests; do not block native core
    support on unrelated companions.

## Stage 2 entry gate

No Darwin implementation or macOS support claim should start from an unmerged
or unreviewed Stage 1 candidate. First reconcile Stage 1 exact-SHA CI,
independent source review, guarded Linux production qualification and rollback
into the Stage 1 acceptance ledger. This backlog is not that approval.
