"""Durable audit-obligation marker protocol tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from binnacle.adapters.audit.obligations import (
    AuditObligationError,
    FileAuditObligationStore,
)
from binnacle.ports.audit import AuditObligation


def _obligation(identifier: str = "obl-fixture") -> AuditObligation:
    return AuditObligation("1", identifier, "op-fixture", 3)


@pytest.mark.anyio
async def test_publish_scan_remove_is_canonical_and_durable(tmp_path: Path) -> None:
    store = FileAuditObligationStore(tmp_path / "obligations")
    await store.initialize()
    await store.publish(_obligation())
    path = tmp_path / "obligations/obl-fixture.json"
    assert path.read_bytes() == (
        b'{"obligation_id":"obl-fixture","operation_id":"op-fixture",'
        b'"running_state_version":3,"schema_version":"1"}'
    )
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert await store.scan() == (_obligation(),)
    await store.remove("obl-fixture")
    assert await store.scan() == ()


@pytest.mark.anyio
async def test_duplicate_invalid_and_malformed_markers_fail_closed(tmp_path: Path) -> None:
    store = FileAuditObligationStore(tmp_path / "obligations")
    await store.initialize()
    with pytest.raises(AuditObligationError):
        await store.publish(AuditObligation("2", "bad", "op", 1))
    with pytest.raises(AuditObligationError):
        await store.publish(_obligation("bad/name"))
    await store.publish(_obligation())
    with pytest.raises(FileExistsError):
        await store.publish(_obligation())
    (tmp_path / "obligations/unknown.txt").write_text("x")
    with pytest.raises(AuditObligationError, match="unexpected"):
        await store.scan()


@pytest.mark.anyio
async def test_symlink_and_filename_mismatch_fail_closed(tmp_path: Path) -> None:
    directory = tmp_path / "obligations"
    store = FileAuditObligationStore(directory)
    await store.initialize()
    target = tmp_path / "target"
    target.write_text("x")
    (directory / "linked.json").symlink_to(target)
    with pytest.raises(AuditObligationError, match="unsafe"):
        await store.scan()
    (directory / "linked.json").unlink()
    (directory / "wrong.json").write_bytes(
        b'{"obligation_id":"right","operation_id":"op","running_state_version":1,'
        b'"schema_version":"1"}'
    )
    with pytest.raises(AuditObligationError, match="filename"):
        await store.scan()
