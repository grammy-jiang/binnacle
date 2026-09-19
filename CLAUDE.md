# binnacle — agent guide

FastMCP server exposed to ChatGPT (as connector "Raspberry Pi MCP") over an
OpenAI tunnel. `server.py` is assembly only; each tool lives in
`tools/<name>.py` (a `register(mcp)` per module), mirroring its spec at
`docs/tools/<name>.md`, with shared helpers `paths.py` (root guard),
`textio.py` (decode/size), and `jobs.py` (disk-backed job store). Two user
systemd services run it: `binnacle-mcp` (uvicorn `server:app --reload`,
port 8000, reload also watches `tools/`) and `binnacle-tunnel`.

v1 is complete: the full toolset is read_file, list_files, search_text,
edit_file, write_file, run_command, job_status, stop_job (no `ping`; the
demo tools are gone). The number of tools a client actually sees varies
per AI agent: `client_tools` in the configuration maps a client-name
prefix to the tools served to it (ChatGPT gets the read/run subset without
the structured edit tools — measured usage showed it edits via run_command
scripts instead). Phase 2 candidates are in the design doc §9. Background
jobs spool to `~/.local/state/binnacle/jobs/<id>/` and survive reloads.

The general workflow — which loop to run, refreshing the connector, tracking and
deleting test chats — lives in the `chatgpt-mcp-dev` skill; load it when working
on the tools. The improvement loop — measure what ChatGPT called from the
journal, rank tool changes by calls absorbed, implement, verify in a real chat,
record a baseline — is the `mcp-usage-review` skill (`mcp-usage-review report
--since <day>`; baselines in `docs/usage-baselines/`, rounds in
`docs/usage-analysis-<date>.md`). This file holds only what is specific to
binnacle.

## Auth

The server requires a bearer token (`StaticTokenVerifier`). The token lives in
`~/.config/binnacle/token` and is shared by three parties: the server reads it,
`scripts/mcp_client.py` sends it, and the tunnel injects it as the `Authorization`
header (both `mcp.extra_headers` and `mcp.discovery_extra_headers` in
`~/.config/tunnel-client/binnacle.yaml` reference the file). The file holds
`Bearer <token>` on one line: the tunnel forwards it verbatim as the header,
and the server strips the prefix. To rotate: `.venv/bin/binnacle token rotate`
(writes the file in that format and restarts both services). The three local
CLI agents below hold the token literally in their own configs, so a rotation
also means updating those registrations.

## Dev loop

Saving `server.py` auto-reloads uvicorn (watchfiles, ~1-2s) — reloading is NOT a
manual step. A manual `systemctl --user restart binnacle-mcp` is only for changes
the reload can't pick up: the token file, new dependencies, the systemd unit, or
`binnacle.yaml` (restart `binnacle-tunnel` too for the last two).

The services get their `PATH` from the systemd user manager, which at boot has
only the base system PATH. `~/.config/environment.d/50-path.conf` prepends
`~/.local/bin` so `run_command` can find `uv` and other user-installed tools
(without it, `uv` exits 127 through the MCP). Changing that file needs
`systemctl --user daemon-reload` and a restart of both services.

Both server units carry an `ExecStartPost` port wait, so systemd (and
`systemctl restart`) reports them started only once uvicorn listens; the
tunnel unit has `After=` on both. That is what lets `token rotate` restart the
server and then the tunnel without the tunnel probing a dead port. The tunnel
caches the token file at startup (measured 2026-09-03), so a rotation must
restart it. Its one startup WARN, "OAuth discovery failed ... invalid
metadata", is expected: the server uses a static token and serves no OAuth
metadata. A `chatgpt-refresh` within seconds of a tunnel restart can still
return HTTP 424 while the poller re-registers with OpenAI; retry.

`binnacle token rotate` restarts the server (blocking until it listens) and
then the tunnel, and returns only when the tunnel's health server reports the
new instance ready with its MCP probe ok. ChatGPT's own tunnel service may
still need a few more seconds; `chatgpt-refresh` retries HTTP 424 by itself.

`.venv/bin/binnacle doctor` checks the whole chain (token, units, service
PATH, /mcp auth, tunnel config, uplink, tunnel poller, watchdog, job spool,
journal errors) and exits 1 on any FAIL; `--json` for machine output,
`--no-probe` to skip the network probes. Run it after touching the token, the
units, `environment.d`, or the tunnel config. Checks live in
`src/binnacle/doctor.py` with tests in `tests/system/test_doctor.py`.

## Uplink watchdog

Everything in `doctor` except the last three checks is local, which is why
they exist. On 2026-09-12 the USB Wi-Fi adapter (wlan1, RTL8812AU) held the
default route for 48 minutes while it silently stopped passing packets:
802.11 association up, carrier up, DHCP lease valid, driver quiet, units
active, `/mcp` answering, tunnel health port green — and ChatGPT saw the
connector as offline the whole time. Nothing was both able to notice and
allowed to act; it ended only when the adapter was physically unplugged and
NetworkManager fell back to the built-in radio.

So three checks look past localhost:

- `uplink` — probes every default route end to end per interface (gateway
  ICMP, DNS for the upstream host, TCP 443), every layer bound to the
  *device* (`SO_BINDTODEVICE`, allowed unprivileged here) so the result is
  attributable. Binding the source address is not enough: with both radios
  on one /24, `ip route get 192.168.50.1 from <wlan0 addr>` still says
  `dev wlan1`. On 2026-09-12 20:31 that made a degraded wlan1 drag wlan0's
  DNS/TCP probes down with it, the watchdog saw "no healthy alternative"
  and did not fail over. The TCP layer connects to the address DNS last
  returned, so a dead resolver is not reported as a dead path. A wedged
  *active* route is a FAIL. Code in `src/binnacle/uplink.py`.
