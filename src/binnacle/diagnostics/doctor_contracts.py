"""Shared health-check result records without platform dependencies."""

from dataclasses import dataclass
from typing import Literal

Status = Literal["ok", "warn", "fail"]


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
