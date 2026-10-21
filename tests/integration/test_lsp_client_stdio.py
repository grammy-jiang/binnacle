"""P2.2–P2.3 real stdio dialogue with P1 fake, NOT production process owner."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from binnacle.features.development_intelligence.lsp_client import LspClient
from binnacle.features.development_intelligence.lsp_session import LspSession
from binnacle.features.development_intelligence.lsp_wire import LspProtocolError

FAKE = Path(__file__).resolve().parents[1] / "fixtures/lsp/fake_stdio_server.py"


async def _fake_dialogue(args: tuple[str, ...], work):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        str(FAKE),
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    client = LspClient(process.stdout, process.stdin, request_timeout=2)
    client.start()
    try:
        await work(client, process)
    finally:
        await client.aclose()
        if process.returncode is None:
            process.kill()  # Test fixture owner, never Binnacle runtime ownership.
        await asyncio.wait_for(process.wait(), timeout=3)
        process.stdin.close()
        assert process.stderr is not None
        assert await process.stderr.read() == b""


def test_real_stdio_initialize_symbols_shutdown():
    async def work(client: LspClient, process):
        session = LspSession(client)
        caps = await session.initialize(root_uri="file:///fixture")
        assert caps["definitionProvider"] is True
        assert session.supports("textDocument/definition")
        assert session.supports("textDocument/references")
        definition = await session.request_semantic(
            "textDocument/definition",
            {
                "textDocument": {"uri": "file:///fixture.py"},
                "position": {"line": 1, "character": 5},
            },
        )
        assert definition["uri"] == "file:///fixture.py"
        assert (
            await session.request_semantic(
                "textDocument/hover",
                {
                    "textDocument": {"uri": "file:///fixture.py"},
                    "position": {"line": 1, "character": 5},
                },
            )
        )["contents"]["value"] == "**sample** → 文"
        observed = await client.request("fixture/observed", {})
        assert any(e["method"] == "initialized" for e in observed["notifications"])
        assert client.pending_count == 0
        await session.shutdown()
        assert await asyncio.wait_for(process.wait(), timeout=2) == 0

    asyncio.run(_fake_dialogue((), work))


def test_unsupported_fake_provider_capability_is_rejected_before_wire():
    async def work(client, _process):
        session = LspSession(client)
        caps = await session.initialize()
        assert caps["definitionProvider"] is False
        assert not session.supports("textDocument/definition")
        with pytest.raises(LspProtocolError, match="lsp_capability_unavailable"):
            await session.request_semantic(
                "textDocument/definition", {"secret": "not_sent"}
            )
        result = await client.request("fixture/observed")
        assert all(
            e["method"] != "textDocument/definition" for e in result["notifications"]
        )
        await session.shutdown()

    asyncio.run(_fake_dialogue(("--disable", "textDocument/definition"), work))


@pytest.mark.parametrize(
    "method",
    [
        "workspace/configuration",
        "client/registerCapability",
        "workspace/applyEdit",
        "workspace/executeCommand",
        "fixture/unknown",
    ],
)
def test_server_reverse_request_does_not_execute_or_mutate(method, tmp_path):
    target = tmp_path / "do-not-write.txt"
    target.write_text("original")
    params = {
        "items": [{"section": "secret"}],
        "edit": {
            "changes": {
                target.as_uri(): [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 8},
                        },
                        "newText": "changed",
                    }
                ]
            }
        },
        "command": "do-not-execute",
    }

    async def work(client, _process):
        # Force the server-side request ID to collide with this client's
        # pending outgoing ID to prove direction is disambiguated by method.
        operation = asyncio.create_task(
            client.request(
                "fixture/serverRequest",
                {"serverId": 1, "method": method, "params": params},
            )
        )
        assert await operation is None
        observed = await client.request("fixture/observed")
        replies = observed["responses"]
        assert len(replies) == 1
        assert replies[0]["id"] == 1
        if method == "workspace/applyEdit":
            assert replies[0]["result"]["applied"] is False
        elif method == "workspace/configuration":
            assert replies[0]["result"] == [None]
        else:
            assert replies[0]["error"]["code"] == -32601
        await client.request("shutdown")
        await client.notify("exit")

    asyncio.run(_fake_dialogue((), work))
    assert target.read_text() == "original"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("mode", ["split", "coalesced"])
def test_real_stdio_fragmented_and_coalesced_frames(mode):
    async def work(client, _process):
        result = await client.request("fixture/transport")
        assert result == "wire → 文"
        if mode == "coalesced":
            note = await client.next_notification()
            assert note == {"jsonrpc": "2.0", "method": "fixture/tick", "params": {}}
        await client.request("shutdown")
        await client.notify("exit")

    asyncio.run(_fake_dialogue(("--transport", mode), work))


@pytest.mark.parametrize(
    "mode",
    [
        "missing-length",
        "malformed-length",
        "duplicate-length",
        "short-body",
        "long-body",
        "invalid-json",
        "oversize-header",
        "non-object",
        "boolean-id",
        "unknown-id",
    ],
)
def test_real_stdio_invalid_wire_never_claims_success(mode):
    async def work(client, _process):
        with pytest.raises((LspProtocolError, asyncio.TimeoutError)):
            await client.request("fixture/transport")
        assert client.failure_reason is not None
        assert client.pending_count == 0

    asyncio.run(_fake_dialogue(("--transport", mode), work))
