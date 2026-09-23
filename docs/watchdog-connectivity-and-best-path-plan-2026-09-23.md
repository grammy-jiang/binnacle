# Watchdog connectivity and best-path convergence plan

- Status: design plan, reviewed and corrected against the journal on the
  evening of 2026-09-23 (section 0); Phases 0-3 implemented and deployed the
  same night
- Date: 2026-09-23
- Scope: Raspberry Pi host-specific Binnacle watchdog companion

## 0. Evidence and corrections (review of 2026-09-23)

The first draft was checked claim by claim against the watchdog journal,
`binnacle-watchdog history`, the state file, NetworkManager and sysfs before
anything was implemented. What the record shows:

| When | What happened | Cost |
| --- | --- | --- |
| 2026-09-15 12:24 to 2026-09-16 about 14:38, three boots and one mid-boot rename | wlan1 and wlan2 swapped. The RTL8188EUS held wlan1 and inherited the RTL8812AU's learned best of 5000 Mbit/s; on 09-16 it held wlan2, which had learned 5000 the day before. | 12 USB resets of a USB 2-only part (6 as wlan1, 6 as wlan2). With interface-name-bound profiles the 2.4 GHz-only adapter also held the metric-100 profiles, then sat disconnected from 13:48 because its preferred profile was 5 GHz. |
| 2026-09-23 10:15 to 12:47 | Reboot in `rtw_switch_usb_mode=0`. The RTL8812AU enumerated at 480 against a learned 5000. | 6 demotions of a healthy primary, about 100 s each; 6 USB resets; 4 tunnel restarts; wlan2 wedged under a minute after one reset. |
| 2026-09-23 20:12 to 20:50 | Real wedge. Fast failover at +20 s; a USB reset brought wlan1 back on 2.4 GHz; restore at 20:16:39; preference demotion 31 s later, and three more. | wlan1 demoted 857 s in total; three of four 5 GHz activations failed after 60 s. |

| Since 2026-09-12 | Wedged | Preference | USB speed |
| --- | --- | --- | --- |
| Demotions | 95 | 50 | 12 |
| USB resets | 62 | 0 | 18 |
| USB speed resets that raised the link | | | 0 of 18 |

Facts that changed the plan:

- **The route ranking is already physical.** Since 2026-09-16 the metrics
  100, 300 and 600 sit on profiles bound by permanent MAC for both USB
  adapters. The interface-name residue is in the watchdog's state file, not
  in NetworkManager. Section 7 no longer proposes a capacity ranking or
  watchdog-owned metrics.
- **Permanent MACs** (`ethtool -P`, `ip -o link`): RTL8812AU
  `00:0f:00:73:77:7f`, RTL8188EUS `48:8a:d2:05:1a:14`, built-in
  `2c:cf:67:c6:73:14`. Both USB serials are generic (`123456`,
  `00E04C0001`) and identify nothing.
- **The USB target follows the driver's mode**, not a fixed number in the
  config (section 5).
- **"Driver not bound" and "absent" have never occurred on their own**: one
  driver-not-bound line (2026-09-18) and five absent lines, all during the
  user's own module reloads and hardware work (sections 9.3, 9.4).
- **Rule one held all day on 2026-09-23**: five failed tunnel polls, none
  per failover. The cost of the two bugs is churn and voluntary demotions
  of a healthy primary, not outage.
- **The preference rung is a third of all demotions** and each failed
  attempt blocks the cycle thread for 60 s (longest cycle that day: 72 s).
  Section 9.1 bounds the normalization; the schedule keeps the retries.

## 1. Intent

The watchdog has four ordered responsibilities:

1. **Keep the Raspberry Pi online.** If at least one local uplink and the
   upstream Internet are usable, the watchdog must preserve a usable path and
   must not cause a self-inflicted total outage while repairing another path.
2. **Use the highest-capacity validated Wi-Fi path available now.** A slower
   adapter is a temporary fallback, not a permanent choice. When a faster path
   becomes healthy again, the watchdog must safely converge back to it.
3. **Return every recoverable adapter to its desired operating state.** This
   includes physical presence, driver/netdev, USB operating policy, Wi-Fi
   profile/band, IP/default route, data path, route role, and tunnel affinity.
4. **Leave enough evidence to reconstruct the full event later.** A later
   review must be able to answer what failed, what was still usable, why a path
   was selected, what the watchdog tried, what each action changed, how long
   recovery took, and what final state was reached.

The first responsibility always wins. Performance optimization must never
sacrifice the last working path.

## 2. Guarantee boundary

"Always online" is an operational invariant, not a claim that software can
create connectivity when none physically exists.

The watchdog must guarantee the following **when at least one end-to-end path
is physically available**:

- never intentionally take down the last validated usable uplink;
- fail over from an unusable active path to the best validated alternative as
  quickly as the failure thresholds allow;
