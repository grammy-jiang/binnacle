"""Linux boot identity and explicit synchronization-marker tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from binnacle.adapters.linux.trusted_time import LinuxTrustedTimeSource


@pytest.mark.anyio
async def test_linux_trusted_time_requires_explicit_sync_marker(tmp_path: Path) -> None:
    boot = tmp_path / "boot-id"
    marker = tmp_path / "synchronized"
    boot.write_text("fixture-boot-id\n", encoding="ascii")
    source = LinuxTrustedTimeSource(boot_id_path=boot, synchronization_marker=marker)
    untrusted = await source.snapshot()
    assert not untrusted.wall_time_trusted
    marker.touch()
    trusted = await source.snapshot()
    assert trusted.wall_time_trusted
    assert trusted.boot_id_digest == untrusted.boot_id_digest
    assert len(trusted.boot_id_digest) == 64


@pytest.mark.anyio
async def test_linux_trusted_time_rejects_symlink_sync_marker(tmp_path: Path) -> None:
    boot = tmp_path / "boot-id"
    boot.write_text("fixture-boot-id", encoding="ascii")
    target = tmp_path / "target"
    target.touch()
    marker = tmp_path / "synchronized"
    marker.symlink_to(target)
    snapshot = await LinuxTrustedTimeSource(
        boot_id_path=boot, synchronization_marker=marker
    ).snapshot()
    assert not snapshot.wall_time_trusted
