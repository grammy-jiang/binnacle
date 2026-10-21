"""P2.3 safe LSP reverse requests, capabilities and UTF-16 conversions."""

import asyncio

import pytest

from binnacle.features.development_intelligence.lsp_policy import server_request_reply
from binnacle.features.development_intelligence.lsp_session import (
    LspSession,
    python_offset,
    utf16_offset,
)
from binnacle.features.development_intelligence.lsp_wire import LspProtocolError


@pytest.mark.parametrize(
    ("text", "python_positions", "lsp_offsets"),
    [
        ("plain", [0, 1, 5], [0, 1, 5]),
        ("文😀B", [0, 1, 2, 3], [0, 1, 3, 4]),
        ("a𐐷b🧭", [0, 1, 2, 3, 4], [0, 1, 3, 4, 6]),
    ],
)
def test_python_and_utf16_offsets_roundtrip(text, python_positions, lsp_offsets):
    for index, units in zip(python_positions, lsp_offsets, strict=True):
        assert utf16_offset(text, index) == units
        assert python_offset(text, units) == index


@pytest.mark.parametrize("offset", [-1, True, 2.0, "2"])
def test_invalid_utf16_positions_refused(offset):
    with pytest.raises(ValueError):
        python_offset("X😀Y", offset)
    with pytest.raises(ValueError):
        utf16_offset("X😀Y", offset)


@pytest.mark.parametrize("offset", [2, 5])
def test_offsets_cannot_split_unicode_surrogate_or_go_past_end(offset):
    with pytest.raises(ValueError):
        python_offset("A😀B", offset)


def test_unpaired_surrogates_refused():
    with pytest.raises(ValueError):
        utf16_offset("A\ud800", 2)
    with pytest.raises(ValueError):
        python_offset("A\ud800", 1)


@pytest.mark.parametrize(
    ("method", "params", "expected"),
    [
        (
            "workspace/applyEdit",
            {"edit": {"changes": {"file:///x": []}}},
            {
                "result": {
                    "applied": False,
                    "failureReason": "Read-only Development Intelligence client",
                }
            },
        ),
        (
            "client/registerCapability",
            {"registrations": []},
            {"error": {"code": -32601, "message": "Method not supported"}},
        ),
        (
            "workspace/executeCommand",
            {"command": "danger"},
            {
                "error": {"code": -32601, "message": "Method not supported"},
            },
        ),
        ("window/workDoneProgress/create", {"token": "t"}, {"result": None}),
        ("workspace/workspaceFolders", {}, {"result": None}),
        (
            "unknown/request",
            {},
            {
                "error": {
                    "code": -32601,
                    "message": "Method not supported",
                }
            },
        ),
    ],
)
def test_fixed_server_request_refusals(method, params, expected):
    request = {
        "jsonrpc": "2.0",
        "id": "server-1",
        "method": method,
        "params": params,
    }
    assert server_request_reply(request) == {
        "jsonrpc": "2.0",
        "id": "server-1",
        **expected,
    }


def test_configuration_request_only_exposes_explicitly_allowed_sections():
    request = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "workspace/configuration",
        "params": {"items": [{"section": "fixture"}, {"section": "secret"}]},
    }
    assert server_request_reply(request)["result"] == [None, None]
    assert server_request_reply(
        request, configuration={"fixture": {"analysis": {"enabled": True}}}
    )["result"] == [{"analysis": {"enabled": True}}, None]


@pytest.mark.parametrize("invalid", [True, None, [], {}])
def test_invalid_server_request_id_is_not_invented(invalid):
    with pytest.raises(LspProtocolError, match="invalid_server_request_id"):
        server_request_reply({"id": invalid, "method": "workspace/applyEdit"})


@pytest.mark.parametrize("items", [None, {}, [None], [{}] * 65])
def test_invalid_configuration_items_rejected_without_side_effects(items):
    result = server_request_reply(
        {
            "id": 1,
            "method": "workspace/configuration",
            "params": {"items": items},
        }
    )
    assert result["error"]["code"] == -32602


class StubClient:
    def __init__(self, capabilities):
        self.response = {"capabilities": capabilities}
        self.calls = []
        self.sent = []

    async def request(self, method, params):
        self.calls.append((method, params))
        if method == "initialize":
            return self.response
        if method == "shutdown":
            return None
        return {"method": method}

    async def notify(self, method, params):
        self.sent.append((method, params))


