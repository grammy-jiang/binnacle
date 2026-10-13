# Original Raspberry Pi: deterministic onboard/USB Wi-Fi boot order

**2026-10-13 — installed and accepted after a real reboot.**

This is **host-specific**. Do not apply it to sextant, the MacBook Pro,
or Raspberry Pi nodes that have different radio MAC addresses.

## Original failure and verified cause

The original Pi has an onboard Broadcom WLAN (brcmfmac, MAC
`2c:cf:67:c6:73:14`) and a USB Realtek RTL8812AU WLAN (MAC
`00:0f:00:73:77:7f`). NetworkManager profiles depend on stable names:
onboard `wlan0` for `Occom_1D36_5G`, USB `wlan1` for the fallback.

After a reboot, the early system unit
`/etc/systemd/system/rtw88-experiment-load.service` loaded
`rtw88_8812au` before the onboard brcmfmac driver registered. The USB
radio became `wlan0`; udev could not rename it to `wlan1` because
that name was already occupied. The onboard radio became `wlan1` and
its profile failed to auto-connect. Logs recorded
`Failed to rename network interface ... File exists`.

## Installed boot-order gate

The byte-for-byte source of the boot-tested helper is
`scripts/pi_wait_onboard_wifi_before_rtw88.sh`, pinned SHA-256
`2aeee77c6ca4b901ee96f94b54e19e58f0df590b6f78e67ebc630cfa6c7fd456`.

On this original Pi it is installed at
`/usr/local/libexec/binnacle/wait-onboard-wlan0.sh` with mode 0755 and
root-owned parent directory. The existing system unit has one added line:

```ini
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/usr/local/libexec/binnacle/wait-onboard-wlan0.sh
ExecStart=/usr/sbin/modprobe rtw88_8812au
```

The helper polls the onboard WLAN MAC at
`/sys/class/net/wlan0/address` up to 200 times with 0.1 s interval
(about 20 seconds). If the expected board radio appears, it permits
the original USB module load. If it never appears, **it returns success
anyway**, so the USB uplink can still be loaded as an emergency
recovery path. It does not unload modules, manipulate route metrics,
reset USB hardware, start/stop NetworkManager or change passwords.

The local unit installation used a byte-exact hash guard, root-owned
atomic replace and `systemd-analyze verify`. The previous unit is backed
up under
`~/.local/state/binnacle/maintenance/20261013-original-pi-reboot-second/`
as `rtw88-experiment-load-before-persistent-naming.service`. The
helper can be tested without any real network operation by overriding
`BINNACLE_NET_SYSFS_ROOT` to a private fixture directory.

### USB fallback profile selection

The existing 5 GHz USB Wi-Fi profile was visible but repeatedly failed
authentication after reboot. The previously verified-good
`Occom_1D36_2.4G-USB` was restored and its
`connection.autoconnect-priority` changed from 0 to **30**, above the
5 GHz USB alternative's priority 20. Both USB profiles are pinned to
the USB card's MAC, so the board radio remains untouched.

## Actual hardware acceptance

Three sequential original-Pi boot tests were conducted, never
concurrently with another host reboot. The third, using the installed
order gate, produced boot ID
`60487950-1d1f-4f26-8fc3-4a54e8271029`. The kernel/systemd journal
included `event=binnacle_onboard_wlan0_ready` before loading the
USB driver. Both expected MACs appeared under their correct names:

- onboard `wlan0`: `2c:cf:67:c6:73:14`, connected 5 GHz;
- USB `wlan1`: `00:0f:00:73:77:7f`, connected 2.4 GHz.

Gateway/DNS/TCP probes succeeded on both uplinks. MCP, Jobs, Tunnel,
hardware Watchdog and resource monitor auto-started; HTTP
`/healthz`, Job Manager ping and real ChatGPT MCP calls succeeded.
All 571 unrelated untracked files were independently SHA-256 checked
and preserved before/after the upgrade and reboot.

Independent control used sextant over authorized LAN SSH; the Mac was
not rebooted during original Pi testing.

## Rollback and cautions

Only if a future maintenance review finds this boot gate inappropriate,
restore the backed-up root-owned unit via a hash-guarded atomic replace,
reload systemd's unit definitions and test network behavior in a quiet
window. Do **not** replace this script/unit in a live boot transaction,
remove the existing blacklist or forcibly reload the Realtek driver:
that could disable the USB recovery path.

The 20-second fail-open deadline is deliberate. It guarantees neither
Wi-Fi availability nor exactly-once naming on unknown future hardware;
the acceptance above applies to this Pi's current boot ordering only.