- continue repairing failed standbys so redundancy is restored;
- automatically re-admit a recovered higher-capacity path and promote it once
  it proves healthy;
- avoid simultaneous disruptive repair of multiple radios;
- avoid treating a common WAN/AP failure as multiple independent adapter
  failures where evidence allows that distinction.

The watchdog cannot guarantee Internet reachability when all radios are
physically absent, the AP is unavailable to every radio, the router/WAN is
down, or the upstream Internet is unreachable. In those cases it must preserve
local link state where useful, avoid destructive churn, record the common-mode
failure clearly, and recover automatically when a usable path returns.

## 3. Desired steady state

The watchdog is a convergence controller. A device is not "fully recovered"
merely because it can pass one packet again.

For each physical adapter, the desired state is:

1. physical device present;
2. correct driver bound and network interface present;
3. USB operating policy satisfied, where configured;
4. NetworkManager-managed and associated;
5. highest-capacity preferred profile/band available to that physical device;
6. gateway, DNS, and upstream TCP path healthy;
7. route role consistent with the current global path ranking;
8. no stale demotion/quarantine/repair state;
9. tunnel connection on the active route.

A recovered adapter should remain quarantined or demoted until the relevant
normalization steps are complete when another healthy path is carrying
traffic. This prevents a `restore -> immediately demote again` cycle.

## 4. Physical identity, not wlanX, is the durable anchor

Interface names are runtime handles only. They are not stable identities on
this host; the USB adapters have changed `wlan1`/`wlan2` assignment across
boots.

The canonical USB device key should use stable physical identity:

```text
usb:<vid:pid>@<permanent-mac>
```

Current examples:

```text
usb:0bda:8812@00:0f:00:73:77:7f   # RTL8812AU
usb:0bda:8179@48:8a:d2:05:1a:14   # RTL8188EU
```

Identity source priority:

1. USB VID:PID + permanent MAC (`ip -o link show dev <ifname>`: `permaddr`
   when NetworkManager has randomized the address of a disconnected radio
   for scanning, else the address itself);
2. USB VID:PID + stable USB serial if permanent MAC is unavailable -- moot
   on this host, where both serials are generic strings;
3. no stable identity -> observe and report, but do not apply historical
   performance state to that device; the state under that name stays
   name-keyed, as today.

Without a network interface there is no MAC to read: a netdev-less USB
device is identified by VID:PID plus USB path only (section 9.3).

NetworkManager already binds the three USB Wi-Fi profiles on this host by MAC,
not interface name. The watchdog should follow the same identity model.

All durable device-specific recovery state should ultimately be keyed by
physical identity, including:

- USB capability/target/repair state;
- reset and USB-reset history;
- preference retry history;
- wedge/flap history;
- persistent demotion/quarantine metadata;
- last known interface name and USB node for diagnostics only.

A change such as `RTL8812AU: wlan1 -> wlan2` should produce an identity mapping
transition, not a new device and not state inheritance by whatever device now
owns `wlan1`.

## 5. Separate capability, policy target, and repair state

The current `usb_best_speed` combines three different concepts. Replace that
model with independent state:

```text
observed_max_mbps       # diagnostic capability history
learned_target_mbps     # actionable target only in learned mode
configured_target_mbps  # actionable target in fixed mode
repair_attempts
last_repair
repair_exhausted
policy_fingerprint
```

Per physical adapter, USB link policy supports:

- `fixed`: an explicit desired speed;
- `learned`: the default for an adapter without a rule -- the best speed the
  adapter has shown, keyed by physical identity, relearned when the module
  parameters change;
- `observe`: record speed/capability but never perform a speed-driven reset;
- `param`: the target follows a kernel module parameter the watchdog already
  records in its inventory line; a parameter value not listed means observe.

Corrected 2026-09-23. For the RTL8812AU, `rtw_switch_usb_mode=1` means the
driver forces the chip to SuperSpeed at probe, so 5000 Mbit/s is the expected
level and a 480 enumeration is a fault to repair; `rtw_switch_usb_mode=0`
means the driver leaves the chip at whatever it enumerated, so there is no
expectation and the mode is observe. This replaces the first draft's
`fixed 480` for the RTL8812AU: a fixed 480 duplicates what the driver already
states, and if the user flips `/etc/modprobe.d/8812au.conf` back to mode 1
and forgets `config.toml`, a 480 enumeration reads as "target satisfied" and
the USB 3 repair is silently lost. The parameter is the single source of
truth; the config names the parameter and what its values promise.

For this host the initial policy is:

```text
RTL8812AU  param rtw_switch_usb_mode: 1 -> 5000, any other value -> observe
RTL8188EU  fixed 480 Mbit/s (its hardware ceiling: the rung can only fire
           on a 12 Mbit/s full-speed enumeration, which is a genuine fault)
```

