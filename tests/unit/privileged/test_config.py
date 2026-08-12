from __future__ import annotations

import os
from pathlib import Path

import pytest

from binnacle.privileged_broker.config import (
    PrivilegedBrokerConfigError,
    PrivilegedBrokerSettings,
    boot_id_sha256,
    load_privileged_broker_settings,
)


def _write_config(path: Path, *, acceptance_enabled: str = "false", extra: str = "") -> None:
    path.parent.chmod(0o700)
    path.write_text(
        f"""
[broker]
database_path = "/var/lib/binnacle-privileged/evidence.db"
runtime_directory = "/run/binnacle-privileged"
runtime_group_gid = 1250
expected_application_uid = 1200
expected_application_gid = 1200
build_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
profile_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
acceptance_enabled = {acceptance_enabled}
busy_timeout_ms = 5000
{extra}
""",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _load(path: Path) -> PrivilegedBrokerSettings:
    return load_privileged_broker_settings(
        path,
        expected_path=path,
        expected_owner_uid=os.geteuid(),
        expected_group_gid=os.getegid(),
    )


def test_privileged_config_is_closed_root_profile_and_default_disabled(tmp_path: Path) -> None:
    path = tmp_path / "broker.toml"
    _write_config(path)

    settings = _load(path)

    assert settings.database_path == Path("/var/lib/binnacle-privileged/evidence.db")
    assert settings.runtime_directory == Path("/run/binnacle-privileged")
    assert settings.runtime_group_gid == 1250
    assert settings.acceptance_enabled is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unexpected = true", "fields are not exact"),
        ('database_path = "/tmp/evidence.db"', "could not be loaded"),
    ],
)
def test_privileged_config_rejects_unknown_or_duplicate_fields(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    path = tmp_path / "broker.toml"
    _write_config(path, extra=mutation)

    with pytest.raises(PrivilegedBrokerConfigError, match=message):
        _load(path)


def test_privileged_config_rejects_promoted_effects_and_unsafe_paths(tmp_path: Path) -> None:
    path = tmp_path / "broker.toml"
    _write_config(path, acceptance_enabled="true")
    with pytest.raises(PrivilegedBrokerConfigError, match="not promoted"):
        _load(path)

    _write_config(path)
    path.chmod(0o640)
    with pytest.raises(PrivilegedBrokerConfigError, match="ownership or mode"):
        _load(path)

    path.chmod(0o600)
    path.parent.chmod(0o755)
    with pytest.raises(PrivilegedBrokerConfigError, match="parent ownership or mode"):
        _load(path)


def test_privileged_config_rejects_noncanonical_config_path(tmp_path: Path) -> None:
    path = tmp_path / "broker.toml"
    _write_config(path)

    with pytest.raises(PrivilegedBrokerConfigError, match="not the protected path"):
        load_privileged_broker_settings(path)


def test_privileged_boot_identity_is_digest_only(tmp_path: Path) -> None:
    path = tmp_path / "boot-id"
    path.write_text("boot-fixture\n", encoding="ascii")

    digest = boot_id_sha256(path)

    assert len(digest) == 64
    assert "boot-fixture" not in digest


def test_privileged_boot_identity_rejects_empty_or_missing_input(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    with pytest.raises(PrivilegedBrokerConfigError, match="invalid"):
        boot_id_sha256(empty)
    with pytest.raises(PrivilegedBrokerConfigError, match="unavailable"):
        boot_id_sha256(tmp_path / "missing")
