"""Every tool's MCP surface, pinned per client profile.

Two profiles are pinned, each built the way the server builds it (see
tests/contracts/surface_support.py): ``chatgpt``, the client name
'openai-mcp', which ``client_tools`` serves 6 tools, and ``default``, a
client that matches no prefix and gets all 8. Per profile the test pins
which tools are served, in order, and per tool a sha256 over the name, the
description, the output schema, the annotations and a normalized input
schema (the normalization makes the hash the same on every supported
Python). The server instructions text is pinned by its own sha256.

This file began on 2026-09-27 as the run_command pin, measured on master
b040984 before the shadow-prediction experiment was removed, and was updated
the same day when the description and wait_seconds began to state that a
wait ends when the command finishes (docs/usage-analysis-2026-09-27.md).
Step 1 of docs/quality-guard-plan-2026-09-27.md generalized it to every tool
on 2026-09-28; run_command's hash did not change.

How to update a pin on purpose: make the change, run this file, and copy
the new hash from the failure into SURFACE_SHA256 (or INSTRUCTIONS_SHA256).
Give the reason in the commit message of the same change. A pin that
changes without a reason in its commit is a regression.
"""

import hashlib

import pytest

from tests.contracts.surface_support import (
    PROFILES,
    digest,
    parameter,
    served,
    surface,
)

# 2026-09-29: job_status hash intentionally changed for frozen cursor v1:
# optional cursor input, cursor-only output properties, and §6 descriptions.
SURFACE_SHA256 = {
    "chatgpt": {
        "read_file": "54ed0646b239adce52a7b872a26203f1d7547199d952d5eb78e8156cad1d0c30",
        "list_files": "3199643b89945d9c6a5f15522cf884d697b1e6b946c4a2528839304b471c24a2",
        "search_text": "bd6f6e576567dad6fd759fac233667aa4b6089d546b90079832fa4761739848a",
        "run_command": "0ac17d1fa543fdc90d9289df5a4e5c92e55683bad869ff74f238c9bd1886e8dd",
        "job_status": "0ece482b0ae5578487301344129c806b3020d11d1d6b975588fa2b4a2970f03e",
        "stop_job": "ef13121e05987b54c837ce1963f8b967cb67064e91e06604f7e6a63535d02a2d",
    },
    "default": {
        "read_file": "54ed0646b239adce52a7b872a26203f1d7547199d952d5eb78e8156cad1d0c30",
        "list_files": "3199643b89945d9c6a5f15522cf884d697b1e6b946c4a2528839304b471c24a2",
        "search_text": "bd6f6e576567dad6fd759fac233667aa4b6089d546b90079832fa4761739848a",
        "edit_file": "de1636ef9ac176c7876f6418caaef428e33f8918e6c77cdc67fa55991684a83b",
        "write_file": "caed318767151115e1715c2cfb27400fa545019cbf3508c7cfb6de426a919e31",
        "run_command": "0ac17d1fa543fdc90d9289df5a4e5c92e55683bad869ff74f238c9bd1886e8dd",
        "job_status": "0ece482b0ae5578487301344129c806b3020d11d1d6b975588fa2b4a2970f03e",
        "stop_job": "ef13121e05987b54c837ce1963f8b967cb67064e91e06604f7e6a63535d02a2d",
    },
}
TOOL_COUNT = {"chatgpt": 6, "default": 8}
INSTRUCTIONS_SHA256 = "55cafa03a706b86aaab8d53b45030a76177f9da70767ca09de608d20573d5339"


def _hashes(client_name: str | None, mode: str | None = None) -> dict[str, str]:
    tools, _ = served(client_name, mode)
    return {tool.name: digest(surface(tool)) for tool in tools}


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_surface_is_pinned(profile):
    hashes = _hashes(PROFILES[profile])
    assert list(hashes) == list(SURFACE_SHA256[profile])  # which tools, in order
    assert hashes == SURFACE_SHA256[profile]


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_tool_count(profile):
    tools, _ = served(PROFILES[profile])
    assert len(tools) == TOOL_COUNT[profile]


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_server_instructions_are_pinned(profile):
    _, instructions = served(PROFILES[profile])
    assert instructions is not None
    assert hashlib.sha256(instructions.encode()).hexdigest() == INSTRUCTIONS_SHA256


@pytest.mark.parametrize(
    ("client_name", "mode"),
    [("openai-mcp", "legacy"), ("openai-mcp(ChatGPT)", None)],
)
def test_every_chatgpt_identity_gets_the_chatgpt_profile(client_name, mode):
    """Both protocol eras carry the name differently; the profile is one."""
    assert _hashes(client_name, mode) == SURFACE_SHA256["chatgpt"]


def test_normalization_reads_both_optional_forms():
    new_form = {
        "anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}],
        "default": None,
        "description": "N lines.",
    }
    old_form = {
        "anyOf": [
            {
                "anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}],
                "description": "N lines.",
            },
            {"type": "null"},
        ],
        "default": None,
    }
    assert parameter(new_form) == parameter(old_form)
    assert parameter({"type": ["string", "null"]})["types"] == ["string"]
