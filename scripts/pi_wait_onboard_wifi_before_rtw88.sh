#!/bin/sh
# Binnacle original Pi: ensure the onboard brcmfmac registers wlan0 before
# explicitly loading the Realtek USB RTL8812AU driver.
# Autoload of rtw88_8812au is blocked by modprobe.d blacklist. The driver
# is loaded by rtw88-experiment-load.service AFTER this check.
# Failure to see the onboard NIC by the deadline is *not* allowed to disable
# the only available USB uplink: log and fall back to module load.
set -eu
ROOT=${BINNACLE_NET_SYSFS_ROOT:-/sys/class/net}
TRIES=${BINNACLE_WAIT_TRIES:-200}
INTERVAL=${BINNACLE_WAIT_INTERVAL:-0.1}
ONBOARD=2c:cf:67:c6:73:14
case "$TRIES" in
  ''|*[!0-9]*) echo "invalid wait tries" >&2; exit 2 ;;
esac
count=0
while [ "$count" -lt "$TRIES" ]; do
  if [ -r "$ROOT/wlan0/address" ]; then
    actual=$(cat "$ROOT/wlan0/address")
    if [ "$actual" = "$ONBOARD" ]; then
      echo "event=binnacle_onboard_wlan0_ready address=$ONBOARD"
      exit 0
    fi
  fi
  count=$((count+1))
  sleep "$INTERVAL"
done
echo "event=binnacle_onboard_wlan0_wait_timeout fallback=load_USB_anyway tries=$TRIES" >&2
exit 0
