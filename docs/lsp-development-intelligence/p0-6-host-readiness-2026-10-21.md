# P0.6 — Nonintrusive host-readiness inventory (2026-10-21)

**Status:** GO for the P1 deterministic **fake-only** testing track, with clear P3 safety and executable-origin limitations. This document records live host context; it is not real-provider initialization or a READ-safety authorization.
**Source baseline:** isolated LSP worktree based on `origin/master 40aafcd`. The running MCP deployments may use their own release paths; this inventory did not modify, restart or reconfigure any services.
**Scope:** MacBook Pro (Darwin arm64), Raspberry Pi 5 `raspberrypi` and Raspberry Pi 5 `sextant` (Linux aarch64). Each Binnacle instance remains host-local.

## Host/process facts

| Field | MacBook Pro | Raspberry Pi | Sextant |
| --- | --- | --- | --- |
| OS | Darwin 27.0.0 arm64 | Linux 6.18.50+rpt-rpi-2712 aarch64 | Linux 6.18.50+rpt-rpi-2712 aarch64 |
| Shell Python | 3.14.8 | 3.13.5 | 3.13.5 |
| Service system | launchd system daemon `com.binnacle.mcp` | user systemd `binnacle-mcp.service` | user systemd `binnacle-mcp.service` |
| Service state observed | process PID 31576 under PID 1; label in `launchctl list` | user unit active/running, PID 343412 | user unit active/running, PID 434431 |
| Service PATH evidence | launchd plist `EnvironmentVariables.PATH` (configured; runtime environ not read) | exact `/proc/343412/environ` PATH, **only** PATH printed | exact `/proc/434431/environ` PATH, **only** PATH printed |
| Platform process primitives | `ps`, `launchctl`, `sandbox-exec` present; confinement not proven | `setsid`, `ps`, cgroup filesystem present; confinement not proven | `setsid`, `ps`, cgroup filesystem present; confinement not proven |

Mac configured service PATH:
`/opt/homebrew/bin:/Users/grammy-jiang/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`.

Both Pi processes observed service PATH:
`/home/grammy-jiang/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/local/games:/usr/games`.

The Pi service executable refers to a separate `binnacle-deploy-fullcapture-20261021` checkout. The isolated development tree is **not** the deployed checkout. Service process and paths may change; P3 must revalidate at run time.

**Important false lead:** `systemctl show binnacle-mcp.service` (system level) showed inactive and PID 0, but `systemctl --user show binnacle-mcp.service` verified the active real user units. Always probe correct service scope. On macOS the launchd plist PATH is a configuration value, not a verified read of the live process's environment.

## Discovery, versions and fingerprints (no provider executed)

| Candidate | Mac service PATH / shell lookup | Both Pi real service PATH | Pi installed version (local package.json only) |
| --- | --- | --- | --- |
| Pyright LSP | not located | `~/.local/bin/pyright-langserver` | 1.1.413 |
| TypeScript LS | not located | `~/.local/bin/typescript-language-server` | 6.0.0 |
| clangd | `/usr/bin/clangd` (macOS shim, further identity needed) | `~/.local/bin/clangd` to `/usr/lib/llvm-19/bin/clangd` | llvm-19 location, runtime version not probed |
| rust-analyzer | not located | `~/.local/bin/rust-analyzer` | version not probed |
| Marksman | not located | `~/.local/bin/marksman` | version not probed |
| Bash LS | not located | `~/.local/bin/bash-language-server` | 5.6.0 |
| make-ls | not located | `~/.local/bin/make-ls` | source path `make-ls-v0.1.20`, not runtime-probed |
| YAML LS | not located | `~/.local/bin/yaml-language-server` | 1.24.0 |
| JSON LS | not located | `~/.local/bin/vscode-json-language-server` | vscode-langservers-extracted 4.10.0 |

Selected executable/script content identities (SHA-256; same on both Pis):

- Pyright language server launcher `langserver.index.js` (229 bytes): `f200762078eb9880faf421a5b30f9ef3055b1d85c6f10780d75db4da8d8499f1`.
- TypeScript language server `lib/cli.mjs` (917064 bytes): `146b113929fd41f12fbe7342ba493adce2bf82a07cdc791d0b9678a17572bc46`.
- clangd `/usr/lib/llvm-19/bin/clangd` (17497056 bytes): `7e233931e6ee410613daeddb2db2f0aa683ba896b83353432cf20f7d20a4e8fe`.
- macOS `/usr/bin/clangd` (200560 bytes, possible system shim): `34129c71a01a74f7f3b2443521519b2e5447553fa187f5fcafaaf8c42cc192e2`.

A launcher hash is **not** a full Node.js language-server package fingerprint, and the version is read from package metadata, **not** a negotiated LSP capability. P3 needs transitive package/binary identity, actual process execution/config and behavior evidence. Path discovery is not permission to run.

## Gate result and remaining non-P1 concerns

- **P0.6 GO:** real per-service PATH and OS primitives were examined; no service changes, provider launch or installer run. P1 runs only self-contained Python fake fixtures, independent of these provider installations.
- **Unverified (P3):** real macOS process PATH and clangd target, provider initialize/capabilities, version/configuration identity, cache/network/project execution effects, per-OS sandbox efficacy, process-tree containment, real-world resource limits, any public READ eligibility.
- **Not to do in P1:** deploy to either Pi; start installed production Pyright/rust-analyzer/etc.; use provider discovery as an implicit permission to access untrusted projects; enable MCP tools.
