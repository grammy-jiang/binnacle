"""Cross-platform unit proof of fail-closed native log-guardian state machine."""

from __future__ import annotations

import fcntl
import hashlib
import os
import plistlib
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.companions import darwin_log_maintenance_guardian as guardian
from binnacle.companions.darwin_log_archive_finalize import ArchiveFinalizeRefused

LABEL = "com.binnacle.archivefixture.unit1234"
TARGET = "system/" + LABEL
PLIST = Path("/private/tmp") / (LABEL + ".plist")


def _root(tmp_path: Path) -> Path:
    path = tmp_path / "guard"
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _record(root: Path, **updates) -> dict:
    base = {
        "version": 1,
        "state": "armed",
        "label": LABEL,
        "plist": str(PLIST),
        "plist_sha256": "0" * 64,
        "lock": str(root / "lease.lock"),
        "previous_pid": 123,
        "nonce": "0" * 32,
    }
    base.update(updates)
    return base


def test_guardian_journal_is_private_complete_and_atomically_updated(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    path = root / "journal.json"
    initial = _record(root)
    guardian._write_record(path, initial)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert guardian._read_verified(path) == initial
    newer = {**initial, "state": "recovered", "restored_pid": 456}
    guardian._write_record(path, newer)
    assert guardian._read_verified(path) == newer
    assert not list(root.glob(".guardian-*.tmp"))


@pytest.mark.parametrize(
    ("kind", "content", "mode"),
    [
        ("json_object_missing", b"", 0o600),
        ("bad_json", b"[", 0o600),
        ("json_array", b"[]", 0o600),
        ("world_readable", b'{"ok":true}', 0o644),
        ("oversized", b"x" * 5000, 0o600),
    ],
)
def test_guardian_journal_rejects_invalid_file(
    tmp_path: Path,
    kind: str,
    content: bytes,
    mode: int,
) -> None:
    root = _root(tmp_path)
    path = root / "journal.json"
    path.write_bytes(content)
    path.chmod(mode)
    with pytest.raises(ArchiveFinalizeRefused):
        guardian._read_verified(path)
    assert kind


def test_guardian_journal_rejects_symlink_and_foreign_directory(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    path = root / "journal.json"
    second = root / "shadow.json"
    guardian._write_record(second, _record(root))
    path.symlink_to(second)
    with pytest.raises(ArchiveFinalizeRefused):
        guardian._read_verified(path)
    path.unlink()
    guardian._write_record(path, _record(root))
    root.chmod(0o755)
    with pytest.raises(ArchiveFinalizeRefused, match="unsafe"):
        guardian._read_verified(path)


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"version": 99}, "state"),
        ({"state": "interrupted"}, "state"),
        ({"label": "com.binnacle.mcp"}, "fixture"),
        ({"label": 1}, "fixture"),
        ({"plist": "/Library/LaunchDaemons/com.binnacle.mcp.plist"}, "plist path"),
        ({"lock": "/tmp/foreign-lock"}, "lock"),
        ({"previous_pid": 0}, "generation"),
        ({"previous_pid": False}, "generation"),
        ({"previous_pid": "123"}, "generation"),
        ({"nonce": "a"}, "transaction"),
        ({"nonce": 123}, "transaction"),
        ({"nonce": "g" * 32}, "transaction"),
    ],
)
def test_guardian_policy_rejects_foreign_inputs(
    tmp_path: Path, change: dict, match: str
) -> None:
    root = _root(tmp_path)
    with pytest.raises(ArchiveFinalizeRefused, match=match):
        guardian._policy(_record(root, **change), root)


def _trusted_plist(
    monkeypatch: pytest.MonkeyPatch, root: Path, **modifications
) -> dict:
    """Simulate a signed-off 0644 root-owned fixture; no host plist is written."""
    payload = {
        "Label": LABEL,
        "KeepAlive": True,
        "ProgramArguments": ["/bin/true"],
    }
    payload.update(modifications)
    wire = plistlib.dumps(payload)
    record = _record(root, plist_sha256=hashlib.sha256(wire).hexdigest())
    original_lstat, original_read = Path.lstat, Path.read_bytes

    def fake_lstat(p: Path):
        if p == PLIST:
            return SimpleNamespace(
                st_mode=stat.S_IFREG | 0o644,
                st_uid=0,
                st_gid=0,
                st_nlink=1,
            )
        return original_lstat(p)

    def fake_read(p: Path):
        return wire if p == PLIST else original_read(p)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(Path, "read_bytes", fake_read)
    return record


def test_guardian_policy_accepts_only_root_owned_exact_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    with monkeypatch.context() as m:
        record = _trusted_plist(m, root)
        assert guardian._policy(record, root) == (TARGET, PLIST)
        with pytest.raises(ArchiveFinalizeRefused, match="digest"):
            guardian._policy({**record, "plist_sha256": "f" * 64}, root)