- `poller` — reads the tunnel's own log for a run of `poll failed; backing
  off` or `poll timed out; backing off` (both are the poller backing off;
  measured 2026-09-14, a wedged uplink shows as a run of timeouts ending
  in `poller recovered`; a single timeout is a blip). This is the only
  check that sees what ChatGPT sees.
- `watchdog` — is the loop running and recent, which profile, band and
  level each radio is on, what is below its highest level, and whether a
  route is demoted.

### The workflow (reviewed 2026-09-13 with the user)

Two rules, in this order: **the connector stays reachable through any
single fault**, and **every radio is brought back to its highest level** —
wlan1 on its 5 GHz profile at USB 3 (5000 Mbit/s), wlan0 on its 5 GHz
profile — step by step, never at the cost of the first rule.

`binnacle-watchdog.service` runs `binnacle watchdog run` (30 s cycles).
Each cycle observes every Wi-Fi device NetworkManager manages, not only the
ones with a default route: NM state (connected / connecting / disconnected
/ unavailable), active profile, band, channel width, tx rate, signal, the
USB link speed of the adapter, the default routes and the layered probes,
and NM's own `autoconnect-priority` ranking with a scan for the better
profile's network. From that, per device, a grade (absent, unavailable,
disconnected, connecting, no route, wedged, degraded, healthy) and a level
(band vs the best profile; USB speed vs the best this adapter has shown;
width and rate are reported only — the AP decides them).

The repair ladder, worst first. Every rung is rate-limited, backed off on a
schedule, and its counters persist across a watchdog restart:

1. **Active route wedged** (fails every layer three cycles running) and
   another route healthy: raise its metric so traffic moves within a cycle
   (a *device-level* demotion: every profile bound to the device is raised,
   so whatever NM brings up afterwards still has to pass the probes), then
   re-activate its profile (`nmcli connection up`, one per 5 min; NM 1.52
   has no `device reconnect`), then if it stays dead re-enumerate its USB
   device on the user's schedule — 1 min ×3, 3 min ×3, 5 min ×3, then every
   10 min — alternating `authorized` (sysfs 0/1) and `port_reset`
   (`USBDEVFS_RESET`), both via `sudo -n`. Restore the metrics after three
   healthy cycles. Proven unattended on a real wedge 2026-09-12 21:49–21:54
   (4.5 min on wlan0). With no healthy alternative: repair in place, then the
   same USB schedule.
2. **Standby route wedged**: re-activate it (to the best profile in range).
   A dead lifeline is the "no healthy alternative" case waiting to happen.
3. **Device without a route** (disconnected, connecting for 6 cycles,
   unavailable): re-activate the best profile in range after three cycles;
   the USB adapter gets the USB schedule when it is unavailable or when a
   re-activation did not bring it back (2026-09-12 21:51: the 5 GHz profile
   did not come up after the reset). Nothing in range: wait. It carries
   nothing, so this costs nothing.
4. **USB link below the best speed this adapter has shown** (a USB 3 part
   enumerated at 480 Mbit/s): re-enumerate it — through a demotion when it
   is the active route — 10 min ×3, 1 h ×3, then every 6 h; after six
   failed attempts the lower speed is accepted as the level until the
   adapter shows the higher one again. Level facts are learned, not
   configured: nothing in the repo says "5000".
5. **Lower-priority profile than one in range**: the preference move. NM
   activates the first profile whose network is in its first scan and
   never revisits, so after the 09-12 21:51 reset and again after the
   09-13 20:40 port-reset test wlan1 came back on its 2.4 GHz profile
   (priority 0) with the 5 GHz one (priority 20) in range, and sat there
   for 24 h with every check green. A standby moves at once; the active
   route only through a demotion (traffic first), with the target's metric
   raised too. 10 min ×3 then hourly; a move that leaves the device
   unhealthy for 5 min is undone. The preference is NM's own
   `connection.autoconnect-priority` (wlan1: 5G-USB 20 over 2.4G-USB 0;
   wlan0: 5G 10 over 2.4G 0, set 2026-09-13 on the user's "highest level"
   rule — wlan0's 5 GHz link in the metal case fails more probes than its
   2.4 GHz one, 178/2402 vs 3/290, so it will fall back and be moved up
   again; that is the intended trade). Nothing in the repo names a profile
   or a band.

Reviewed again the same night against every failure case we could name
(the user: "do you really cover every corner?"). What changed:

- **Dead end, not only wedge.** The failover trigger is "no TCP path for
  three cycles" — a route whose gateway pings while nothing beyond it
  connects is as dead for the tunnel as a wedge, so it moves when the
  standby is healthy. In-place resets and USB resets stay reserved for a
  radio that passes *nothing*; a dead end on the only route, or on both,
  is the WAN, and radios are left alone. A standby dead end is repaired
  only while the active route proves the upstream works.
- **Resolver or link.** When the system resolver (192.168.50.1) fails, the
  probe asks 1.1.1.1 over the same device (`dns_fallback`): an answer
  means the DNS server is the problem, silence means the link. The verdict
  stays the system resolver's (that is what the tunnel uses); the
  classification lands in the error text and the issues.
- **A probe that cannot run is no verdict.** SO_BINDTODEVICE refused →
  `ProbeResult.unavailable`: no failover, no reset, a demotion stays put.
- **Absent and driverless adapters.** Devices ever seen are remembered;
  one that vanishes from NetworkManager is an issue ("absent"), and a USB
  node carrying a listed adapter id without a network interface is
  reported as "driver not bound".
- **A wedged standby USB adapter** escalates to the USB schedule when
  re-association does not revive it (it carries nothing).
- **Driver reload for the built-in radio** (`driver_reload_enabled`, off
  in the repo default, **on for this host** in `~/.config/binnacle/config.toml`):
  `modprobe -r <holders> <module> && modprobe <module>` through `sudo -n`
  on the USB schedule, for a wedged or unavailable non-USB radio. Tested
  2026-09-13 22:50 on wlan0: a sysfs unbind/bind of the SDIO function
  left the firmware bus down (`bus is down`, bind returned EIO) and the
  radio gone, and `modprobe -r brcmfmac_cyw brcmfmac; modprobe brcmfmac`
  brought it back in about ten seconds — so the rung reloads the module,
  never touches sysfs bind. `binnacle watchdog reload-driver --dev wlan0
  [--apply]` runs it by hand.
- **The watchdog watches itself.** Each cycle runs in a worker thread
  with `cycle_timeout_s` (180 s); a hung cycle exits the process and
  systemd (Restart=always) starts a fresh one on the persisted state.
- **The two processes between the uplink and ChatGPT.** If the server
  unit is active but `/mcp` stops answering for three cycles, or the
  tunnel's poller has failed for 5 min while the active route has been
  healthy for three cycles, the unit is restarted (one per 15 min). A unit
  the user stopped is never started. The tunnel case is the 2026-09-12
  shape: alive and useless.
- **A profile stuck at metric 900 with no demotion on record** (a lost
  state file) is reported every 10 min as an issue with the nmcli command
  to fix it; the original metric is not known to the loop.
- `doctor` gained a `privileges` check (`sudo -n true`): without it the
  USB and driver-reload rungs fail silently.
- The rfk healer cron (`rtl8812au-rfk-check.sh`) now defers to a watchdog
  demotion instead of racing it.

Third look, later the same night (the user: hardware spec, machine
configuration, every fault, and a journal you can replay):

- **Connected without a default route** (a DHCP offer without a router, a
  deleted route): counted like a down device, re-activated after three
  cycles; a profile with `ipv4.never-default` is left alone.
- **NetworkManager and wpa_supplicant** (system units, `sudo -n systemctl
  restart`): NM inactive/failed, or active but answering nothing for
  three cycles, is restarted — nothing below it can act without it;
  wpa_supplicant inactive while a radio is "unavailable" is restarted.
  Same 15-min rate limit (`system_service_repair`). A hung nmcli now
  returns exit 124 instead of aborting the cycle.
- **Host power and thermal** (`vcgencmd get_throttled`, `measure_temp`):
  under-voltage or throttling *now* is an issue (WARN in doctor); the
  flags and the temperature are in the `inventory_host` journal line. The
  classic cause of a USB adapter going quiet is the supply, and it was
  0x0 on 2026-09-13.
- **Pause switch**: `binnacle watchdog pause [--minutes N]` writes an
  expiring file; the loop keeps observing and logging but takes no action
  (`event=paused ... skipped=...`), `doctor` warns, `resume` ends it. For
  when you rearrange radios or profiles by hand.
- `doctor` checks **lingering** (`loginctl show-user`): without it no user
  unit starts after a reboot until someone logs in. It is on here.

Fourth look (2026-09-13/14, the user: "after three rounds you still find
new bugs, so I'm not confident"): a line-by-line audit of the whole
module, fixes, and fault injection on the live host instead of trust.

What the audit found and fixed:

- A demotion whose `nmcli device reapply` failed after the metric modify
  had landed left the active profile at 900 with no demotion on record
  (a stranded adapter); it is reverted now, and logged as `demote_failed`.
- The failure counter survived a change of role (active ↔ standby), so
  two dead-end cycles as a standby could count towards a failover once
  the device became the active route; the count restarts on a role change.
- An empty NetworkManager device list counted as "NetworkManager not
  answering" (three cycles → restart); responsiveness is now the exit
  code of `nmcli general`, not the device count. NM "not active" also
  needs three cycles: an NM restarting on its own must not be restarted
  again.
- A frozen tunnel process (no log lines at all, as opposed to `poll
  failed` lines) was invisible; the log's last-line age is now a signal
  (`tunnel_stale_after_s`, 300 s; idle it logs a poll every 30-60 s). A
  first draft of that rule read a zero timestamp as "now"; the test
  caught it.
- `cycle_timeout_s` (180 s) could have shot a legitimately slow cycle
  (probe timeouts plus a scan plus a 60 s `nmcli connection up` add up to
  minutes): 600 s now, with a `cycle_slow` line over 30 s.
- Decision notes said "USB reset in -1 s" before any repair was on record.
- **The test suite acted on the host.** At 23:49 on 2026-09-13
  NetworkManager's audit log named the pytest process re-activating both
  real Wi-Fi profiles: three loop tests ran `cycle()` without a fake
  `run`, and the new "connected without a default route" rung (routes
  patched to `[]`, devices real) fired real `nmcli connection up`
  commands on both radios at once. wlan1 then spent five minutes
  re-associating on 5 GHz (`association took too long`), the watchdog
  demoted it and restored it after 153 s of failover, and ChatGPT never
  noticed (0 tunnel poll failures). Two fixes: `tests/conftest.py` wraps
  `subprocess.run` for every test and refuses any mutating command
  (`sudo`, `nmcli connection up/modify`, `device reapply`, `systemctl
  restart`, `modprobe`, `iw scan`, `ip route add/del`), failing the test
  that tried; and the no-route rung itself now needs a *readable* route
  table (a failed `ip route` used to look like every radio losing its
  route at once), waits the longer threshold, touches one device per
  cycle, and reapplies the profile before it re-associates.
- Deploys now rehearse: `binnacle watchdog run --cycles 3 --dry-run
  --state-file <scratch>` runs the whole observe-decide-log path on the
  live host and applies nothing; the unit is restarted only when no
  demotion is in flight (restarting mid-episode resets the transient
  counters and delays the repair — it cost three minutes on 2026-09-13).

Fault injection on the live host (2026-09-14), first round, taught three
more things before the second round could pass:

- The tunnel's log is no liveness signal. A rule that restarted the
  tunnel after 300 s of silence fired on a *healthy* tunnel (its idle
  gaps reach 32 min, measured), and the 15-min rate limit it consumed
  then blocked the restart when the tunnel really was frozen. The signal
  now is the tunnel's own health HTTP server (URL in
  `~/.local/state/tunnel-client/health/binnacle.url`, it changes on every
  restart): not answering for three cycles restarts the unit; log
  silence over 30 min is reported only.
- Freezing the MCP unit's MainPID freezes uvicorn's reloader, not the
  worker that serves port 8000, so nothing was wrong and nothing was
  detected; the test has to freeze the worker (child of the reloader).
- A preference-demoted device that becomes wedged promised "USB reset
  attempt 1 in 0 s" in its decision note while the preference kind never
  escalates; after the fallback re-activation the demotion now becomes a
  wedge and takes the USB schedule like any other. A single degraded
  cycle between healthy ones (one lost ping on wlan0's lossy 5 GHz link)
  no longer logs a transition; it needs two.

Second round (00:44–01:00), with the fixes above:

- MCP worker frozen (SIGSTOP): `/mcp` not answering for three cycles →
  `service_restart binnacle-mcp` at +100 s, back in seconds. **Pass.**
- Tunnel frozen (SIGSTOP): health server not answering for three cycles →
  `service_restart binnacle-tunnel` at +103 s. **Pass.**
- wlan1's data path cut while it was the active route (DHCP still
  passing): wedged detected at +23 s; at the third cycle the standby
  wlan0 had just lost a ping and a DNS reply on its 5 GHz link (TCP
  fine) and the rule "another route must be *healthy*" refused the
  failover; the in-place re-association ran (+2:09), then USB reset
  attempt 1 (+3:42) re-enumerated the adapter, NM tried 5 GHz (three
  `association took too long`) and settled on 2.4 GHz, the data path
  came back when the rule expired (+5:00). ChatGPT saw the connector
  offline for those five minutes: the tunnel logged `poll timed out;
  backing off` every 35 s and `poller recovered` at +6:00. **Two fixes:**
  a failover target now only needs a working TCP path (`usable`, not
  `healthy`: the tunnel needs TCP 443, not a ping), and `poll timed out;
  backing off` counts as a failed poll everywhere (`doctor`, the
  watchdog's tunnel rung, the stability job) — 132 of 186 timeout runs in
  the log end with `poller recovered`, so it was never the idle long poll
  it was documented as. Third injection (01:07): wedged detected at
  +28 s, **demoted at +1:52 with "wlan0 has a TCP path"**, re-association
  +2:06, USB reset attempt 1 at +3:02, restored at +6:44 (demoted 292 s).
  ChatGPT still saw ~6 min offline: the standby wlan0 went wedged itself
  at +2:58 and degraded until +5:00 on its 5 GHz link, exactly while it
  carried the connector. A control experiment right after (the default
  route moved to wlan0 by hand for 150 s with no fault present) showed
  the tunnel's one long-lived TCP connection to OpenAI, bound to wlan1's
  address, keeps working across the route change — no tunnel restart on
  failover is needed; the offline minutes were the lifeline's own.

Also seen tonight and worth knowing: since 23:53 on 2026-09-13 wlan1
cannot complete an association on 5 GHz (`association took too long`
three times per attempt, RTW `rtw_set_802_11_connect` with no `auth
success`), while wlan0 associates on the same 5 GHz AP and wlan1 does on
2.4 GHz; the preference rung retries 5 GHz on its schedule (attempts 1-3
at 00:03, 00:14, 00:25, then hourly) and each attempt costs a few minutes
on the standby. wlan0's own 5 GHz link in the case flaps between healthy
and degraded every few minutes and was the reason the failover was
refused once; if the lifeline should be the reliable band rather than
the fast one, set `Occom_1D36_2.4G` above `Occom_1D36_5G` in
autoconnect-priority — the user's decision.

### The fast path (2026-09-14: "under one minute")

The full cycle's failover needs three 30 s cycles plus their own duration
(a wedged route costs every probe layer's timeout per cycle), and the
tunnel's in-flight poll then hangs on the dead path for up to a minute:
about three minutes offline for ChatGPT in the injections. So a second
thread runs the *fast path*: every 5 s one TCP connect to the upstream's
cached address through the active route (`fast_interval_s`,
`fast_timeout_s` 2 s); after four failures in a row (20 s) it asks the
standbys, in metric order, for a TCP path, and the first that has one
makes it a failover: the same device-level demotion and re-association
the cycle would do, under the same lock (`ACT_LOCK`), logged as
`fast_failure` (each miss), `fast_failover` (the act) or
`fast_failover_blocked` (no standby with a TCP path), `fast_recovered`.
Right after any failover — fast or slow — the tunnel unit is restarted
(`restart_tunnel_on_failover`; a restart is back polling in about a
second, measured), once per 60 s. The fast path never acts while paused
or in dry-run, never on a demoted route, and never before the cycle has
resolved the upstream. The full cycle's failover stays as the backstop.
Probe timeouts went from 3 s to 2 s per layer for the same reason.

Measured on 2026-09-14 with the data-path injection on wlan1 (three
radios): first run, tunnel restarted *after* the 14 s re-association —
demoted at +25 s, poller back at +40 s, no poll timed out. A genuine 5 GHz
wedge at 08:44 in between: fast failover at +47 s (a watchdog restart of
mine mid-event had reset the counter; without it ~+30 s), one poll timed
out, poller back at +50 s. Final run with the restart moved ahead of the
re-association: fast failures at +4/+11/+18/+25 s, **demoted and tunnel
restarted at +25 s, a real ChatGPT call forwarded at +31 s, no poll timed
out** — the connector's outage on a wedge of the active route is now
about 25 s. Lesson recorded from the 08:44 event: never restart the
watchdog while a route is failing (the deploy check now waits for every
grade healthy and no fast failure in the last minute, besides "no
demotion in flight").

### Fifth look (2026-09-14 night: "is anything missing?")

Evidence first: the afternoon's journal (six fast failovers in three hours,
ChatGPT unaware) and one live measurement -- `ss -tnp` showed the tunnel's
only connection to OpenAI bound to **wlan2's address** while wlan1 had
carried the default route for 15 minutes (and later, bound to wlan0's).
Five gaps, all fixed and tested:

- **Tunnel socket affinity.** The tunnel's long-lived connection is bound
  to the address of whichever route was active when it started, and the
  kernel keeps routing it (`ip route get ... from <wlan2 addr>` says
  `dev wlan1`; replies follow the router's ARP entry). So after every
  restore the connector kept riding the standby, and a wedge of that
  standby would have stalled the poller for its 35 s deadline
  (`poll-timeout` 30 s + 5 s guardrail) with no rule to notice for 5 min.
  Each cycle now reads the tunnel process's established `:443` sockets
  (`ss -tnpH`, MainPID from systemd) and maps the local address to a
  device (`tunnel_via=` on the cycle line). Off the active route and
  without a TCP path: restart at once (`failover_restart_floor_s`, 15 s,
  between such restarts). Off it but usable: after
  `tunnel_affinity_cycles` (3) cycles with the active route healthy, at a
  quiet moment (no command forwarded for `tunnel_quiet_s`, 30 s, read
  from the tunnel log), one per minute -- waiting those cycles means a
  route that wedges again right after its restore costs no restart at
  all. `after_failover` restarts on the same test (skipped as
  `tunnel_kept` when the socket is already on the new active route)
  instead of a 60 s clock, so a second failover 30 s after the first
  still moves the socket.
- **Flap damping.** 15:51 wedge -> restored 15:53:46 -> wedged again 42 s
  later -> restored 15:56:09 -> wedged 40 s later: each bounce a
  demotion, a tunnel restart and a 20 s detection window, while wlan2 was
  healthy all day. A restore now needs the fast path to have seen the
  demoted route pass for `restore_fast_quiet_s` (90 s; the fast thread
  probes demoted routes too, `fast_failure ... role=demoted`), and the
  healthy-cycle count doubles with every wedge demotion of that device
  inside `flap_window_s` (an hour): 3, 6, 12, 24, capped at
  `restore_hold_max_cycles` (40). `wedge_times` persists; the decision
  note says "hold-down 6: 2 wedges in the last 60 min".
- **Escalation per episode.** A second wedge minutes after the first went
  straight to a USB reset (15:39:16, 15:54:34, 09:29:13): the fast path's
  re-association was blocked by the 5-min `min_reset_interval_s`, the
  demoted-and-wedged branch had no re-association of its own, and the
  reason line said "still unhealthy after re-association" with none made.
  Rate limits are per episode now (a demotion, or a failure streak that
  began after the last re-association): the first re-association of a
  new episode needs only `reset_floor_s` (60 s), repeats within an
  episode the 5 min; a demoted wedged route re-associates before the USB
  schedule, and every USB wait counts from a repair *in this episode*.
  A demoted wedged route with no re-association on record used to sit
  there forever; it is re-associated now.
- **The lock.** `ACT_LOCK` covered every action, including a `nmcli
  connection up` that blocks up to 60 s, so the fast path could not fail
  the active route over while the cycle was re-activating a standby. The
  lock now covers the decision, the metric changes and the tunnel move;
  re-associations, USB resets and driver reloads run outside it, marked
  `repair_in_flight` (every rung leaves that device alone meanwhile) and
  re-checked first (`action_skipped` when the device became the active
  route since the decision).
- **The fast thread is supervised** (`supervise_fast_path` after each
  cycle): heartbeat `fast_last` in the state file and
  `fast=<failures>/<threshold>@<age>s` on the cycle line; a dead thread
  is started again (`fast_path_restarted`), a heartbeat older than 30 s
  logs `fast_path_stalled`, older than the cycle timeout exits the process
  (`fast_path_hung`); `doctor` warns on a stale heartbeat.
- **Tunnel restarts are verified**: `restart_tunnel` waits up to
  `tunnel_ready_timeout_s` (10 s) for the health URL file to be rewritten
  and answer, `ready_ms=` on the `service_restart` line, `tunnel_not_ready`
  otherwise. All three restart paths (failover, affinity, the health/poll
  rung) go through it.
- **Journal**: `trigger=fast|cycle` on demotions and re-associations (the
  cycle's `before=` grade is stale when the fast path acts), `tunnel_via=`
  and `fast=` on the cycle line, and issue lines are flap-damped: past
  `flap_log_limit` (3) changes per device inside a snapshot interval, one
  `uplink_issue_flapping ... changes=N current=...` line per interval
  stands for them (wlan0 wrote 56 in three hours). `history` reads the
  tunnel log for the same window and prints what ChatGPT saw: failed or
  timed-out polls in total and per failover, plus fast failovers, blocked
  ones and tunnel restarts by reason.

Not done, on purpose: a windowed fast-path rule (4 of the last 6 probes)
-- the user said no need for more speed; `tunnel_restart_after_s` stays
300 s (the affinity rules cover the socket case); a dead USB host
controller still needs a human and a reboot.

Deployed 2026-09-14 22:20:45 at a quiet moment (the deploy check: no
demotion in flight, every grade healthy, no fast failure in the last
minute). First live result within a minute: the tunnel's connection had
sat on wlan2's address since the 22:16 failover; the new loop logged
"connection on wlan2 (usable), active wlan1; waiting 1/3 cycles", then
2/3, and at cycle 3 (22:21:49, quiet for 55 s) restarted the tunnel --
`ready_ms=538` -- after which `ss` showed the connection bound to wlan1's
address and no poll failed.

Also seen that evening, worth knowing: both USB adapters lost their link
at the same moment twice (09:19:57 and 21:44:01, each time while wlan1
was re-associating or being reset), wlan0 carried the connector, and
ChatGPT saw three failed polls each time. Different bands, same host: the
common factor is the USB side (bus or supply), not the AP.

### The journal as the record

The watchdog's journal is written so a window of it, however short, can
be replayed without the host (`journalctl --user -u binnacle-watchdog`,
every line `event=<name> key=value ...`; `cycle=<n>` on every line
correlates them, and `n` persists across restarts):

- `watchdog_start`: versions (binnacle, Python, kernel, NM), the state
  file, the counters carried over, and the whole effective policy as JSON.
- `inventory` per device (at start and every 10 min, logged when it
  changes): bus and USB id, node, link speed, driver, module and the
  parameters named in `inventory_params` (here `rtw_switch_usb_mode`),
  every profile bound to it with priority, metric and autoconnect.
  `inventory_host`: throttle flags, temperature, resolver, radio switch.
- `uplink_probe` per route per cycle with the layer timings
  (`gateway=ok(3ms) dns=ok(2ms) tcp=ok(20ms)`) and `uplink_probe_error`
  with the reason (including the resolver-vs-link classification).
- `transition` when a device's grade changes (healthy, degraded,
  dead_end, wedged, no_route, connecting, disconnected, unavailable,
  absent, unknown), with the previous grade, how long it lasted and the
  probe detail; WARNING when it gets worse, INFO when it recovers.
- `decision` when a rung looked at a device and declined, with the reason
  (below threshold, rate-limited with seconds left, no healthy
  alternative, target out of range, demotion in flight, WAN suspected,
  waiting for a schedule); logged on change and re-stated every 10 min,
  so "why did nothing happen" is answerable.
- the actions: `uplink_demoted`, `uplink_reset`, `uplink_reapply`,
  `uplink_usb_reset`, `uplink_driver_reload`, `uplink_restored`,
  `uplink_radio_on`, `service_restart`, `system_service_restart`, each
  with `cycle=`, the device's grade before (`before=`), the reason, the
  attempt number, the method, the outcome, the command's `duration_ms`
  and the next wait; `demote_failed` / `restore_failed` /
  `actions_failed` when an apply did not go through; `paused` /
  `dry_run` with the actions that were skipped; `pause_started` /
  `pause_ended`; `watchdog_stop` with the signal on a clean shutdown;
  `routes_unreadable` when `ip route` fails.
- `uplink_issue` / `uplink_issue_cleared` for everything below the
  highest level (`uplink_issue_flapping` once per snapshot interval when
  a device's issue keeps changing); `cycle` every cycle (duration, active
  route, routes with metric, source and gateway, every device's grade,
  demotions, issue count, the actions planned and the actions done, the
  two services, `tunnel_via=` the device the tunnel's connection sits on,
  `fast=` the fast path's failure count and heartbeat age, healthy-uplink
  cycles, paused / dry-run flags); `snapshot` per device and
  `snapshot_state` every 10 min (grade and since when, state, probe,
  pending preference, all counters, demotions as JSON, issues as JSON).
- the fast path and the tunnel: `fast_failure` (each miss; `role=demoted`
  for a demoted route it keeps probing), `fast_recovered`,
  `fast_failover` / `fast_failover_blocked`, `tunnel_kept` (a failover
  whose socket already sat on the new route), `service_restart_deferred`
  (inside the floor), `tunnel_not_ready`, `action_skipped` (a repair
  whose device became the active route meanwhile), `fast_path_stalled` /
  `fast_path_restarted` / `fast_path_hung`.

`binnacle watchdog history --since="-1 day" [--verbose]` reconstructs the
timeline (starts, inventory changes, transitions, actions, issues,
pauses; `--verbose` adds every declined decision and probe error) and
sums it up: cycles and their duration, actions by kind, failovers and
restores (how many by the fast path, how many blocked), tunnel restarts
by reason, minutes per grade per device -- and, from the tunnel's own log
over the same window, what ChatGPT saw: polls failed or timed out in
total and per failover. Code in `src/binnacle/watchlog.py`.

Known gaps, on purpose: a hardware rfkill switch, an unplugged adapter
and an unbound driver are reported, not repaired; channel width and rate
are the AP's decision; IPv6 is not probed (this network has no IPv6
default route).

Invariants that keep rule one: a link-down action on the active route only
after a demotion, and a demotion only when another route is healthy *this
cycle*; one voluntary action (level or preference) per cycle and none
while any demotion is in flight; the last healthy route is never demoted;
a device with no route is never USB-reset on top of a reset still settling
(the schedule); every voluntary change is undone or restored by the loop
itself. The adapter is never removed. A scan on a connected device (a brief
off-channel gap) happens only for a device off its best profile, every
5 min; NM's own rescan on the built-in radio missed the 2.4 GHz network
twice while `iw dev wlan0 scan` saw it, so a rescan also asks the driver.
One repair sits above the ladder: if NM's Wi-Fi radio switch is off (a
software rfkill makes every device "unavailable"), the loop runs `nmcli
radio wifi on`, once per 5 min; a hardware switch is reported, not touched.

Route changes go through NetworkManager (`connection modify
ipv4.route-metric`, then `device reapply`), not `ip route`: NM re-applies
its own routes on every DHCP renew — measured every ~11 minutes here — and
reverts direct edits.

Proven live 2026-09-13: wlan1 moved 2.4G-USB → 5G-USB at 21:56:37 through a
preference demotion and was restored at 21:58:08 (91 s, traffic on wlan0);
wlan0 moved between its profiles as a standby at once when the target SSID
appeared in its scan list. The USB-level and down-device rungs are covered
by `tests/system/test_watchdog.py` (the fake NetworkManager `nm_fake`); they have
not yet fired on real hardware.

Tools: `binnacle watchdog status [--rescan]` probes both routes and prints
every device's state, profile, band, width, rate, signal, USB link and
pending preference, plus what is below its highest level; `binnacle
watchdog usb-reset --dev wlan1 [--method port_reset] [--apply]` runs one
USB reset by hand; `doctor` shows the levels, warns per issue, and shows a
demotion with its kind. `watchdog.evaluate` is pure, so the whole policy is
tested without a network (`tests/system/test_watchdog.py`, `tests/system/test_uplink.py`).
Tunables live under `[watchdog]` in the config (`WatchdogSettings`).

The USB adapter is deliberately preferred (route-metric 100 vs the built-in
radio's 600) and stays that way — the user needs it. The watchdog is what
makes that preference safe.

### Three radios since 2026-09-14

The user added a second USB adapter for reliability: an **RTL8188EUS**
(`0bda:8179`, in-kernel `rtl8xxxu`, 1T1R, **2.4 GHz only**, USB 2 at
480 Mbit/s, bus 1 port 2) as `wlan2`. Its profile `Occom_1D36_2.4G-USB2`
is a clone of the wlan1 2.4 GHz profile bound to `wlan2` (`autoconnect-retries
0` = forever) at **route metric 300**, so the failover order is wlan1 (100)
→ wlan2 (300) → wlan0 (600): the kernel moves traffic to the next metric
by itself once a demotion raises the wedged route to 900. It has one
profile, so the preference rung never touches it; the USB rungs apply
because its id is in `usb_reset_ids` in `~/.config/binnacle/config.toml`
(host-specific, not the repo default); its link level is learned as 480.
Measured at install: -48 dBm, 72 Mbit/s (HT20 MCS7). The demotion reason
names the next route by metric, not by name.

Proven the same morning with the data-path injection on wlan1: wedge at
08:14:37, detected +61 s (a scan had stretched that cycle to 82 s — scans
now wait while the active route is unhealthy), **demoted to wlan2 at
+2:18**, re-association +2:32, USB reset attempt 1 at +3:52 after which
wlan1 associated on 5 GHz again, restored at +5:26 (demoted 188 s). The
tunnel timed out four polls (08:15:36–08:17:22) and recovered at 08:17:53:
ChatGPT saw about three minutes offline, then real calls went through on
wlan2 while wlan1 was still demoted. The remaining window is the detection
threshold (three 30 s cycles) plus the cycle's own duration.

### USB 3 mode, measured throughput, and the stability job

The adapter runs in USB 3 mode on purpose: `/etc/modprobe.d/8812au.conf` sets
`rtw_switch_usb_mode=1`, which makes the driver switch the chip to SuperSpeed
at probe (one forced re-enumeration; mode 0 leaves it in its power-on USB 2
link). The built-in radio is inside a metal case and links at ~24 Mbit/s, so
wlan1 is the only real uplink and wlan0 is a lifeline, not a substitute.

Measured 2026-09-12 (Cloudflare WAN download over wlan1): single stream 152 /
198 / 243 Mbit/s in USB 2 mode and 190 / 232 / 201 Mbit/s in USB 3 mode — no
difference; four parallel streams reach ~303 Mbit/s. The ~300 Mbit/s ceiling
is the WAN or air path, not USB. The Wi-Fi PHY rate of 867 Mbit/s is the
chip's hardware maximum (VHT80, 2x2, MCS9; no 160 MHz), so that reading is
correct. USB 3 only matters for LAN-local transfers above ~280 Mbit/s.

The `maintain-rtl8812au` skill's baseline expects the mode recorded as
`BASELINE_USB_MODE` in its `references/baseline.env` (0 until promoted), so
its weekly audit (`rtl8812au-check.sh`, Friday 03:00 via `cron-report`)
reports two FAILs for mode 1 until the mode is promoted. Do not "repair" the
live config back to mode 0 without asking.

Promotion is automatic, on evidence: `~/.local/bin/rtl8812au-stability.sh`
(cron daily 03:30, weekly digest Friday 03:20, both via `cron-report`) takes
one sample a day — live mode, USB link speed, driver bound, associated,
on 5 GHz (added 09-13: a day on the 2.4 GHz profile says nothing about the
configuration being promoted, and all three 09-12 wedges were on 5 GHz),
primary route, `RTW: ERROR` lines and USB fault events since the previous
sample, watchdog demotions, and `poll failed` lines in the tunnel log (3 or
more break the streak: that is the signal that ChatGPT lost the connector,
and an RF degradation on 2026-09-12 20:31 did exactly that with a clean
kernel log) — and after 7 consecutive clean samples spanning
6+ days runs `maintain.py promote-usb-mode --apply` in the skill. That
rewrites `baseline.env` and `assets/8812au.conf` together, gated on the
skill's own test suite (both files are restored if it fails). The job is
silent while the streak grows and mails only when the streak breaks, when it
promotes, or when it cannot sample; its ledger is
`~/.local/state/rtl8812au/stability.log`. `binnacle doctor` surfaces the last
sample as the `driver` check and skips it on a host without the job.

## Logging

The server's journal is the record a quality review runs on: one
`tool_call` and one `tool_result` line per call sharing a `call=` id, with
the tunnel's `X-Request-Id` as `turn=` (the `wfr_<turn>/<call>` id the
tunnel log carries), duration, `is_error` with the error class, the payload
size the model receives (`structured_bytes`, `est_tokens` = chars/4), and
the truncation facts lifted from each tool's structured result;
`job_start` carries the `call=` that spawned it. `docs/logging.md` (added
2026-09-13) holds the inventory, the gaps it closed and live examples;
`binnacle stats` and `scripts/usage_breakdown.py` read both the old and
the new shapes.

`scripts/mcp_client.py` usage (talks to the running server on :8000, no ChatGPT round
trip): `scripts/mcp_client.py` (list) / `... ping` /
`... read_file '{"path":"~/Projects/binnacle/server.py","end_line":20}'`.
Per-tool unit tests live in `tests/unit/tools/test_<name>.py`; broader
coverage is grouped by responsibility under `tests/{unit,integration,contracts,system,scripts}`.
See `docs/testing.md` for placement rules and test levels. Run
`.venv/bin/python -m pytest tests/ -q` (or just the changed tool's module)
before the loop. Tool specs: `docs/agent-toolset-design.md` +
`docs/tools/<name>.md`.
Three cross-cutting modules sit beside them: `tests/unit/core/test_properties.py`
(hypothesis invariants for the path guard, the glob matcher — differential
against `PurePath.full_match` on 3.13+ — the output clipper and the text
decoder), `tests/contracts/test_protocol.py` (the tool surface as a client sees it
through fastmcp's in-memory `Client`: annotations, output schemas, end-to-end
calls) and `tests/integration/test_auth_asgi.py` (bearer auth at the HTTP edge through
httpx2's `ASGITransport`; the app lifespan must be open or the session
manager is not initialized). Branch coverage is about 88.2% (2026-09-19, 613 tests); the gate is `fail_under = 86.9` in `[tool.coverage.report]` and
`--cov-fail-under=86.9` in tox's test command (the exact floor was 86.99,
so an integer 87 failed on rounding — ratchet it up, never down). A plain
`pytest` stays uncovered and fast. mutmut is configured in `[tool.mutmut]`
and runs on demand per module: `mutmut run '*textio*'`, then `mutmut
results`; never as a hook. Two things it needs on this repo: `source_paths
= ["src"]` (mutmut runs the suite from inside `./mutants` and puts
`mutants/<source_path>` first on `sys.path`; with the package directory as
the entry, `import binnacle` still hit the editable install and 24/24
mutants "survived" untested on 2026-09-13), and `also_copy` for the skill
references `tests/contracts/test_descriptions.py` reads by repo-relative path. Budget: the
25-statement `textio.py` took over 30 minutes on the Pi; run one module at
a time, in the background, never the whole tree.

Pick the path by what changed:

- Fast loop — tool body / logic only, with signature, description, and
  annotations unchanged: edit → save → `.venv/bin/python scripts/mcp_client.py`. Done.
  No refresh, no browser needed: ChatGPT's cached schema is still valid and every
  `tools/call` already runs the live server code.

- Full loop — tool surface changed (add / remove / rename a tool, or change its
  params, description, or annotations):
  1. edit → save (auto-reloads).
  2. `.venv/bin/python scripts/mcp_client.py` — confirms the new tool loaded and works.
     Run this BEFORE the refresh: it gates that the server actually reloaded
     before ChatGPT re-reads the list (and a syntax error surfaces here as a
     connection failure, so a bad build never reaches ChatGPT).
  3. `chatgpt-refresh "Raspberry Pi MCP"` — syncs ChatGPT's cached schema to the
     server (name is a case-insensitive substring, so `chatgpt-refresh raspberry`
     also works).
  4. Test in the SAME chat. This is the only step that checks the ChatGPT
     side: semantic discovery of the new tool, the READ/write labels, and
     end-to-end through the tunnel. `chatgpt-send --chat <id> "..."` does it
     from the terminal (headed Chrome via Playwright; see the skill's "Full
     pass test"); the standing test chat is
     `https://chatgpt.com/c/6a9827ce-c40c-83ec-91b4-f1f4e7cfd53c`. Put a nonce
     in the command and match it in the journal and the reply. (A brand-new
     chat re-syncs on its own with no refresh, but clutters the chat list —
     prefer refresh + existing chat.)

