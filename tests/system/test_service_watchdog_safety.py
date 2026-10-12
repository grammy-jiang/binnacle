"""Recovery requires fresh local failure AND no durable jobs in the store."""

from __future__ import annotations

import json
import os
import stat

import pytest

from binnacle.companions import service_watchdog_safety as safety

JOB = "0123456789ab"
ANOTHER = "deadbeef1234"


def record(root, job=JOB, **fields):
    directory = root / job
    directory.mkdir()
    document = {
        "started_at": 100,
        "command": "simulated",
        "workdir": "/tmp",
        "pid": 123,
        **fields,
    }
    (directory / "meta.json").write_text(json.dumps(document))
    return directory


def terminal(**fields):
    return {"ended_at": 110, "exit_code": 0, **fields}


def test_empty_store_is_idle_and_live_job_blocks(tmp_path):
    assert safety.active_jobs(tmp_path) == 0
    record(tmp_path)
    assert safety.active_jobs(tmp_path) == 1


def test_completed_records_not_counted_and_unknown_is_busy(tmp_path):
    record(tmp_path, **terminal())
    record(tmp_path, ANOTHER, **terminal(signal=9))
    assert safety.active_jobs(tmp_path) == 0
    p = tmp_path / ANOTHER / "meta.json"
    doc = json.loads(p.read_text())
    doc["authority"] = "UNKNOWN"
    p.write_text(json.dumps(doc))
    assert safety.active_jobs(tmp_path) == 1


@pytest.mark.parametrize(
    "fields,completed",
    [
        ({"ended_at": 101, "exit_code": 0}, True),
        ({"ended_at": 101, "signal": 9}, True),
        ({"ended_at": 101, "termination_reason": "owner_restart"}, True),
        ({"ended_at": 101, "termination_reason": "host_reboot"}, True),
        ({"ended_at": 101, "termination_reason": "normal_exit"}, False),
        ({"ended_at": 101, "exit_code": None}, False),
        ({"ended_at": 101, "exit_code": True}, False),
        ({"ended_at": 101, "signal": True}, False),
        ({"ended_at": "101", "exit_code": 0}, False),
        ({"ended_at": True, "exit_code": 0}, False),
        ({"exit_code": 0}, False),
        ({"ended_at": 101, "exit_code": 0, "authority": "UNKNOWN"}, False),
    ],
)
def test_terminal_evidence_is_durable_not_a_guess(fields, completed):
    assert safety._completed(fields) is completed


def test_terminal_signal_bool_not_valid(tmp_path):
    record(tmp_path, ended_at=101, signal=None)
    assert safety.active_jobs(tmp_path) == 1


def test_unknown_metadata_is_not_idle(tmp_path):
    directory = tmp_path / JOB
    directory.mkdir()
    for payload in ("not json", "[]", "{}", '"text"'):
        (directory / "meta.json").write_text(payload)
        observed = safety.active_jobs(tmp_path)
        assert observed in (None, 1)
        assert observed != 0


