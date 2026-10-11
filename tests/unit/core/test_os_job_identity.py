"""OI-06: Linux pidfd leases must not send signals to unproven processes."""

import signal
import time

import pytest

from binnacle.platform.contracts.process_contracts import (
    JobProcessIdentity,
    UnverifiedJobProcess,
)
from binnacle.platform.linux import job_identity as native


def record(**overrides):
    fields = {
        "pid": 1001,
        "pgid": 1001,
        "starttime": 9844,
        "started_at": time.time(),
        "boot_id": "test-boot",
    }
    fields.update(overrides)
    return fields


def test_invalid_and_legacy_records_are_not_signal_capabilities():
    for broken in (
        {"starttime": None},
        {"starttime": 0},
        {"starttime": "9844"},
        {"pid": 0},
        {"pid": 1002},
        {"pgid": 1002},
        {"pgid": "1001"},
        {"started_at": 0},
        {"started_at": True},
        {"boot_id": 12},
    ):
        assert native.identity_from_record(record(**broken)) is None
    opaque = native.identity_from_record(record())
    assert isinstance(opaque, JobProcessIdentity)
    assert isinstance(opaque.native, native.LinuxJobRecord)


@pytest.fixture
def native_table(monkeypatch):
    original = {
        1001: native._Proc(1001, 9, 1001, 9844, "S"),
        1002: native._Proc(1002, 1001, 1001, 9845, "S"),
        1003: native._Proc(1003, 1002, 1003, 9846, "S"),  # setsid descendant
        1004: native._Proc(1004, 1, 8000, 9846, "S"),  # unrelated
    }
    current = dict(original)
    opened = []
    signed = []
    closed = []

    def fake_open(pid):
        opened.append(pid)
        return pid + 10_000

    monkeypatch.setattr(native.os, "pidfd_open", fake_open, raising=False)
    monkeypatch.setattr(
        native.signal,
        "pidfd_send_signal",
        lambda fd, sig: signed.append((fd, sig)),
        raising=False,
    )

    def forbid_numeric_signal(*args):
        pytest.fail("numeric-PID signals must never replace verified pidfds")

    monkeypatch.setattr(native.os, "kill", forbid_numeric_signal)
    monkeypatch.setattr(native.os, "killpg", forbid_numeric_signal)
    monkeypatch.setattr(native, "_proc", lambda pid: current.get(pid))
    monkeypatch.setattr(native, "_scan", lambda: dict(original))
    with monkeypatch.context() as local:
        local.setattr(native.os, "close", closed.append)
        yield current, opened, signed, closed


@pytest.mark.parametrize("capability", ["pidfd_open", "pidfd_send_signal"])
def test_missing_pidfd_capability_rejects_acquisition(
    monkeypatch, native_table, capability
):
    _, opened, signed, closed = native_table
    module = native.os if capability == "pidfd_open" else native.signal
    monkeypatch.delattr(module, capability)
    with pytest.raises(UnverifiedJobProcess, match="pidfd support is required"):
        native.open_job_signals(
            native.identity_from_record(record()), boot_id=lambda: "test-boot"
        )
    assert opened == signed == closed == []


def test_missing_pidfd_sender_after_acquisition_fails_closed(monkeypatch, native_table):
    _, _, signed, closed = native_table
    lease = native.open_job_signals(
        native.identity_from_record(record()), boot_id=lambda: "test-boot"
    )
    monkeypatch.delattr(native.signal, "pidfd_send_signal")
    with pytest.raises(native.JobSignalDeliveryError, match="pidfd support"):
        lease.signal("terminate")
    assert signed == []
    lease.close()
    assert set(closed) == {11001, 11002, 11003}


def test_pidfd_signals_only_pinned_owned_group_and_setsid_child(native_table):
    _, opened, signed, closed = native_table
    identity = native.identity_from_record(record())
    lease = native.open_job_signals(identity, boot_id=lambda: "test-boot")
    assert set(opened) == {1001, 1002, 1003}
    assert 1004 not in opened
    lease.signal("terminate")
    lease.signal("kill")
    assert signed == [
        (11003, signal.SIGTERM),
        (11002, signal.SIGTERM),
        (11001, signal.SIGTERM),
        (11003, signal.SIGKILL),
        (11002, signal.SIGKILL),
        (11001, signal.SIGKILL),
    ]
    lease.close()
    assert set(closed) == {11001, 11002, 11003}
    lease.close()
    assert len(closed) == 3


def test_boot_generation_mismatch_is_rejected_before_opening_any_fd(native_table):
    _, opened, signed, closed = native_table
    identity = native.identity_from_record(record())
    with pytest.raises(UnverifiedJobProcess, match="another host boot"):
        native.open_job_signals(identity, boot_id=lambda: "other-boot")
    assert not opened and not signed and not closed


