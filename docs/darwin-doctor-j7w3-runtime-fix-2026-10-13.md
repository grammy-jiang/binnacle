# Darwin doctor compatibility for the guarded Mac release

**Date:** 2026-10-13. **Scope:** Native Mac CLI diagnostics and the
J7m/W3 production acceptance gate. This is a change in an isolated Git
worktree and is not deployed to a live service until the protected gate passes.

## Reproduced incident

The original checksum-pinned J7m/W3 production gate targeted GitHub
master SHA 4920559bc4727cfae8abd77a0db3d9e0138bdbd9. It passed
protected CI, runtime process ownership, idle durable-job checks, unchanged
Jobs launchd plist, managed revision upgrade, and full authenticated
MCP smoke test.

The new step 7a_startup_doctor correctly refused: on Darwin, the doctor
CLI tried to construct the Linux-only service provisioner and raised
UnsupportedHostOS before writing any JSON. The W3 adapter therefore
returned startup_doctor_unparseable.

The gate successfully restored the original source and runtime through
its existing rollback steps 8a, 8b, 8u and 8c, then proved full smoke
in 8d. The receipt shows FAILED_ROLLED_BACK (exit 3), zero interrupted
user jobs, and no host reboot or Tunnel restart. See the private
per-attempt receipt at:

    ~/Projects/binnacle-mac-reviewed-deploy-4920559-20261013/gate-receipt.json

## Platform-correct behavior

Linux CLI doctor remains byte-for-byte behaviorally unchanged, using
the existing systemd service checks and unit provisioner.

On Darwin the doctor now routes to an explicit read-only installed
LaunchDaemon diagnostic implementation. It renders the same stable JSON
schema (checks and exit_code), including a required startup check. It
inspects the five root-owned system/com.binnacle.* launchd plists,
secure Umask, boot configuration and running PID; it never prints
plist arguments or environment variables.

The Jobs check uses authenticated Darwin-generation IPC, proves the
manager PID against launchd, verifies the durable job directory and
both activity counters, and reports any mismatch from checkout revision.
Other checks cover configuration, provenance, token, ripgrep, and
unauthenticated/authenticated local MCP initialization.

A failure to inspect a non-startup check becomes a JSON fail entry,
rather than erasing the startup check with a traceback. A failed or
unreadable startup import record remains a blocking startup fail,
preserving the W3 gate's fail-closed contract. This path does not
write to launchd, restart services, alter credentials or rotate logs.

## Tests and deployment contract

The original Mac exception was reproduced against the precise
pre-fix source. The proposed fixed CLI was run in a detached source
worktree: 23 JSON checks, startup=ok, and the reviewed W3 parser
returned startup_ok. No live service/source mutation was needed.

Regression tests cover launchd corruption, symlinks and hardlinks,
unverified PID/status, bad authenticated manager identity, unknown
jobs, mismatched manager Git revision, Python/waitid capability,
startup-failure records, failure-path JSON, nonleakage of secrets
and unchanged Linux CLI routing. Focused new-module statement and
branch coverage was 100 percent.

**A new exact-SHA review is mandatory** for the eventual merged fix.
The previous JCR record only covered SHA 4920559 and must not be
reused to authorize any different commit. Production deploy must
still pass the unmodified pinned J7m/W3 CI, owner, idle-jobs, quiet,
rollback and startup-doctor gates. A failed gate must not be bypassed.
