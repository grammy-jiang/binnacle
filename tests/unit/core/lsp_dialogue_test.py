"""P1.3 notifications and safe bidirectional fixture smoke, not client acceptance."""

from pathlib import Path

import pytest

from tests.fixtures.lsp.lsp_dialogue import refusal_response
from tests.fixtures.lsp.lsp_peer import LspPeer


def test_lsp_observed_notifications_are_ordered_and_not_answered():
    notifications = [
        ("initialized", {}),
        (
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": "file:///fixture.py",
                    "version": 1,
                    "languageId": "python",
                    "text": "文",
                }
            },
        ),
        (
            "textDocument/didChange",
            {
                "textDocument": {"uri": "file:///fixture.py", "version": 2},
                "contentChanges": [{"text": "next"}],
            },
        ),
        ("$/cancelRequest", {"id": 77}),
        ("textDocument/didClose", {"textDocument": {"uri": "file:///fixture.py"}}),
    ]
    with LspPeer() as peer:
        peer.request("initialize")
        sent = [
            {"jsonrpc": "2.0", "method": method, "params": params}
            for method, params in notifications
        ]
        for message in sent:
            peer.send(message)
        assert peer.request("fixture/observed", 2)["result"] == {
            "notifications": sent,
            "responses": [],
            "pending": [],
        }
        assert (
            peer.request("textDocument/definition", 3)["result"]["uri"]
            == "file:///fixture.py"
        )
        peer.finish()


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
def test_lsp_server_request_safe_policy(method: str, tmp_path: Path):
    sentinel = tmp_path / "untouched.txt"
    sentinel.write_text("original")
    params = {
        "items": [{"section": "fixture"}, {"section": "secrets"}],
        "registrations": [{"id": "write", "method": "workspace/executeCommand"}],
        "edit": {
            "changes": {
                sentinel.as_uri(): [
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
        "command": "fixture.must-not-execute",
        "arguments": [sentinel.as_uri()],
    }
    with LspPeer() as peer:
        # Same numeric ID in opposite directions must not be mistaken for a reply.
        peer.send(
            {
                "jsonrpc": "2.0",
                "id": 42,
                "method": "fixture/serverRequest",
                "params": {"serverId": 42, "method": method, "params": params},
            }
        )
        request = peer.receive()
        assert request == {
            "jsonrpc": "2.0",
            "id": 42,
            "method": method,
            "params": params,
        }
        response = refusal_response(request)
        peer.send(response)
        assert peer.receive() == {"jsonrpc": "2.0", "id": 42, "result": None}
        observed = peer.request("fixture/observed", 43)["result"]
        assert observed == {"notifications": [], "responses": [response], "pending": []}
        if method == "workspace/configuration":
            assert response["result"] == [{"analysis": {"enabled": True}}, None]
        elif method == "workspace/applyEdit":
            assert response["result"] == {
                "applied": False,
                "failureReason": "Read-only fixture peer",
            }
        else:
            assert response["error"] == {
                "code": -32601,
                "message": "Unsupported by read-only fixture peer",
            }
        assert sentinel.read_text() == "original"
        assert list(tmp_path.iterdir()) == [sentinel]
        peer.finish()