Evidence for the change: since 2026-09-12 the learned-level rung made 18 USB
resets, 12 of them on the USB 2-only RTL8188EUS (a level inherited through
the name swaps of 09-15 and 09-16) and 6 on the RTL8812AU in deliberate
mode 0 (2026-09-23), and not one raised a link.

A target is a **minimum required operating level for automatic repair**, not
an instruction to destructively downgrade a healthy link that happens to
negotiate above it.

Therefore:

- `actual < fixed target`: repair when safe;
- `actual == fixed target`: target satisfied;
- `actual > fixed target`: keep the healthy path, log policy drift, do not
  reset merely to force a lower link speed.

Observed maximum remains useful evidence even when it is not the desired
operating point.

## 6. Connectivity grades and path eligibility

Path selection is always two-stage: **eligibility first, performance second**.

Suggested eligibility classes, from best to worst:

1. `healthy`: gateway, DNS, and upstream TCP all pass;
2. `usable-degraded`: TCP path works but a non-fatal layer is degraded;
3. `recovering/quarantined`: path may work but has not completed its recovery
   hold or desired-state normalization;
4. `dead_end/wedged/down/absent`: not eligible to carry normal traffic.

A lower-capacity `healthy` path beats a higher-capacity `wedged` path every
single time. Connectivity is not part of the performance score; it is the gate
that decides whether a path is allowed into the ranking at all.

## 7. Path selection: health first, configured order second

Corrected 2026-09-23. The first draft ranked eligible paths by a capacity
estimate and made route metrics an output of that ranking. That is dropped.
On this hardware the capacity order never crosses: RTL8812AU (2x2 VHT80),
then RTL8188EUS (1T1R HT20, 72 Mbit/s ceiling), then the built-in radio,
which the user ranks last on purpose because its in-case link is lossy (57
minutes not healthy on 2026-09-23 as a standby). A computed ranking cannot
produce a better answer than the configured one, only a wrong one. Its
inputs are also not trustworthy: `iw` reports the built-in radio at 24 Mbit/s
and the RTL8188EUS at 48 Mbit/s while idle, and the vendor RTL8812AU driver
exposes no rx rate. The watchdog measures no throughput, so there is no
history to validate a margin against.

The rule that stays:

1. **Eligibility first**: only `healthy` and `usable-degraded` paths may
   carry traffic; a lower-capacity healthy path beats a higher-capacity
   wedged one every time (section 6).
2. **Configured order second**: among eligible paths the order is the
   user's, expressed once, in NetworkManager, as the route metric of each
   profile: RTL8812AU profiles 100, RTL8188EUS profile 300, built-in 600.
   Since 2026-09-16 the USB profiles are bound by permanent MAC, so this
   order already follows the physical adapter, not `wlanX`. The interface
   name residue is in the watchdog's state file (section 11), not in the
   ranking.
3. **Rates and capacity are reported, never used to rank**: PHY rate, width,
   signal and USB link speed stay in `status`, the inventory line and the
   snapshots as evidence.

Do **not** run continuous Internet speed tests as part of the watchdog.

### 7.1 Ranking rule

Among eligible paths:

1. prefer `healthy` over `usable-degraded`;
2. within the same health class, follow the configured metric order;
3. keep the current active path on a change of health class that lasts
   less than the failure threshold (no churn on one lost ping).

The kernel already implements rule 2: a demotion raises the failed route to
900 and traffic moves to the next configured metric by itself. The fast path
picks its failover target the same way: standbys in metric order, the first
with a TCP path. Nothing here needs a new ranking engine; the work is to key
the watchdog's own state by physical identity (Phase 2) so that its
counters, levels and demotions follow the adapter the way the profiles
already do.

The role mapping stays what it is today:

```text
configured primary         metric 100  (RTL8812AU profiles, MAC-bound)
configured second          metric 300  (RTL8188EUS profile, MAC-bound)
configured third           metric 600  (built-in radio)
demoted path               metric 900  (transient, restored by the loop)
```

NetworkManager's profile metrics remain the configured baseline. Every metric
the watchdog writes is a transient override that the loop itself restores;
the watchdog never owns the steady-state metrics. Reason: `nmcli connection
modify ipv4.route-metric` writes the profile file on disk, and a lost state
file already produces the "stuck at 900" issue; owning the metrics would
widen that failure class to every ranking change.

Optional, later, if "materially slower" ever matters: a *degraded-active*
rule -- an active route that stays `usable-degraded` while a standby is
`healthy` for N cycles moves over, with hysteresis. That is a health-class
rule, not a capacity one, and it is not in the phases below.

### 7.2 Restore hysteresis and normalization

"Promotion" here means restoring a demoted route to its configured metric.
The hold that exists today stays as the rule:

- the route must be end-to-end healthy for `successes_before_restore`
  cycles, doubled for every wedge demotion inside `flap_window_s` (3, 6, 12,
  24, capped at `restore_hold_max_cycles`);
