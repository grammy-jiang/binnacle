"""Shared exact Phase 5 kernel and authenticated-call fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from binnacle.adapters.sqlite.engine import DatabaseRuntimeSettings
from binnacle.adapters.sqlite.migrations import upgrade_database
from binnacle.composition import (
    ComposedOperationKernel,
    KernelCompositionPaths,
    compose_operation_kernel,
)
from binnacle.config import BinnacleSettings, ProbeWorkspaceSettings
from binnacle.contracts import ContractRegistry
from binnacle.domain.controller import ControllerIdentity, ControllerSecurityContext
from binnacle.domain.mcp import McpCallContext, ProtocolEra
from binnacle.domain.operation import OperationOwner
from binnacle.domain.trusted_time import TrustedTimeSnapshot


class MutableTrustedTime:
    def __init__(self) -> None:
        self.wall = datetime(2026, 8, 12, tzinfo=UTC)
        self.monotonic_ns = 1_000

    async def snapshot(self) -> TrustedTimeSnapshot:
        return TrustedTimeSnapshot(self.wall, self.monotonic_ns, "3" * 64, True)

    def advance(self, seconds: int) -> None:
        self.wall += timedelta(seconds=seconds)
        self.monotonic_ns += seconds * 1_000_000_000


def controller_context(*, authenticated: bool = True) -> McpCallContext:
    controller = None
    if authenticated:
        now = datetime.now(UTC)
        controller = ControllerSecurityContext(
            identity=ControllerIdentity("controller-fixture", "profile-fixture"),
            profile_version="1.0.0",
            issuer="issuer-fixture",
            subject="subject-fixture",
            canonical_audience="audience-fixture",
            authorized_client=None,
            owner_boundary=None,
            credential_binding_id=None,
            scopes=frozenset({"selected-probe-scope"}),
            authentication_time=now,
            expires_at=now + timedelta(hours=1),
            revocation_checked_at=None,
            revocation_fresh_until=None,
            connection_binding_digest=None,
            evidence_id_digest=None,
        )
    return McpCallContext(
        revision="2026-07-28",
        era=ProtocolEra.MODERN,
        request_id="req_fixture",
        controller=controller,
    )


@asynccontextmanager
async def phase5_kernel(
    root: Path,
    repo_root: Path,
    *,
    entitled: bool = True,
) -> AsyncIterator[tuple[ComposedOperationKernel, Path, MutableTrustedTime]]:
    probe_root = root / "probe"
    (probe_root / ".staging").mkdir(parents=True)
    probe_root.chmod(0o700)
    (probe_root / ".staging").chmod(0o700)
    database = root / "state/binnacle.db"
    database.parent.mkdir()
    paths = KernelCompositionPaths(
        database=database,
        audit=root / "audit",
        payload=root / "results",
        runtime=root / "run",
        probe=probe_root,
        verify_runtime_directory=False,
    )
    upgrade_database(
        DatabaseRuntimeSettings(database, paths.runtime, verify_runtime_directory=False),
        project_root=repo_root,
    )
    trusted_time = MutableTrustedTime()

    def resolve_owner(context: McpCallContext) -> OperationOwner:
        assert context.controller is not None
        return OperationOwner(
            context.controller.identity.controller_id,
            1,
            context.controller.identity.profile_id,
            context.controller.profile_version,
        )

    kernel = await compose_operation_kernel(
        settings=BinnacleSettings(
            probe_workspace=ProbeWorkspaceSettings(enabled=True),
        ),
        project_root=repo_root,
        paths=paths,
        write_catalogue_eligible=True,
        contracts=ContractRegistry.load_phase("compatibility-write-probe"),
        controller_resolver=resolve_owner,
        probe_entitlement=lambda _context: entitled,
        trusted_time_source=trusted_time,
    )
    try:
        yield kernel, probe_root, trusted_time
    finally:
        await kernel.close()


__all__ = ["MutableTrustedTime", "controller_context", "phase5_kernel"]
