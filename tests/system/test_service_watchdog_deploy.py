"""Review installation plans without touching systemd, launchd or live services."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from binnacle.companions.service_watchdog_deploy import (
    LINUX_UNIT,
    MAC_LABEL,
    linux_user_unit,
    mac_system_plist,
)


def test_linux_user_service_has_no_network_hardware_reset_or_service_wants():
    unit = linux_user_unit(Path("/home/user/binnacle/.venv/bin/python"))
    assert LINUX_UNIT == "binnacle-service-watchdog.service"
    assert "WantedBy=default.target" in unit
    assert "Restart=always" in unit
    assert " --restart-enabled\n" in unit
    assert not any(k in unit for k in ("nmcli", "sudo", "USB", "Wants="))
    assert (
        linux_user_unit(Path("/opt/python"), restart_enabled=False).count(
            "--restart-enabled"
        )
        == 0
    )


def test_mac_plist_is_independent_and_explicitly_unprivileged():
    plist = plistlib.loads(
        mac_system_plist(
            python=Path("/Users/me/Projects/binnacle/.venv/bin/python"),
            home=Path("/Users/me"),
            username="me",
        )
    )
    assert plist["Label"] == MAC_LABEL
    assert plist["UserName"] == "me"
    assert plist["RunAtLoad"] and plist["KeepAlive"]
    assert plist["ThrottleInterval"] >= 10
    assert "--restart-enabled" in plist["ProgramArguments"]
    assert not any(k in plist for k in ("Sockets", "MachServices", "RootDirectory"))
    assert plist["StandardErrorPath"].startswith("/Users/me/Library/Logs/binnacle")
    inactive = plistlib.loads(
        mac_system_plist(
            python=Path("/usr/bin/python3"),
            home=Path("/Users/me"),
            username="me",
            restart_enabled=False,
        )
    )
    assert "--restart-enabled" not in inactive["ProgramArguments"]


def test_render_rejects_ambiguous_paths_and_bad_account(tmp_path):
    with pytest.raises(ValueError):
        linux_user_unit(Path("relative/python"))
    with pytest.raises(ValueError):
        linux_user_unit(Path("/tmp/space in path/python"))
    with pytest.raises(ValueError):
        mac_system_plist(
            python=Path("/usr/bin/python3"),
            home=tmp_path,
            username="owner;rm",
        )