When a test DOES need a fresh chat, record its id as soon as it exists — the
browser tab shows it as `https://chatgpt.com/c/<id>` — then clean up by id:

    chatgpt-chats --track <that url> --note "what this test was"
    chatgpt-chats --tracked            # review (dry run)
    chatgpt-chats --tracked --delete   # backs each up, deletes, clears the ledger

Tracking by id is exact, so cleanup can never touch a real conversation. Nothing
in a chat's metadata marks it as a test, and deletion is irreversible, so never
clean up by guessing at titles; `chatgpt-chats --match` exists only for chats
that were never tracked, and stays a dry run until `--delete`.

If a chat occasionally shows a stale tool list, that is a ChatGPT snapshot
glitch, not the server: resend the message or run the refresh again.

## Refreshing the ChatGPT tool list (agent does this — no user clicks)

ChatGPT caches the connector's tool schema. After adding/removing/renaming a
tool or changing its signature/description/annotations, refresh so a running
chat picks it up (a brand-new chat re-syncs on its own, but that clutters the
chat list).

One terminal command, no browser:

    chatgpt-refresh "Raspberry Pi MCP"   # prints "Refreshed Raspberry Pi MCP. Tools now: ..."

`chatgpt-refresh` is a shared tool at `~/.local/bin/chatgpt-refresh`, reused by
every ChatGPT MCP project. It is fully automatic — it discovers your connectors
live and resolves the name to its link id itself (nothing to register); run
`chatgpt-refresh --list` to see them. It reuses the browser's logged-in ChatGPT
session on this Pi: it reads the chatgpt.com cookies from the local
Chromium/Chrome cookie DB (decrypting with the GNOME-keyring key), mints a
short-lived access token via /api/auth/session, lists connectors, then POSTs the
connector-refresh endpoint. Nothing is written to disk; the durable credential
stays in the browser's cookie/keyring store. The session cookie lasts ~months;
when it finally expires, just re-log-in to ChatGPT in the browser. Must run as the
desktop user (needs the session D-Bus + keyring). Run this automatically after
changing the server's tool set; report the list.

