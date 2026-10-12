"""E2 g6 §9.3 CV-F: the frozen (c′) fixture and lab manifest capture. TEST ONLY.

Lab-only, never product. (c′) is the STRUCT *shape* with the hint field
declared in the advertised output schema of ``fixture_unrelated_read``. The
STRUCT carrier itself is not implemented (§9.2 S-1); the CV lab moves the
routed hint into this shape. The schema and the result rule below mirror the
E2-RUN lab CV variant ``e``: a closed object, ``note`` required, an optional
undescribed ``job_awareness_hint`` string of at most 512 characters, and one
text block that is the ``json.dumps`` of the structured content.

The manifest hash rule is the frozen E2-RUN rule: sha256 of
``json.dumps(manifest, sort_keys=True, separators=(",", ":"))`` where
``manifest = {schema, server_info{name, version}, tools}`` and ``tools`` is
the ``tools/list`` result sorted by name.
"""

import hashlib
import json
from functools import partial
from pathlib import Path
from typing import Any

from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from tests.contracts.job_awareness.e2_composition import _HTTP, E2Server, running

FIXTURE = Path(__file__).parent / "fixtures" / "e2_cv" / "lab-manifests.json"
HINT_FIELD = "job_awareness_hint"
HINT_MAX = 512
CPRIME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "note": {"type": "string"},
        HINT_FIELD: {"type": "string", "maxLength": HINT_MAX},
    },
    "required": ["note"],
    "additionalProperties": False,
}
MANIFEST_SCHEMA = "ja-e2-lab-manifest-v1"


def cprime_result(note: str, hint: str | None = None) -> ToolResult:
    """The (c′) result: the hint only as the declared field, never over 512."""
    if hint is not None and len(hint) > HINT_MAX:
        hint = None  # never send a schema-invalid result
    body: dict[str, Any] = {"note": note}
    if hint:
        body[HINT_FIELD] = hint
    return ToolResult(
        content=[TextContent(type="text", text=json.dumps(body))],
        structured_content=body,
    )


def cprime_server(path: Path, hint: str | None = None) -> E2Server:
    """The (c′) lab tool on the in-process composition, adapter off."""
    server = E2Server(
        path,
        note_schema=CPRIME_SCHEMA,
        note_result=partial(cprime_result, hint=hint),
    )
    server.adapter = server.build_adapter(enabled=False)
    return server


def manifest_sha256(manifest: dict[str, Any]) -> str:
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


async def capture_manifest(server: E2Server) -> dict[str, Any]:
    """``tools/list`` and serverInfo exactly as a client receives them."""
    async with running(server) as wire:
        init = await wire.client.post(
            "/mcp",
            headers=_HTTP,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "e2-manifest", "version": "1"},
                },
            },
        )
        listed = await wire.client.post(
            "/mcp",
            headers=_HTTP,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
    info = init.json()["result"]["serverInfo"]
    return {
        "schema": MANIFEST_SCHEMA,
        "server_info": {"name": info.get("name"), "version": info.get("version")},
        "tools": sorted(listed.json()["result"]["tools"], key=lambda t: t["name"]),
    }


def frozen() -> dict[str, Any]:
    return dict(json.loads(FIXTURE.read_text()))
