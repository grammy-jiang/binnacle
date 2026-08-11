"""Tests for the exact probe_error manifest binding."""

import pytest

from binnacle.application import CompatibilityUseCases
from binnacle.bootstrap.probe_error import v1_1
from binnacle.domain.mcp import (
    ExecutionErrorEnvelope,
    McpCallContext,
    ProbeErrorCase,
    ProbeErrorRequest,
    ProtocolEra,
)


@pytest.mark.anyio
async def test_binding_delegates_to_probe_error(
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    result = await v1_1(
        use_cases=compatibility_use_cases,
        request=ProbeErrorRequest(case=ProbeErrorCase.POLICY_REJECTION),
        context=McpCallContext("2026-07-28", ProtocolEra.MODERN, "req_binding"),
    )

    assert isinstance(result, ExecutionErrorEnvelope)
    assert result.error.code == "policy_rejected"