There is no public OpenAI API for this and no service-account path — the
refresh always rides the user's ChatGPT web session; the tool just drives that
session from the terminal instead of the browser UI.

## Tool annotations

Declare hints so ChatGPT distinguishes reads from writes:
`readOnlyHint: True` on read-only tools (currently `ping`, `read_file`);
`destructiveHint: True` on write tools as they land per
`docs/agent-toolset-design.md` §7. These surface as READ vs write/destructive
in the connector UI and gate the per-action permission prompts.

## Standing test rig — do not clean up

The three local CLI agents are registered against this server **on purpose**,
so capability testing needs no setup:

| Agent | Registration |
| ----- | ------------ |
| Claude Code | `binnacle` -> `http://127.0.0.1:8000/mcp`, `Authorization` header |
| Codex | `binnacle` -> same URL, bearer token from `BINNACLE_TOKEN` (exported in `~/.bashrc`) |
| GitHub Copilot CLI | `binnacle` in `~/.copilot/mcp-config.json` |

The skill's testing guidance says to remove client registrations after a probe
run. That applies to throwaway registrations (`conformance-probe`, `res-test`,
`era-*`), **not** to these three.

The server deliberately exposes **no prompt**. Prompt support was measured
across all four hosts and only Claude Code has it, so a prompt would be dead
weight here; the evidence and a recipe for re-testing live in the skill's
`references/prompt-support.md`.