- the fast path must have seen it pass for `restore_fast_quiet_s` (90 s);
- new: if the route came back on a lower-priority profile than one in range,
  **one** activation of the preferred profile is attempted while it is still
  demoted (section 9.1); whether that attempt succeeds or fails, the route
  is then restored on whatever profile works and the preference schedule
  takes over.

No capacity margin: there is nothing to compare (section 7).

Failure failover remains asymmetric and faster: an active path that loses its
TCP path does **not** wait for the restore hold. The existing fast path
(5-second checks, four consecutive failures, roughly 20 seconds) remains the
primary failure detector when a standby with a TCP path exists.

## 8. Safe path switching protocol

### 8.1 Failure switch

When the active path becomes unusable:

```text
active fails
  -> validate available standbys
  -> choose highest-ranked usable standby
  -> demote failed active to metric 900
  -> kernel moves traffic
  -> move/restart tunnel onto new active path if required
  -> repair old path in the background
```

The standby selection must use the same validated ranking as normal operation,
not simply the numerically next historical interface metric.

### 8.2 Restore of a repaired higher-ranked path

When a demoted path is healthy again while a lower-ranked healthy path is
active:

```text
demoted path passes the probes
  -> stays demoted (metric 900)
  -> source-bound health verification (the cycle's probes and the fast path's)
  -> desired-state normalization: one attempt at the preferred profile
  -> restore hold / fast-path clean window
  -> restore its configured metric; the kernel moves traffic back
  -> converge tunnel affinity (existing rule)
```

The active path is never touched for this. If the restored path fails again
it is demoted again by the ordinary rules, with the flap hold-down doubled.

## 9. Failure journeys and expected convergence

### 9.1 Active adapter data-path wedge

Example: associated Wi-Fi and USB link look normal, but TCP stops passing.

Expected path:

```text
fast failures -> best healthy standby selected -> failed route demoted
-> tunnel moved -> reassociation -> USB reset only if still wedged
-> validate recovered path -> normalize USB/profile -> promotion hold
-> return it to the ranking -> restore it as active only if it is again best
```

A recovered device on the wrong 2.4 GHz profile is normalized while it is
still safely demoted and a standby is healthy: **one** activation of the
preferred profile, bounded, because on 2026-09-23 the 5 GHz activation failed
three times out of four after a USB reset (the `association took too long`
problem on record since 09-13), and an unbounded normalization would have
kept the primary demoted for over 30 minutes on the 48 Mbit/s standby. If the
attempt fails, restore on the working band and leave the retries to the
preference schedule. What must not happen again is the 20:16 shape: restore
at 20:16:39, preference demotion 31 s later, four demotions in 34 minutes.

### 9.2 Healthy active path, faster standby fails

Keep the current active path online. Repair the faster standby without touching
the active path. Once the faster path is healthy and validated again, promote
it through the safe reclaim protocol.

### 9.3 USB device present but NetworkManager netdev absent

Current watchdog behavior is report-only. New behavior:

```text
physical USB identity present
+ no netdev/driver binding
  -> wait a short settling threshold
  -> locate USB node by physical identity
  -> authorized reset / port reset on schedule
  -> rediscover the new netdev name
  -> restore NetworkManager/profile state
  -> validate and rejoin ranking
```

This requires a physical-device USB reset path that does not depend on a
pre-existing `wlanX` interface.

Corrections (2026-09-23): without a network interface there is no MAC to
read, so the identity here is VID:PID plus USB path, and the reset is only
allowed when exactly one node carries that VID:PID. The only occurrence on
record (2026-09-18 11:20) was the user's own `modprobe -r 8812au` for the USB
mode experiment, and a reset then would have raced a human. So: the settling
threshold is minutes, longer than a module reload; the rung never fires while
paused; and driver maintenance (the `maintain-rtl8812au` skill) pauses the
watchdog first. Low priority: no organic occurrence yet.

### 9.4 Physical USB adapter absent

Software cannot replug absent hardware.

Expected behavior:

```text
mark physical device absent
-> remove it from candidate ranking
-> keep/promote best remaining usable path
-> do not spam impossible reset attempts
-> keep watching USB inventory
-> when the same physical identity returns, enter controlled rejoin
```

### 9.5 Recovered adapter returns under a different wlanX name

Resolve the physical identity first, attach its existing persistent state to
the new runtime interface name, and continue recovery. Do not transfer the old
`wlanX` history to the unrelated adapter that now owns that name.

### 9.6 USB link below configured/learned target

If another healthy path exists, remove traffic first and run the USB speed
repair schedule. If it is the last working path, keep it online and report
`service healthy / policy degraded` until a safe repair window exists.

In learned mode, repair exhaustion may lower the learned target while retaining
`observed_max_mbps`. In fixed mode, the configured target never silently
changes; exhaustion stops destructive retries and leaves a persistent warning.

### 9.7 USB link above fixed target