def test_wrong_or_reused_leader_aborts_without_signals(native_table):
    current, opened, signed, closed = native_table
    current[1001] = native._Proc(1001, 9, 1001, 123456, "S")
    identity = native.identity_from_record(record())
    with pytest.raises(UnverifiedJobProcess, match="leader identity"):
        native.open_job_signals(identity, boot_id=lambda: "test-boot")
    assert opened == [1001]
    assert closed == [11001]
    assert signed == []


def test_descendant_generation_swap_closes_every_fd_without_signaling(native_table):
    current, opened, signed, closed = native_table
    current[1003] = native._Proc(1003, 1002, 1003, 12_345, "S")
    identity = native.identity_from_record(record())
    with pytest.raises(UnverifiedJobProcess, match="identity changed"):
        native.open_job_signals(identity, boot_id=lambda: "test-boot")
    assert set(closed) == {pid + 10000 for pid in opened}
    assert not signed


def test_descendant_reparenting_aborts_without_signals(native_table):
    current, opened, signed, closed = native_table
    current[1003] = native._Proc(1003, 1, 1003, 9846, "S")
    identity = native.identity_from_record(record())
    with pytest.raises(UnverifiedJobProcess, match="ancestry changed"):
        native.open_job_signals(identity, boot_id=lambda: "test-boot")
    assert set(closed) == {pid + 10_000 for pid in opened}
    assert signed == []


def test_process_vanishing_during_open_never_retargets_reused_pid(
    monkeypatch, native_table
):
    _, opened, signed, closed = native_table

    def open_process(pid):
        opened.append(pid)
        if pid == 1003:
            raise ProcessLookupError
        return pid + 10000

    monkeypatch.setattr(native.os, "pidfd_open", open_process)
    lease = native.open_job_signals(
        native.identity_from_record(record()), boot_id=lambda: "test-boot"
    )
    lease.signal("terminate")
    lease.close()
    assert 11003 not in set(closed)
    assert all(fd != 11003 for fd, _ in signed)


def test_unknown_native_identity_and_scan_failure_fail_closed(
    native_table, monkeypatch
):
    _, opened, signed, closed = native_table
    with pytest.raises(UnverifiedJobProcess, match="unrecognized"):
        native.open_job_signals(
            JobProcessIdentity(object()), boot_id=lambda: "test-boot"
        )
    assert not opened
    monkeypatch.setattr(
        native,
        "_scan",
        lambda: (_ for _ in ()).throw(UnverifiedJobProcess("procfs vanished")),
    )
    with pytest.raises(UnverifiedJobProcess, match="procfs vanished"):
        native.open_job_signals(
            native.identity_from_record(record()), boot_id=lambda: "test-boot"
        )
    assert closed == [11001] and signed == []


def test_lease_handles_process_exit_after_pin_without_new_numeric_lookup(
    native_table, monkeypatch
):
    _, _, signed, closed = native_table

    def sender(fd, sig):
        if fd == 11003:
            raise ProcessLookupError
        signed.append((fd, sig))

    monkeypatch.setattr(native.signal, "pidfd_send_signal", sender)
    lease = native.open_job_signals(
        native.identity_from_record(record()), boot_id=lambda: "test-boot"
    )
    lease.signal("terminate")
    lease.close()
    assert {fd for fd, _ in signed} == {11001, 11002}
    assert len(closed) == 3


def test_unsignalable_descendant_does_not_prevent_signaling_job_leader(
    native_table, monkeypatch
):
    """P1 independent review: setuid child EPERM must not strand job leader."""
    _, opened, signed, closed = native_table

    def deliver(fd, sig):
        if fd == 11003:
            raise PermissionError(1, "operation not permitted")
        signed.append((fd, sig))

    monkeypatch.setattr(native.signal, "pidfd_send_signal", deliver)
    lease = native.open_job_signals(
        native.identity_from_record(record()), boot_id=lambda: "test-boot"
    )
    with pytest.raises(
        native.JobSignalDeliveryError, match="1 verified process"
    ) as err:
        lease.signal("terminate")
    assert "terminate" in str(err.value)
    assert signed == [(11002, signal.SIGTERM), (11001, signal.SIGTERM)]
    assert opened == [1001, 1003, 1002]
    lease.close()
    assert set(closed) == {11001, 11002, 11003}


def test_multiple_native_permission_errors_report_after_all_pinned_attempts(
    native_table, monkeypatch
):
    """A failed member cannot suppress later attempts or a structured failure."""
    _, _, signed, closed = native_table

    def deliver(fd, sig):
        if fd in {11003, 11002}:
            raise OSError(13, "verified target rejected signal")
        signed.append((fd, sig))

    monkeypatch.setattr(native.signal, "pidfd_send_signal", deliver)
    lease = native.open_job_signals(
        native.identity_from_record(record()), boot_id=lambda: "test-boot"
    )
    with pytest.raises(native.JobSignalDeliveryError, match="2 verified process"):
        lease.signal("kill")
    assert signed == [(11001, signal.SIGKILL)]
    lease.close()
    assert len(closed) == 3
