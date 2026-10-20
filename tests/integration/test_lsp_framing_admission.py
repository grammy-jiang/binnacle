"""Malformed frames cannot become benchmark evidence, even with pinned gold."""

import io
import json
from unittest.mock import Mock

import pytest

from tests.fixtures.lsp import raw_benchmark as bench
from tests.fixtures.lsp.lsp_peer import LspPeer
from tests.fixtures.lsp.lsp_transport import emit, frame
from tests.fixtures.lsp.process_observer import ProcessObserver

MODES = [
    "nonfinite-json",
    "invalid-utf8",
    "wrong-header",
    "invalid-header",
    "missing-length",
    "malformed-length",
    "negative-length",
    "duplicate-length",
    "conflicting-length",
    "short-body",
    "long-body",
    "invalid-json",
    "oversize-header",
    "oversize-body",
    "non-object",
]


def malformed(mode):
    manifest = bench.load_manifest(bench.MANIFEST)
    response = {"jsonrpc": "2.0", "id": 2, "result": manifest["gold"]}
    if mode in ("nonfinite-json", "invalid-utf8"):
        body = b'{"result":NaN}' if mode == "nonfinite-json" else b'{"result":"\xff"}'
        return f"Content-Length: {len(body)}\r\n\r\n".encode() + body
    if mode == "wrong-header":
        return frame(response).replace(b"Content-Length", b"Wrong-Header")
    if mode == "invalid-header":
        return b"Broken\r\n" + frame(response)
    stream = io.BytesIO()
    emit(stream, mode, response)
    return stream.getvalue()


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("peer_type", [LspPeer, ProcessObserver])
def test_bad_wire_cannot_pass_gold(peer_type, mode):
    peer = object.__new__(peer_type)
    peer.buffer = bytearray()
    peer.pending_length = None
    peer.max_buffered = 0
    wire = malformed(mode)
    chunks = [wire[i : i + 1024] for i in range(0, len(wire), 1024)]
    peer.read_chunk = Mock(side_effect=[*chunks, b""])
    peer.send = Mock()
    with pytest.raises((ValueError, EOFError)):
        bench.semantic(peer, bench.load_manifest(bench.MANIFEST), 2, 1)
    assert peer.max_buffered <= 9216


@pytest.mark.parametrize("mode", MODES)
def test_bad_wire_persists_invalid_artifact(monkeypatch, tmp_path, mode):
    class CorruptedObserver(ProcessObserver):
        def send(self, message):
            if message.get("id") == 2:
                wire = malformed(mode)
                self.read_chunk = Mock(
                    side_effect=[
                        *[wire[i : i + 1024] for i in range(0, len(wire), 1024)],
                        b"",
                    ]
                )
            else:
                super().send(message)

    monkeypatch.setattr(bench, "ProcessObserver", CorruptedObserver)
    output = tmp_path / "invalid.json"
    result = bench.run(output)
    assert json.loads(output.read_text()) == result
    assert result["valid"] is False
    assert result["gold_verified"] is False
    assert result["samples"] == []
    assert result["correct_samples"] == 0
    assert "first_request" not in result
    assert "warm_ms" not in result
    assert result["failure"] in (
        "ValueError",
        "JSONDecodeError",
        "UnicodeDecodeError",
        "EOFError",
    )
