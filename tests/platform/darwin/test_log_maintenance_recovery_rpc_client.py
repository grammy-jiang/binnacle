"""Client accepts only a generation-bound manual-review A3 RPC snapshot."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.darwin import ipc_transport
from binnacle.platform.darwin import log_maintenance_recovery_rpc as rpc
from tests.platform.darwin.test_log_maintenance_recovery_rpc_handler import (
    NONCE,
    request,
)


class FakeChannel:
    """Only a fake A3 channel: testing transport bindings, not Darwin sockets."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[dict[str, object], float]] = []
        self.closed = 0

    def request(self, payload, *, timeout_s: float):
        self.calls.append((dict(payload), timeout_s))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def endpoint(tmp_path: Path) -> tuple[Path, ServiceLease]:
    sock = tmp_path / "log-maintenance-observer-ipc" / "observe.sock"
    lease = ServiceLease(os.getuid(), rpc._LABEL, "g" * 32, 123, 456)
    return sock, lease


def _as_dict(value: dict[str, object], **updates) -> dict[str, object]:
    return {**value, **updates}


def _valid_reply(phase: str) -> dict[str, object]:
    status, risks = rpc._expected_from_phase(phase)
    return {
        "version": 1,
        "ok": True,
        "op": "inspect",
        "nonce": NONCE,
        "phase": phase,
        "revision": rpc._PHASES.index(phase),
        "status": status,
        "risks": list(risks),
        "manual_review_required": True,
        "production_authorized": False,
        "autonomous_restart_allowed": False,
    }