def test_initialize_is_read_only_utf16_and_once_only():
    async def exercise():
        client = StubClient({"definitionProvider": True, "hoverProvider": False})
        session = LspSession(client)
        with pytest.raises(LspProtocolError, match="lsp_not_initialized"):
            await session.request_semantic("textDocument/definition", {})
        caps = await session.initialize(root_uri="file:///tmp/example")
        assert caps["definitionProvider"] is True
        method, params = client.calls[0]
        assert method == "initialize"
        assert params["capabilities"]["general"]["positionEncodings"] == ["utf-16"]
        assert params["capabilities"]["workspace"]["applyEdit"] is False
        assert (
            params["capabilities"]["textDocument"]["definition"]["dynamicRegistration"]
            is False
        )
        assert client.sent == [("initialized", {})]
        assert session.supports("textDocument/definition")
        assert not session.supports("textDocument/hover")
        assert not session.supports("workspace/executeCommand")
        assert (
            await session.request_semantic(
                "textDocument/definition",
                {"textDocument": {"uri": "file:///tmp/example"}},
            )
        )["method"] == "textDocument/definition"
        with pytest.raises(LspProtocolError, match="lsp_capability_unavailable"):
            await session.request_semantic("textDocument/hover", {})
        with pytest.raises(LspProtocolError, match="lsp_capability_unavailable"):
            await session.request_semantic("workspace/executeCommand", {})
        with pytest.raises(LspProtocolError, match="lsp_already_initialized"):
            await session.initialize()
        await session.shutdown()
        assert client.calls[-1][0] == "shutdown"
        assert client.sent[-1] == ("exit", {})
        await session.shutdown()
        assert len([x for x in client.calls if x[0] == "shutdown"]) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("encoding", ["utf-8", "utf-32", "unknown", None])
def test_incompatible_lsp_encoding_never_marked_initialized(encoding):
    async def exercise():
        fake = StubClient({"definitionProvider": True, "positionEncoding": encoding})
        session = LspSession(fake)
        with pytest.raises(LspProtocolError, match="unsupported_lsp_position_encoding"):
            await session.initialize()
        assert not session.initialized
        assert not fake.sent

    asyncio.run(exercise())


@pytest.mark.parametrize("malformed", [None, [], {}, {"capabilities": []}])
def test_bad_lsp_initialize_response_cannot_enable_semantic_calls(malformed):
    async def exercise():
        fake = StubClient({})
        fake.response = malformed
        session = LspSession(fake)
        with pytest.raises(LspProtocolError, match="malformed_lsp_initialize_result"):
            await session.initialize()
        assert not session.initialized

    asyncio.run(exercise())


def test_lsp_root_must_be_a_file_uri():
    async def exercise():
        session = LspSession(StubClient({}))
        with pytest.raises(ValueError, match="root_uri"):
            await session.initialize(root_uri="https://example.com")

    asyncio.run(exercise())


def test_initialize_race_sends_one_request():
    async def exercise():
        waiting = asyncio.Event()
        release = asyncio.Event()

        class Slow(StubClient):
            async def request(self, method, params):
                if method == "initialize":
                    self.calls.append((method, params))
                    waiting.set()
                    await release.wait()
                    return self.response
                return await super().request(method, params)

        client = Slow({"definitionProvider": True})
        session = LspSession(client)
        first = asyncio.create_task(session.initialize())
        await waiting.wait()
        with pytest.raises(LspProtocolError, match="lsp_already_initialized"):
            await session.initialize()
        release.set()
        assert (await first)["definitionProvider"] is True
        assert len([x for x in client.calls if x[0] == "initialize"]) == 1

    asyncio.run(exercise())


def test_failed_initialize_is_not_unsafely_retried_on_same_connection():
    async def exercise():
        client = StubClient({"positionEncoding": "utf-8"})
        session = LspSession(client)
        with pytest.raises(LspProtocolError, match="unsupported_lsp_position_encoding"):
            await session.initialize()
        client.response = {"capabilities": {"definitionProvider": True}}
        with pytest.raises(LspProtocolError, match="lsp_already_initialized"):
            await session.initialize()

    asyncio.run(exercise())
