"""FastMCP/Uvicorn adaptation for the read-only compatibility server."""

from __future__ import annotations

import importlib
import json
import math
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, MutableMapping
from contextlib import asynccontextmanager, suppress
from typing import Any, Protocol, TypeAlias, cast

import structlog
import uvicorn
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_context
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import FunctionTool
from mcp.shared.exceptions import MCPError
from mcp.shared.inbound import (
    MCP_METHOD_HEADER,
    MCP_NAME_HEADER,
    MCP_PROTOCOL_VERSION_HEADER,
    NAME_BEARING_METHODS,
    decode_header_value,
    find_duplicated_routing_header,
)
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    PROTOCOL_VERSION_META_KEY,
    UNSUPPORTED_PROTOCOL_VERSION,
    CallToolResult,
    TextContent,
    ToolAnnotations,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from binnacle.application import BinnacleApplication, CompatibilityUseCases
from binnacle.contracts import (
    EXPECTED_REVISIONS,
    ContractRegistry,
    InputContractError,
    OutputContractError,
    ToolContract,
    mutable_json_object,
)
from binnacle.domain.mcp import (
    BinnacleProbeRequest,
    CompatibilityReportRequest,
    ExecutionErrorEnvelope,
    McpCallContext,
    ProbeErrorCase,
    ProbeErrorRequest,
    ProbeResultFormatsRequest,
    ProtocolEra,
    SuccessEnvelope,
    SystemInspectRequest,
    envelope_to_mapping,
)
from binnacle.domain.system import SystemSection

ASGIMessage: TypeAlias = MutableMapping[str, Any]
ASGIReceive: TypeAlias = Callable[[], Awaitable[ASGIMessage]]
ASGISend: TypeAlias = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp: TypeAlias = Callable[
    [MutableMapping[str, Any], ASGIReceive, ASGISend],
    Awaitable[None],
]
ToolEnvelope: TypeAlias = SuccessEnvelope[object] | ExecutionErrorEnvelope
RevisionRejection: TypeAlias = tuple[int, str, str]
TARGET_REVISION = EXPECTED_REVISIONS[0]
LEGACY_REVISIONS = frozenset(EXPECTED_REVISIONS[1:])
MCP_SESSION_ID_HEADER = "mcp-session-id"
MAX_BODY_CHUNKS = 1024
_LOGGER = structlog.get_logger(__name__)


class ServerConfiguration(Protocol):
    @property
    def host(self) -> str: ...

    @property
    def port(self) -> int: ...

    @property
    def workers(self) -> int: ...

    @property
    def max_request_bytes(self) -> int: ...

    @property
    def graceful_shutdown_seconds(self) -> float: ...


class ManifestHandler(Protocol):
    async def __call__(
        self,
        *,
        use_cases: CompatibilityUseCases,
        request: object,
        context: McpCallContext,
    ) -> ToolEnvelope: ...


