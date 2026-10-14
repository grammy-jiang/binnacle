"""Default-off maintenance A3 protocol: strict allowlist and no stop authority."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Event
from typing import Any, cast

import pytest

from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain
from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.darwin import (
    ipc_transport,
)
from binnacle.platform.darwin import (
    mcp_maintenance_admission_rpc as rpc,
)


def fixture(tmp_path: Path):
    gate = ToolAdmissionDrain()
    root = tmp_path / rpc._DIR
    root.mkdir(mode=0o700)
    path = root / rpc._SOCKET
    lease = ServiceLease(os.getuid(), rpc._LABEL, "e" * 32, 1, 2)
    handler = rpc.MCPAdmissionHandler(gate)
    return gate, path, lease, handler


def status(gate: ToolAdmissionDrain) -> dict[str, object]:
    return {"version": 1, "op": "status", "generation": gate.generation}


def fence(gate: ToolAdmissionDrain, nonce: str = "a" * 32) -> dict[str, object]:
    return {**status(gate), "op": "fence", "nonce": nonce}


def wait(gate: ToolAdmissionDrain, nonce: str = "a" * 32) -> dict[str, object]:
    return {**fence(gate, nonce), "op": "wait_drained", "timeout_s": 0.0}


def test_status_never_grants_control_permission(tmp_path: Path) -> None:
    gate, _, _, handler = fixture(tmp_path)
    result = handler(status(gate))
    assert result == {
        "version": 1,
        "ok": True,
        "generation": gate.generation,
        "pause_nonce": None,
        "in_flight": 0,
        "drained": False,
        "shutdown_authorized": False,
        "production_authorized": False,
    }
    assert (
        rpc._check_reply(result, generation=gate.generation).shutdown_authorized
        is False
    )


def test_fence_blocks_new_tools_but_drains_admitted_calls(tmp_path: Path) -> None:
    gate, _, _, handler = fixture(tmp_path)
    admitted = gate.admit()
    waiting = handler(fence(gate))
    assert waiting["pause_nonce"] == "a" * 32
    assert waiting["drained"] is False and waiting["in_flight"] == 1
    assert handler(wait(gate))["drained"] is False
    assert handler(status(gate))["in_flight"] == 1
    gate.release(admitted)
    ended = handler(wait(gate))
    assert ended["drained"] is True
    assert ended["in_flight"] == 0
    assert ended["shutdown_authorized"] is False
    with pytest.raises(Exception, match="temporarily unavailable"):
        gate.admit()


def test_foreign_nonce_cannot_take_over_closed_gate(tmp_path: Path) -> None:
    gate, _, _, handler = fixture(tmp_path)
    handler(fence(gate))
    with pytest.raises(rpc.MCPAdmissionRPCRefused, match="owner"):
        handler(fence(gate, "b" * 32))
    assert handler(status(gate))["pause_nonce"] == "a" * 32


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        "stop",
        {},
        {"version": 1, "op": "status"},
        {"version": True, "op": "status", "generation": "b" * 32},
        {"version": 2, "op": "status", "generation": "b" * 32},
        {"version": "1", "op": "status", "generation": "b" * 32},
    ],
)
def test_invalid_generation_or_request_schema_is_refused(
    tmp_path: Path, bad: object
) -> None:
    _gate, _path, _lease, handler = fixture(tmp_path)
    with pytest.raises(rpc.MCPAdmissionRPCRefused):
        handler(cast(Any, bad))


@pytest.mark.parametrize(
    "op",
    [
        "shutdown",
        "restart",
        "bootout",
        "bootstrap",
        "prune",
        "release",
        "unfence",
        "kill",
        "stop",
        "delete",
    ],
)
def test_no_command_other_than_status_fence_and_wait(tmp_path: Path, op: str) -> None:
    gate, _, _, handler = fixture(tmp_path)
    with pytest.raises(rpc.MCPAdmissionRPCRefused, match="allowlisted"):
        handler({**status(gate), "op": op, "nonce": "a" * 32})
    assert gate.snapshot().pause_nonce is None


@pytest.mark.parametrize(
    "changed",
    [
        {"nonce": "short"},
        {"nonce": 9},
        {"nonce": "A" * 32},
        {"nonce": "g" * 32},
        {"nonce": None},
    ],
)
def test_invalid_fence_nonce_refused(tmp_path: Path, changed: dict) -> None:
    gate, _path, _lease, handler = fixture(tmp_path)
    with pytest.raises(rpc.MCPAdmissionRPCRefused, match="nonce"):
        handler({**fence(gate), **changed})


@pytest.mark.parametrize(
    "bad", [None, False, True, float("nan"), float("inf"), -1, 61, "2"]
)
def test_wait_timeout_must_be_bounded_and_numeric(tmp_path: Path, bad: object) -> None:
    gate, _, _, handler = fixture(tmp_path)
    handler(fence(gate))
    with pytest.raises(rpc.MCPAdmissionRPCRefused, match="wait parameters"):
        handler({**wait(gate), "timeout_s": bad})


def test_wait_for_unowned_nonce_refused_without_resuming_client(tmp_path: Path) -> None:
    gate, _, _, handler = fixture(tmp_path)
    with pytest.raises(rpc.MCPAdmissionRPCRefused, match="owner unknown"):
        handler(wait(gate))
    assert gate.snapshot().pause_nonce is None


@pytest.mark.parametrize(
    "extra",
    [
        {"path": "/tmp/other"},
        {"label": "system/com.binnacle.jobs"},
        {"allowed": True},
        {"run_command": "rm -rf /"},
        {"approval": "yes"},
    ],
)
def test_extra_fields_cannot_elevate_permissions(tmp_path: Path, extra: dict) -> None:
    gate, _, _, handler = fixture(tmp_path)
    with pytest.raises(rpc.MCPAdmissionRPCRefused, match="allowlisted"):
        handler({**status(gate), **extra})


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"ok": False},
        {"ok": 1},
        {"generation": "b" * 32},
        {"drained": "true"},
        {"in_flight": True},
        {"in_flight": -1},
        {"shutdown_authorized": True},
        {"shutdown_authorized": 0},
        {"production_authorized": True},
        {"production_authorized": 0},
        {"pause_nonce": "invalid"},
        {"pause_nonce": "A" * 32},
        {"drained": True},
    ],
)
def test_untrusted_ack_reply_cannot_claim_authority(
    tmp_path: Path, change: dict
) -> None:
    gate, _, _, handler = fixture(tmp_path)
    response = {**handler(status(gate)), **change}
    with pytest.raises(rpc.MCPAdmissionRPCRefused):
        rpc._check_reply(response, generation=gate.generation)


def test_reply_cannot_have_extra_or_missing_keys(tmp_path: Path) -> None:
    gate, _, _, handler = fixture(tmp_path)
    ordinary = dict(handler(status(gate)))
    with pytest.raises(rpc.MCPAdmissionRPCRefused):
        rpc._check_reply(
            {**ordinary, "accepted_delete": True}, generation=gate.generation
        )
    ordinary.pop("drained")
    with pytest.raises(rpc.MCPAdmissionRPCRefused):
        rpc._check_reply(ordinary, generation=gate.generation)


class FakeAuthenticatedChannel:
    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.calls: list[tuple[dict[str, object], float]] = []
        self.closed = 0

    def request(self, payload: dict, *, timeout_s: float):
        self.calls.append((dict(payload), timeout_s))
        return self.answer

    def close(self) -> None:
        self.closed += 1


@pytest.mark.parametrize("op", ["status", "fence", "wait_drained"])
def test_client_passes_only_exact_protocol_to_a3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    op: str,
) -> None:
    gate, path, lease, handler = fixture(tmp_path)
    if op == "fence":
        answer = handler(fence(gate))
    elif op == "wait_drained":
        handler(fence(gate))
        answer = handler(wait(gate))
    else:
        answer = handler(status(gate))
    channel = FakeAuthenticatedChannel(answer)
    hits = [0]

    def connect(*a: object, **kw: object) -> FakeAuthenticatedChannel:
        hits[0] += 1
        return channel

    monkeypatch.setattr(ipc_transport, "connect_authenticated", connect)
    actual = rpc.read_mcp_admission_a3(
        path,
        lease=lease,
        generation=gate.generation,
        op=op,
        nonce="a" * 32 if op != "status" else None,
    )
    assert actual.generation == gate.generation
    assert actual.pause_nonce == ("a" * 32 if op != "status" else None)
    assert not actual.shutdown_authorized
    assert len(channel.calls) == 1
    assert hits == [1] and channel.closed == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("op", "shutdown"),
        ("generation", "invalid"),
        ("timeout_s", 0),
        ("timeout_s", 11),
        ("timeout_s", float("nan")),
    ],
)
def test_bad_client_inputs_do_not_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    gate, path, lease, _handler = fixture(tmp_path)
    monkeypatch.setattr(
        ipc_transport,
        "connect_authenticated",
        lambda *a, **kw: pytest.fail("invalid request connected"),
    )
    args: dict[str, Any] = {
        "socket_path": path,
        "lease": lease,
        "generation": gate.generation,
        "op": "status",
    }
    args[field] = value
    with pytest.raises(rpc.MCPAdmissionRPCRefused):
        rpc.read_mcp_admission_a3(**args)


@pytest.mark.parametrize(
    "bad",
    [
        "/tmp/jobs.sock",
        "/tmp/mcp-maintenance-admission/other.sock",
        "/tmp/not-mcp/mcp-admission.sock",
        "relative/mcp-admission.sock",
    ],
)
def test_foreign_client_endpoints_refused(tmp_path: Path, bad: str) -> None:
    gate, _, lease, _ = fixture(tmp_path)
    with pytest.raises(rpc.MCPAdmissionRPCRefused, match="endpoint"):
        rpc.read_mcp_admission_a3(
            Path(bad),
            lease=lease,
            generation=gate.generation,
        )


def test_client_closed_on_invalid_authenticated_reply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate, path, lease, _ = fixture(tmp_path)
    channel = FakeAuthenticatedChannel({"ok": True, "delete": True})
    monkeypatch.setattr(
        ipc_transport, "connect_authenticated", lambda *a, **kw: channel
    )
    with pytest.raises(rpc.MCPAdmissionRPCRefused):
        rpc.read_mcp_admission_a3(path, lease=lease, generation=gate.generation)
    assert channel.closed == 1
    assert len(channel.calls) == 1


def test_server_uses_existing_a3_transport_without_registering_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate, path, lease, _ = fixture(tmp_path)
    stop = Event()
    seen: list[tuple] = []

    def fake_serve(socket_path, *, lease, handler, stop):
        seen.append((socket_path, lease, stop))
        assert handler(status(gate))["shutdown_authorized"] is False

    monkeypatch.setattr(ipc_transport, "serve_authenticated", fake_serve)
    rpc.serve_mcp_admission_a3(path, lease=lease, gate=gate, stop=stop)
    assert seen == [(path, lease, stop)]
