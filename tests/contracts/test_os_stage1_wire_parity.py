"""FM-08/OI-12: compare candidate surface against immutable v1.0.1 OS0 capture."""

import asyncio
import json
from collections import Counter
from pathlib import Path

from binnacle import server
from tests.contracts.surface_support import served

REFERENCE = (
    Path(__file__).resolve().parents[2]
    / "docs/os-independent-stage1-evidence/os0-raw-mcp-surface.json"
)


def baseline():
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def test_four_client_profiles_match_v101_exact_raw_mcp_models():
    original = baseline()["profile_surfaces"]
    profiles = {
        "default": (None, None),
        "modern_chatgpt": ("openai-mcp(ChatGPT)", None),
        "legacy_chatgpt": ("openai-mcp", "legacy"),
        "unrelated": ("claude-code", None),
    }
    for key, (name, mode) in profiles.items():
        actual, instructions = served(name, mode, mcp_server=server.create_server())
        assert instructions == original[key]["instructions"], key
        assert [
            tool.model_dump(mode="json", by_alias=True) for tool in actual
        ] == original[key]["tools"], key


def test_native_raw_provider_ownership_and_middleware_match_v101():
    original = baseline()

    async def raw():
        root = server.create_server()
        local = await root.local_provider.list_tools()
        all_tools = await root.list_tools(run_middleware=False)
        return {
            "root_local": [t.model_dump(mode="json", by_alias=True) for t in local],
            "raw_aggregate": [
                t.model_dump(mode="json", by_alias=True) for t in all_tools
            ],
            "multiplicity": dict(Counter(t.name for t in all_tools)),
            "middleware": [type(m).__name__ for m in root.middleware],
            "transforms": [type(t).__name__ for t in root._transforms]
            if hasattr(root, "_transforms")
            else "unavailable",
        }

    got = asyncio.run(raw())
    assert got["root_local"] == original["raw_ownership"]["root_local"]
    assert got["raw_aggregate"] == original["raw_ownership"]["raw_aggregate"]
    assert got["multiplicity"] == original["raw_ownership"]["multiplicity"]
    assert got["middleware"] == original["original_middleware"]
    assert got["transforms"] == original["original_transforms"]
