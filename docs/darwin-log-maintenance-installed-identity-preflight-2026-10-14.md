# Issue #30 — independently pinned installed LaunchDaemon identity preflight

Status: **read-only producer identity validation, no native controller
enablement**. Not a stop/restart authority, not a release approval.

## Evidence gathered safely from the existing Mac

Without touching a Binnacle service, this investigation verified on
2026-10-14 that the five repository-managed LaunchDaemon plists are at
/Library/LaunchDaemons/com.binnacle.{mcp,jobs,tunnel,service-watchdog,
resource-monitor}.plist. Each is root:wheel, mode 0644, single-link.
Their stdout/stderr target paths are in the current user-owned, mode-0700
~/Library/Logs/binnacle directory. The two service types Jobs and
resource-monitor use KeepAlive SuccessfulExit=false, while MCP, tunnel
and service-watchdog use KeepAlive=true. Session-observability is separately
installed and therefore excluded from Issue #30's allowlist.

## New boundary

The native reader is deliberately **not** an operational controller.
A future independent privileged supervisor must supply an out-of-band,
reviewed SHA-256 of the exact installed plist. The reader rejects
blank/noncanonical fingerprints and refuses if the current plist hash
does not match that approved digest. It does not calculate a hash and
then automatically approve it as trusted.

Before returning an advisory record it verifies: exact allowlisted
label and raw generation, original system-domain plist path, opened
root:wheel 0644 single-link plist inode and stable file bytes, parsing
the launchd name, identity, RunAtLoad, KeepAlive, owner, stdout/stderr
paths and executable arguments, with no unexpected socket/Mach
activation. The approved account's home and 0700 private log directory
must be canonical and owned by the unprivileged user. The selected
existing raw inode must be private, mode 0600 and single-link. It is
opened with O_NOFOLLOW and checked again by pathname, but its contents
are deliberately **not read** by this identity probe.

The returned InstalledWriterIdentity structurally enforces
production_authorized=false. No service-action method or CLI is
registered, and the module never imports or invokes launchctl/sudo,
issues A3 commands, kills processes, reads private log contents, writes
or unlinks any file. No arbitrary source and no separately installed
session-observability source is eligible.

## Tests and caveats

Portable tests exercise all five exact names, forbidden source/labels,
typed KeepAlive forms, bad root owner, symlink/hardlink/public/empty
raw source, digest mismatches, malformed/oversized plists and unexpected
activation paths. The Linux fixture substitutes synthetic root:wheel
metadata only at the test-owned plist read boundary; it does not
chown/install a real system file.

A successful read-only attestation cannot prove the currently loaded
launchd generation or live writable inherited FDs. Before authorizing
ANY writer outage, a separately authenticated native controller must
prove exact launchctl process PID/start, J7 locks, MCP/Jobs and Watchdog
ACKs, independent guardian readiness and privileged complete all-
process FD census (including a same-scan positive canary). These
requirements remain unchecked in Issue #30.

Production log pruning and service bootout remain **DISABLED**.
