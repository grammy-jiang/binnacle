"""The operator verifier observes all stores without creating or repairing state."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from scripts.verify_operation_kernel import _verify, _verify_temporary

from binnacle.adapters.verification import KernelVerificationError, KernelVerificationPaths


def _snapshot(root: Path) -> tuple[tuple[str, int, int, str | None], ...]:
    values: list[tuple[str, int, int, str | None]] = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        values.append((str(path.relative_to(root)), info.st_mode, info.st_size, digest))
    return tuple(values)


def _paths(root: Path) -> KernelVerificationPaths:
    return KernelVerificationPaths(
        root / "state/binnacle.db",
        root / "audit",
        root / "results",
        root / "run",
    )


@pytest.mark.anyio
async def test_read_only_verifier_changes_no_durable_entry(tmp_path: Path) -> None:
    initialized = await _verify_temporary(tmp_path)
    assert initialized["status"] == "pass"
    before = _snapshot(tmp_path)
    verified = await _verify(None, paths=_paths(tmp_path))
    after = _snapshot(tmp_path)
    assert verified["status"] == "pass"
    assert after == before


@pytest.mark.anyio
async def test_read_only_verifier_rejects_payload_orphan_without_repair(
    tmp_path: Path,
) -> None:
    await _verify_temporary(tmp_path)
    orphan = tmp_path / "results/objects/orphan"
    orphan.write_bytes(b"crash-window")
    before = _snapshot(tmp_path)
    with pytest.raises(KernelVerificationError, match="orphan"):
        await _verify(None, paths=_paths(tmp_path))
    assert _snapshot(tmp_path) == before
