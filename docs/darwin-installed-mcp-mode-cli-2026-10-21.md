# Installed macOS MCP service mode management

**Status:** implementation candidate, 2026-10-21. Linux systemd paths are unchanged.

## Root cause

The MCP runtime supports Linux and Darwin, but Binnacle setup and mode
previously selected the Linux user-unit provisioner on both hosts. Darwin
correctly rejected that Linux-only provisioner. Native installed-launchd
management is now selected separately by platform composition.

## Operator commands

    binnacle mode --target status
    binnacle setup --dev "$HOME/Projects/binnacle" --dry-run
    binnacle mode --target dev --repo "$HOME/Projects/binnacle" --force
    binnacle mode --target prod --force

The first two examples are read-only. On an active installed daemon, a
mode change requires an explicit --force after checking no significant
in-flight MCP requests. The flag does not bypass identity, ownership,
revision or path constraints.

Setup manages an **existing verified** installed macOS MCP LaunchDaemon.
It does not cold-install an unknown root daemon, Jobs manager, token,
ChatGPT tunnel or system service. The initial native system installation
remains a separately gated rollout. The --adopt switch cannot bypass
identity validation.

## Native safety boundary

Only /Library/LaunchDaemons/com.binnacle.mcp.plist with the expected
label, current non-root user, known environment, checkout binary and
known command shape is eligible. Development adds --reload to the
checkout's binnacle serve command; this preserves macOS asyncio rather
than importing Linux uvloop service logic. Reload watches src/ only.

The controller locks the private transaction root, pins the pre-change
plist SHA-256, stores the complete old/candidate plists in private files,
then uses fixed sudo -n install / launchctl bootout/bootstrap commands
for the single MCP label.
The controller does not call sudo -n -v as a preliminary approval check:
some valid NOPASSWD configurations reject that generic validation request
even though the specific install and launchctl operations are permitted.
Each fixed-argument native operation is checked directly; failures remain
bounded by the existing restoration path. Unknown service identity, missing privilege,
a changed source plist or incomplete rollback is a refusal, not implicit
adoption. The Jobs manager and tunnel are never restarted as part of a
frontend mode change.

Avoid triggering a self-restart from an MCP tool call that depends on
the very same MCP server. Use a separately controlled deployment session.

## Release gates

Validate native plan/status/dry-run on actual Mac, separate Linux+Darwin
tests, Linux systemd regression, full CI, installed plist identity,
non-running important tasks, backup, deliberate restart, live health
and private Full Capture sentinel. The enabled logging preference is
independent of running the frontend in development mode.

## Launchd transition and rollback safety

The installed MCP controller waits for positive label absence after
a successful bootout. Bootstrap errors are retried only when the
label is absent; a failed bootstrap with a loaded label is ambiguous
and must instead be rolled back. Restoration must verify that the old
plist and original launchd label have been reinstated. An independent
deployment controller handles failures of the CLI transaction itself.
