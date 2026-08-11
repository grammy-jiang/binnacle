"""Real MCP discovery tests for the exact compatibility-core catalogue."""

from __future__ import annotations

import pytest
from tests.support import running_http_client

from binnacle.application import BinnacleApplication
from binnacle.contracts import EXPECTED_TOOL_NAMES, ContractRegistry, mutable_json_object


@pytest.mark.anyio
async def test_local_client_lists_exact_compatibility_core(
    phase2_application: BinnacleApplication,
    contract_registry: ContractRegistry,
) -> None:
    async with running_http_client(phase2_application) as client:
        discovered = await client.list_tools()

    assert tuple(tool.name for tool in discovered) == EXPECTED_TOOL_NAMES
    assert all("probe_workspace" not in tool.name for tool in discovered)
    for tool in discovered:
        expected = contract_registry.tools[tool.name]
        assert tool.title == expected.title
        assert tool.description == expected.description
        assert tool.input_schema == mutable_json_object(expected.input_schema.schema)
        assert tool.output_schema == mutable_json_object(expected.output_schema.schema)
        assert tool.annotations is not None
        assert tool.annotations.model_dump(by_alias=True, exclude_none=True) == dict(
            expected.annotations
        )
        assert tool.meta is not None
        assert tool.meta["fastmcp"]["version"] == expected.contract_version


@pytest.mark.anyio
async def test_catalogue_has_no_resources_prompts_or_tasks(
    phase2_application: BinnacleApplication,
) -> None:
    async with running_http_client(phase2_application) as client:
        assert await client.list_resources() == []
        assert await client.list_resource_templates() == []
        assert await client.list_prompts() == []
