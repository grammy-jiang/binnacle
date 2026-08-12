from __future__ import annotations

import os
from pathlib import Path

import pytest

from binnacle.executor.config import (
    ExecutorConfigError,
    boot_id_digest,
    load_executor_settings,
)


def _write_config(path: Path, *, extra: str = "") -> None:
    path.write_text(
        """
[executor]
database_path = "/var/lib/binnacle-executor/state/executor-state.sqlite3"
runtime_directory = "/run/binnacle-executor/private"
output_directory = "/var/lib/binnacle-executor/output"
expected_application_uid = 1200
expected_application_gid = 1200
build_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
profile_sha256 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
busy_timeout_ms = 5000
"""
        + extra,
        encoding="utf-8",
    )
    path.chmod(0o640)


def test_executor_config_is_closed_and_uses_separate_roots(tmp_path: Path) -> None:
    path = tmp_path / "executor.toml"
    _write_config(path)

    settings = load_executor_settings(path, expected_owner_uid=os.geteuid())

    assert settings.runtime_directory == Path("/run/binnacle-executor/private")
    assert settings.output_directory == Path("/var/lib/binnacle-executor/output")


def test_executor_config_rejects_unknown_fields_and_broad_mode(tmp_path: Path) -> None:
    path = tmp_path / "executor.toml"
    _write_config(path, extra="unexpected = true\n")
    with pytest.raises(ExecutorConfigError, match="fields are not exact"):
        load_executor_settings(path, expected_owner_uid=os.geteuid())

    _write_config(path)
    path.chmod(0o644)
    with pytest.raises(ExecutorConfigError, match="ownership or mode"):
        load_executor_settings(path, expected_owner_uid=os.geteuid())


def test_boot_identity_is_digest_only(tmp_path: Path) -> None:
    path = tmp_path / "boot-id"
    path.write_text("boot-fixture\n", encoding="ascii")

    digest = boot_id_digest(path)

    assert len(digest) == 64
    assert "boot-fixture" not in digest
