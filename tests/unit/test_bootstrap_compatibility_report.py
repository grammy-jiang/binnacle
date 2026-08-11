"""Tests for the exact compatibility_report manifest binding."""

import pytest

from binnacle.application import CompatibilityUseCases
from binnacle.bootstrap.compatibility_report import v1_1
from binnacle.domain.mcp import (
    CompatibilityReportData,
    CompatibilityReportRequest,
    McpCallContext,
    ProtocolEra,
)


@pytest.mark.anyio
async def test_binding_delegates_to_compatibility_report(
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    result = await v1_1(
        use_cases=compatibility_use_cases,
        request=CompatibilityReportRequest(),
        context=McpCallContext("2026-07-28", ProtocolEra.MODERN, "req_binding"),
    )

    assert result.tool.name == "compatibility_report"
    assert isinstance(result.data, CompatibilityReportData)
    assert result.data.evidence_bundle_sha256 is None
