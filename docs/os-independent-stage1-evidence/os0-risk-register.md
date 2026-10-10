# OS0 risk, interfaces, and dependent proofs

Source: exact v1.0.1 02f4bab9bc7562668ffc41d622c4274449933768.
The full per-file KEEP/SPLIT/LINUX/BOUNDARY map and every import edge is in os0-source-inventory.json.

| Priority | Contract/observable invariant | Implementation owner | Verification |
| --- | --- | --- | --- |
| P0 | FastMCP three mounts, eight tools, four wire profiles | OS2 | OI-03, OI-05, FM-01–FM-08 |
| P0 | Process identity checks before signal, durable RPC/records stable | OS1 + OS3 | OI-06, OI-07 |
| P0 | CLI, systemd unit bytes, no surprise restart | OS4 | OI-09, OI-12 |
| P0 | Root aliases allowed, escaping symlinks denied | OS5 | OI-08 |
| P1 | Log analytics independent of service_journal | OS5 | OI-10 |
| P1 | Linux-only script and companion direction | OS6 | OI-01, OI-11 |
| P1 | No eager Linux adapter activation in importable business core | OS2 + OS3 | OI-03–OI-05 |
| P1 | Linux metadata retained including pid, pgid, starttime, resource history | OS3 | OI-07, OI-12 |

Dependency order: OS0 -> OS1 reviewed contracts -> OS2 pure composition -> OS3 / OS4 and OS5 path -> OS5 diagnostics -> OS6 -> OS7.

Immutable snapshots are OS0 evidence, not new goldens or permission to rewrite existing wire pins.
