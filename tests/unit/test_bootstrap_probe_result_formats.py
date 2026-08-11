"""Tests for the exact probe_result_formats manifest binding."""

import pytest

from binnacle.application import CompatibilityUseCases
from binnacle.bootstrap.probe_result_formats import v1_1
from binnacle.domain.mcp import (
    McpCallContext,
    ProbeResultFormatsData,
    ProbeResultFormatsRequest,
    ProtocolEra,
)


@pytest.mark.anyio
async def test_binding_delegates_to_probe_result_formats(
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    result = await v1_1(
        use_cases=compatibility_use_cases,
        request=ProbeResultFormatsRequest(array_length=1),
        context=McpCallContext("2026-07-28", ProtocolEra.MODERN, "req_binding"),
    )

    assert result.tool.name == "probe_result_formats"
    assert isinstance(result.data, ProbeResultFormatsData)
    assert result.data.array_values == (0,)
