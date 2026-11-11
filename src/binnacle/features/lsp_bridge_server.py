"""Read-only ChatGPT-facing bridge to the separately isolated P4 Pyright MCP.

The bridge runs inside the *authenticated main Binnacle MCP* process but never
launches a provider, changes provider authority, or exports private credentials.
Only the operator-started P4 service on 127.0.0.1 is allowed to execute LSP
requests. The workspace is fixed by the host; clients cannot supply a root,
URL, port, token or opaque grant handle.

Enable only with BINNACLE_LSP_BRIDGE_STATE_DIR in the main server environment,
after deploying a P4 private service granted exactly one trusted workspace.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

_MAX_RESULT_BYTES = 200_000
_TIMEOUT_SECONDS = 150


def _private_text(path: Path) -> str:
    """Read an owned, 0600 regular file without following its final symlink."""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(path, flags)
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        meta = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_uid != os.getuid()
            or (stat.S_IMODE(meta.st_mode) & 0o077) != 0
        ):
            raise ValueError("private_lsp_state_permissions_invalid")
        return handle.read(_MAX_RESULT_BYTES + 1)


def _credentials(state_dir: Path, workspace: Path) -> tuple[str, str]:
    """Admit only one host-granted workspace; reject stale/multiple grants."""
    token = _private_text(state_dir / "token").strip()
    if not 32 <= len(token) <= 256:
        raise ValueError("private_lsp_token_invalid")
    grants = json.loads(_private_text(state_dir / "grants.json"))
    mapping = grants.get("grants")
    if (
        not isinstance(mapping, dict)
        or len(mapping) != 1
        or not isinstance(grants.get("pid"), int)
    ):
        raise ValueError("private_lsp_grant_invalid")
    handle, name = next(iter(mapping.items()))
    if (
        not isinstance(handle, str)
        or not handle.startswith("wsg_")
        or name != workspace.name
    ):
        raise ValueError("private_lsp_grant_invalid")
    return token, handle


def create_lsp_bridge_server(
    *,
    state_dir: Path,
    workspace: Path,
    port: int = 18767,
) -> FastMCP:
    """Create a focused child; server startup is inert when this isn't mounted."""
    if not (1024 <= port <= 65535) or port in (8000, 18765):
        raise ValueError("invalid_lsp_bridge_port")
    workspace = workspace.expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("invalid_lsp_bridge_workspace")
    state_dir = state_dir.expanduser()
    if not state_dir.is_absolute():
        raise ValueError("invalid_lsp_bridge_state_dir")
    child = FastMCP("binnacle-lsp-chatgpt-bridge", on_duplicate="error")

    @child.tool(
        name="inspect_symbol",
        description=(
            "Inspect Python symbol definitions and references using trusted "
            "Pyright LSP. path is relative to the host's ~/Projects directory "
            "(for example 'my-repo/src/module.py'), NEVER absolute. Give the "
            "1-based line and exact symbol_text on that line, or a 1-based "
            "column. Returns bounded workspace-relative locations, "
            "completeness/status/reason codes. Prefer this before repeated "
            "manual grep when navigating Python definitions, usages, and "
            "refactors. Does not modify files."
        ),
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    async def inspect_symbol(
        path: str,
        line: int,
        symbol_text: str | None = None,
        column: int | None = None,
        reference_limit: int | None = None,
        include_hover: bool = False,
    ) -> dict[str, Any]:
        # The private endpoint validates and bounds paths, anchors and results.
        # Inputs cannot change the registered workspace or provider process.
        try:
            token, handle = _credentials(state_dir, workspace)
        except (OSError, ValueError, TypeError):
            raise ToolError("private_lsp_unavailable") from None
        args = {
            "workspace_id": handle,
            "path": path,
            "line": line,
            "symbol_text": symbol_text,
            "column": column,
            "reference_limit": reference_limit,
            "include_hover": include_hover,
        }
        try:
            transport = StreamableHttpTransport(
                f"http://127.0.0.1:{port}/mcp",
                headers={"Authorization": f"Bearer {token}"},
            )
            async with Client(transport, timeout=_TIMEOUT_SECONDS) as client:
                reply = await client.call_tool(
                    "inspect_symbol", args, raise_on_error=False
                )
            if reply.is_error:
                raise ToolError("private_lsp_provider_unavailable")
            content = reply.structured_content
            if not isinstance(content, dict):
                raise ToolError("private_lsp_response_invalid")
            if (
                len(json.dumps(content, separators=(",", ":")).encode())
                > _MAX_RESULT_BYTES
            ):
                raise ToolError("private_lsp_response_too_large")
            return content
        except ToolError:
            raise
        except Exception:  # noqa: BLE001 - untrusted local MCP peer, fixed-code redaction
            # Never forward token, protocol errors, file paths or provider text.
            raise ToolError("private_lsp_unavailable") from None

    return child
