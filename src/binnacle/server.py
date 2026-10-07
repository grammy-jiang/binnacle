"""MCP server for the binnacle project — assembly only.

One tool per module under tools/, mirroring docs/tools/<name>.md. Shared
helpers: paths.py (root guard), textio.py (decode/size). The design doc
is docs/agent-toolset-design.md.
"""

import logging
import os

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from starlette.requests import Request
from starlette.responses import JSONResponse

from binnacle import jobs
from binnacle.config import get_settings
from binnacle.features.commands.commands_server import create_commands_server
from binnacle.features.files.files_server import create_files_server
from binnacle.features.search.search_server import create_search_server
from binnacle.identity import ClientIdentity
from binnacle.logging_middleware import (
    RequestLoggingMiddleware,
    ToolLoggingMiddleware,
)
from binnacle.provenance import runtime_provenance
from binnacle.run_command_telemetry import (
    AUTO_BACKGROUND_SEMANTICS_VERSION,
    auto_background_behavior_hash,
    auto_background_policy_hash,
)
from binnacle.tool_order import PublicToolOrder
from binnacle.visibility import ClientToolVisibility, ClientToolVisibilityTransform

# binnacle's own lines (event=tool_call/tool_result/job_*/config) go through
# the root handler as single lines with a millisecond local timestamp, so
# `journalctl -o cat` output stays self-describing; fastmcp's request lines
# keep their rich handler. Format read back by binnacle.logstats.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("binnacle.server")

TOKEN_FILE = get_settings().auth.token_file


def _log_tool_config(tool: str, **fields: object) -> None:
    rendered = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("event=tool_config tool=%s %s", tool, rendered)


