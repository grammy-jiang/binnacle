"""MCP server for the binnacle project — assembly only.

One tool per module under tools/, mirroring docs/tools/<name>.md. Shared
helpers: paths.py (root guard), textio.py (decode/size). The design doc
is docs/agent-toolset-design.md.
"""

import importlib.metadata
import logging
import os

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier

from binnacle import jobs
from binnacle.config import get_settings
from binnacle.identity import ClientIdentity
from binnacle.logging_middleware import (
    RequestLoggingMiddleware,
    ToolLoggingMiddleware,
)
from binnacle.run_command_telemetry import auto_background_policy_hash
from binnacle.tools import register_all
from binnacle.visibility import ClientToolVisibility

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


def _version() -> str:
    try:
        return importlib.metadata.version("binnacle-mcp")
    except importlib.metadata.PackageNotFoundError:
        return "?"


def _log_tool_config(tool: str, **fields: object) -> None:
    rendered = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("event=tool_config tool=%s %s", tool, rendered)


def log_effective_config() -> None:
    """One journal line per (re)start naming the settings that change behavior."""
    s = get_settings()
    logger.info(
        "event=config pid=%d version=%s roots=%s jobs_dir=%s keep_newest=%d "
        "client_tools=%s auto_background=%s rg_bin=%s indexed_context=%s indexed_reconcile=%s "
        "indexed_max_open=%d tokenizer_enabled=%s tokenizer_encoding=%s "
        "tokenizer_clients=%s",
        os.getpid(),
        _version(),
        [str(r) for r in s.roots.allowed],
        s.jobs.dir,
        s.jobs.keep_newest,
        {prefix: len(tools) for prefix, tools in s.client_tools.items()},
        {
            prefix: len(patterns)
            for prefix, patterns in s.run_command.auto_background_patterns.items()
        },
        s.rg_bin,
        str(s.indexed_context.enabled).lower(),
        str(s.indexed_context.reconcile_on_query).lower(),
        s.indexed_context.max_open_indexes,
        str(s.telemetry.tokenizer.enabled).lower(),
        s.telemetry.tokenizer.encoding,
        ",".join(s.telemetry.tokenizer.client_prefixes),
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


mcp = FastMCP(
    "binnacle",
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
_identity = ClientIdentity()
mcp.add_middleware(
    RequestLoggingMiddleware(_identity, include_payloads=True, max_payload_length=500)
)
mcp.add_middleware(ToolLoggingMiddleware(_identity))
mcp.add_middleware(ClientToolVisibility(get_settings().client_tools, _identity))
register_all(mcp)
log_effective_config()

app = mcp.http_app()


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="127.0.0.1",
        port=8000,
        show_banner=False,
    )
