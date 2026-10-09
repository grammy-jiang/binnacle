"""OS-independent native FastMCP composition; inject long-lived domain backends.

FastMCP alone owns registration, providers, middleware, transforms and lifespan.
This module does not inspect or select the host platform, load a token from disk
or import durable jobs / Linux adapters. Normal production composition remains
in binnacle.server for backward-compatible CLI and ASGI exports.
"""

from collections.abc import Callable
from functools import partial

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from starlette.requests import Request
from starlette.responses import JSONResponse

from binnacle.config import Settings
from binnacle.features.commands.command_contracts import CommandBackend
from binnacle.features.commands.commands_server import create_commands_server
from binnacle.features.files.files_server import create_files_server
from binnacle.features.search.search_server import create_search_server
from binnacle.mcp.identity import ClientIdentity
from binnacle.mcp.logging_middleware import (
    RequestLoggingMiddleware,
    ToolLoggingMiddleware,
)
from binnacle.mcp.tool_order import PublicToolOrder
from binnacle.mcp.visibility import ClientToolVisibility, ClientToolVisibilityTransform
from binnacle.observability.log_safety import safe_request_payload


def create_application(
    *,
    settings: Settings,
    token: str,
    backend: CommandBackend,
    files_factory: Callable[..., FastMCP] = create_files_server,
    search_factory: Callable[..., FastMCP] = create_search_server,
    commands_factory: Callable[..., FastMCP] = create_commands_server,
) -> FastMCP:
    """Build a pure native FastMCP tree from supplied application dependencies."""
    settings = settings.model_copy(deep=True)
    root = FastMCP(
        "binnacle",
        on_duplicate="error",
        # A tool map only. Workflow rules live in the ChatGPT Project's
        # instructions (the single client in use); tool contracts live in the
        # tool descriptions. First 512 chars self-contained (OpenAI guidance).
        instructions=(
            "binnacle: a Raspberry Pi 5 development workstation. Paths live under "
            "~/Projects and /tmp. list_files (browse or glob), search_text (regex "
            "over contents), read_file, edit_file (exact-string replace), "
            "write_file (whole file), run_command (shell; long commands become "
            "jobs for job_status/stop_job). Pi hardware and health: run_command "
            "(vcgencmd, pinctrl, i2cdetect, libcamera-still)."
        ),
        auth=StaticTokenVerifier(
            tokens={token: {"client_id": "binnacle-tunnel"}},
        ),
    )
    identity = ClientIdentity()
    root.add_middleware(
        RequestLoggingMiddleware(
            identity,
            include_payloads=True,
            max_payload_length=500,
            payload_serializer=partial(
                safe_request_payload, root=settings.roots.default_root
            ),
        )
    )
    root.add_middleware(
        ToolLoggingMiddleware(
            identity,
            tokenizer=settings.telemetry.tokenizer,
            path_root=settings.roots.default_root,
        )
    )
    root.add_middleware(ClientToolVisibility(settings.client_tools, identity))
    root.add_transform(PublicToolOrder())
    root.add_transform(ClientToolVisibilityTransform())
    root.mount(
        files_factory(
            roots=settings.roots,
            read_settings=settings.read_file,
            list_settings=settings.list_files,
            edit_settings=settings.edit_file,
            rg_bin=settings.rg_bin,
        )
    )
    root.mount(
        search_factory(
            roots=settings.roots,
            search_settings=settings.search_text,
            rg_bin=settings.rg_bin,
        )
    )
    root.mount(
        commands_factory(
            backend=backend,
            roots=settings.roots,
            run_settings=settings.run_command,
            quiet_after_s=settings.jobs.quiet_after_s,
            listing_history_limit=settings.jobs.listing_history_limit,
            listing_command_preview_chars=settings.jobs.listing_command_preview_chars,
        )
    )

    @root.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(request: Request) -> JSONResponse:
        """Process liveness only; no auth, readiness, or host-state disclosure."""
        return JSONResponse({"status": "ok"})

    return root
