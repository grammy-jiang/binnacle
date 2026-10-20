"""Fixture-only bidirectional state and deterministic read-only peer policy."""

from typing import Any


def refusal_response(request: dict[str, Any]) -> dict[str, Any]:
    """Fixed profile settings only; never execute commands or apply edits."""
    response = {"jsonrpc": "2.0", "id": request["id"]}
    if request["method"] == "workspace/configuration":
        response["result"] = [
            {"analysis": {"enabled": True}}
            if item.get("section") == "fixture"
            else None
            for item in request["params"]["items"]
        ]
    elif request["method"] == "workspace/applyEdit":
        response["result"] = {
            "applied": False,
            "failureReason": "Read-only fixture peer",
        }
    else:
        response["error"] = {
            "code": -32601,
            "message": "Unsupported by read-only fixture peer",
        }
    return response


class Dialogue:
    def __init__(self):
        self.notifications: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.pending: set[str | int] = set()

    def accept(self, message: dict[str, Any]) -> bool:
        if "method" not in message:
            if message.get("id") not in self.pending:
                raise ValueError("unexpected client response")
            self.pending.remove(message["id"])
            self.responses.append(message)
            return True
        if "id" not in message:
            self.notifications.append(message)
            return True
        return False

    def server_request(self, params: dict[str, Any]) -> dict[str, Any]:
        request_id = params.get("serverId", "server-1")
        if request_id in self.pending:
            raise ValueError("duplicate pending server ID")
        self.pending.add(request_id)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": params["method"],
            "params": params.get("params", {}),
        }

    def observed(self) -> dict[str, Any]:
        return {
            "notifications": self.notifications,
            "responses": self.responses,
            "pending": sorted(self.pending, key=str),
        }
