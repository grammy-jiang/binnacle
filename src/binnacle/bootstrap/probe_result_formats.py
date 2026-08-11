"""Manifest binding for ``probe_result_formats`` contract 1.1."""

from binnacle.application import CompatibilityUseCases
from binnacle.domain.mcp import (
    McpCallContext,
    ProbeResultFormatsRequest,
    SuccessEnvelope,
)


async def v1_1(
    *,
    use_cases: CompatibilityUseCases,
    request: ProbeResultFormatsRequest,
    context: McpCallContext,
) -> SuccessEnvelope[object]:
    return await use_cases.probe_result_formats(request, context)
