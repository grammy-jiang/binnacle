"""The operator verifier observes all stores without creating or repairing state."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from scripts.verify_operation_kernel import _verify, _verify_temporary
from sqlalchemy import text
from tests.phase5_support import controller_context, phase5_kernel

from binnacle.adapters.verification import KernelVerificationError, KernelVerificationPaths
from binnacle.domain.mcp import (
    ProbeWorkspacePrepareRequest,
    ProbeWorkspaceWriteRequest,
    SuccessEnvelope,
)
from binnacle.domain.probe_workspace import ProbeOperationKind


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


@pytest.mark.anyio
async def test_read_only_verifier_rejects_coordinated_probe_fact_corruption(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    content = b"phase-five-verifier"
    content_digest = hashlib.sha256(content).hexdigest()
    async with phase5_kernel(tmp_path, repo_root) as (kernel, _probe_root, _time):
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        preparation = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.WRITE,
                "probe.txt",
                content_digest,
                len(content),
            ),
            controller_context(),
        )
        assert isinstance(preparation, SuccessEnvelope)
        written = await use_cases.write(
            ProbeWorkspaceWriteRequest(
                preparation.data.prepared_operation_id,
                preparation.data.execution_nonce,
                "a" * 32,
                "probe.txt",
                content,
                False,
            ),
            controller_context(),
        )
        assert isinstance(written, SuccessEnvelope)
        assert written.operation is not None
        async with kernel.database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE probe_artifacts SET content_sha256=:digest "
                    "WHERE create_operation_id=:operation_id"
                ),
                {"digest": "f" * 64, "operation_id": written.operation.operation_id},
            )
            await connection.execute(
                text(
                    "UPDATE probe_operations SET expected_content_sha256=:digest "
                    "WHERE operation_id=:operation_id"
                ),
                {"digest": "f" * 64, "operation_id": written.operation.operation_id},
            )

    with pytest.raises(KernelVerificationError, match="provenance"):
        await _verify(None, paths=_paths(tmp_path))