def log_effective_config() -> None:
    """One journal line per (re)start naming the settings that change behavior."""
    s = get_settings()
    provenance = runtime_provenance()
    logger.info(
        "event=config pid=%d version=%s revision=%s roots=%s jobs_dir=%s keep_newest=%d "
        "client_tools=%s auto_background=%s rg_bin=%s "
        "tokenizer_enabled=%s tokenizer_encoding=%s "
        "tokenizer_clients=%s",
        os.getpid(),
        provenance.package_version,
        provenance.revision,
        [str(r) for r in s.roots.allowed],
        s.jobs.dir,
        s.jobs.keep_newest,
        {prefix: len(tools) for prefix, tools in s.client_tools.items()},
        {
            prefix: len(patterns)
            for prefix, patterns in s.run_command.auto_background_patterns.items()
        },
        s.rg_bin,
        str(s.telemetry.tokenizer.enabled).lower(),
        s.telemetry.tokenizer.encoding,
        ",".join(s.telemetry.tokenizer.client_prefixes),
    )
    for section in s.removed_sections:
        logger.warning(
            "event=config_warning section=%s reason=removed action=ignored",
            section,
        )
    for section in s.run_command.removed_sections:
        logger.warning(
            "event=config_warning section=run_command.%s reason=removed action=ignored",
            section,
        )
    for key in s.jobs.removed_keys:
        logger.warning(
            "event=config_warning section=jobs.%s reason=removed action=ignored",
            key,
        )
    _log_tool_config(
        "read_file",
        max_lines=s.read_file.max_lines,
        max_chars=s.read_file.max_chars,
        max_line_chars=s.read_file.max_line_chars,
        max_file_bytes=s.read_file.max_file_bytes,
    )
    _log_tool_config(
        "list_files",
        max_results_default=s.list_files.max_results_default,
        max_results_cap=s.list_files.max_results_cap,
        rg_timeout_s=s.list_files.rg_timeout_s,
        rg_bin=s.rg_bin,
    )
    _log_tool_config(
        "search_text",
        exact_execution=s.search_text.exact_execution,
        max_results_default=s.search_text.max_results_default,
        max_results_cap=s.search_text.max_results_cap,
        timeout_s=s.search_text.timeout_s,
        max_line_chars=s.search_text.max_line_chars,
        result_max_bytes=s.search_text.result_max_bytes,
        auto_context_single=s.search_text.auto_context_single,
        auto_context_few=s.search_text.auto_context_few,
        adaptive_enabled=str(s.search_text.adaptive_discovery_enabled).lower(),
        adaptive_detailed_files=s.search_text.adaptive_detailed_files,
        adaptive_total_files=s.search_text.adaptive_total_files,
        adaptive_representative_matches=s.search_text.adaptive_representative_matches,
        adaptive_snippet_chars=s.search_text.adaptive_snippet_chars,
    )
    _log_tool_config(
        "run_command",
        wait_default_s=s.run_command.wait_default_s,
        wait_max_s=s.run_command.wait_max_s,
        auto_background_clients=len(s.run_command.auto_background_patterns),
        auto_background_rules=sum(
            len(patterns)
            for patterns in s.run_command.auto_background_patterns.values()
        ),
        auto_background_policy_hash=auto_background_policy_hash(
            s.run_command.auto_background_patterns
        ),
        auto_background_behavior_hash=auto_background_behavior_hash(
            s.run_command.auto_background_patterns,
            s.jobs.warmup_s,
        ),
        auto_background_semantics_version=AUTO_BACKGROUND_SEMANTICS_VERSION,
        auto_background_warmup_s=s.jobs.warmup_s,
        auto_background_evidence_retention_days=(
            s.run_command.auto_background_evidence_retention_days
        ),
        auto_background_evidence_dir=s.run_command.auto_background_evidence_dir,
    )
    _log_tool_config(
        "jobs",
        configured_owner=s.jobs.owner,
        effective_owner=jobs.OWNER_MODE,
        keep_newest=s.jobs.keep_newest,
        listing_history_limit=s.jobs.listing_history_limit,
        listing_command_preview_chars=s.jobs.listing_command_preview_chars,
        max_output_chars=s.jobs.max_output_chars,
        warmup_s=s.jobs.warmup_s,
        quiet_after_s=s.jobs.quiet_after_s,
        stop_sigterm_grace_s=jobs.STOP_SIGTERM_GRACE_S,
        stop_sigkill_grace_s=jobs.STOP_SIGKILL_GRACE_S,
    )
    _log_tool_config(
        "edit_file", snippet_context_lines=s.edit_file.snippet_context_lines
    )


def _load_token() -> str:
    raw = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if raw == "Bearer":
        raise RuntimeError(f"Token file {TOKEN_FILE} is empty.")
    token = raw.removeprefix("Bearer ").strip()
    if not token:
        raise RuntimeError(f"Token file {TOKEN_FILE} is empty.")
    return token


def create_server() -> FastMCP:
    """Build a fresh root with the existing auth, middleware, and tool surface."""
    settings = get_settings().model_copy(deep=True)
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
            tokens={_load_token(): {"client_id": "binnacle-tunnel"}},
        ),
    )
    identity = ClientIdentity()
    root.add_middleware(
        RequestLoggingMiddleware(
            identity, include_payloads=True, max_payload_length=500
        )
    )
    root.add_middleware(
        ToolLoggingMiddleware(identity, tokenizer=settings.telemetry.tokenizer)
    )
    root.add_middleware(ClientToolVisibility(settings.client_tools, identity))
    root.add_transform(PublicToolOrder())
    root.add_transform(ClientToolVisibilityTransform())
    root.mount(
        create_files_server(
            roots=settings.roots,
            read_settings=settings.read_file,
            list_settings=settings.list_files,
            edit_settings=settings.edit_file,
            rg_bin=settings.rg_bin,
        )
    )
    root.mount(
        create_search_server(
            roots=settings.roots,
            search_settings=settings.search_text,
            rg_bin=settings.rg_bin,
        )
    )
    root.mount(
        create_commands_server(
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


mcp = create_server()
log_effective_config()

app = mcp.http_app()


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="127.0.0.1",
        port=8000,
        show_banner=False,
    )
