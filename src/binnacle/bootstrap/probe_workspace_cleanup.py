"""Manifest binding for ``probe_workspace_cleanup`` contract 1.1."""

from binnacle.application.probe_workspace import ProbeWorkspaceUseCases
from binnacle.domain.mcp import (
    ExecutionErrorEnvelope,
    McpCallContext,
    ProbeWorkspaceCleanupData,
    ProbeWorkspaceCleanupRequest,
    SuccessEnvelope,
)


async def v1_1(
    *,
    use_cases: ProbeWorkspaceUseCases,
    request: ProbeWorkspaceCleanupRequest,
    context: McpCallContext,
) -> SuccessEnvelope[ProbeWorkspaceCleanupData] | ExecutionErrorEnvelope:
    return await use_cases.cleanup(request, context)