class RequestBodyLimitMiddleware:
    """Bound MCP bodies and enforce Binnacle's narrow revision integrity rules."""

    def __init__(self, app: ASGIApp, *, max_request_bytes: int) -> None:
        if max_request_bytes <= 0:
            raise ValueError("max_request_bytes must be positive")
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        if not (scope.get("type") == "http" and scope.get("path") == "/mcp"):
            await self.app(scope, receive, send)
            return

        if scope.get("method") != "POST":
            rejection = self._validate_transport_revision(scope)
            if rejection is not None:
                code, data_code, error_message = rejection
                await _send_jsonrpc_error(
                    send,
                    request_id=None,
                    code=code,
                    data_code=data_code,
                    message=error_message,
                )
                return
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", ())
        content_lengths = [
            value
            for name, value in headers
            if isinstance(name, bytes) and name.lower() == b"content-length"
        ]
        if len(content_lengths) > 1:
            await _send_http_error(send, 400, "invalid_content_length")
            return
        if content_lengths:
            try:
                declared_length = int(content_lengths[-1])
            except ValueError:
                await _send_http_error(send, 400, "invalid_content_length")
                return
            if declared_length < 0:
                await _send_http_error(send, 400, "invalid_content_length")
                return
            if declared_length > self.max_request_bytes:
                await _send_http_error(send, 413, "request_too_large")
                return

        body_buffer = bytearray()
        chunk_count = 0
        disconnected = False
        saw_request = False
        total = 0
        while True:
            message = await receive()
            message_type = message.get("type")
            if message_type == "http.disconnect":
                disconnected = True
                break
            if message_type != "http.request":
                await _send_http_error(send, 400, "invalid_request_body")
                return
            saw_request = True
            chunk_count += 1
            if chunk_count > MAX_BODY_CHUNKS:
                await _send_http_error(send, 413, "request_too_large")
                return
            body = message.get("body", b"")
            if not isinstance(body, bytes):
                await _send_http_error(send, 400, "invalid_request_body")
                return
            if len(body) > self.max_request_bytes - total:
                await _send_http_error(send, 413, "request_too_large")
                return
            total += len(body)
            body_buffer.extend(body)
            if not message.get("more_body", False):
                break

        body = bytes(body_buffer)
        replay_messages: list[ASGIMessage]
        if disconnected:
            replay_messages = []
            if saw_request:
                replay_messages.append({"type": "http.request", "body": body, "more_body": True})
            replay_messages.append({"type": "http.disconnect"})
        else:
            replay_messages = [{"type": "http.request", "body": body}]

        async def replay() -> ASGIMessage:
            if replay_messages:
                return replay_messages.pop(0)
            return await receive()

        parsed: object = None
        if body:
            with suppress(UnicodeDecodeError, json.JSONDecodeError):
                parsed = json.loads(body)

        if isinstance(parsed, dict):
            rejection = self._validate_revision_request(scope, parsed)
            if rejection is not None:
                code, data_code, error_message = rejection
                await _send_jsonrpc_error(
                    send,
                    request_id=parsed.get("id"),
                    code=code,
                    data_code=data_code,
                    message=error_message,
                )
                return

        await self.app(scope, replay, send)

    def _validate_transport_revision(
        self,
        scope: MutableMapping[str, Any],
    ) -> RevisionRejection | None:
        raw_headers = [
            (name.decode("latin-1"), value.decode("latin-1"))
            for name, value in scope.get("headers", ())
            if isinstance(name, bytes) and isinstance(value, bytes)
        ]
        headers = {name.lower(): value for name, value in raw_headers}
        duplicate = find_duplicated_routing_header(raw_headers)
        if duplicate is not None:
            return (
                -32020,
                "protocol_header_mismatch",
                f"Duplicate routing header: {duplicate}",
            )

        header_version = headers.get(MCP_PROTOCOL_VERSION_HEADER)
        if header_version is None:
            return (
                -32021,
                "unsupported_protocol_version",
                "The transport request is missing MCP-Protocol-Version.",
            )
        if header_version not in EXPECTED_REVISIONS:
            return (
                -32021,
                "unsupported_protocol_version",
                "The transport request does not declare a reviewed protocol revision.",
            )
        if header_version == TARGET_REVISION and MCP_SESSION_ID_HEADER in headers:
            return (
                -32020,
                "protocol_header_mismatch",
                "The target revision prohibits Mcp-Session-Id.",
            )
        return None

    def _validate_revision_request(
        self,
        scope: MutableMapping[str, Any],
        body: Mapping[str, Any],
    ) -> RevisionRejection | None:
        raw_headers = [
            (name.decode("latin-1"), value.decode("latin-1"))
            for name, value in scope.get("headers", ())
            if isinstance(name, bytes) and isinstance(value, bytes)
        ]
        headers = {name.lower(): value for name, value in raw_headers}
        method = body.get("method")
        params = body.get("params")
        meta = params.get("_meta") if isinstance(params, Mapping) else None
        declared = meta.get(PROTOCOL_VERSION_META_KEY) if isinstance(meta, Mapping) else None
        header_version = headers.get(MCP_PROTOCOL_VERSION_HEADER)
        duplicate = find_duplicated_routing_header(raw_headers)
        if duplicate is not None:
            return (
                -32020,
                "protocol_header_mismatch",
                f"Duplicate routing header: {duplicate}",
            )

        if (
            isinstance(method, str)
            and method != "initialize"
            and declared is None
            and header_version is None
        ):
            return (
                -32021,
                "unsupported_protocol_version",
                "The request is missing MCP-Protocol-Version.",
            )
        if (
            isinstance(method, str)
            and method != "initialize"
            and declared is None
            and header_version not in EXPECTED_REVISIONS
        ):
            return (
                -32021,
                "unsupported_protocol_version",
                "The request does not declare a reviewed protocol revision.",
            )

        modern_signal = declared is not None or header_version == TARGET_REVISION
        if method == "initialize" and modern_signal:
            return (
                -32021,
                "unsupported_protocol_version",
                "The reviewed target revision does not support initialize.",
            )
        if modern_signal:
            if not isinstance(declared, str) or declared != TARGET_REVISION:
                return (
                    -32021,
                    "unsupported_protocol_version",
                    "The target request does not declare the reviewed modern revision.",
                )
            if header_version is None:
                return (
                    -32021,
                    "unsupported_protocol_version",
                    "The target request is missing MCP-Protocol-Version.",
                )
            if header_version != declared:
                return (
                    -32020,
                    "protocol_header_mismatch",
                    "MCP-Protocol-Version does not match the request envelope.",
                )
            if MCP_SESSION_ID_HEADER in headers:
                return (
                    -32020,
                    "protocol_header_mismatch",
                    "The target revision prohibits Mcp-Session-Id.",
                )
            if headers.get(MCP_METHOD_HEADER) != method:
                return (
                    -32020,
                    "protocol_header_mismatch",
                    "Mcp-Method does not match the JSON-RPC method.",
                )
            name_field = NAME_BEARING_METHODS.get(method) if isinstance(method, str) else None
            if name_field is not None and isinstance(params, Mapping):
                body_name = params.get(name_field)
                if (
                    body_name is not None
                    and decode_header_value(headers.get(MCP_NAME_HEADER)) != body_name
                ):
                    return (
                        -32020,
                        "protocol_header_mismatch",
                        "Mcp-Name does not match the named JSON-RPC target.",
                    )
            return None

        if method == "initialize" and isinstance(params, Mapping):
            requested = params.get("protocolVersion")
            if not isinstance(requested, str) or requested not in LEGACY_REVISIONS:
                return (
                    -32021,
                    "unsupported_protocol_version",
                    "The initialize request does not declare a reviewed legacy revision.",
                )
            if header_version is not None and header_version != requested:
                return (
                    -32020,
                    "protocol_header_mismatch",
                    "MCP-Protocol-Version does not match initialize.",
                )
            return None

        session_id = headers.get(MCP_SESSION_ID_HEADER)
        if session_id is not None and header_version is None:
            return (
                -32021,
                "unsupported_protocol_version",
                "The legacy session request is missing MCP-Protocol-Version.",
            )
        if session_id is not None and header_version not in LEGACY_REVISIONS:
            return (
                -32021,
                "unsupported_protocol_version",
                "The legacy session request does not declare a reviewed revision.",
            )
        return None


