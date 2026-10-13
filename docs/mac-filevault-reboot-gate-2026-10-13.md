# MacBook Pro: unresolved FileVault reboot and runtime-version admission

**Later operational update, 2026-10-13:** The owner subsequently remained
at the Mac and explicitly authorized a single reboot. At **16:19:56 AEDT**
the Mac booted successfully, and independent Pi/sextant SSH, all five
LaunchDaemons and actual ChatGPT MCP tool calls recovered. FileVault
unlock is no longer the current blocker. A later guarded runtime release
encountered the separate Darwin doctor defect and automatically rolled back.
See [Darwin doctor compatibility](darwin-doctor-j7w3-runtime-fix-2026-10-13.md)
for the new remediation and mandatory release checks.

**Recorded:** 2026-10-13. **Status:** Mac was not rebooted. Original Pi
and sextant rebooted separately and passed their hardware acceptance.

## FileVault boot-time SSH risk

MacBook Pro hardware: Apple silicon, macOS **27.0.1**, FileVault **On**,
Remote Login **On**. Both Raspberry Pis can access macOS over
public-key SSH after the volume is unlocked.

Apple's macOS 26+ FileVault-over-SSH mode supports remote volume unlock,
but at the **preboot stage it requires the authorised local account's
password**. Its configured data-volume SSH keys cannot authenticate until
after FileVault is unlocked.

- Apple documentation:
  [FileVault introduction](https://support.apple.com/en-au/guide/deployment/dep82064ec40/web)
- Apple's OpenSSH documentation:
  [SSH and FileVault](https://github.com/apple-oss-distributions/OpenSSH/blob/main/apple_ssh_and_filevault.7)

The deployment session has no authorised FileVault login password or
recovery key. It did **not** attempt to recover, export or store these
secrets. A normal unattended reboot could therefore leave the Mac at
preboot authentication, with both Binnacle MCP and the approved
public-key SSH recovery paths offline. The Mac was deliberately
**left running**.

Apple also provides the one-time `fdesetup authrestart` mechanism on
supported Macs. That operation requires appropriate authorised user
credentials; it should be prepared interactively by the owner or
through an existing approved device-management channel. It must not
be performed with extracted, guessed or chat-transmitted credentials.

## Version consistency and protected deploy gate

The installed Mac primary checkout is clean at
`2dc5085b5158d6fee6ef50894a46d014f0e65a0a` while the current
approved GitHub `master` is
`37de147a01e60f6fd79c814481fbf2a47480bad7`.

The live Job Manager's last reported revision was
`0a40b064caed`, even though the working Git checkout had previously
been fast-forwarded without restarting the manager.

The independently reviewed
`scripts/mac_w3_deploy_gate.py` verifies a pinned base gate SHA,
GitHub CI, service ownership, private logs, quiet windows, authoritative
durable-job identity, rendered launchd plist and rollback capability.
A read-only `--render-only` run for the current target reported
`UPGRADE_PLIST_UNCHANGED`, so the Jobs plist does not need replacing.

A full production gate attempt returned
`REFUSED_NOTHING_CHANGED` **before any source or service mutation**,
because the running manager's revision was different from the installed
checkout HEAD. Its receipt is stored at:
`~/Projects/binnacle-mac-ops-upgrade-receipts-20261013/gate-receipt.json`.

Neither Mac MCP, Job Manager, Tunnel, Watchdog nor resource monitor was
restarted by the refused deploy gate. The Mac remains reachable over
MCP and SSH, and the 50 GiB rename-only GN log rotation remains active.

## Safe follow-up

In a deliberately arranged maintenance window with approved FileVault
credentials available to the owner:

1. Verify both Pi recovery channels and the Mac's AC/network connection.
2. Use the owner's authorised one-time authenticated restart workflow,
   or explicitly arrange for a FileVault password unlock at preboot.
   Never use a normal remote reboot hoping SSH-key auth will work
   before the volume unlocks.
3. After full unlock, check all five LaunchDaemons, Binnacle HTTP health,
   the Mac manager's durable-job state and actual running Git revision.
4. Once the manager revision matches the clean Git checkout and the
   reviewed gate's quiet/CI/owner checks pass, rerun the pinned J7m/W3
   production upgrade to `master`. Respect any new refusal; never
   bypass a failed owner, quiet, revision or rollback guard.
5. Verify tokenizer telemetry, timestamped job events and
   `binnacle stats`, then record the full results.

The owner previously authorised *sequential* reboots, but authorisation
alone does not provide a FileVault password or a safe recovery channel.
This is a deliberately open acceptance item, not evidence of a successful
Mac reboot.
