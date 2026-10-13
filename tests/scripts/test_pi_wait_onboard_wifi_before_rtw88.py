"""Offline-only reenactment of original Pi RTL8812AU boot-order race.

Every test runs the exact installed shell program against a mock sysfs tree;
no test opens the network driver, udev, nmcli or systemctl.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts/pi_wait_onboard_wifi_before_rtw88.sh"
)
ONBOARD = "2c:cf:67:c6:73:14"
USB = "00:0f:00:73:77:7f"


def run_script(root: Path, *, tries: str = "3", interval: str = "0.002"):
    return subprocess.run(
        ["/bin/sh", str(SCRIPT)],
        env={
            **os.environ,
            "BINNACLE_NET_SYSFS_ROOT": str(root),
            "BINNACLE_WAIT_TRIES": tries,
            "BINNACLE_WAIT_INTERVAL": interval,
        },
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )


def test_source_equals_boot_tested_pi_script():
    assert SCRIPT.is_file()
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == (
        "2aeee77c6ca4b901ee96f94b54e19e58f0df590b6f78e67ebc630cfa6c7fd456"
    )
    subprocess.run(["/bin/sh", "-n", str(SCRIPT)], check=True, timeout=2)


def test_onboard_registered_as_wlan0_allows_usb_loading_immediately(tmp_path):
    path = tmp_path / "wlan0"
    path.mkdir()
    (path / "address").write_text(ONBOARD + "\n")
    result = run_script(tmp_path)
    assert result.returncode == 0
    assert "event=binnacle_onboard_wlan0_ready" in result.stdout
    assert "wait_timeout" not in result.stderr


@pytest.mark.parametrize("mac", [USB, "12:34:56:78:9a:bc", ""])
def test_incorrect_owner_of_wlan0_falls_back_after_bounded_timeout(tmp_path, mac):
    path = tmp_path / "wlan0"
    path.mkdir()
    (path / "address").write_text(mac + "\n")
    result = run_script(tmp_path, tries="2")
    assert result.returncode == 0
    assert "event=binnacle_onboard_wlan0_wait_timeout" in result.stderr
    assert "fallback=load_USB_anyway" in result.stderr
    assert "onboard_wlan0_ready" not in result.stdout


def test_missing_built_in_nic_does_not_disable_emergency_usb_uplink(tmp_path):
    result = run_script(tmp_path, tries="2")
    assert result.returncode == 0
    assert "fallback=load_USB_anyway" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_builtin_appearing_later_wins_before_usb_driver_is_loaded(tmp_path):
    def appear():
        time.sleep(0.025)
        path = tmp_path / "wlan0"
        path.mkdir()
        (path / "address").write_text(ONBOARD + "\n")

    producer = threading.Thread(target=appear)
    producer.start()
    try:
        result = run_script(tmp_path, tries="40", interval="0.005")
    finally:
        producer.join(timeout=2)
    assert result.returncode == 0
    assert "onboard_wlan0_ready" in result.stdout
    assert "wait_timeout" not in result.stderr


def test_wlan1_does_not_count_as_correct_onboard_wlan0(tmp_path):
    path = tmp_path / "wlan1"
    path.mkdir()
    (path / "address").write_text(ONBOARD + "\n")
    result = run_script(tmp_path, tries="2")
    assert result.returncode == 0
    assert "wait_timeout" in result.stderr


@pytest.mark.parametrize("bad", ["-1", "1.5", "fifty", "yes", "1x", "  "])
def test_invalid_retry_count_fails_instead_of_waiting_forever(tmp_path, bad):
    result = run_script(tmp_path, tries=bad)
    assert result.returncode == 2
    assert "invalid wait tries" in result.stderr


def test_zero_retry_count_fails_open_without_hanging(tmp_path):
    result = run_script(tmp_path, tries="0")
    assert result.returncode == 0
    assert "fallback=load_USB_anyway" in result.stderr


def test_current_script_never_changes_live_network_or_process_control(tmp_path):
    source = SCRIPT.read_text()
    assert "/usr/sbin/modprobe" not in source
    assert "nmcli" not in source
    assert "systemctl " not in source
    assert "ip link" not in source
    assert "kill " not in source
    assert "rm " not in source
    assert "sudo " not in source
    result = run_script(tmp_path, tries="1")
    assert result.returncode == 0
