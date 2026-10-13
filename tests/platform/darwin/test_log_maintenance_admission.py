"""Issue #30 P1: dry-run admission NEVER opens a production maintenance gate."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.companions import darwin_log_maintenance_admission as admit

OWNER = "a" * 32
REVISION = "b" * 12
PID = 4629


def fixture(tmp_path: Path):
    root = tmp_path / "jobs"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def reply(root: Path, **patch):
    value = {
        "ok": True,
        "owner_instance_id": OWNER,
        "pid": PID,
        "revision": REVISION,
        "jobs_dir": str(root),
        "running_jobs": 0,
        "unknown_jobs": 0,
    }
    value.update(patch)
    return value


def inspect(root: Path, pings=None, *, pid=PID, records=0):
    replies = pings if pings is not None else [reply(root)]
    calls = [0]

    def ping():
        calls[0] += 1
        return replies[min(len(replies) - 1, calls[0] - 1)]

    return admit.audit_jobs(
        root,
        ping=ping,
        service_pid=lambda: pid,
        record_counter=lambda _: records,
    )


def test_perfectly_idle_manager_still_does_not_authorize_any_action(tmp_path):
    root = fixture(tmp_path)
    result = inspect(root)
    assert result.manager == admit.ManagerGeneration(
        OWNER, PID, REVISION, str(root), 0, 0
    )
    assert result.record_active == 0
    assert result.reasons == ("maintenance_barrier_not_held",)
    assert not result.approved


@pytest.mark.parametrize(
    ("changed", "records", "needed"),
    [
        ({"running_jobs": 1}, 1, "running_jobs"),
        ({"unknown_jobs": 1}, 1, "unknown_jobs"),
        ({}, 1, "durable_jobs_active"),
        ({"running_jobs": 2}, 0, "durable_manager_counts_disagree"),
        ({"running_jobs": 1, "unknown_jobs": 3}, 3, "durable_manager_counts_disagree"),
    ],
)
def test_nonidle_or_inconsistent_manager_never_authorizes(
    tmp_path, changed, records, needed
):
    root = fixture(tmp_path)
    result = inspect(root, [reply(root, **changed)], records=records)
    assert needed in result.reasons
    assert not result.approved


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("ok", False),
        ("ok", 1),
        ("owner_instance_id", ""),
        ("owner_instance_id", "a" * 31),
        ("owner_instance_id", "g" * 32),
        ("pid", 0),
        ("pid", -1),
        ("pid", True),
        ("pid", "4629"),
        ("revision", ""),
        ("revision", "bad"),
        ("revision", "G" * 12),
        ("jobs_dir", "/tmp/forged"),
        ("jobs_dir", 3),
        ("running_jobs", -1),
        ("running_jobs", 1.0),
        ("running_jobs", False),
        ("running_jobs", "0"),
        ("unknown_jobs", -1),
        ("unknown_jobs", True),
        ("unknown_jobs", None),
    ],
)
def test_malformed_authenticated_rpc_is_unknown_and_refused(tmp_path, field, invalid):
    root = fixture(tmp_path)
    result = inspect(root, [reply(root, **{field: invalid})])
    assert "manager_ping_unverifiable" in result.reasons
    assert "manager_reping_unverifiable" in result.reasons
    assert not result.approved


@pytest.mark.parametrize(
    ("field", "updated"),
    [
        ("owner_instance_id", "c" * 32),
        ("pid", PID + 1),
        ("revision", "e" * 12),
        ("running_jobs", 1),
        ("unknown_jobs", 1),
    ],
)
def test_changed_owner_or_counters_between_pings_is_not_idle(tmp_path, field, updated):
    root = fixture(tmp_path)
    result = inspect(root, [reply(root), reply(root, **{field: updated})])
    assert "manager_generation_or_counts_changed" in result.reasons
    assert not result.approved


@pytest.mark.parametrize("pid", [None, -1, 0, True, 1234])
def test_missing_or_mismatched_launchd_pid_blocks(tmp_path, pid):
    root = fixture(tmp_path)
    result = inspect(root, pid=pid)
    if pid == PID:
        assert result.reasons == ("maintenance_barrier_not_held",)
    elif pid is None or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        assert "launchd_jobs_pid_unverifiable" in result.reasons
    else:
        assert "manager_launchd_pid_mismatch" in result.reasons
    assert not result.approved


def test_auth_callback_exception_is_unknown(tmp_path):
    root = fixture(tmp_path)

    def fails():
        raise RuntimeError("synthetic manager socket closed")

    result = admit.audit_jobs(
        root, ping=fails, service_pid=lambda: PID, record_counter=lambda r: 0
    )
    assert "manager_ping_unverifiable" in result.reasons
    assert "manager_reping_unverifiable" in result.reasons
    assert not result.approved


def test_probe_error_during_second_ping_never_inherits_first(tmp_path):
    root = fixture(tmp_path)
    calls = [0]

    def changing():
        calls[0] += 1
        if calls[0] == 2:
            raise TimeoutError("late server restart")
        return reply(root)

    result = admit.audit_jobs(
        root, ping=changing, service_pid=lambda: PID, record_counter=lambda r: 0
    )
    assert "manager_reping_unverifiable" in result.reasons
    assert not result.approved


def test_record_counter_unknown_or_exception_is_a_blocker(tmp_path):
    root = fixture(tmp_path)
    for seen in (None, False, -1, "0"):
        result = inspect(root, records=seen)
        assert "durable_jobs_unverifiable" in result.reasons

    def raises(_):
        raise OSError("metadata vanished")

    result = admit.audit_jobs(
        root,
        ping=lambda: reply(root),
        service_pid=lambda: PID,
        record_counter=raises,
    )
    assert "durable_jobs_unverifiable" in result.reasons
    assert not result.approved


def test_missing_log_directory_and_symlink_are_never_trusted(tmp_path):
    root = fixture(tmp_path)
    root.rename(tmp_path / "other")
    root.symlink_to(tmp_path / "other", target_is_directory=True)
    result = inspect(root)
    assert "jobs_directory_untrusted" in result.reasons
    assert not result.approved
    root.unlink()
    result = inspect(root)
    assert "jobs_directory_untrusted" in result.reasons


def test_world_accessible_durable_store_is_never_admissible(tmp_path):
    root = fixture(tmp_path)
    root.chmod(0o755)
    result = inspect(root)
    assert "jobs_directory_untrusted" in result.reasons
    root.chmod(0o700)


def test_wrong_ownership_detected_by_fd_metadata(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    root = fixture(tmp_path)
    real = admit.os.fstat

    def foreign(fd):
        info = real(fd)
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_uid=os.getuid() + 1,
            st_dev=info.st_dev,
            st_ino=info.st_ino,
        )

    monkeypatch.setattr(admit.os, "fstat", foreign)
    result = inspect(root)
    assert "jobs_directory_untrusted" in result.reasons


def test_durable_directory_replace_between_scans_is_detected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    root = fixture(tmp_path)
    first = [True]

    def move_root(p):
        if first[0]:
            first[0] = False
            p.rename(tmp_path / "moved")
            p.mkdir(mode=0o700)
        return 0

    result = admit.audit_jobs(
        root,
        ping=lambda: reply(root),
        service_pid=lambda: PID,
        record_counter=move_root,
    )
    assert "jobs_directory_changed" in result.reasons
    assert not result.approved


def test_launchd_pid_probe_failure_refuses(tmp_path):
    root = fixture(tmp_path)

    def fails():
        raise ValueError("launchctl output not a real pid")

    result = admit.audit_jobs(
        root,
        ping=lambda: reply(root),
        service_pid=fails,
        record_counter=lambda r: 0,
    )
    assert "launchd_jobs_pid_unverifiable" in result.reasons


def test_admission_audit_constructor_cannot_be_used_as_authority():
    good = ("maintenance_barrier_not_held",)
    with pytest.raises(ValueError, match="never grant"):
        admit.AdmissionAudit(None, None, good, approved=True)
    with pytest.raises(ValueError, match="never grant"):
        admit.AdmissionAudit(None, None, (), approved=False)


def test_non_darwin_adapter_is_always_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(admit.platform, "system", lambda: "Linux")
    value = admit.inspect_local_jobs(tmp_path / "not-read")
    assert not value.approved
    assert value.manager is None
    assert value.reasons == ("host_not_darwin", "maintenance_barrier_not_held")


def test_true_live_adapter_must_never_return_approved(monkeypatch, tmp_path):
    monkeypatch.setattr(admit.platform, "system", lambda: "Darwin")
    root = fixture(tmp_path)
    import binnacle.companions.darwin_log_writer_hold as holder
    from binnacle import config
    from binnacle.platform import composition

    class Config:
        class jobs:
            socket_path = None

    class Paths:
        jobs_socket = Path("/fake/trusted.sock")

    class Client:
        def ping(self, socket):
            assert socket == Path("/fake/trusted.sock")
            return reply(root)

    monkeypatch.setattr(config, "get_settings", lambda: Config())
    monkeypatch.setattr(composition, "create_runtime_paths", lambda: Paths())
    monkeypatch.setattr(composition, "create_job_client", lambda: Client())
    monkeypatch.setattr(holder, "_running_pid", lambda label: PID)
    monkeypatch.setattr(admit, "active_jobs", lambda r: 0)
    # Default callback binding is intentional, so override audit_jobs only to
    # inject the synthetic durable store counter in a local adapter test.
    actual = admit.audit_jobs

    def inject(root, *, ping, service_pid, record_counter=admit.active_jobs):
        return actual(
            root, ping=ping, service_pid=service_pid, record_counter=record_counter
        )

    monkeypatch.setattr(admit, "audit_jobs", inject)
    result = admit.inspect_local_jobs(root)
    assert result.manager is not None
    assert "maintenance_barrier_not_held" in result.reasons
    assert not result.approved
