"""MCP server for the binnacle project — assembly only.

The FastMCP root composes focused Files, Search and Commands servers.
Their adapters and shared helpers live in binnacle.features.
Tool contracts are documented in docs/tools/ and docs/agent-toolset-design.md.
"""

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from binnacle.startup_imports import (
    StartupImportFailed,
    clear_record,
    import_runtime_modules,
    record_start_failure,
    serving_entry_marked,
    state_root_of,
)

# binnacle's own lines (event=tool_call/tool_result/job_*/config) go through
# the root handler as single lines with a millisecond local timestamp, so
# `journalctl -o cat` output stays self-describing; fastmcp's request lines
# keep their rich handler. Preserve journal names for existing log consumers.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("binnacle.server")

# E1: import the whole runtime tree now, after logging is configured, so this
# process never first-imports binnacle source that a later deploy synced.
# E1-a4: a required import failure raises StartupImportFailed (exit 70) here,
# before uvicorn binds the port.


def _argv_serving_process() -> bool:
    """True when argv names the uvicorn CLI (the dev unit), which serves
    ``binnacle.server:app`` but hands binnacle no Server object. Never a test,
    ``python -c``, ``binnacle`` itself (``binnacle serve`` marks itself instead)
    or any other importer."""
    entry = Path(sys.argv[0])
    return entry.name == "uvicorn" or (
        entry.name == "__main__.py" and entry.parent.name == "uvicorn"
    )


def _serving_process() -> bool:
    """True only in a process that serves ``binnacle.server:app``: the one
    ``binnacle serve`` marked (the deployed entry on the Mac and in the Linux
    prod unit), or one argv names (:func:`_argv_serving_process`)."""
    return serving_entry_marked() or _argv_serving_process()


def _record_import_failure(failure: StartupImportFailed) -> None:
    """E1-a5: the serving process's own record write (never an importer's)."""
    if not _serving_process():
        return
    try:
        # The guard executes before the normal config import; load config
        # only when recording a failure, and preserve the structured log
        # when the failed module itself prevents config import.
        from binnacle.config import get_settings as failure_settings

        root = state_root_of(failure_settings().jobs.dir)
    except Exception:  # noqa: BLE001 - no configured root: the log line remains
        logger.error("event=startup_import_record_error process=mcp-server")
        return
    record_start_failure("mcp-server", failure, root)


# Fail closed while every required Binnacle import is still guarded.
# Loading business/framework modules before this call lets SyntaxError escape
# without the required exit=70 or durable failure record (R6W3-01).
import_runtime_modules(on_failure=_record_import_failure)

from fastmcp import FastMCP

from binnacle.config import get_settings

# Preserve the public monkeypatch seam after (not before) the startup guard.
from binnacle.features.commands.commands_server import create_commands_server
from binnacle.features.commands.run_command_telemetry import (
    AUTO_BACKGROUND_SEMANTICS_VERSION,
    auto_background_behavior_hash,
    auto_background_policy_hash,
)
from binnacle.features.files.files_server import create_files_server
from binnacle.features.search.search_server import create_search_server
from binnacle.provenance import runtime_provenance

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
    _log_jobs_config(s)
    _log_tool_config(
        "edit_file", snippet_context_lines=s.edit_file.snippet_context_lines
    )


def _log_jobs_config(s) -> None:
    from binnacle.platform.composition import host_os_family

    if host_os_family() == "darwin":
        from binnacle.platform.contracts.darwin_release_scope import (
            release_scope_for_owner,
            resolve_darwin_job_owner,
        )

        owner = resolve_darwin_job_owner(s.jobs.owner)
        scope = release_scope_for_owner(owner)
        for tool in ("run_command", "job_status", "stop_job"):
            _log_tool_config(tool, capability=scope[tool].capability.state.value)
        if owner == "manager":
            # CR0-1.2.0 point 4: auto means manager on Darwin; say it at startup.
            logger.info(
                "event=jobs_owner configured_owner=%s effective_owner=manager "
                "service=com.binnacle.jobs socket=%s note=%s",
                s.jobs.owner,
                s.jobs.socket_path or "runtime-default",
                "command tools need the com.binnacle.jobs service; when it is "
                "absent they fail closed with 'job manager unavailable' and "
                "never fall back to embedded execution",
            )
        else:
            logger.info(
                "event=jobs_owner configured_owner=%s effective_owner=embedded",
                s.jobs.owner,
            )
        return
    from binnacle.features.commands import jobs

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


def _load_token() -> str:
    raw = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if raw == "Bearer":
        raise RuntimeError(f"Token file {TOKEN_FILE} is empty.")
    token = raw.removeprefix("Bearer ").strip()
    if not token:
        raise RuntimeError(f"Token file {TOKEN_FILE} is empty.")
    return token


def create_server() -> FastMCP:
    """Maintain the Linux production factory contract and its token bootstrap."""
    from binnacle.application import compose_native_tools, create_application
    from binnacle.features.commands.command_backend import create_command_backend
    from binnacle.platform.composition import host_os_family

    file_access = None
    if host_os_family() == "darwin":
        file_access, backend = compose_native_tools(settings=get_settings())
    else:
        backend = create_command_backend()
    return create_application(
        file_access=file_access,
        settings=get_settings(),
        token=_load_token(),
        backend=backend,
        files_factory=create_files_server,
        search_factory=create_search_server,
        commands_factory=create_commands_server,
    )


mcp = create_server()
log_effective_config()

app = mcp.http_app()

# The start-up import record is cleared only after a successful start of the
# serving process. ``binnacle serve`` (marked) owns its uvicorn server: the
# record is cleared when the public ``uvicorn.Server.started`` turns True, which
# uvicorn sets after the lifespan startup AND the bind. The uvicorn CLI (the dev
# unit) hands binnacle no Server object, so there the record is cleared
# START_CONFIRM_S after the ASGI lifespan startup if the process is still alive
# (uvicorn binds right after the lifespan and exits on a bind error). Under
# ``uvicorn --reload`` the supervisor binds first; this applies to the worker.
START_CONFIRM_S = 1.0


def _clear_record_after_start() -> None:
    try:
        root = state_root_of(get_settings().jobs.dir)
    except Exception:  # noqa: BLE001 - no configured root: nothing to clear
        return
    clear_record("mcp-server", root)


def _clear_record_when_server_started() -> None:
    """Clear the record once the uvicorn.Server this process runs has started."""
    import uvicorn

    original = uvicorn.Server.startup

    async def startup(self: Any, *args: Any, **kwargs: Any) -> None:
        await original(self, *args, **kwargs)
        configured_app = getattr(getattr(self, "config", None), "app", None)
        if (
            self.started
            and serving_entry_marked()
            and (configured_app is app or configured_app == "binnacle.server:app")
        ):
            # The hook is on uvicorn.Server globally: an unrelated server
            # must never clear Binnacle's durable failure record.
            _clear_record_after_start()

    uvicorn.Server.startup = startup  # type: ignore[method-assign]


if serving_entry_marked():
    _clear_record_when_server_started()
elif _argv_serving_process():
    _inner_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _lifespan(application: Any) -> AsyncIterator[Any]:
        async with _inner_lifespan(application) as state:
            asyncio.get_running_loop().call_later(
                START_CONFIRM_S, _clear_record_after_start
            )
            yield state

    app.router.lifespan_context = _lifespan


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="127.0.0.1",
        port=8000,
        show_banner=False,
    )
