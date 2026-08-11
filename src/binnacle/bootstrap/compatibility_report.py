"""Manifest binding for ``compatibility_report`` contract 1.1."""

from binnacle.application import CompatibilityUseCases
from binnacle.domain.mcp import CompatibilityReportRequest, McpCallContext, SuccessEnvelope


async def v1_1(
    *,
    use_cases: CompatibilityUseCases,
    request: CompatibilityReportRequest,
    context: McpCallContext,
) -> SuccessEnvelope[object]:
    return await use_cases.compatibility_report(request, context)
