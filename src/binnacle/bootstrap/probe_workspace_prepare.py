"""Manifest binding for ``probe_workspace_prepare`` contract 1.1."""

from binnacle.application.probe_workspace import ProbeWorkspaceUseCases
from binnacle.domain.mcp import (
    ExecutionErrorEnvelope,
    McpCallContext,
    ProbeWorkspacePreparationData,
    ProbeWorkspacePrepareRequest,
    SuccessEnvelope,
)


async def v1_1(
    *,
    use_cases: ProbeWorkspaceUseCases,
    request: ProbeWorkspacePrepareRequest,
    context: McpCallContext,
) -> SuccessEnvelope[ProbeWorkspacePreparationData] | ExecutionErrorEnvelope:
    return await use_cases.prepare(request, context)
