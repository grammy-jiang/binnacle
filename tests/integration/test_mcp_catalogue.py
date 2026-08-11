"""Real MCP discovery tests for the exact compatibility-core catalogue."""

from __future__ import annotations

import pytest
from tests.support import running_http_client

from binnacle.application import BinnacleApplication, CompatibilityUseCases
from binnacle.application.probe_workspace import ProbeWorkspaceUseCases
from binnacle.contracts import (
    EXPECTED_TOOL_NAMES,
    EXPECTED_WRITE_PROBE_TOOL_NAMES,
    ContractRegistry,
    mutable_json_object,
)
from binnacle.domain.runtime import PackageIdentity


class _WriteKernel:
    def __init__(self) -> None:
        self.probe_workspace = object.__new__(ProbeWorkspaceUseCases)
        self.write_catalogue_available = True
        self.closed = False

    async def close(self) -> None:
        self.closed = True


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


@pytest.mark.anyio
async def test_write_catalogue_enables_only_for_a_healthy_lifespan_kernel(
    package_identity: PackageIdentity,
    contract_registry: ContractRegistry,
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    write_contracts = ContractRegistry.load_phase("compatibility-write-probe")
    application = BinnacleApplication(
        identity=package_identity,
        contracts=contract_registry,
        write_contracts=write_contracts,
        compatibility=compatibility_use_cases,
    )
    kernel = _WriteKernel()

    async def factory() -> _WriteKernel:
        return kernel

    async with running_http_client(
        application,
        operation_kernel_factory=factory,
    ) as client:
        discovered = await client.list_tools()
        assert tuple(tool.name for tool in discovered) == EXPECTED_WRITE_PROBE_TOOL_NAMES
        assert application.contracts.catalogue_phase == "compatibility-write-probe"
    assert kernel.closed
    assert application.contracts.catalogue_phase == "compatibility-core"


@pytest.mark.anyio
async def test_write_catalogue_kernel_failure_falls_back_to_exact_core(
    package_identity: PackageIdentity,
    contract_registry: ContractRegistry,
    compatibility_use_cases: CompatibilityUseCases,
) -> None:
    write_contracts = ContractRegistry.load_phase("compatibility-write-probe")
    application = BinnacleApplication(
        identity=package_identity,
        contracts=contract_registry,
        write_contracts=write_contracts,
        compatibility=compatibility_use_cases,
    )

    async def factory() -> _WriteKernel:
        raise RuntimeError("synthetic kernel failure")

    async with running_http_client(
        application,
        operation_kernel_factory=factory,
    ) as client:
        discovered = await client.list_tools()
        assert tuple(tool.name for tool in discovered) == EXPECTED_TOOL_NAMES
        assert application.is_ready
