# Issue #30 — remaining work, acceptance and dependency order

Status: **ACTIVE, NOT production-approved**. Owner: Binnacle Issue #30.
Canonical issue: [Binnacle #30](https://github.com/grammy-jiang/binnacle/issues/30).
This is the single implementation checklist; associated documents explain
individual designs but must not be mistaken for independently finished goals.

## Already accepted on master

- [x] Private raw archive staging, deterministic checksum and no-overwrite
  canonical .bz2 finalizer; raw preserved when quiescence is not verified
- [x] Fixture-only writer-generation hold, J7 locks, Watchdog maintenance
  fence, MCP tools/call gate, Jobs manager start fence and coherent ping
- [x] Existing A3 HMAC peer/generation IPC, test-only recovery guardian,
  durable phase journal, orphan-only reader and manual-only recovery risk
- [x] Advisory positive-control lsof parser, strict privacy and inode checks
- [x] Integrated **disposable Linux fixture**: gate, stop independent test
  writer, publish/verify/prune actual BZ2, start new writer, release fences
- [x] Synthetic controller SIGKILL and independent fixture recovery for
  four critical windows; full test suite and PR #50 CI passed

## Still outstanding, in strict dependency order

### C1 — True request and job admission in service lifetime

- [x] Every externally relevant MCP request is admitted before dispatch,
  including asynchronous tool calls and resource/prompt operations.
  Already accepted calls drain, even if the maintenance fence begins while
  they run; subsequent calls refuse. Cancellation and exceptions release.
- [x] Explicit config-gated composition for installed **Darwin MCP**;
  default disabled. Health and readiness policy documented distinctly.
  No maintenance control tools exposed through ordinary ChatGPT MCP.
- [x] Installed Darwin Jobs Manager hooks are wired to a durable, exact
  generation-bound private pause root, not merely fixture hand injection.
  Absent configuration preserves legacy behavior; unknown or foreign
  pause fails closed. Production install profile stays OFF.
- [x] Watchdog real launchd startup profile uses the existing private
  nonce/PID maintenance ACK, so it cannot surprise-restart a stopped writer.
- [ ] Integration tests: actual FastMCP HTTP/tool contexts, late arrivals,
  cancellation, SIGTERM, stale PID, UNKNOWN jobs and negative ACK.

C1 implementation is default OFF and currently verified only in
disposable Linux fixtures. Installed Mac service request coverage and
native cancellation behavior still require native acceptance; the
final C1 test item remains OPEN.

### C2 — Independent authenticated native maintenance control plane

A reusable ordered controller is now exercised against real private
J7/Watchdog/MCP/Jobs/journal/BZ2 **Linux fixture** components, including
single-attempt restoration and freshly admitting MCP generation proof.
This is only the transaction sequence: the trusted installed native
actuator and independent privileged recovery guardian do not yet exist.
No C2 authorization item is accepted complete on that basis.

- [ ] A controller not hosted by the service being stopped, with exact
  allowlisted service label, root:wheel 0644 pinned launchd plist and
  exact stderr/stdout source. No arbitrary path/command or broad sudo.
- [ ] Controller obtains the outer J7 and jobs-service locks, authenticated
  MCP/HTTP + Jobs generation-bound admission, Watchdog ACK, zero running
  and UNKNOWN Jobs, then an independent **READY** restoration guardian.
- [ ] Controller publishes a durable transaction with no stale-owner
  adoption, monotonic receipts and bounded leases/deadlines. Mid-phase
  errors never get promoted to success. No log unlink on unknown.
- [ ] Subprocess or privileged-helper trust boundary independently
  authenticated; same-UID markers, arbitrary JSON and PID reuse alone
  never authorize actions.
- [ ] Simulated full transaction with malformed/replayed/unauthorized
  protocol packets and hung-controller recovery, not just unit mocks.

### C3 — Real Mac writer quiescence and irreversible data path

- [ ] Under pinned production identity and held independent guardian,
  actually unload only the eligible writer's exact launchd generation.
  Watchdog/KeepAlive coordination must remain effective during downtime.
- [ ] Privileged all-process old-inode writable FD census including
  inherited descendants; same-call known writable canary; process
  visibility, access modes, old dev/inode and exit semantics verified.
  An empty or partial scan is never sufficient.
- [ ] Exact source inode and canonical generation reverified before unlink,
  with durable canonical_verified receipt before and raw_pruned after fsync;
  retain GN rename-only, 100 GiB reserve, 40 GiB warning, 2 raw histories,
  no forced rotation and no double-counted log stats.
- [ ] Recover with pinned *same* root-owned plist/label and verified new
  PID/generation/readiness; release all barriers only after recovery.
  Never kill unrelated Jobs to make a quiet window.

### C4 — Native macOS isolation, safety review and controlled deployment

- [ ] Repeat full tests on a native Mac in **owned disposable fixtures**:
  launchctl KeepAlive, root plist checks, lsof complete visibility,
  inherited writable FD, identity swaps, SIGKILL at all 4 boundaries,
  hung controller timeout, power-loss replay, repeated GN rotations.
- [ ] Independent security review of exact native privileged operations
  and cross-service deadlock/recovery behavior; Linux/ARM64 regression,
  Python 3.10–3.14 CI, formatting/typing/architecture and coverage >=90%.
- [ ] Only after Mac's other development and durable Jobs drain, perform
  an explicit approved, **non-destructive installed-service dry run**.
- [ ] A later manual maintenance window may authorize an actual producer
  outage and separately approve real raw source pruning. Without that
  approval, **no real service bootout, prune, deployment, reboot or issue
  closure**. Automatic operation stays disabled.

## Stop conditions and release decision

The code for C1–C3 can be developed off-host with injected native adapters,
but no Linux fixture is evidence that macOS root privileges or launchd
semantics are correct. If native Mac is busy, continue safe work and leave
C4 blocked explicitly. CI success alone never means a production rollout
or the Issue #30 acceptance contract is complete.

**Completion requires every C1–C4 item verified, not simply a count of
merged pull requests.** Do not close Issue #30 while any are pending.