No destructive action. Record actual/target/max and the relevant driver/module
parameters as policy drift evidence.

### 9.8 Wrong Wi-Fi profile/band after recovery

If a higher-capacity preferred profile is visible, normalize the device before
final route restoration when another healthy path exists. If the preferred
profile cannot be activated, keep the lower-band path if it is healthy and
back off retries. Connectivity beats profile perfection.

### 9.9 All routes lose upstream TCP but gateways remain reachable

Treat this as probable WAN/upstream failure, not three adapter failures. Keep
radios up, avoid reset churn, record the common-mode evidence, and continue
probing for recovery.

### 9.10 All radios lose gateway/AP reachability

This may be AP/router/common RF failure. Do not disrupt every lifeline at once.
Use a **global disruptive-action budget of one**: repair one candidate at a
time while preserving any still-associated/usable path. Re-observe the global
state after each action before touching another radio.

### 9.11 All local paths are unusable

There is no connectivity to preserve, so recovery may be more aggressive, but
still serial rather than simultaneous. Start with the physical device/path with
the highest expected capacity and best recovery confidence, re-observe, then
move to the next candidate if needed. The moment one end-to-end path recovers,
connectivity protection becomes the dominant rule again.

### 9.12 Tunnel remains on an old route after route switch

Keep the current tunnel-affinity behavior: detect the socket's route, restart
or move it only when needed, and record failover/reclaim reason, old/new path,
readiness time, and outcome.

### 9.13 A standby wedges right after a USB reset elsewhere

On 2026-09-23 10:35:48 the watchdog USB-reset wlan1; at 10:36:35 wlan2, then
the active route, stopped passing TCP for 20 s and the fast path failed it
over to wlan0. The two adapters sit on different USB controllers but share
the host's supply; this is the third such pairing on record (2026-09-14
09:19:57 and 21:44:01). Treat a standby wedge inside a settle window after a
disruptive USB action on another adapter as suspicious: re-observe before a
second disruptive action, and record the pairing in the episode.

## 10. Global safety invariants

The implementation must preserve these as hard invariants:

1. Never intentionally disrupt the last validated usable path for a voluntary
   performance/profile repair.
2. A failover (the metric change that moves traffic) never waits for
   anything. Disruptive repairs -- re-association, USB reset, driver reload
   -- are serialized: one in flight at a time across the cycle and the fast
   path, with a re-observation before the next. (The first draft said "one
   disruptive action globally", which would have made the fast path wait
   for a 60 s `nmcli connection up` on a standby; the fifth review of
   2026-09-14 narrowed the lock on purpose so that it does not.)
3. A failed active path is demoted before a disruptive repair whenever a usable
   standby exists.
4. Route selection always chooses the best **validated usable** path, never the
   fastest broken path.
5. A newly returned path cannot become primary before rejoin validation unless
   no other usable route exists.
6. A performance optimization may be abandoned to preserve connectivity.
7. Common WAN/upstream failures must not trigger radio reset storms.
8. USB reset allow-lists remain authoritative even with physical identities.
9. Persistent state must never be transferred merely because two devices used
   the same `wlanX` name at different times.
10. Every destructive action is rate-limited, attributable to an incident, and
    followed by re-observation before escalation.
11. No recovery action is considered successful solely because the command
    returned zero; the post-action state must be observed and validated.
12. NetworkManager's profile metrics are the configured baseline. Every
    metric the watchdog writes is a transient override that the loop itself
    restores; the watchdog never owns steady-state metrics.
13. A USB link level is judged against what the driver's mode promises (or
    an explicit target), never against the best the adapter has ever shown
    under a different mode or a different name.

## 11. Persistent state model

Introduce a physical-device state object, conceptually:

```text
devices[device_key]:
  identity:
    usb_id
    permanent_mac
    serial
  runtime:
    last_seen_ifname
    last_seen_usb_node
  presence:
    last_present
    last_netdev_present
  performance:
    observed_max_mbps
    learned_target_mbps
    rolling_capacity_estimate_mbps
    capacity_confidence
  usb_policy:
    mode
    configured_target_mbps
    policy_fingerprint
    repair_attempts
    last_repair
    repair_exhausted
  recovery:
    last_reset
    last_usb_reset
    usb_attempts
    preference_attempts
    last_preference
    wedge_times
  role:
    quarantine/demotion metadata
```

`wlan1`/`wlan2` state remains transient mapping and reporting context.

Implementation note (2026-09-23): the rungs keep addressing devices by
interface name, because that is what NetworkManager, `iw` and the routes
speak. What changes is that the per-device state is re-keyed when a name's
identity changes: durable entries (demotions, reset and USB counters, learned
level and policy fingerprint, preference counters, wedge times, grades)
follow the adapter to its new name, or are parked by identity while the
adapter is absent; transient entries (failure streaks, hysteresis counters,
last summaries) are dropped and re-observed. The identity is
`usb:<vid:pid>@<permanent MAC>` for a USB adapter and `builtin@<MAC>` for the
SDIO radio, read once per cycle from `ip -o link`. A name whose MAC cannot be
read keeps its name-keyed state untouched: a failed read must never park
anything.