def test_guardian_policy_requires_keepalive_and_exact_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    with monkeypatch.context() as m:
        record = _trusted_plist(m, root, KeepAlive=False)
        with pytest.raises(ArchiveFinalizeRefused, match="plan"):
            guardian._policy(record, root)


def test_guardian_readiness_file_is_private_idempotent_and_fsynced(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    token = "a" * 32
    guardian._ready(root, token)
    path = root / ("ready-" + token)
    assert path.read_text() == str(os.getpid())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    guardian._ready(root, token)
    assert path.read_text() == str(os.getpid())
    path.chmod(0o644)
    with pytest.raises(ArchiveFinalizeRefused, match="foreign"):
        guardian._ready(root, token)


@pytest.mark.parametrize("state", ["armed", "disarmed", "recovered"])
def test_simulated_supervisor_normal_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    root = _root(tmp_path)
    record = _record(root, state=state)
    p = root / "journal.json"
    guardian._write_record(p, record)
    lock = root / "lease.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    monkeypatch.setattr(guardian.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guardian, "_policy", lambda r, b: (TARGET, PLIST))
    monkeypatch.setattr(guardian, "_loaded", lambda target: True)
    monkeypatch.setattr(guardian, "_running_pid", lambda target: 456)
    answer = guardian.supervise(p, max_wait_s=0.5)
    assert answer == ("recovered" if state == "armed" else state)
    result = guardian._read_verified(p)
    if state == "armed":
        assert result["state"] == "recovered"
        assert result["restored_pid"] == 456
        assert result["outcome"] == "already-running"
    else:
        assert result["state"] == state


def test_simulated_guardian_bootstrap_only_after_controller_flock_releases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    journal = root / "journal.json"
    guardian._write_record(journal, _record(root))
    lock = root / "lease.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    monkeypatch.setattr(guardian.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guardian, "_policy", lambda r, b: (TARGET, PLIST))
    state = {"loaded": True, "restored": False}
    monkeypatch.setattr(guardian, "_loaded", lambda target: state["loaded"])

    def bootstrap(argv, timeout=12):
        assert argv[-3:] == ["bootstrap", "system", str(PLIST)]
        state["loaded"] = True
        state["restored"] = True
        return subprocess.CompletedProcess(argv, 0, "", "")

    count = [0]

    def loading(target):
        count[0] += 1
        if count[0] >= 2 and not state["restored"]:
            state["loaded"] = False
        return state["loaded"]

    monkeypatch.setattr(guardian, "_loaded", loading)
    monkeypatch.setattr(guardian, "_run", bootstrap)
    monkeypatch.setattr(guardian, "_running_pid", lambda target: 456)
    assert guardian.supervise(journal, max_wait_s=1) == "recovered"
    assert guardian._read_verified(journal)["outcome"] == "bootstrapped"


def test_guardian_rejects_no_prior_ready_if_writer_already_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    path = root / "journal.json"
    guardian._write_record(path, _record(root))
    lock = root / "lease.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    monkeypatch.setattr(guardian.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guardian, "_policy", lambda r, b: (TARGET, PLIST))
    monkeypatch.setattr(guardian, "_loaded", lambda target: False)
    with pytest.raises(ArchiveFinalizeRefused, match="cannot arm"):
        guardian.supervise(path, max_wait_s=0.2)


def test_guardian_never_breaks_controller_lease_to_force_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    path = root / "journal.json"
    guardian._write_record(path, _record(root))
    lock = root / "lease.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    monkeypatch.setattr(guardian.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guardian, "_policy", lambda r, b: (TARGET, PLIST))
    monkeypatch.setattr(guardian, "_loaded", lambda target: True)
    exclusive = os.open(lock, os.O_RDONLY)
    fcntl.flock(exclusive, fcntl.LOCK_EX)
    try:
        with pytest.raises(ArchiveFinalizeRefused, match="deadline"):
            guardian.supervise(path, max_wait_s=0.02)
    finally:
        os.close(exclusive)


def test_guardian_rejects_unsupported_platform_without_launchctl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guardian.platform, "system", lambda: "Linux")
    with pytest.raises(ArchiveFinalizeRefused, match="native"):
        guardian.supervise(tmp_path / "journal.json")


@pytest.mark.parametrize("fail", [False, True])
def test_guardian_cli_exit_and_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fail: bool,
) -> None:
    def run_guardian(*args, **kwargs):
        if fail:
            raise ArchiveFinalizeRefused("simulated refusal")
        return "recovered"

    monkeypatch.setattr(guardian, "supervise", run_guardian)
    rc = guardian.main(["--fixture-state", str(tmp_path / "journal.json")])
    assert rc == (2 if fail else 0)
    stdout, stderr = capsys.readouterr()
    if fail:
        assert "refused" in stderr
    else:
        assert "recovered" in stdout


