"""Phase 5 write, retained retry, cleanup, and ledger lifecycle."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from tests.phase5_support import controller_context, phase5_kernel

from binnacle.adapters.sqlite.probe_workspace import SqliteProbeWorkspaceRepository
from binnacle.contracts import ContractRegistry
from binnacle.domain.mcp import (
    ExecutionErrorEnvelope,
    ProbeWorkspaceCleanupRequest,
    ProbeWorkspacePrepareRequest,
    ProbeWorkspaceWriteRequest,
    SuccessEnvelope,
    envelope_to_mapping,
)
from binnacle.domain.probe_workspace import ProbeOperationKind


@pytest.mark.anyio
async def test_write_retry_after_expiry_then_cleanup_is_exact(
    tmp_path: Path, repo_root: Path
) -> None:
    async with phase5_kernel(tmp_path, repo_root) as (kernel, probe_root, trusted_time):
        assert kernel.write_catalogue_available
        use_cases = kernel.probe_workspace
        assert use_cases is not None
        context = controller_context()
        contracts = ContractRegistry.load_phase("compatibility-write-probe")
        content = b"phase-five"
        content_digest = hashlib.sha256(content).hexdigest()
        preparation = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.WRITE,
                "probe.txt",
                content_digest,
                len(content),
            ),
            context,
        )
        assert isinstance(preparation, SuccessEnvelope)
        write_request = ProbeWorkspaceWriteRequest(
            preparation.data.prepared_operation_id,
            preparation.data.execution_nonce,
            "a" * 32,
            "probe.txt",
            content,
            False,
        )
        written = await use_cases.write(write_request, context)
        assert isinstance(written, SuccessEnvelope)
        assert (probe_root / "probe.txt").read_bytes() == content
        contracts.validate_output("probe_workspace_write", envelope_to_mapping(written))

        trusted_time.advance(1_000)
        retained = await use_cases.write(write_request, context)
        assert isinstance(retained, SuccessEnvelope)
        assert retained.operation == written.operation
        assert retained.data == written.data
        assert (probe_root / "probe.txt").read_bytes() == content

        conflicting = await use_cases.write(
            ProbeWorkspaceWriteRequest(
                preparation.data.prepared_operation_id,
                preparation.data.execution_nonce,
                "b" * 32,
                "probe.txt",
                content,
                False,
            ),
            context,
        )
        assert isinstance(conflicting, ExecutionErrorEnvelope)
        assert conflicting.error.code == "idempotency_conflict"

        cleanup_preparation = await use_cases.prepare(
            ProbeWorkspacePrepareRequest(
                ProbeOperationKind.CLEANUP,
                "probe.txt",
                content_digest,
                artifact_id=written.data.artifact_id,
            ),
            context,
        )
        assert isinstance(cleanup_preparation, SuccessEnvelope)
        cleaned = await use_cases.cleanup(
            ProbeWorkspaceCleanupRequest(
                cleanup_preparation.data.prepared_operation_id,
                cleanup_preparation.data.execution_nonce,
                "c" * 32,
                "probe.txt",
                written.data.artifact_id,
                content_digest,
            ),
            context,
        )
        assert isinstance(cleaned, SuccessEnvelope)
        assert cleaned.data.removed and not cleaned.data.already_missing
        assert not (probe_root / "probe.txt").exists()
        contracts.validate_output("probe_workspace_cleanup", envelope_to_mapping(cleaned))
        await SqliteProbeWorkspaceRepository(kernel.database, kernel.store).verify_integrity()
