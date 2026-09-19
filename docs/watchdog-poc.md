# Host watchdog POC

> Operational companion, not a Binnacle product feature. Binnacle core must not depend on it.

Uplink watchdog: keep the connector reachable when a radio wedges.

The failure this exists for (2026-09-12): the USB adapter held the default
route, stopped passing packets, and kept every local health signal green --
association up, carrier up, DHCP lease valid, driver silent. Nothing in the
system was both able to notice and allowed to act, so the outage ran 48
minutes and ended only because the adapter was physically unplugged.

Policy, in order:

1. Probe every default route each cycle (binnacle.uplink).
2. When the *active* route (lowest metric) fails every layer for
   `failures_before_action` cycles in a row, and another route is healthy,
   demote it: raise its metric so traffic moves to the healthy interface.
   The connector comes back within one cycle; it never waits on a repair.
3. Then try to repair the demoted interface (`nmcli connection up`),
   rate-limited so a persistently broken radio cannot cause a reset storm.
4. If it stays unhealthy, re-enumerate its USB device -- the software form
   of the replug that revived it on 2026-09-12 21:00 when re-association
   had not (802.11 auth, assoc, 4-way handshake and DHCP all succeeded and
   the data path stayed dead). Attempts follow `usb_reset_schedule`: 1 min
   x3, 3 min x3, 5 min x3, then every 10 min without limit, counted from
   the re-association; the counter resets once the device is healthy.
   Only a device whose USB id is in `usb_reset_ids` is ever touched, its
   node is resolved fresh each time (it moves 1-1 -> 2-1 across the mode-1
   re-enumeration), and it only happens while the device is demoted, so the
   connector is already on the other route.
5. Keep probing the demoted interface. After `successes_before_restore`
   healthy cycles, restore its original metric.

Two more things run beside the failover (2026-09-13):

- Standby repair: a wedged *standby* route is re-activated on the same
  threshold and rate limit as the active one. A dead lifeline is the "no
  healthy alternative" case waiting to happen (wlan0 sat on a dead 5 GHz
  link at 18:16 and nothing looked at it), so it is fixed while nothing
  depends on it.
- Profile preference: NetworkManager activates the first profile whose
  network shows up in the first scan and never revisits the choice, so
  after each reset the USB adapter came back on its 2.4 GHz profile
  (autoconnect-priority 0) with the 5 GHz one (priority 20) in range --
  24 hours on the wrong band before anyone noticed. Each cycle the
  watchdog reads the priorities NetworkManager already holds and, when a
  strictly higher-priority profile's network is in range, re-activates
  it: a standby device at once; the active device only through a
  demotion, so traffic is on the other route before the link goes down,
  with the target profile's metric raised too, so the new link earns its
  way back with `successes_before_restore` healthy cycles like any
  repaired device. Attempts back off on `prefer_schedule`, never start
  while a demotion is in flight, and a move that does not come up falls
  back to the profile that worked after `prefer_timeout_s`. Preference
  is expressed only in NetworkManager (`connection.autoconnect-priority`);
  nothing here names a profile or a band.

Reviewed 2026-09-13 (user: keep the network up first, then bring every
radio back to its highest level). Every cycle observes every Wi-Fi device
NetworkManager manages -- not only the ones with a default route -- and
grades it: absent / unavailable / disconnected / connecting / no route /
wedged / degraded / healthy, plus the *level* of a healthy one: the band
(the profile NetworkManager ranks highest), the USB link speed against the
best this device has shown, channel width and rate (reported, not repaired).
The repair ladder, worst first, each rung rate-limited and backed off:

- a wedged active route: failover, re-association, USB reset (above);
- a wedged standby: re-association to the best profile in range;
- a device without a route (disconnected, connecting too long,
  unavailable): re-activate the best profile in range; a USB adapter that
  is unavailable, or that a re-activation did not bring back, gets the
  USB reset schedule -- it carries nothing, so this costs nothing;
- a USB adapter whose link is below the best speed it has shown (a USB 3
  part enumerated at 480 Mbit/s): re-enumerate it -- through a demotion
  when it is the active route -- on `usb_speed_schedule`, and accept the
  lower level after `usb_speed_give_up` attempts until it shows the
  higher one again;
- a device on a lower-priority profile than one in range: the preference
  move (above).

Invariants that put connectivity first: a link-down action on the active
route happens only after a demotion, and a demotion only when another
route is healthy this cycle; a demotion raises the metric of *every*
profile bound to the device, so whatever NetworkManager brings up after
the repair still waits for `successes_before_restore` healthy cycles; one
voluntary action (level or preference) per cycle and none while a
demotion is in flight; the last healthy route is never demoted.

The adapter is never removed and never left out of service permanently --
demotion is reversed as soon as it carries traffic again.

Route changes go through NetworkManager (`connection modify` +
`device reapply`), not `ip route`: NM re-applies its own routes on every
DHCP renew -- measured every ~11 minutes on this host -- and would revert a
direct route edit. `evaluate` is pure, so the policy is tested without a
network.