@pytest.mark.parametrize("phase", rpc._PHASES)
def test_successful_client_never_returns_service_authority(
    endpoint: tuple[Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    sock, lease = endpoint
    channel = FakeChannel(_valid_reply(phase))
    connections: list[tuple[Path, ServiceLease, float]] = []

    def connect(path, *, lease, timeout_s):
        connections.append((path, lease, timeout_s))
        return channel

    monkeypatch.setattr(ipc_transport, "connect_authenticated", connect)
    result = rpc.observe_recovery_over_a3(
        sock, lease=lease, transaction_nonce=NONCE, timeout_s=4.5
    )
    status, risks = rpc._expected_from_phase(phase)
    assert result.phase == phase
    assert result.status == status
    assert result.risks == risks
    assert result.transaction_nonce == NONCE
    assert result.manual_review_required
    assert not result.production_authorized
    assert not result.autonomous_restart_allowed
    assert channel.calls == [(request(), 4.5)]
    assert channel.closed == 1
    assert connections == [(sock, lease, 4.5)]


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"ok": False}, "unavailable"),
        ({"ok": None}, "unavailable"),
        ({"ok": 1}, "unavailable"),
        ({"version": False}, "authority-safe"),
        ({"version": "1"}, "authority-safe"),
        ({"version": 2}, "authority-safe"),
        ({"op": "restart"}, "authority-safe"),
        ({"op": None}, "authority-safe"),
        ({"nonce": "a"}, "authority-safe"),
        ({"nonce": "b" * 32}, "authority-safe"),
        ({"manual_review_required": False}, "authority-safe"),
        ({"manual_review_required": 1}, "authority-safe"),
        ({"manual_review_required": None}, "authority-safe"),
        ({"production_authorized": True}, "authority-safe"),
        ({"production_authorized": 0}, "authority-safe"),
        ({"autonomous_restart_allowed": True}, "authority-safe"),
        ({"autonomous_restart_allowed": 0}, "authority-safe"),
        ({"phase": "anything"}, "malformed"),
        ({"phase": None}, "malformed"),
        ({"phase": "complete"}, "malformed"),
        ({"revision": True}, "malformed"),
        ({"revision": -1}, "malformed"),
        ({"revision": "0"}, "malformed"),
        ({"revision": 1}, "malformed"),
        ({"risks": None}, "malformed"),
        ({"risks": []}, "classification"),
        ({"risks": ["unverified"]}, "malformed"),
        ({"risks": [False]}, "malformed"),
        ({"risks": [["not-string"]]}, "malformed"),
        ({"status": "approved"}, "classification"),
        ({"status": None}, "classification"),
        ({"risks": ["observation_not_authenticated"] * 2}, "classification"),
    ],
)
def test_every_malformed_remote_reply_is_rejected_and_channel_closed(
    endpoint: tuple[Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
    error: str,
) -> None:
    sock, lease = endpoint
    channel = FakeChannel(_as_dict(_valid_reply("intent"), **changes))
    monkeypatch.setattr(
        ipc_transport, "connect_authenticated", lambda *a, **kw: channel
    )
    with pytest.raises(rpc.RecoveryRPCRefused, match=error):
        rpc.observe_recovery_over_a3(sock, lease=lease, transaction_nonce=NONCE)
    assert len(channel.calls) == 1
    assert channel.closed == 1


def test_non_dict_or_missing_or_extra_reply_fails_closed(
    endpoint: tuple[Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sock, lease = endpoint
    values: list[object] = [
        None,
        "complete",
        1,
        {},
        [],
        {**_valid_reply("complete"), "permit": True},
        {k: v for k, v in _valid_reply("complete").items() if k != "risks"},
    ]
    for value in values:
        channel = FakeChannel(value)
        monkeypatch.setattr(
            ipc_transport, "connect_authenticated", lambda *a, ch=channel, **kw: ch
        )
        with pytest.raises(rpc.RecoveryRPCRefused):
            rpc.observe_recovery_over_a3(sock, lease=lease, transaction_nonce=NONCE)
        assert channel.closed == 1


@pytest.mark.parametrize(
    "bad",
    [
        None,
        False,
        True,
        0,
        -1,
        11,
        11.1,
        float("nan"),
        float("inf"),
        -float("inf"),
        "",
        "5",
    ],
    ids=[
        "none",
        "false",
        "true",
        "zero",
        "negative",
        "too-big",
        "too-big-float",
        "nan",
        "inf",
        "neg-inf",
        "empty",
        "text",
    ],
)
def test_invalid_timeout_refused_before_transport(
    endpoint: tuple[Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
    bad: object,
) -> None:
    sock, lease = endpoint
    calls = [0]

    def unexpected(*args, **kwargs):
        calls[0] += 1
        pytest.fail("malformed timeout must never access A3")

    monkeypatch.setattr(ipc_transport, "connect_authenticated", unexpected)
    with pytest.raises(rpc.RecoveryRPCRefused, match="timeout"):
        rpc.observe_recovery_over_a3(
            sock, lease=lease, transaction_nonce=NONCE, timeout_s=cast(float, bad)
        )
    assert calls == [0]


@pytest.mark.parametrize("bad", ["b", "A" * 32, "g" * 32, 9, None])
def test_bad_nonce_refused_before_transport(
    endpoint: tuple[Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
    bad: object,
) -> None:
    sock, lease = endpoint
    monkeypatch.setattr(
        ipc_transport,
        "connect_authenticated",
        lambda *a, **kw: pytest.fail("bad nonce dispatched"),
    )
    with pytest.raises(rpc.RecoveryRPCRefused, match="nonce"):
        rpc.observe_recovery_over_a3(
            sock, lease=lease, transaction_nonce=cast(str, bad)
        )


@pytest.mark.parametrize(
    "name",
    [
        "/tmp/unauthorized.sock",
        "/tmp/log-maintenance-observer-ipc/jobs.sock",
        "/tmp/txn-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/observe.sock",
        "/tmp/another/observe.sock",
    ],
)
def test_client_endpoint_path_is_fixed_allowlist(
    endpoint: tuple[Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    _, lease = endpoint
    monkeypatch.setattr(
        ipc_transport,
        "connect_authenticated",
        lambda *a, **kw: pytest.fail("unexpected A3 use"),
    )
    with pytest.raises(rpc.RecoveryRPCRefused, match="endpoint"):
        rpc.observe_recovery_over_a3(
            Path(name),
            lease=lease,
            transaction_nonce=NONCE,
        )


def test_client_wrong_service_label_and_owner_are_rejected(
    endpoint: tuple[Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sock, lease = endpoint
    monkeypatch.setattr(
        ipc_transport,
        "connect_authenticated",
        lambda *a, **kw: pytest.fail("unexpected A3 use"),
    )
    for badlease in (
        ServiceLease(lease.uid, "com.binnacle.jobs", lease.generation, 1, 1),
        ServiceLease(lease.uid + 1, lease.label, lease.generation, 1, 1),
    ):
        with pytest.raises(rpc.RecoveryRPCRefused, match="endpoint"):
            rpc.observe_recovery_over_a3(
                sock,
                lease=badlease,
                transaction_nonce=NONCE,
            )


@pytest.mark.parametrize(
    "error", [OSError("lost A3 connection"), RuntimeError("failed")]
)
def test_client_performs_no_auto_retry_when_authenticated_request_fails(
    endpoint: tuple[Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    sock, lease = endpoint
    channel = FakeChannel(error)
    calls = [0]

    def connect(*a, **kw):
        calls[0] += 1
        return channel

    monkeypatch.setattr(ipc_transport, "connect_authenticated", connect)
    with pytest.raises(type(error)):
        rpc.observe_recovery_over_a3(sock, lease=lease, transaction_nonce=NONCE)
    assert calls == [1]
    assert len(channel.calls) == 1
    assert channel.closed == 1
