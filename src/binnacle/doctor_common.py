"""Shared health-check records and systemd primitives."""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Status = Literal["ok", "warn", "fail"]
Systemctl = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(slots=True)
class Check:
    group: str
    status: Status
    detail: str
    hint: str = ""


def ok(group: str, detail: str) -> Check:
    return Check(group, "ok", detail)


def warn(group: str, detail: str, hint: str = "") -> Check:
    return Check(group, "warn", detail, hint)


def fail(group: str, detail: str, hint: str = "") -> Check:
    return Check(group, "fail", detail, hint)


def systemctl(*args: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, check=False
    )


def unit_state(unit: str, run: Systemctl = systemctl) -> str:
    return run("is-active", unit).stdout.strip() or "unknown"


def unit_property(unit: str, prop: str, run: Systemctl = systemctl) -> str:
    return run("show", unit, "-p", prop, "--value").stdout.strip()
