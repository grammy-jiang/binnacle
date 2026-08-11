"""Manifest binding for ``probe_workspace_write`` contract 1.1."""

from binnacle.application.probe_workspace import ProbeWorkspaceUseCases
from binnacle.domain.mcp import (
    ExecutionErrorEnvelope,
    McpCallContext,
    ProbeWorkspaceWriteData,
    ProbeWorkspaceWriteRequest,
    SuccessEnvelope,
)


async def v1_1(
    *,
    use_cases: ProbeWorkspaceUseCases,
    request: ProbeWorkspaceWriteRequest,
    context: McpCallContext,
) -> SuccessEnvelope[ProbeWorkspaceWriteData] | ExecutionErrorEnvelope:
    return await use_cases.write(request, context)