Legacy state migration must verify the old `known_devices[ifname]` USB ID
against the currently observed physical identity. A mismatch discards the old
device-specific state rather than applying it to a different adapter. On this
host the file matched on 2026-09-23 (wlan1 `0bda:8812`, wlan2 `0bda:8179`),
so the migration adopts the current state under the new keys.

## 12. Policy-change reconciliation

Every actionable USB policy has a fingerprint, for example:

```text
fixed:480
param:rtw_switch_usb_mode=1:5000
param:rtw_switch_usb_mode=0:None
learned|rtw_switch_usb_mode=0
observe
```

The fingerprint includes the values of the module parameters named in
`inventory_params`, so a learned level is relearned when the driver's mode
changes, and a `param` target changes with the parameter it follows.

When the fingerprint changes, clear only repair state that belonged to the old
policy:

- speed repair attempts;
- last speed repair time;
- learned promotion candidate timer;
- repair-exhausted marker.

Retain factual history such as observed maximum and fault episodes.

Log a structured `usb_speed_policy_changed` event with old/new policy and what
state was invalidated. A fingerprint alone would not have prevented the
2026-09-23 10:15 episode: the parameter changed on 09-18 but the chip stayed
at 5000 until the reboot five days later, so a learned level would have been
relearned as 5000 in between. The `param` mode covers that gap: with mode 0
there is no target at all, whatever the chip shows.

## 13. Observability and forensic record

The journal must let a later reviewer reconstruct an incident without guessing.
Keep current `cycle=` correlation and add a durable `episode=` identifier for a
failure/recovery journey and a physical `device=` key in addition to current
`ifname=`.

### 13.1 Inventory/snapshot facts

At start, on change, and periodically record per physical device:

- physical device key, VID:PID, permanent MAC, serial;
- current interface name and USB node;
- presence/netdev/driver/module;
- relevant module parameters;
- USB actual speed, target mode/target, observed maximum;
- current profile/SSID, band, channel, width, signal;
- raw PHY rates when available;
- rolling capacity estimate and confidence/source;
- IP/source address and route metric;
- health grade and gateway/DNS/TCP timings;
- current role: active, standby, demoted, quarantine, absent;
- current rank among eligible paths;
- repair counters/backoff state.

Do not log Wi-Fi credentials, session secrets, or other authentication material.

### 13.2 Decision evidence

Every consequential decision or deliberate no-op should include:

- episode/cycle/device/ifname;
- active path at decision time;
- complete candidate ranking with health and capacity estimate;
- candidates excluded and why;
- trigger (`fast_failure`, `full_probe`, `performance_promotion`, `rejoin`,
  `usb_target`, `profile_preference`, etc.);
- threshold/streak/hold values and current counters;
- selected next path and reason;
- reason for waiting when no action is taken.

This is essential for answering "why did it choose wlanX instead of wlanY?"
months later.

### 13.3 Action evidence

Every action should log:

- planned and actual start/end times;
- state before action;
- exact logical action and target physical identity;
- current ifname/USB node resolved immediately before acting;
- route/profile metrics before and after;
- reset/reassociation method and attempt number;
- command result and duration;
- immediate observed post-action state;
- whether the desired convergence condition was reached;
- next retry/backoff if not;
- tunnel movement/restart/readiness where relevant.

### 13.4 Episode close

When an incident converges, write one summary event containing:

- failure start and detection time;
- service-impact interval;
- path sequence, e.g. `RTL8812AU -> RTL8188EU -> RTL8812AU`;
- all repairs attempted and outcomes;
- number/duration of tunnel poll failures;
- final active device/profile/USB speed/capacity estimate;
- whether full desired state or only connectivity was restored;
- total time to connectivity recovery and total time to full convergence.

`binnacle-watchdog history` should render these episodes directly, not require a
human to manually join dozens of journal lines.

## 14. CLI and doctor surfaces

Extend `status` so it answers, for every path:

```text
physical identity
current ifname
health / eligibility
current profile and band
USB actual / target / observed max
capacity estimate and source
current rank
current route metric / role
pending recovery or promotion hold
```

`doctor` should distinguish at least:

- service connectivity healthy;
- redundancy degraded;
- best path unavailable, running on fallback;
- connectivity healthy but performance target degraded;
- policy drift;
- recovery exhausted;
- physical device absent;
- identity/interface remap;
- stale/mismatched persistent state.

Add a history view capable of selecting an `episode=` identifier for full
forensic replay.

## 15. Configuration shape

Initial host-specific shape:

