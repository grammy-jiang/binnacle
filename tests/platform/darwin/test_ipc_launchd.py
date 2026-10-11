"""Owned launchd lifecycle tests; real mutations require explicit opt-in.

The opt-in creates only com.binnacle.r3test.<random> labels and cleans only
those labels. The probe is a non-job IPC server; it proves no durable parity.
"""

from __future__ import annotations

import dataclasses
import json
import os
import plistlib
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from binnacle.platform.contracts.capability_contracts import (
    CapabilityState,
    NativeCapabilityError,
)
from binnacle.platform.contracts.native_service_contracts import ServicePlan
from binnacle.platform.darwin import service_launchd as launchd
from binnacle.platform.darwin.generation_runtime import open_service_lease
from binnacle.platform.darwin.ipc_transport import connect_authenticated


@pytest.fixture
def service_root():
    with tempfile.TemporaryDirectory(
        prefix="bnld-", dir=Path(tempfile.gettempdir()).resolve()
    ) as value:
        root = Path(value)
        root.chmod(0o700)
        yield root


def make_plan(root, role="probe"):
    label = "com.binnacle.r3test." + secrets.token_hex(12) + "." + role
    lease = open_service_lease(root=root, label=label, generation=secrets.token_hex(16))
    script = Path(__file__).with_name("test_ipc_generation.py").resolve()
    value = {
        "Label": label,
        "ProgramArguments": [
            sys.executable,
            str(script),
            "serve",
            str(root),
            label,
            lease.generation,
            "-",
        ],
        "EnvironmentVariables": {
            "BINNACLE_RUNTIME_DIR": str(root),
            "BINNACLE_SERVICE_ROLE": role,
        },
        "WorkingDirectory": str(Path.cwd()),
        "RunAtLoad": True,
        "KeepAlive": False,
        "LimitLoadToSessionType": "Background",
    }
    data = plistlib.dumps(value)
    path = root / "service.plist"
    path.write_bytes(data)
    path.chmod(0o600)
    return ServicePlan(lease, data, path, None)


def test_never_adopts_foreign_label_or_lease(service_root, monkeypatch):
    plan = make_plan(service_root)
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="foreign service", stderr="")

    monkeypatch.setattr(launchd, "_run", run)
    owner = launchd.LaunchdUserServices(plan.lease)
    with pytest.raises(NativeCapabilityError, match="not_owned"):
        owner.bootout(plan.lease, timeout_s=1)
    with pytest.raises(NativeCapabilityError, match="not_absent"):
        owner.bootstrap(plan)
    assert calls == [("print", owner.target)]
    with pytest.raises(NativeCapabilityError):
        launchd.LaunchdUserServices(
            dataclasses.replace(plan.lease, label="com.foreign")
        )


def test_plist_replacement_and_manager_unknown_refuse_mutation(
    service_root, monkeypatch
):
    plan = make_plan(service_root, "manager")
    owner = launchd.LaunchdUserServices(plan.lease)
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        if args[0] == "print" and owner._plan is None:
            return subprocess.CompletedProcess(args, 113, "", "Could not find service")
        return subprocess.CompletedProcess(
            args, 0, f"\tpath = {plan.plist_path}\n\tstate = running\n\tpid = 100\n", ""
        )

    monkeypatch.setattr(launchd, "_run", run)
    owner.bootstrap(plan)
    with pytest.raises(NativeCapabilityError, match="quiet_gate_unavailable"):
        owner.bootout(plan.lease, timeout_s=1)
    assert owner.restart(plan.lease.label).returncode == 1
    assert not any(args[0] == "bootout" for args in calls)
    plan.plist_path.write_bytes(b"foreign bytes")
    with pytest.raises(NativeCapabilityError, match="plan_changed"):
        owner.bootout(plan.lease, timeout_s=1)
    assert plan.plist_path.read_bytes() == b"foreign bytes"


