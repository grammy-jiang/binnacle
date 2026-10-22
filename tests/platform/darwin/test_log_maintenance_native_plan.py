"""Test-only planning: no privileged helper or launchctl is ever invoked."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from binnacle.platform.darwin.log_maintenance_installed_identity import (
    InstalledWriterIdentity,
)
from binnacle.platform.darwin.log_maintenance_native_plan import (
    NativeActuatorPlan,
    NativePlanRefused,
    build_native_actuator_plan,
)

_SHA = "a" * 64
_NONCE = "b" * 32
_GENERATION = "c" * 32


@pytest.fixture
def identity() -> InstalledWriterIdentity:
    return InstalledWriterIdentity(
        "com.binnacle.mcp",
        "system/com.binnacle.mcp",
        Path("/Library/LaunchDaemons/com.binnacle.mcp.plist"),
        _SHA,
        10,
        20,
        Path("/Users/fixture/Library/Logs/binnacle/mcp.stderr.log.1"),
        30,
        40,
        50,
    )


def propose(identity: InstalledWriterIdentity, **overrides):
    args: dict[str, Any] = {
        "action": "stop",
        "approved_plist_sha256": _SHA,
        "transaction_nonce": _NONCE,
        "controller_generation": _GENERATION,
        "expected_source": (30, 40),
        "approved_logs_root": Path("/Users/fixture/Library/Logs/binnacle"),
    }
    args.update(overrides)
    return build_native_actuator_plan(identity, **args)


@pytest.mark.parametrize(
    ("action", "argv"),
    [
        ("stop", ("/bin/launchctl", "bootout", "system/com.binnacle.mcp")),
        (
            "restore",
            (
                "/bin/launchctl",
                "bootstrap",
                "system",
                "/Library/LaunchDaemons/com.binnacle.mcp.plist",
            ),
        ),
    ],
)
def test_exact_static_argv_remains_advisory(identity, action, argv) -> None:
    plan = propose(identity, action=action)
    assert plan.argv == argv
    assert not plan.production_authorized
    assert not hasattr(plan, "execute")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("action", "bootout; sudo rm -rf /"),
        ("action", "prune"),
        ("action", []),
        ("approved_logs_root", Path("/tmp/Library/Logs/binnacle")),
        ("approved_logs_root", "/Users/fixture/Library/Logs/binnacle"),
        ("approved_plist_sha256", "a" * 63),
        ("approved_plist_sha256", "b" * 64),
        ("transaction_nonce", "z" * 32),
        ("transaction_nonce", _GENERATION),
        ("controller_generation", _NONCE),
        ("controller_generation", "c" * 31),
        ("expected_source", (30, 41)),
        ("expected_source", (True, 40)),
        ("expected_source", [30, 40]),
    ],
)
def test_untrusted_request_is_rejected(identity, key, value) -> None:
    with pytest.raises(NativePlanRefused):
        propose(identity, **{key: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label", "com.binnacle.evil"),
        ("label", "com.binnacle.mcp;echo"),
        ("label", []),
        ("launchd_target", []),
        ("plist_digest", []),
        ("raw_path", []),
        ("plist_path", []),
        ("launchd_target", "gui/501/com.binnacle.mcp"),
        ("launchd_target", "system/com.binnacle.jobs"),
        ("plist_path", Path("/tmp/com.binnacle.mcp.plist")),
        ("plist_path", Path("/Library/LaunchDaemons/com.binnacle.jobs.plist")),
        ("raw_path", Path("/tmp/mcp.stderr.log.1")),
        ("raw_path", Path("/Users/fixture/Library/Logs/binnacle/mcp.bad.log.1")),
        ("raw_path", Path("/Users/fixture/Library/Logs/binnacle/../mcp.stderr.log.1")),
        ("raw_device", 31),
        ("raw_inode", 41),
        ("raw_size", 0),
        ("plist_device", 0),
        ("plist_inode", -1),
    ],
)
def test_installed_claim_substitution_fails(identity, field, value) -> None:
    with pytest.raises(NativePlanRefused):
        propose(replace(identity, **{field: value}))


def test_foreign_identity_type_is_rejected() -> None:
    with pytest.raises(NativePlanRefused):
        propose(None)  # type: ignore[arg-type]


def test_plan_cannot_be_misrepresented_as_production_authority(identity) -> None:
    plan = propose(identity)
    with pytest.raises(ValueError, match="never grants authority"):
        replace(plan, production_authorized=True)
    with pytest.raises(ValueError, match="never grants authority"):
        NativeActuatorPlan(
            plan.action,
            plan.label,
            plan.launchd_target,
            plan.plist_path,
            plan.raw_path,
            plan.plist_sha256,
            plan.transaction_nonce,
            plan.controller_generation,
            plan.source_device,
            plan.source_inode,
            plan.argv,
            True,
        )