```toml
[watchdog]
usb_reset_ids = ["0bda:8812", "0bda:8179"]

[[watchdog.usb_link_policies]]
usb_id = "0bda:8812"
mode = "param"
param = "rtw_switch_usb_mode"
targets = { "1" = 5000 }

[[watchdog.usb_link_policies]]
usb_id = "0bda:8179"
mode = "fixed"
target_mbps = 480
```

`permanent_mac` is optional on a rule: without it the rule applies to every
adapter with that USB id, which is what this host wants. An adapter with no
rule stays in `learned` mode, keyed by identity.

Performance-selection thresholds should be explicit tunables rather than hidden
constants, including promotion hold, capacity advantage margin, and minimum
confidence needed to promote a path.

## 16. Test strategy: prove convergence, not only individual actions

Unit/system tests must assert **final state after a journey**, not just that a
single action was emitted.

Required scenario families:

1. active fastest adapter wedges -> next best path carries traffic -> original
   adapter repairs -> normalizes -> reclaims primary;
2. fastest adapter physically disappears -> best remaining path becomes active
   -> returning adapter rejoins under quarantine -> reclaims primary;
3. USB present but netdev absent -> physical-node reset -> rediscovery under a
   different interface name -> rejoin;
4. interface-name swap across reboot -> no physical-device state leakage;
5. persisted demotion across reboot + interface rename -> restore only the
   correct physical device/profile metrics;
6. param mode with `rtw_switch_usb_mode=0` and a historical 5000 -> zero
   speed-driven resets (2026-09-23 10:15); mode 1 at 480 -> one repair on
   the schedule;
7. fixed target below actual -> log-only, no destructive downgrade;
8. learned target promotion requires sustained evidence;
9. learned/fixed repair-exhaustion semantics differ correctly;
10. wrong profile after wedge repair -> one normalization attempt while
    demoted -> one final restore, no restore/demote churn (2026-09-23 20:16);
11. a demoted higher-ranked path becomes healthy while a lower-ranked path is
    active -> restored through the hold, on its configured metric;
12. a restore followed by a wedge inside the flap window -> the hold-down
    doubles (existing rule, kept);
13. standby fails while primary remains healthy -> repair standby without
    touching primary;
14. WAN-wide upstream failure -> no adapter-reset storm;
15. AP/common gateway failure -> global disruption budget permits one repair at
    a time only;
16. all links dead -> serial recovery -> stop disruptive recovery as soon as
    one usable path returns;
17. last working path has degraded USB performance -> keep it online;
18. action command succeeds but post-state is still bad -> escalate based on
    observation, not command exit code;
19. tunnel remains on old route -> affinity converges without unnecessary
    restart when already on the correct path;
20. structured journal/history can recreate each synthetic incident and its
    final convergence result;
21. the 2026-09-15 name swap replayed against the real state file shape ->
    the RTL8188EUS under `wlan1` gets no USB-speed action and the
    RTL8812AU's counters follow it to `wlan2`;
22. a USB reset on one adapter followed by a standby wedge inside the
    settle window -> no second disruptive action before a re-observation.

Property/state-machine testing should additionally check invariants across
random fault sequences: never disrupt the last usable path, never act on a
physical identity mismatch, at most one disruptive repair in flight, and the
system eventually selects the highest-ranked healthy path once faults stop.

## 17. Implementation phases

Order after the 2026-09-23 review: 0, 1, 2, 3, then the episode id from 7,
then 5 (normalization), 6, 4, then the rest of 7 and 8. Phases 0 to 3 fix
the two bugs the journal proves; everything after them is new behavior with
little or no organic evidence yet, and is done only when the earlier phases
are deployed and green.

Stopgap, config only, if Phase 3 cannot be deployed the same day:
`usb_speed_repair = false` in `~/.config/binnacle/config.toml`, restarted
through `deploy-check`. The rung has a 0-of-18 record; the one thing this
gives up is a repair that has never fired legitimately.

### Phase 0 - Freeze evidence and acceptance baseline

