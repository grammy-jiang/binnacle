"""P1.4 adversarial fixture/harness smoke; no production parser claims."""

import io
import json
from typing import Any

import pytest

from tests.fixtures.lsp.lsp_peer import LspPeer
from tests.fixtures.lsp.lsp_transport import emit, frame


@pytest.mark.parametrize("mode", ["split", "coalesced"])
def test_lsp_valid_wire_modes(mode: str):
    with LspPeer("--transport", mode) as peer:
        peer.send({"jsonrpc": "2.0", "id": 1, "method": "fixture/transport"})
        if mode == "coalesced":
            assert peer.receive() == {
                "jsonrpc": "2.0",
                "method": "fixture/tick",
                "params": {},
            }
        assert peer.receive() == {"jsonrpc": "2.0", "id": 1, "result": "wire → 文"}
        peer.finish()


class WriteWitness(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.sizes: list[int] = []

    def write(self, value: Any) -> int:
        self.sizes.append(len(value))
        return super().write(value)


@pytest.mark.parametrize("mode", ["split", "coalesced"])
def test_lsp_emitter_write_boundaries(mode: str):
    stream = WriteWitness()
    response = {"jsonrpc": "2.0", "id": 1, "result": "文"}
    assert emit(stream, mode, response) is False
    if mode == "split":
        assert stream.getvalue() == frame(response)
        assert stream.sizes == [1] * len(frame(response))
    else:
        assert stream.getvalue() == frame(
            {"jsonrpc": "2.0", "method": "fixture/tick", "params": {}}
        ) + frame(response)
        assert stream.sizes == [len(stream.getvalue())]


@pytest.mark.parametrize(
    ("mode", "exception", "reason"),
    [
        ("missing-length", ValueError, "missing or duplicate"),
        ("malformed-length", ValueError, "invalid Content-Length"),
        ("negative-length", ValueError, "invalid Content-Length"),
        ("duplicate-length", ValueError, "missing or duplicate"),
        ("conflicting-length", ValueError, "missing or duplicate"),
        ("short-body", EOFError, "truncated frame"),
        ("long-body", json.JSONDecodeError, "Expecting"),
        ("invalid-json", json.JSONDecodeError, "Expecting"),
        ("oversize-header", ValueError, "header too large"),
        ("oversize-body", ValueError, "body too large"),
        ("non-object", ValueError, "expected object"),
    ],
)
def test_lsp_bad_frames_are_bounded(mode: str, exception: type[Exception], reason: str):
    with LspPeer("--transport", mode) as peer:
        peer.send({"jsonrpc": "2.0", "id": 1, "method": "fixture/transport"})
        with pytest.raises(exception, match=reason):
            peer.receive(timeout=2)
        assert peer.max_buffered <= 9216  # 8 KiB body limit plus one read chunk.
    assert peer.process is not None and peer.process.poll() is not None


@pytest.mark.parametrize("mode", ["unknown-id", "null-id", "boolean-id", "list-id"])
def test_lsp_invalid_response_ids(mode: str):
    with LspPeer("--transport", mode) as peer:
        with pytest.raises(ValueError, match="unexpected response ID"):
            peer.request("fixture/transport")
        peer.finish()


def test_lsp_duplicate_response_is_not_next_request_result():
    with LspPeer("--transport", "duplicate-id") as peer:
        assert peer.request("fixture/transport")["result"] == "wire → 文"
        duplicate = peer.receive()
        assert duplicate == {"jsonrpc": "2.0", "id": 1, "result": "wire → 文"}
        with pytest.raises(ValueError, match="unexpected response ID"):
            peer.validate_response(duplicate, 2)
        assert (
            peer.request("initialize", 2)["result"]["serverInfo"]["name"]
            == "binnacle-fake-lsp"
        )
        peer.finish()


def test_lsp_late_response_released_only_after_deadline():
    with LspPeer("--transport", "late-id") as peer:
        peer.send({"jsonrpc": "2.0", "id": 1, "method": "fixture/transport"})
        with pytest.raises(TimeoutError, match="fixture response deadline"):
            peer.receive(timeout=0.05)
        # Explicit release, not a scheduling-sensitive server sleep.
        peer.send({"jsonrpc": "2.0", "id": 2, "method": "fixture/release"})
        late = peer.receive()
        assert late == {"jsonrpc": "2.0", "id": 1, "result": "wire → 文"}
        with pytest.raises(ValueError, match="unexpected response ID"):
            peer.validate_response(late, 2)
        assert peer.receive() == {"jsonrpc": "2.0", "id": 2, "result": None}
        peer.finish()


def test_lsp_server_request_rejected_by_response_validator():
    with pytest.raises(ValueError, match="server request is not a response"):
        LspPeer.validate_response(
            {"jsonrpc": "2.0", "id": 1, "method": "workspace/applyEdit"}, 1
        )


@pytest.mark.parametrize(
    ("wire", "exit_code"),
    [
        (b"", 0),
        (b"Content-Length: 10\r\n\r\n{}", 2),
        (b"Content-Length: nope\r\n\r\n", 2),
    ],
)
def test_lsp_input_eof_exits_without_hanging(wire: bytes, exit_code: int):
    with LspPeer() as peer:
        assert peer.process is not None
        stdout, stderr = peer.process.communicate(input=wire, timeout=3)
        assert peer.process.returncode == exit_code
        assert stdout == b""
        assert stderr == b""