def test_readiness_requires_authenticated_ping_and_unknown_fields(service_root):
    plan = make_plan(service_root)
    owner = launchd.LaunchdUserServices(plan.lease)
    assert owner.readiness(plan.lease, timeout_s=0.1).state == CapabilityState.UNKNOWN
    assert owner.started_at_epoch(plan.lease.label) is None
    assert owner.rss_kb(plan.lease.label) is None
    assert owner.main_process_path(plan.lease.label) is None
    assert owner.main_process_has_environment(plan.lease.label, "X", "Y") is None
    assert owner.status("foreign").state == "unknown"


@pytest.mark.parametrize(
    "code,stderr", [(1, "Could not find service"), (113, "Permission denied"), (0, "")]
)
def test_print_failure_is_not_positive_absence(code, stderr):
    assert not launchd._absent(subprocess.CompletedProcess([], code, "", stderr))


def _wait_ready(owner):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if owner.readiness(owner.lease, timeout_s=0.3).state == CapabilityState.LIMITED:
            return
        time.sleep(0.05)
    pytest.fail("launchd authenticated readiness failed")


def _observed_pid(owner):
    channel = connect_authenticated(
        owner.root / "jobs.sock", lease=owner.lease, timeout_s=2
    )
    try:
        return channel.request({"version": 1, "op": "ping"}, timeout_s=2)["pid"]
    finally:
        channel.close()


@pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("BINNACLE_A3_LAUNCHD") != "1",
    reason="A3/T0: outside-sandbox BINNACLE_A3_LAUNCHD=1 required for owned launchd gate",
)
def test_frontend_restart_manager_continuity_and_positive_bootout(
    service_root, monkeypatch
):
    native_run = launchd._run

    def observed_run(*args, **kwargs):
        result = native_run(*args, **kwargs)
        print(
            json.dumps(
                {
                    "event": "launchctl",
                    "args": args,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        )
        return result

    monkeypatch.setattr(launchd, "_run", observed_run)
    owners = []
    cleanup = []
    try:
        for role in ("probe", "frontend", "probe"):
            root = service_root / str(len(owners))
            root.mkdir(mode=0o700)
            plan = make_plan(root, role)
            owner = launchd.LaunchdUserServices(plan.lease)
            owner.bootstrap(plan)
            owners.append(owner)
            _wait_ready(owner)
        manager, frontend, sentinel = owners
        manager_pid = _observed_pid(manager)
        sentinel_pid = _observed_pid(sentinel)
        frontend_pid = _observed_pid(frontend)
        action = frontend.restart(frontend.lease.label, timeout=5)
        assert action.returncode == 0, action
        _wait_ready(frontend)
        assert _observed_pid(frontend) != frontend_pid
        assert _observed_pid(manager) == manager_pid
        assert _observed_pid(sentinel) == sentinel_pid
        print(
            json.dumps(
                {
                    "event": "frontend_restart",
                    "manager_pid": manager_pid,
                    "manager_generation": manager.lease.generation,
                    "sentinel_pid": sentinel_pid,
                    "frontend_old_pid": frontend_pid,
                    "frontend_new_pid": _observed_pid(frontend),
                }
            )
        )
    finally:
        for owner in reversed(owners):
            if owner._plan is None:
                continue  # never acquired ownership, so never boot out
            receipt = owner.bootout(owner.lease, timeout_s=6)
            record = {
                "label": owner.lease.label,
                "generation": owner.lease.generation,
                "root": str(owner.root),
                "absent": receipt.absent,
                "reason": receipt.capability.reason_code,
                "registration_absent": owner.status(owner.lease.label).state
                == "inactive",
                "socket_absent": not os.path.lexists(owner.root / "jobs.sock"),
                "auth_absent": not os.path.lexists(owner.root / "jobs.sock.auth"),
            }
            cleanup.append(record)
            print(json.dumps({"event": "owned_cleanup", **record}))
        assert len(cleanup) == len(owners)
        assert all(
            record["absent"]
            and record["registration_absent"]
            and record["socket_absent"]
            and record["auth_absent"]
            for record in cleanup
        )


def test_owned_bootout_checks_leader_and_positive_absence(service_root, monkeypatch):
    """Model fault paths only; native receipt remains a separate required gate."""
    plan = make_plan(service_root)
    owner = launchd.LaunchdUserServices(plan.lease)
    state = {"present": False, "exit": False}
    commands = []

    def run(*args, **kwargs):
        commands.append(args)
        if args[0] == "bootstrap":
            state["present"] = True
            return subprocess.CompletedProcess(args, 0, "", "")
        if state["present"]:
            return subprocess.CompletedProcess(
                args,
                0,
                f"\tpath = {plan.plist_path}\n\tstate = running\n\tpid = 100\n",
                "",
            )
        return subprocess.CompletedProcess(args, 113, "", "Could not find service")

    def bootout(target, pid, deadline):
        assert target == owner.target and pid == 100
        state["present"] = False
        return state["exit"]

    monkeypatch.setattr(launchd, "_run", run)
    monkeypatch.setattr(launchd, "_bootout_observed", bootout)
    owner.bootstrap(plan)
    assert not owner.bootout(plan.lease, timeout_s=0.02).absent
    state["present"] = True
    state["exit"] = True
    assert owner.bootout(plan.lease, timeout_s=0.1).absent
    assert owner._plan is None
    with pytest.raises(NativeCapabilityError, match="not_owned"):
        owner.bootout(plan.lease, timeout_s=0.1)


def test_registration_replacement_and_invalid_plans_do_not_mutate(
    service_root, monkeypatch
):
    plan = make_plan(service_root)
    owner = launchd.LaunchdUserServices(plan.lease)
    commands = []

    def run(*args, **kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "path = /foreign\n", "")

    monkeypatch.setattr(launchd, "_run", run)
    owner._plan = plan
    owner._digest = launchd.hashlib.sha256(plan.plist_bytes).hexdigest()
    with pytest.raises(NativeCapabilityError, match="registration_changed"):
        owner.bootout(plan.lease, timeout_s=0.1)
    assert commands == [("print", owner.target)]
    for key, value in (
        ("KeepAlive", True),
        ("Label", "foreign"),
        ("Program", "/bin/sh"),
    ):
        data = plistlib.loads(plan.plist_bytes)
        data[key] = value
        with pytest.raises(NativeCapabilityError):
            owner._validate_plist(data)


@pytest.mark.skipif(sys.platform != "darwin", reason="A3 native AF_UNIX peer identity")
@pytest.mark.parametrize(
    "fault", ["slow", "idle", "capacity", "nested", "depth", "handler", "timeout"]
)
def test_manager_serving_survives_review_regressions(
    service_root, fault, caplog, monkeypatch
):
    from binnacle.platform.darwin import ipc_transport as ipc
    from tests.platform.darwin.test_ipc_generation import connect_when_ready, serving

    if fault == "capacity":
        monkeypatch.setattr(ipc, "_MAX_CLIENTS", 2)
    with serving(service_root) as (lease, calls, errors):
        channel = connect_when_ready(service_root / "jobs.sock", lease)
        try:
            if fault == "slow":
                assert channel.request({"delay": 2.3}, timeout_s=10)["ok"]
                assert len(calls) == 1
            elif fault == "idle":
                other = connect_authenticated(
                    service_root / "jobs.sock", lease=lease, timeout_s=1
                )
                other.close()
                time.sleep(2.2)
                assert channel.request({}, timeout_s=1)["ok"]
            elif fault == "capacity":
                other = connect_when_ready(service_root / "jobs.sock", lease)
                try:
                    with pytest.raises(NativeCapabilityError):
                        connect_authenticated(
                            service_root / "jobs.sock", lease=lease, timeout_s=0.2
                        )
                finally:
                    other.close()
            elif fault in ("nested", "depth"):
                import socket
                import struct

                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                    conn.connect(str(service_root / "jobs.sock"))
                    size = 200000 if fault == "nested" else 256
                    conn.settimeout(1)
                    try:
                        conn.sendall(struct.pack("!I", size) + b"[" * size)
                        assert conn.recv(1) == b""
                    except (ConnectionResetError, BrokenPipeError):
                        pass
            else:
                from binnacle.platform.contracts.capability_contracts import (
                    BudgetExceeded,
                )

                expected = (
                    BudgetExceeded if fault == "timeout" else NativeCapabilityError
                )
                sequence = channel.sequence
                with pytest.raises(expected):
                    channel.request(
                        {"delay": 0.3} if fault == "timeout" else {"raise": True},
                        timeout_s=0.1,
                    )
                time.sleep(0.4)
                if fault == "timeout":
                    assert "ipc_response_undelivered" in caplog.text
                    replay = connect_when_ready(service_root / "jobs.sock", lease)
                    payload = {"delay": 0.3}
                    value = [channel.transcript, sequence, "rpc", payload]
                    ipc._send(
                        replay.conn,
                        {
                            "sequence": sequence,
                            "kind": "rpc",
                            "payload": payload,
                            "proof": ipc._proof(channel.key, "request", value),
                        },
                        time.monotonic() + 1,
                    )
                    assert replay.conn.recv(1) == b""
                    replay.close()
                    assert calls == [payload]
            other = connect_when_ready(service_root / "jobs.sock", lease, timeout=1)
            assert other.request({}, timeout_s=1)["ok"]
            other.close()
        finally:
            channel.close()
    assert not errors


@pytest.mark.parametrize(
    "key", ["AbandonProcessGroup", "StartInterval", "WatchPaths", "LaunchEvents"]
)
def test_plist_rejects_unowned_lifecycle_triggers(service_root, key):
    plan = make_plan(service_root)
    value = plistlib.loads(plan.plist_bytes)
    value[key] = True
    with pytest.raises(NativeCapabilityError, match="scope_refused"):
        launchd.LaunchdUserServices(plan.lease)._validate_plist(value)


def test_manager_label_cannot_declare_frontend_role(service_root, monkeypatch):
    plan = make_plan(service_root, "manager")
    value = plistlib.loads(plan.plist_bytes)
    value["EnvironmentVariables"]["BINNACLE_SERVICE_ROLE"] = "frontend"
    data = plistlib.dumps(value)
    plan.plist_path.write_bytes(data)
    plan = dataclasses.replace(plan, plist_bytes=data)
    commands = []
    monkeypatch.setattr(launchd, "_run", lambda *args: commands.append(args))
    owner = launchd.LaunchdUserServices(plan.lease)
    with pytest.raises(NativeCapabilityError, match="scope_refused"):
        owner.bootstrap(plan)
    assert owner.restart(plan.lease.label).returncode == 1
    assert commands == []


@pytest.mark.skipif(sys.platform != "darwin", reason="A3 native singleton drain")
def test_delayed_executor_retains_singleton_until_quiescent(service_root):
    import threading

    from binnacle.platform.darwin import ipc_transport as ipc
    from tests.platform.darwin.test_ipc_generation import (
        connect_when_ready,
        lease_for,
        serving,
    )

    runtime = service_root
    lease = lease_for(runtime)
    stop, entered, release = threading.Event(), threading.Event(), threading.Event()
    replies, errors = [], []

    def handler(payload):
        entered.set()
        assert release.wait(3)
        return {"ok": True}

    def serve():
        try:
            ipc.serve_authenticated(
                runtime / "jobs.sock", lease=lease, handler=handler, stop=stop
            )
        except NativeCapabilityError as exc:
            errors.append(exc)

    server = threading.Thread(target=serve)
    server.start()
    channel = connect_when_ready(runtime / "jobs.sock", lease)

    def request():
        replies.append(channel.request({"op": "delayed"}, timeout_s=2))

    caller = threading.Thread(target=request)
    caller.start()
    try:
        assert entered.wait(1)
        stop.set()
        with pytest.raises(NativeCapabilityError, match="duplicate_starter"):
            ipc.serve_authenticated(
                runtime / "jobs.sock",
                lease=lease_for(runtime),
                handler=lambda p: p,
                stop=threading.Event(),
            )
        assert server.is_alive()
    finally:
        release.set()
        caller.join(3)
        channel.close()
        server.join(3)
    assert not caller.is_alive() and not server.is_alive()
    assert replies == [{"ok": True}] and not errors
    with serving(runtime) as (_, calls, errors):
        with pytest.raises(NativeCapabilityError):
            ipc.connect_authenticated(runtime / "jobs.sock", lease=lease, timeout_s=1)
        assert not calls
    assert not errors
