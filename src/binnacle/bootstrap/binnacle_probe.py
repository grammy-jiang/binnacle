"""Manifest binding for ``binnacle_probe`` contract 1.1."""

from binnacle.application import CompatibilityUseCases
from binnacle.domain.mcp import BinnacleProbeRequest, McpCallContext, SuccessEnvelope


async def v1_1(
    *,
    use_cases: CompatibilityUseCases,
    request: BinnacleProbeRequest,
    context: McpCallContext,
) -> SuccessEnvelope[object]:
    return await use_cases.binnacle_probe(request, context)