async def _send_http_error(send: ASGISend, status: int, code: str) -> None:
    body = json.dumps({"error": code}, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _send_jsonrpc_error(
    send: ASGISend,
    *,
    request_id: object,
    code: int,
    data_code: str,
    message: str,
) -> None:
    identifier = request_id if isinstance(request_id, (str, int)) else None
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": identifier,
            "error": {
                "code": code,
                "message": message,
                "data": {
                    "code": data_code,
                    "supported": list(EXPECTED_REVISIONS),
                },
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 400,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RevisionGuardMiddleware(Middleware):
    """Reject protocol revisions outside Binnacle's reviewed finite set."""

    def __init__(self, supported_revisions: tuple[str, ...]) -> None:
        self._supported_revisions = frozenset(supported_revisions)

    async def on_initialize(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        requested = context.message.params.protocol_version
        self._require_supported(requested)
        return await call_next(context)

    async def on_message(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is not None and fastmcp_context.request_context is not None:
            request_context = fastmcp_context.request_context
            self._require_supported(request_context.protocol_version)
            request = request_context.request
            if (
                context.method != "initialize"
                and request_context.protocol_version in LEGACY_REVISIONS
                and request is not None
            ):
                header_version = request.headers.get(MCP_PROTOCOL_VERSION_HEADER)
                if header_version != request_context.protocol_version:
                    raise MCPError(
                        -32020,
                        "MCP-Protocol-Version does not match the negotiated legacy session.",
                    )
        return await call_next(context)

    def _require_supported(self, revision: str) -> None:
        if revision not in self._supported_revisions:
            raise MCPError(
                UNSUPPORTED_PROTOCOL_VERSION,
                f"Unsupported Binnacle MCP revision: {revision}",
            )


def create_mcp_server(application: BinnacleApplication) -> FastMCP[None]:
    """Create the exact five-Tool compatibility-core FastMCP server."""

    contracts = application.contracts
    tool_count = len(contracts.tools)

    @asynccontextmanager
    async def lifespan(_server: FastMCP[None]) -> AsyncIterator[None]:
        application.set_registered_tool_count(tool_count)
        _LOGGER.info("application_starting", registered_tool_count=tool_count)
        try:
            await application.start()
        except Exception as exc:
            application.set_registered_tool_count(0)
            _LOGGER.error(
                "application_start_failed",
                error_type=type(exc).__name__,
            )
            raise
        _LOGGER.info("application_started", registered_tool_count=tool_count)
        try:
            yield
        finally:
            application.set_registered_tool_count(0)
            _LOGGER.info("application_stopping")
            await application.stop()
            _LOGGER.info("application_stopped")

    server = FastMCP[None](
        name="Binnacle",
        version=application.identity.version,
        lifespan=lifespan,
        middleware=[RevisionGuardMiddleware(contracts.supported_revisions)],
        tasks=False,
    )

    for contract in contracts.tools.values():
        server.add_tool(_create_function_tool(application, contracts, contract))
    application.set_registered_tool_count(tool_count)

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def health(_request: Request) -> Response:
        _LOGGER.info("health_checked", status="healthy")
        return JSONResponse({"status": "healthy"}, status_code=200)

    @server.custom_route("/readyz", methods=["GET"], include_in_schema=False)
    async def readiness(_request: Request) -> Response:
        if application.is_ready:
            _LOGGER.info("readiness_checked", status="ready")
            return JSONResponse({"status": "ready"}, status_code=200)
        _LOGGER.info(
            "readiness_checked",
            status="not_ready",
            reason_code="application_not_started",
        )
        return JSONResponse(
            {"status": "not_ready", "reasons": ["application_not_started"]},
            status_code=503,
        )

    return server


def _create_function_tool(
    application: BinnacleApplication,
    contracts: ContractRegistry,
    contract: ToolContract,
) -> FunctionTool:
    handler = _load_handler(contract.handler_binding)

    async def invoke(**arguments: Any) -> CallToolResult:
        try:
            contracts.validate_input(contract.name, arguments)
            request = _request_from_arguments(contract.name, arguments)
        except (InputContractError, KeyError, TypeError, ValueError) as exc:
            raise MCPError(INVALID_PARAMS, str(exc)) from exc

        framework_context = get_context()
        request_context = framework_context.request_context
        if request_context is None:
            raise MCPError(INTERNAL_ERROR, "MCP request context is unavailable")
        revision = request_context.protocol_version
        try:
            era = ProtocolEra(contracts.era_for(revision))
        except (InputContractError, ValueError) as exc:
            raise MCPError(UNSUPPORTED_PROTOCOL_VERSION, str(exc)) from exc
        context = McpCallContext(
            revision=revision,
            era=era,
            request_id=f"req_{secrets.token_hex(16)}",
        )
        call_logger = _LOGGER.bind(
            request_id=context.request_id,
            tool_name=contract.name,
            contract_version=contract.contract_version,
            protocol_revision=revision,
            protocol_era=era.value,
        )
        call_logger.info("mcp_tool_call_started")
        try:
            result = await handler(
                use_cases=application.compatibility,
                request=request,
                context=context,
            )
            structured = envelope_to_mapping(result)
            contracts.validate_output(contract.name, structured)
        except OutputContractError as exc:
            call_logger.error(
                "mcp_tool_call_finished",
                call_status="internal_error",
                error_type=type(exc).__name__,
            )
            raise MCPError(INTERNAL_ERROR, "Binnacle output contract validation failed") from exc
        except Exception as exc:
            call_logger.error(
                "mcp_tool_call_finished",
                call_status="internal_error",
                error_type=type(exc).__name__,
            )
            raise
        raw_warnings = structured.get("warnings")
        warning_codes = (
            [
                warning.get("code")
                for warning in raw_warnings
                if isinstance(warning, dict) and isinstance(warning.get("code"), str)
            ]
            if isinstance(raw_warnings, list)
            else []
        )
        error = structured.get("error")
        error_code = error.get("code") if isinstance(error, dict) else None
        call_logger.info(
            "mcp_tool_call_finished",
            call_status=structured.get("call_status", "internal_error"),
            warning_codes=warning_codes,
            error_code=error_code,
        )
        text = _model_readable_text(structured)
        return CallToolResult(
            content=[TextContent(text=text)],
            structured_content=structured,
            is_error=structured.get("call_status") == "execution_error",
        )

    return FunctionTool(
        fn=invoke,
        name=contract.name,
        version=contract.contract_version,
        title=contract.title,
        description=contract.description,
        parameters=mutable_json_object(contract.input_schema.schema),
        output_schema=mutable_json_object(contract.output_schema.schema),
        annotations=ToolAnnotations.model_validate(dict(contract.annotations)),
        run_in_thread=False,
    )


def _load_handler(binding: str) -> ManifestHandler:
    module_name, _, attribute_name = binding.rpartition(".")
    module = importlib.import_module(module_name)
    return cast(ManifestHandler, getattr(module, attribute_name))


def _request_from_arguments(tool_name: str, arguments: Mapping[str, Any]) -> object:
    if tool_name == "binnacle_probe":
        return BinnacleProbeRequest()
    if tool_name == "system_inspect":
        raw_sections = arguments.get("sections")
        sections = None
        if raw_sections is not None:
            if not isinstance(raw_sections, list):
                raise TypeError("sections must be an array")
            sections = tuple(SystemSection(value) for value in raw_sections)
        return SystemInspectRequest(sections=sections)
    if tool_name == "probe_result_formats":
        return ProbeResultFormatsRequest(
            include_warning=arguments.get("include_warning", False),
            nullable_value=arguments.get("nullable_value"),
            array_length=arguments.get("array_length", 3),
        )
    if tool_name == "probe_error":
        return ProbeErrorRequest(
            case=ProbeErrorCase(arguments["case"]),
            delay_ms=arguments.get("delay_ms"),
        )
    if tool_name == "compatibility_report":
        return CompatibilityReportRequest()
    raise InputContractError(f"unknown Tool contract: {tool_name}")


def _model_readable_text(structured: Mapping[str, Any]) -> str:
    tool = structured.get("tool")
    tool_name = tool.get("name", "unknown") if isinstance(tool, dict) else "unknown"
    request_id = structured.get("request_id", "unknown")
    if structured.get("call_status") == "execution_error":
        error = structured.get("error")
        if isinstance(error, dict):
            text = (
                f"{tool_name} execution error {error.get('code', 'unknown')}: "
                f"{error.get('message', 'No message')} (request {request_id})"
            )
        else:
            text = f"{tool_name} execution error (request {request_id})"
    else:
        facts = []
        data = structured.get("data")
        if isinstance(data, dict):
            for key in (
                "build_version",
                "device_id",
                "protocol_revision",
                "hostname",
                "profile_version",
                "string_value",
                "case",
            ):
                if key in data:
                    facts.append(f"{key}={json.dumps(data[key], ensure_ascii=False)}")
        text = f"{tool_name} succeeded (request {request_id})"
        if facts:
            text += ": " + ", ".join(facts)
    warnings = structured.get("warnings")
    if isinstance(warnings, list):
        codes = [item.get("code") for item in warnings if isinstance(item, dict)]
        if codes:
            text += "; warnings=" + ",".join(str(code) for code in codes)
    encoded = text.encode("utf-8")
    if len(encoded) <= 4096:
        return text
    return encoded[:4096].decode("utf-8", errors="ignore")


def create_http_app(
    application: BinnacleApplication,
    *,
    max_request_bytes: int = 1_048_576,
) -> ASGIApp:
    """Return FastMCP's native stateless Streamable HTTP application at ``/mcp``."""

    server = create_mcp_server(application)
    # The SDK routes 2026-era requests to its sessionless modern path while
    # retaining negotiated sessions for the three reviewed legacy revisions.
    app = cast(ASGIApp, server.http_app(path="/mcp", stateless_http=False))
    return RequestBodyLimitMiddleware(app, max_request_bytes=max_request_bytes)


def run_http_server(
    *,
    application: BinnacleApplication,
    settings: ServerConfiguration,
) -> None:
    """Run the unauthenticated Phase 2 server on a canonical loopback address."""

    if settings.workers != 1:
        msg = "Binnacle's application-object server requires exactly one worker"
        raise ValueError(msg)
    if settings.host not in {"127.0.0.1", "::1"}:
        raise ValueError("Phase 2 MCP server requires canonical loopback bind")
    uvicorn.run(
        create_http_app(
            application,
            max_request_bytes=settings.max_request_bytes,
        ),
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        log_config=None,
        timeout_graceful_shutdown=math.ceil(settings.graceful_shutdown_seconds),
    )
