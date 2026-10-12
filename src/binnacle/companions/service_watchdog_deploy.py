"""Side-effect-free, reviewable service definitions for the lightweight watchdog.

The heavy Raspberry Pi uplink watchdog is a separate companion and is never
replaced here. Render functions do NOT install, bootstrap, or restart anything.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

MAC_LABEL = "com.binnacle.service-watchdog"
LINUX_UNIT = "binnacle-service-watchdog.service"


def _path(path: Path) -> str:
    if not path.is_absolute() or any(c.isspace() for c in str(path)):
        raise ValueError("service watchdog path must be absolute with no whitespace")
    return str(path)


def linux_user_unit(python: Path, *, restart_enabled: bool = True) -> str:
    executable = _path(python)
    enabled = " --restart-enabled" if restart_enabled else ""
    return f"""[Unit]
Description=Binnacle application-only service health watchdog
After=network.target binnacle-mcp.service binnacle-tunnel.service

[Service]
Type=simple
ExecStart={executable} -m binnacle.companions.service_watchdog{enabled}
Restart=always
RestartSec=10
UMask=0077

[Install]
WantedBy=default.target
"""


def mac_system_plist(
    *,
    python: Path,
    home: Path,
    username: str,
    group: str = "staff",
    restart_enabled: bool = True,
) -> bytes:
    if not username or not username.replace("-", "").replace("_", "").isalnum():
        raise ValueError("invalid service watchdog user")
    if not group or not group.replace("-", "").replace("_", "").isalnum():
        raise ValueError("invalid service watchdog group")
    logs = home / "Library/Logs/binnacle"
    body = {
        "Label": MAC_LABEL,
        "UserName": username,
        "GroupName": group,
        "ProgramArguments": [
            _path(python),
            "-m",
            "binnacle.companions.service_watchdog",
            *(["--restart-enabled"] if restart_enabled else []),
        ],
        "WorkingDirectory": _path(home),
        "EnvironmentVariables": {
            "HOME": _path(home),
            "PYTHONUNBUFFERED": "1",
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 15,
        "StandardErrorPath": _path(logs / "service-watchdog.stderr.log"),
        "StandardOutPath": _path(logs / "service-watchdog.stdout.log"),
        "Umask": 0o077,
    }
    return plistlib.dumps(body, fmt=plistlib.FMT_XML, sort_keys=True)
