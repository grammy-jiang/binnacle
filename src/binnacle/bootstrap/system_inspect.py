"""Manifest binding for ``system_inspect`` contract 1.1."""

from binnacle.application import CompatibilityUseCases
from binnacle.domain.mcp import (
    ExecutionErrorEnvelope,
    McpCallContext,
    SuccessEnvelope,
    SystemInspectRequest,
)


async def v1_1(
    *,
    use_cases: CompatibilityUseCases,
    request: SystemInspectRequest,
    context: McpCallContext,
) -> SuccessEnvelope[object] | ExecutionErrorEnvelope:
    return await use_cases.system_inspect(request, context)