def test_journal_size_cap_enforced_before_partial_write(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with pytest.raises(ArchiveFinalizeRefused, match="too large"):
        guardian._write_record(root / "journal.json", {"payload": "x" * 5000})


def test_guardian_recovers_after_previous_guardian_restart_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    rec = _record(root)
    path = root / "journal.json"
    guardian._write_record(path, rec)
    token = rec["nonce"]
    ready = root / ("ready-" + token)
    ready.write_text("1111")
    ready.chmod(0o600)
    lock = root / "lease.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    monkeypatch.setattr(guardian.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guardian, "_policy", lambda r, b: (TARGET, PLIST))
    active = [False, False]

    def loaded(_target):
        return active.pop(0) if active else False

    monkeypatch.setattr(guardian, "_loaded", loaded)
    monkeypatch.setattr(
        guardian,
        "_run",
        lambda argv, timeout=12: subprocess.CompletedProcess(argv, 0, "", ""),
    )
    monkeypatch.setattr(guardian, "_running_pid", lambda target: 789)
    assert guardian.supervise(path, max_wait_s=0.6) == "recovered"
    assert guardian._read_verified(path)["restored_pid"] == 789
    assert ready.read_text() == str(os.getpid())


def test_guardian_restarted_with_foreign_readiness_receipt_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    path = root / "journal.json"
    guardian._write_record(path, _record(root))
    lock = root / "lease.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    ready = root / ("ready-" + "0" * 32)
    ready.write_text("111")
    ready.chmod(0o666)
    monkeypatch.setattr(guardian.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guardian, "_policy", lambda r, b: (TARGET, PLIST))
    monkeypatch.setattr(guardian, "_loaded", lambda target: False)
    with pytest.raises(ArchiveFinalizeRefused, match="untrusted"):
        guardian.supervise(path, max_wait_s=0.5)


def test_simulated_bootstrap_error_stays_outside_source_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    path = root / "journal.json"
    guardian._write_record(path, _record(root))
    lock = root / "lease.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    state = [True, False]
    monkeypatch.setattr(guardian.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guardian, "_policy", lambda r, b: (TARGET, PLIST))
    monkeypatch.setattr(guardian, "_loaded", lambda target: state.pop(0))
    monkeypatch.setattr(
        guardian,
        "_run",
        lambda argv, timeout=12: subprocess.CompletedProcess(argv, 2, "", "refused"),
    )
    with pytest.raises(ArchiveFinalizeRefused, match="could not restore"):
        guardian.supervise(path, max_wait_s=0.5)
    assert guardian._read_verified(path)["state"] == "armed"


def test_already_loaded_old_generation_is_not_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    path = root / "journal.json"
    guardian._write_record(path, _record(root))
    lock = root / "lease.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    monkeypatch.setattr(guardian.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guardian, "_policy", lambda r, b: (TARGET, PLIST))
    monkeypatch.setattr(guardian, "_loaded", lambda target: True)
    monkeypatch.setattr(guardian, "_running_pid", lambda target: 123)
    with pytest.raises(ArchiveFinalizeRefused, match="reused"):
        guardian.supervise(path, max_wait_s=0.5)


def test_invalid_guardian_lease_file_refuses_without_bootout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    path = root / "journal.json"
    guardian._write_record(path, _record(root))
    lock = root / "lease.lock"
    lock.write_bytes(b"")
    lock.chmod(0o644)
    monkeypatch.setattr(guardian.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guardian, "_policy", lambda r, b: (TARGET, PLIST))
    with pytest.raises(ArchiveFinalizeRefused, match="invalid guardian maintenance"):
        guardian.supervise(path, max_wait_s=0.5)


def test_guardian_nonce_change_during_hold_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    path = root / "journal.json"
    initial = _record(root)
    guardian._write_record(path, initial)
    lock = root / "lease.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    monkeypatch.setattr(guardian.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(guardian, "_policy", lambda r, b: (TARGET, PLIST))
    monkeypatch.setattr(guardian, "_loaded", lambda target: True)
    original_read = guardian._read_verified
    reads = [0]

    def changed(p):
        reads[0] += 1
        d = original_read(p)
        if reads[0] == 2:
            return {**d, "nonce": "f" * 32}
        return d

    monkeypatch.setattr(guardian, "_read_verified", changed)
    with pytest.raises(ArchiveFinalizeRefused, match="transaction changed"):
        guardian.supervise(path, max_wait_s=0.5)


def test_guardian_policy_refuses_bad_plist_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    with monkeypatch.context() as m:
        record = _trusted_plist(m, root)
        good_lstat = Path.lstat

        def bad_owner(p):
            if p == PLIST:
                return SimpleNamespace(
                    st_mode=stat.S_IFREG | 0o644,
                    st_uid=99,
                    st_gid=0,
                    st_nlink=1,
                )
            return good_lstat(p)

        m.setattr(Path, "lstat", bad_owner)
        with pytest.raises(ArchiveFinalizeRefused, match="ownership"):
            guardian._policy(record, root)
