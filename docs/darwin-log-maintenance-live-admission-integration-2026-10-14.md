# Issue #30 — Installed service admission prerequisites, default OFF

Status: implementation gated by CI, no production activation or change
to installed Mac services, live log archives, Jobs or service processes.

## Actual service lifetime integration, not test-only monkeypatching

- **MCP:** The FullRequestAdmissionMiddleware can be explicitly injected
  into the application and HTTP server factory. It counts all externally
  submitted MCP requests before dispatch, and also directly typed tool
  calls. An already admitted request retains its ticket through nested
  dispatch; cancellation and errors release exactly once. New requests
  after fencing get an MCP protocol error and cannot run a tool. Routine
  production configuration never installs this gate.
- **MCP A3 endpoint:** The mcp_maintenance profile uses enabled=false
  and control_root=null by default. Explicit opt-in on Darwin creates
  one process-generation gate and a private authenticated A3 status,
  fence and wait sidecar inside its HTTP lifespan before requests.
  The root must already exist, be unprivileged user-owned and mode 0700.
  This does not create an MCP control tool, unfence, stop, restart or
  modify files.
- **Jobs Manager:** The jobs.maintenance_fence_dir config is NULL by
  default. Explicit native manager startup connects the existing
  nonce/owner/PID maintenance file fence into the same atomic job-start
  transaction that reserves a child. Its coherent ping carries the
  paused nonce and current running/UNKNOWN counts under the same lock.
  Unsafe/missing roots prevent startup; malformed records deny new
  starts. This commit never restarts installed Jobs.
- **Watchdog:** The native Mac launchd plist renderer accepts an
  optional preapproved maintenance_pause_dir that passes the existing
  CLI ACK/pause protocol. Default renderer output is unchanged; it
  has no automatic effect on existing service installations.

## Verified and unverified behavior

Unit and integration tests cover real in-memory/HTTP FastMCP admission,
late arrivals, cancellation, concurrent accepted calls, real A3 Unix
socket HMAC/generation requests on Linux private disposable fixtures,
Jobs Manager configured start/ping integration, malformed settings
and identities, and Watchdog plist rendering.

The Linux A3 test adapts ONLY Darwin-only getpeereid and RENAME_EXCL
syscalls. A3 sequencing, challenge, signed response and peer check
source remains unchanged. Linux tests cannot prove native launchd,
macOS all-process visibility, privileged writer closure or KeepAlive.

**SECURITY LIMIT:** Same-UID HMAC authentication does NOT constitute an
independently privileged controller. Production stop and delete
authorization still requires separate root-owned exact label/plist
identity, validated J7 locks, Watchdog/Jobs/MCP admission generations,
a bounded independent crash guardian and privileged old-inode writable
FD census. The control channels return no production prune authority.
Do not enable these controls on the installed Mac without explicit
review and non-destructive native acceptance. Production cleaner stays
OFF; Issue #30 stays OPEN.
