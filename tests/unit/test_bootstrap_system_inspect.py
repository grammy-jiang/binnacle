"""Tests for the exact system_inspect manifest binding."""

import pytest

from binnacle.application import CompatibilityUseCases
from binnacle.bootstrap.system_inspect import v1_1
from binnacle.domain.mcp import McpCallContext, ProtocolEra, SystemInspectRequest
from binnacle.domain.system import SystemSection


@pytest.mark.anyio
async def test_binding_delegates_to_system_inspect(
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    result = await v1_1(
        use_cases=compatibility_use_cases,
        request=SystemInspectRequest(sections=(SystemSection.CPU,)),
        context=McpCallContext("2026-07-28", ProtocolEra.MODERN, "req_binding"),
    )

    assert result.tool.name == "system_inspect"
    assert result.request_id == "req_binding"
