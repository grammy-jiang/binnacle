"""Manifest binding for ``probe_error`` contract 1.1."""

from binnacle.application import CompatibilityUseCases
from binnacle.domain.mcp import (
    ExecutionErrorEnvelope,
    McpCallContext,
    ProbeErrorRequest,
    SuccessEnvelope,
)


async def v1_1(
    *,
    use_cases: CompatibilityUseCases,
    request: ProbeErrorRequest,
    context: McpCallContext,
) -> SuccessEnvelope[object] | ExecutionErrorEnvelope:
    return await use_cases.probe_error(request, context)