def test_job_dir_symlink_or_job_meta_symlink_fail_closed(tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    other = tmp_path / "outside"
    other.mkdir()
    (root / JOB).symlink_to(other)
    assert safety.active_jobs(root) is None
    (root / JOB).unlink()
    directory = record(root, **terminal())
    path = directory / "meta.json"
    path.unlink()
    path.symlink_to(tmp_path / "none")
    assert safety.active_jobs(root) is None


def test_root_symlink_absent_and_wrong_owner(tmp_path, monkeypatch):
    root = tmp_path / "jobs"
    assert safety.active_jobs(root) is None
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    assert safety.active_jobs(alias) is None
    monkeypatch.setattr(safety.os, "getuid", lambda: -1000)
    assert safety.active_jobs(root) is None


def test_record_nonregular_oversized_or_missing(tmp_path):
    directory = record(tmp_path, **terminal())
    meta = directory / "meta.json"
    meta.write_text("x" * (safety._MAX_META + 1))
    assert safety.active_jobs(tmp_path) is None
    meta.unlink()
    assert safety.active_jobs(tmp_path) is None
    meta.mkdir()
    assert safety.active_jobs(tmp_path) is None


def test_max_jobs_guard_and_nonmatching_noise(tmp_path, monkeypatch):
    record(tmp_path, **terminal())
    (tmp_path / ".manager.lock").write_text("ignored")
    assert safety.active_jobs(tmp_path) == 0
    monkeypatch.setattr(safety, "_MAX_JOBS", 0)
    assert safety.active_jobs(tmp_path) is None


@pytest.mark.parametrize(
    "running,responsive,expected",
    [
        (True, False, (True, "verified")),
        (False, False, (False, "service_not_confirmed_running")),
        (None, False, (False, "service_not_confirmed_running")),
        (True, None, (False, "endpoint_not_confirmed_unresponsive")),
        (True, True, (False, "endpoint_not_confirmed_unresponsive")),
    ],
)
def test_fresh_observation_blocks_changes_and_unknowns(
    tmp_path, running, responsive, expected
):
    assert (
        safety.recovery_allowed(
            root=tmp_path, fresh_running=running, fresh_responsive=responsive
        )
        == expected
    )


def test_running_jobs_and_unknown_store_prevent_restart(tmp_path):
    record(tmp_path)
    assert safety.recovery_allowed(
        root=tmp_path, fresh_running=True, fresh_responsive=False
    ) == (False, "jobs_active")
    assert safety.recovery_allowed(
        root=tmp_path / "nonexistent", fresh_running=True, fresh_responsive=False
    ) == (False, "jobs_state_unknown")


def test_never_changes_jobs_permissions_or_metadata(tmp_path):
    directory = record(tmp_path)
    meta = directory / "meta.json"
    original = meta.read_bytes()
    before = os.stat(meta)
    assert safety.active_jobs(tmp_path) == 1
    after = os.stat(meta)
    assert meta.read_bytes() == original
    assert before.st_mtime_ns == after.st_mtime_ns
    assert stat.S_IMODE(before.st_mode) == stat.S_IMODE(after.st_mode)


def test_malformed_terminal_shape_does_not_claim_idle(tmp_path):
    directory = record(tmp_path, **terminal())
    p = directory / "meta.json"
    obj = json.loads(p.read_text())
    obj.pop("started_at")
    p.write_text(json.dumps(obj))
    assert safety.active_jobs(tmp_path) is None


def test_darwin_recovery_uses_authoritative_job_manager_ping(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from binnacle import config
    from binnacle.platform import composition

    seen = []
    calls = {"reply": {"ok": True, "running_jobs": 4, "unknown_jobs": 0}}

    class Client:
        def ping(self, path):
            seen.append(path)
            return calls["reply"]

    monkeypatch.setattr(composition, "create_job_client", lambda: Client())
    monkeypatch.setattr(
        composition,
        "create_runtime_paths",
        lambda: SimpleNamespace(jobs_socket=tmp_path / "manager.sock"),
    )
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(jobs=SimpleNamespace(socket_path=None)),
    )

    # Darwin's running manager is the authority, not historical spool records.
    assert safety.current_job_activity(tmp_path / "missing", host="darwin") == 4
    assert seen == [tmp_path / "manager.sock"]
    assert safety.recovery_allowed(
        root=tmp_path / "missing",
        host="darwin",
        fresh_running=True,
        fresh_responsive=False,
    ) == (False, "jobs_active")

    calls["reply"] = {"ok": True, "running_jobs": 0, "unknown_jobs": 0}
    assert safety.recovery_allowed(
        root=tmp_path / "missing",
        host="darwin",
        fresh_running=True,
        fresh_responsive=False,
    ) == (True, "verified")


@pytest.mark.parametrize(
    "invalid",
    [
        {"ok": False, "running_jobs": 0, "unknown_jobs": 0},
        {"ok": True, "running_jobs": None, "unknown_jobs": 0},
        {"ok": True, "running_jobs": -1, "unknown_jobs": 0},
        {"ok": True, "running_jobs": 0, "unknown_jobs": True},
        {"ok": True, "running_jobs": 0},
    ],
)
def test_darwin_manager_bad_counts_are_unknown(monkeypatch, tmp_path, invalid):
    from types import SimpleNamespace

    from binnacle import config
    from binnacle.platform import composition

    monkeypatch.setattr(
        composition,
        "create_job_client",
        lambda: SimpleNamespace(ping=lambda path: invalid),
    )
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(jobs=SimpleNamespace(socket_path=tmp_path / "sock")),
    )
    assert safety.current_job_activity(tmp_path, host="darwin") is None


def test_darwin_manager_disconnect_is_not_idle(monkeypatch, tmp_path):
    from binnacle.platform import composition

    monkeypatch.setattr(
        composition,
        "create_job_client",
        lambda: (_ for _ in ()).throw(OSError("manager disconnected")),
    )
    assert safety.current_job_activity(tmp_path, host="darwin") is None