- Save the current live topology, config, state and representative history.
- Convert the 2026-09-15 name swap (the RTL8188EUS under `wlan1` with the
  RTL8812AU's learned 5000), the 2026-09-16 mid-boot rename, the 2026-09-23
  10:15 mode-0 false repair and the 20:12 wedge with its four preference
  demotions into deterministic regression fixtures.
- Define current expected steady state without changing production behavior.

Stop point: existing behavior is reproducibly captured by tests.

### Phase 1 - Physical identity observation

- Observe permanent MAC and USB serial/VID:PID.
- Build `device_key <-> current ifname` mapping.
- Log identity/interface transitions.
- No recovery behavior changes yet.

Stop point: interface renames can be detected and explained safely.

### Phase 2 - Physical-device persistent state and migration

- Introduce physical-device keyed state.
- Migrate USB/recovery history safely.
- Make demotion/quarantine metadata physical-device aware.
- Reject/discard legacy state on identity mismatch.

Stop point: reboot/interface swap cannot transfer recovery state to another
adapter.

### Phase 3 - USB desired-state model

- Implement `fixed / learned / observe / param` policies.
- Separate observed maximum from actionable target.
- Add policy fingerprint reconciliation and repair-exhaustion state (fixed
  and param targets never lower themselves; learned still accepts the lower
  level after `usb_speed_give_up`).
- Configure the RTL8812AU for `param` on `rtw_switch_usb_mode` (1 -> 5000)
  and the RTL8188EUS for `fixed 480`.

Stop point: `RTL8812AU actual=480 rtw_switch_usb_mode=0 max_seen=5000`
produces zero speed-repair actions; `actual=480 rtw_switch_usb_mode=1`
produces one, on the schedule, through a demotion when it is the active
route.

### Phase 4 - Offline/presence recovery and controlled rejoin

- Reset a USB device by physical identity when USB is present but netdev is
  absent.
- Treat physically absent hardware as unavailable rather than endlessly
  repairable.
- Add rejoin quarantine and post-return validation.

Stop point: unplug/replug or driver-loss journeys recover without assuming a
stable `wlanX` name.

### Phase 5 - Restore normalization (replaces "dynamic best-path selection")

- One bounded activation of the preferred profile while the repaired route
  is still demoted and a standby is healthy; then the restore, whatever the
  outcome (section 9.1).
- Ranking stays health class first, configured order second (section 7);
  verified by test against a name swap, not re-implemented.
- Rates, width, signal and USB speed become report-only fields in `status`.

Stop point: the 2026-09-23 20:12 journey replayed ends with one restore,
not five demotions; the configured primary is active; when it fails the next
configured path with a TCP path takes over; when it returns and proves
healthy it takes the primary route back.

### Phase 6 - Global disruption safety

- Enforce one disruptive radio action globally.
- Add common-mode AP/WAN classification guards.
- Re-observe after every disruptive action before planning another.

Stop point: multi-radio/common failures cannot trigger simultaneous reset
storms.

### Phase 7 - Forensic observability

- Add episode IDs, physical device keys, ranking snapshots, decision evidence,
  action post-state and convergence summaries.
- Extend `status`, `doctor` and `history`.
- Update stale watchdog documentation, including the old USB3-on-purpose text.

Stop point: a past incident can be reconstructed from logs without inspecting
source code or guessing why the watchdog acted.

### Phase 8 - Validation and deployment

1. targeted unit/system tests;
2. full repository test/coverage/lint gates;
3. dry-run against live Pi hardware;
4. controlled fault injection for each safe scenario;
5. verify zero USB-speed action at 480 Mbit/s in mode 0, and one on the
   schedule in mode 1;
6. verify failover picks the next configured path with a TCP path, by
   physical identity, after a name swap;
7. verify the restore of the repaired primary through the hold, with one
   normalization attempt;
8. verify log/history reconstruction;
9. `deploy-check`;
10. restart watchdog and perform post-deploy observation before considering the
    design promoted.

## 18. Acceptance criteria

The redesign is complete only when all of these are true:

- while any end-to-end uplink is available, the watchdog does not create a
  self-inflicted total outage;
- active-path failure moves traffic to the highest-ranked validated remaining
  path within the configured failure window;
- a higher-capacity recovered path automatically returns to service and safely
  becomes active after its validation/hold window;
- route ranking follows health class first and the configured order by
  physical identity second; interface names never enter it, and no capacity
  estimate does either;
- no healthy primary is demoted for a USB level that the driver's own mode
  does not promise (zero `usb_speed` demotions in mode 0);
- adapter/netdev disappearance and reappearance are tracked by physical
  identity;
- intentional RTL8812AU USB2 operation does not trigger attempts to restore a
  historical USB3 maximum;
- the last usable path is never disrupted merely for performance optimization;
- common WAN/AP failures do not cause multi-radio repair storms;
- only one disruptive radio action is in flight at a time;
- every recovery is validated by observed post-state;
- an incident record identifies the failure, selected fallback, ranking,
  actions, outcomes, service impact, and final convergence state in enough
  detail to reconstruct the full picture later.

## 19. Current host target after this plan is implemented

The fallback order is the configured one, by physical adapter: RTL8812AU on
its 5 GHz profile (metric 100), then RTL8188EUS (300), then the built-in radio
(600), each bound to its adapter by permanent MAC in NetworkManager. If the
RTL8812AU loses its TCP path, the next configured path with a TCP path carries
traffic within about 20 s. When the RTL8812AU is healthy and normalized again
it is restored through the hold and takes the primary route back. Its USB link
level is judged against what its driver mode promises, never against the best
it has ever shown.

This preserves the user's governing rule, as recorded on 2026-09-20:

> Always the fast adapter first, the next one when it is down, the fast one
> again once it is back, and connectivity above everything.

And the plan's own addition: record enough evidence to explain every
transition afterwards.
