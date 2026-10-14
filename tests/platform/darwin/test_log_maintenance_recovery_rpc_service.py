"""Server facade permits ONLY preconfigured read-only observation over A3."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from threading import Event

import pytest

from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.darwin import ipc_transport
from binnacle.platform.darwin import log_maintenance_recovery_rpc as rpc
from tests.platform.darwin.test_log_maintenance_recovery_rpc_handler import (
    NONCE,
    record,
    request,
)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, Path, ServiceLease]:
    transaction = tmp_path / ("txn-" + NONCE)
    transaction.mkdir(mode=0o700)
    transaction.chmod(0o700)
    runtime = tmp_path / "log-maintenance-observer-ipc"
    runtime.mkdir(mode=0o700)
    runtime.chmod(0o700)
    socket_path = runtime / "observe.sock"
    lease = ServiceLease(
        os.getuid(), rpc._LABEL, "0123456789abcdef0123456789abcdef", 34, 56
    )
    return transaction, socket_path, lease


def test_serve_function_is_only_an_explicit_a3_wrapper(
    setup: tuple[Path, Path, ServiceLease], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, path, lease = setup
    snapshot = record(root, "guardian_armed")
    stop = Event()
    received: list[tuple] = []

    def fake_serve(socket_path, *, lease, handler, stop):
        received.append((socket_path, lease, stop))
        result = handler(request())
        assert result == rpc._wire(rpc.assess_recovery(snapshot), snapshot.revision)
        assert result["production_authorized"] is False
        assert result["autonomous_restart_allowed"] is False
        assert result["manual_review_required"] is True

    monkeypatch.setattr(ipc_transport, "serve_authenticated", fake_serve)
    before = (root / "transaction.json").read_bytes()
    rpc.serve_readonly_recovery_over_a3(
        path, lease=lease, transaction_root=root, stop=stop
    )
    assert received == [(path, lease, stop)]
    assert (root / "transaction.json").read_bytes() == before
    assert not path.exists()


def test_served_handler_refuses_all_noninspection_requests(
    setup: tuple[Path, Path, ServiceLease], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, path, lease = setup
    record(root, "guardian_armed")
    seen: list[str] = []

    def fake_serve(socket_path, *, lease, handler, stop):
        for op in ("bootstrap", "bootout", "restart", "prune", "stop", "kill"):
            with pytest.raises(rpc.RecoveryRPCRefused):
                handler({"version": 1, "op": op, "nonce": NONCE})
            seen.append(op)
        with pytest.raises(rpc.RecoveryRPCRefused):
            handler({**request(), "source": "/private/var/log/binnacle.log"})
        assert handler(request())["ok"] is True

    monkeypatch.setattr(ipc_transport, "serve_authenticated", fake_serve)
    rpc.serve_readonly_recovery_over_a3(
        path, lease=lease, transaction_root=root, stop=Event()
    )
    assert seen == ["bootstrap", "bootout", "restart", "prune", "stop", "kill"]


@pytest.mark.parametrize(
    "badpath",
    [
        "/tmp/binnacle-jobs-ipc/observe.sock",
        "/tmp/log-maintenance-observer-ipc/jobs.sock",
        "/tmp/log-maintenance-observer-ipc/control.sock",
        "/tmp/log-maintenance-observer-ipc/observe.sockx",
        "log-maintenance-observer-ipc/observe.sock",
    ],
)
def test_service_refuses_wrong_socket_endpoint_before_a3_call(
    setup: tuple[Path, Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
    badpath: str,
) -> None:
    root, _, lease = setup
    monkeypatch.setattr(
        ipc_transport,
        "serve_authenticated",
        lambda *a, **kw: pytest.fail("foreign A3 endpoint must not be bound"),
    )
    with pytest.raises(rpc.RecoveryRPCRefused, match="endpoint"):
        rpc.serve_readonly_recovery_over_a3(
            Path(badpath), lease=lease, transaction_root=root, stop=Event()
        )


@pytest.mark.parametrize(
    "label",
    ["com.binnacle.jobs", "com.binnacle.mcp", "com.binnacle.service-watchdog"],
)
def test_service_cannot_share_an_existing_critical_label(
    setup: tuple[Path, Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
    label: str,
) -> None:
    root, path, lease = setup
    monkeypatch.setattr(
        ipc_transport,
        "serve_authenticated",
        lambda *a, **kw: pytest.fail("wrong service label"),
    )
    wrong = ServiceLease(lease.uid, label, lease.generation, 34, 56)
    with pytest.raises(rpc.RecoveryRPCRefused, match="endpoint"):
        rpc.serve_readonly_recovery_over_a3(
            path, lease=wrong, transaction_root=root, stop=Event()
        )


def test_wrong_service_uid_refuses_without_touching_socket(
    setup: tuple[Path, Path, ServiceLease], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, path, lease = setup
    wrong = ServiceLease(os.getuid() + 1, lease.label, lease.generation, 34, 56)
    monkeypatch.setattr(
        ipc_transport,
        "serve_authenticated",
        lambda *a, **kw: pytest.fail("wrong UID"),
    )
    with pytest.raises(rpc.RecoveryRPCRefused, match="endpoint"):
        rpc.serve_readonly_recovery_over_a3(
            path, lease=wrong, transaction_root=root, stop=Event()
        )


@pytest.mark.parametrize("kind", ["root", "setuid"])
def test_service_refuses_root_or_mixed_euid(
    setup: tuple[Path, Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    root, path, lease = setup
    from binnacle.platform.darwin import log_maintenance_recovery_rpc as target

    initial = os.getuid()
    with monkeypatch.context() as m:
        if kind == "root":
            m.setattr(target.os, "getuid", lambda: 0)
        else:
            m.setattr(target.os, "geteuid", lambda: initial + 1)
        with pytest.raises(rpc.RecoveryRPCRefused, match="unprivileged"):
            rpc.serve_readonly_recovery_over_a3(
                path, lease=lease, transaction_root=root, stop=Event()
            )
    assert not path.exists()


def test_service_requires_root_pinned_by_authorized_caller(
    setup: tuple[Path, Path, ServiceLease],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, path, lease = setup
    monkeypatch.setattr(
        ipc_transport,
        "serve_authenticated",
        lambda *a, **kw: pytest.fail("unknown root must not start A3"),
    )
    with pytest.raises(rpc.RecoveryRPCRefused, match="root not pinned"):
        rpc.serve_readonly_recovery_over_a3(
            path, lease=lease, transaction_root=root.parent / "txn-bad", stop=Event()
        )


def test_server_and_client_share_one_strict_response_schema(
    setup: tuple[Path, Path, ServiceLease],
) -> None:
    root, _, _ = setup
    record(root, "producer_stopped")
    handler = rpc.RecoveryObservationHandler(root)
    response = handler(request())
    decision = rpc._parse_reply(response, NONCE)
    assert decision.phase == "producer_stopped"
    assert decision.risks == rpc._expected_from_phase("producer_stopped")[1]
    assert decision.manual_review_required
    assert not decision.production_authorized
    assert not decision.autonomous_restart_allowed


def test_handler_only_runs_in_independent_subprocess_without_writes(
    setup: tuple[Path, Path, ServiceLease],
) -> None:
    root, _, _ = setup
    record(root, "guardian_armed")
    record_file = root / "transaction.json"
    before = (record_file.read_bytes(), record_file.stat().st_mtime_ns)
    # Real subprocess boundary, but no sockets or native launchd devices.
    code = (
        "import json,sys\n"
        "from pathlib import Path\n"
        "from binnacle.platform.darwin.log_maintenance_recovery_rpc import "
        "RecoveryObservationHandler\n"
        "root=Path(sys.argv[1])\n"
        "print(json.dumps(RecoveryObservationHandler(root)"
        "({'version':1,'op':'inspect','nonce':'a'*32})))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(root)],
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )
    assert result.returncode == 0, result.stderr
    assert '"production_authorized": false' in result.stdout
    assert '"autonomous_restart_allowed": false' in result.stdout
    assert '"phase": "guardian_armed"' in result.stdout
    assert (record_file.read_bytes(), record_file.stat().st_mtime_ns) == before
