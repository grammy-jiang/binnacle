"""Tests for the exact binnacle_probe manifest binding."""

import pytest

from binnacle.application import CompatibilityUseCases
from binnacle.bootstrap.binnacle_probe import v1_1
from binnacle.domain.mcp import BinnacleProbeRequest, McpCallContext, ProtocolEra


@pytest.mark.anyio
async def test_binding_delegates_to_binnacle_probe(
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    result = await v1_1(
        use_cases=compatibility_use_cases,
        request=BinnacleProbeRequest(),
        context=McpCallContext("2026-07-28", ProtocolEra.MODERN, "req_binding"),
    )

    assert result.tool.name == "binnacle_probe"
    assert result.request_id == "req_binding"
