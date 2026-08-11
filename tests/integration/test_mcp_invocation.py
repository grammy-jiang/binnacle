"""Real MCP invocation, envelope, and validation-boundary tests."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent
from tests.support import running_http_client

from binnacle.application import BinnacleApplication, CompatibilityUseCases
from binnacle.contracts import ContractRegistry
from binnacle.domain.mcp import (
    McpCallContext,
    ProbeResultFormatsData,
    ProbeResultFormatsRequest,
    SuccessEnvelope,
    ToolIdentity,
)

REQUEST_ID = re.compile(r"^req_[a-f0-9]{32}$")


class RecordingLogger:
    """Capture bounded structured events without configuring global logging."""

    def __init__(
        self,
        records: list[tuple[str, str, dict[str, Any]]] | None = None,
        bound: dict[str, Any] | None = None,
    ) -> None:
        self.records = records if records is not None else []
        self.bound = bound or {}

    def bind(self, **values: Any) -> RecordingLogger:
        return RecordingLogger(self.records, {**self.bound, **values})

    def info(self, event: str, **values: Any) -> None:
        self.records.append(("info", event, {**self.bound, **values}))

    def error(self, event: str, **values: Any) -> None:
        self.records.append(("error", event, {**self.bound, **values}))


def _structured(result: CallToolResult) -> dict[str, object]:
    assert result.structured_content is not None
    return result.structured_content


@pytest.mark.anyio
async def test_local_client_invokes_all_five_tools(
    phase2_application: BinnacleApplication,
    contract_registry: ContractRegistry,
) -> None:
    requests: tuple[tuple[str, dict[str, object]], ...] = (
        ("binnacle_probe", {}),
        ("system_inspect", {"sections": ["cpu"]}),
        (
            "probe_result_formats",
            {"array_length": 3, "nullable_value": "fixture", "include_warning": True},
        ),
        ("probe_error", {"case": "bounded_delay", "delay_ms": 1}),
        ("compatibility_report", {}),
    )

    async with running_http_client(phase2_application) as client:
        results = [(name, await client.call_tool(name, arguments)) for name, arguments in requests]

    for name, result in results:
        structured = _structured(result)
        assert result.is_error is False
        assert result.content
        text = result.content[0]
        assert isinstance(text, TextContent)
        assert len(text.text.encode("utf-8")) <= 4096
        assert name in text.text
        assert structured["call_status"] == "succeeded"
        assert structured["operation"] is None
        assert structured["evidence"] == []
        assert isinstance(structured["request_id"], str)
        assert REQUEST_ID.fullmatch(structured["request_id"])
        tool = structured["tool"]
        assert isinstance(tool, dict)
        assert tool == {"name": name, "contract_version": "1.1"}
        contract_registry.validate_output(name, structured)


@pytest.mark.anyio
async def test_synthetic_execution_error_is_a_successful_mcp_exchange(
    phase2_application: BinnacleApplication,
    contract_registry: ContractRegistry,
) -> None:
    async with running_http_client(phase2_application) as client:
        result = await client.call_tool(
            "probe_error",
            {"case": "policy_rejection"},
            raise_on_error=False,
        )

    structured = _structured(result)
    assert result.is_error is True
    assert structured["call_status"] == "execution_error"
    error = structured["error"]
    assert isinstance(error, dict)
    assert error["code"] == "policy_rejected"
    text = result.content[0]
    assert isinstance(text, TextContent)
    assert "policy_rejected" in text.text
    contract_registry.validate_output("probe_error", structured)


@pytest.mark.anyio
async def test_schema_invalid_input_never_invokes_application_binding(
    phase2_application: BinnacleApplication,
    compatibility_use_cases: CompatibilityUseCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = False

    async def should_not_run(
        request: ProbeResultFormatsRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[ProbeResultFormatsData]:
        del request, context
        nonlocal invoked
        invoked = True
        raise AssertionError("invalid input reached use case")

    monkeypatch.setattr(
        compatibility_use_cases,
        "probe_result_formats",
        should_not_run,
    )

    async with running_http_client(phase2_application) as client:
        result = await client.call_tool(
            "probe_result_formats",
            {"array_length": 17},
            raise_on_error=False,
        )

    assert result.is_error is True
    assert invoked is False


@pytest.mark.anyio
async def test_output_schema_failure_cannot_be_sent_as_success(
    phase2_application: BinnacleApplication,
    compatibility_use_cases: CompatibilityUseCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def invalid_output(
        request: ProbeResultFormatsRequest,
        context: McpCallContext,
    ) -> SuccessEnvelope[ProbeResultFormatsData]:
        del request
        return SuccessEnvelope(
            schema_version="1.1",
            call_status="succeeded",
            tool=ToolIdentity(name="probe_result_formats", contract_version="1.1"),
            request_id=context.request_id,
            data=ProbeResultFormatsData(
                string_value="fixture",
                integer_value=42,
                boolean_value=True,
                nullable_value=None,
                array_values=tuple(range(17)),
                nested={"name": "nested", "enabled": True},
                warning_included=False,
            ),
        )

    monkeypatch.setattr(
        compatibility_use_cases,
        "probe_result_formats",
        invalid_output,
    )

    async with running_http_client(phase2_application) as client:
        result = await client.call_tool(
            "probe_result_formats",
            {},
            raise_on_error=False,
        )

    assert result.is_error is True
    assert result.structured_content is None


@pytest.mark.anyio
async def test_tool_logs_are_correlated_bounded_and_payload_free(
    phase2_application: BinnacleApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = RecordingLogger()
    secret_input = "input-that-must-not-enter-logs"
    monkeypatch.setattr("binnacle.adapters.mcp._LOGGER", logger)

    async with running_http_client(phase2_application) as client:
        await client.call_tool(
            "probe_result_formats",
            {
                "include_warning": True,
                "nullable_value": secret_input,
                "array_length": 2,
            },
        )

    started = next(record for record in logger.records if record[1] == "mcp_tool_call_started")
    finished = next(record for record in logger.records if record[1] == "mcp_tool_call_finished")
    assert REQUEST_ID.fullmatch(started[2]["request_id"])
    assert started[2] == {
        "request_id": started[2]["request_id"],
        "tool_name": "probe_result_formats",
        "contract_version": "1.1",
        "protocol_revision": "2026-07-28",
        "protocol_era": "modern",
    }
    assert finished[2]["call_status"] == "succeeded"
    assert finished[2]["warning_codes"] == ["synthetic_probe_warning"]
    assert secret_input not in json.dumps(logger.records, sort_keys=True)
