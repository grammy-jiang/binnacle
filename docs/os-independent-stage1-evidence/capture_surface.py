"""Capture exact v1.0.1 four-profile FastMCP wire and local provider surface."""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

BASE = "02f4bab9bc7562668ffc41d622c4274449933768"
ROOT = Path(__file__).resolve().parents[2]
DEST = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def collect():
    from binnacle import server
    from tests.contracts.surface_support import served

    async def raw():
        root = server.create_server()
        local = await root.local_provider.list_tools()
        all_tools = await root.list_tools(run_middleware=False)
        return {
            "root_local": [x.model_dump(mode="json", by_alias=True) for x in local],
            "raw_aggregate": [
                x.model_dump(mode="json", by_alias=True) for x in all_tools
            ],
            "multiplicity": dict(Counter(x.name for x in all_tools)),
        }

    payload = {
        "baseline_sha": BASE,
        "protocol": "FastMCP in-process Client exact raw MCP tool model",
        "profile_surfaces": {},
        "raw_ownership": asyncio.run(raw()),
        "original_middleware": [type(m).__name__ for m in server.mcp.middleware],
        "original_transforms": [type(t).__name__ for t in server.mcp._transforms]
        if hasattr(server.mcp, "_transforms")
        else "unavailable",
    }
    cases = [
        ("default", None, None),
        ("modern_chatgpt", "openai-mcp(ChatGPT)", None),
        ("legacy_chatgpt", "openai-mcp", "legacy"),
        ("unrelated", "claude-code", None),
    ]
    for key, client, mode in cases:
        tools, instructions = served(client, mode)
        payload["profile_surfaces"][key] = {
            "name": client,
            "mode": mode,
            "instructions": instructions,
            "tools": [t.model_dump(mode="json", by_alias=True) for t in tools],
        }
    path = DEST / "os0-raw-mcp-surface.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "profile_counts": {
                    k: len(v["tools"]) for k, v in payload["profile_surfaces"].items()
                },
                "raw_multiplicity": payload["raw_ownership"]["multiplicity"],
                "middleware": payload["original_middleware"],
                "transforms": payload["original_transforms"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="binnacle-os0-wire-") as folder:
        p = Path(folder)
        token = p / "token"
        token.write_text("os0-non-production-test-token")
        cfg = p / "config.toml"
        cfg.write_text(
            f'[auth]\ntoken_file = "{token}"\n[jobs]\nowner = "embedded"\ndir = "{p}/jobs"\nsocket_path = "{p}/jobs.sock"\n'
        )
        os.environ["BINNACLE_CONFIG_FILE"] = str(cfg)
        os.environ.pop("BINNACLE_MANAGED_DEPLOYMENT", None)
        collect()
