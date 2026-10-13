"""Private restart lock and watchdog pause receipt tests; no live services."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from binnacle.companions import service_watchdog_maintenance as pause

NONCE = "a" * 32


@pytest.fixture
def root(tmp_path: Path) -> Path:
    directory = tmp_path / "watchdog-pause"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


def arm(root: Path, nonce: object = NONCE, **change: object) -> Path:
    record: dict[str, object] = {
        "version": 1,
        "nonce": nonce,
        "scope": "all",
        "until": time.time() + 90,
    }
    record.update(change)
    path = root / "request.json"
    path.write_text(json.dumps(record))
    path.chmod(0o600)
    return path


def test_absent_request_permits_action_but_no_ack(root: Path) -> None:
    fence = pause.WatchdogMaintenanceFence(root)
    assert fence.poll() is False
    with fence.action() as allowed:
        assert allowed is True
    assert not (root / "ack.json").exists()
    lock = root / "restart.lock"
    assert lock.stat().st_mode & 0o777 == 0o600


def test_valid_request_blocks_action_and_publishes_generation_ack(root: Path) -> None:
    arm(root)
    fence = pause.WatchdogMaintenanceFence(root)
    assert fence.poll() is True
    assert pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=os.getpid())
    assert not pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=os.getpid() + 1)
    assert not pause.confirmed_ack(root, nonce="b" * 32, watchdog_pid=os.getpid())
    with fence.action() as allowed:
        assert allowed is False
    assert (root / "ack.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"version": 2}, "invalid"),
        ({"version": True}, "invalid"),
        ({"nonce": "bad"}, "invalid"),
        ({"nonce": "G" * 32}, "invalid"),
        ({"scope": "mcp"}, "invalid"),
        ({"until": time.time() - 600}, "invalid"),
        ({"until": time.time() + 1000}, "invalid"),
        ({"until": "tomorrow"}, "invalid"),
        ({"until": True}, "invalid"),
        ({"unexpected": "field"}, "invalid"),
    ],
)
def test_invalid_or_expired_request_never_allows_restart(
    root: Path, change: dict[str, object], reason: str
) -> None:
    arm(root, **change)
    fence = pause.WatchdogMaintenanceFence(root)
    with pytest.raises(pause.WatchdogPauseRefused, match=reason):
        fence.poll()
    assert fence.safely_paused()
    with pytest.raises(pause.WatchdogPauseRefused, match=reason), fence.action():
        pytest.fail("invalid request must not authorize restart")
    assert not (root / "ack.json").exists()


@pytest.mark.parametrize(
    "bad_bytes",
    [b"not-json", b"[]", b'{"version":1,"version":1}', b"", b"x" * 513],
)
def test_bad_request_bytes_fail_closed(root: Path, bad_bytes: bytes) -> None:
    path = root / "request.json"
    path.write_bytes(bad_bytes)
    path.chmod(0o600)
    fence = pause.WatchdogMaintenanceFence(root)
    with pytest.raises(pause.WatchdogPauseRefused):
        fence.poll()
    assert fence.safely_paused()
    assert not (root / "ack.json").exists()


@pytest.mark.parametrize("violation", ["public", "symlink", "hardlink", "directory"])
def test_untrusted_request_file_never_yields_maintenance_ack(
    root: Path, violation: str
) -> None:
    path = root / "request.json"
    if violation == "directory":
        path.mkdir()
    else:
        other = root / "external"
        other.write_bytes(b'{"version":1}')
        other.chmod(0o600)
        if violation == "public":
            path.write_bytes(other.read_bytes())
            path.chmod(0o644)
        elif violation == "symlink":
            path.symlink_to(other)
        else:
            os.link(other, path)
    with pytest.raises(pause.WatchdogPauseRefused):
        pause.WatchdogMaintenanceFence(root).poll()
    assert path.exists()


def test_foreign_symlink_root_is_rejected(root: Path) -> None:
    saved = root.with_name("real-pause")
    root.rename(saved)
    root.symlink_to(saved, target_is_directory=True)
    with pytest.raises(pause.WatchdogPauseRefused):
        pause.WatchdogMaintenanceFence(root).poll()


def test_directory_world_permission_is_rejected(root: Path) -> None:
    root.chmod(0o755)
    with pytest.raises(pause.WatchdogPauseRefused, match="private"):
        pause.WatchdogMaintenanceFence(root).poll()


def test_public_or_hardlinked_mutex_is_rejected(root: Path) -> None:
    lock = root / "restart.lock"
    lock.write_bytes(b"owner")
    lock.chmod(0o644)
    with pytest.raises(pause.WatchdogPauseRefused, match="private"):
        pause.WatchdogMaintenanceFence(root).poll()
    lock.chmod(0o600)
    os.link(lock, root / "foreign-hardlink")
    with pytest.raises(pause.WatchdogPauseRefused, match="private"):
        pause.WatchdogMaintenanceFence(root).poll()


def test_mutex_held_by_another_fd_blocks_both_poll_and_restart(root: Path) -> None:
    fence = pause.WatchdogMaintenanceFence(root)
    fence.poll()
    with (root / "restart.lock").open("rb+") as owner:
        fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(pause.WatchdogPauseRefused, match="busy"):
            fence.poll()
        with pytest.raises(pause.WatchdogPauseRefused, match="busy"), fence.action():
            pytest.fail("contended restart gate")


def test_controller_request_cannot_be_created_during_restart(root: Path) -> None:
    with pause.WatchdogMaintenanceFence(root).action() as allowed:
        assert allowed
        with (
            pytest.raises(pause.WatchdogPauseRefused, match="busy"),
            pause._directory(root) as dfd,
            pause._interlock(dfd),
        ):
            pytest.fail("controller must not claim pause during restart")
    # After the watchdog leaves the action, controller may publish the request.
    with pause._directory(root) as dfd, pause._interlock(dfd):
        arm(root)
    assert pause.WatchdogMaintenanceFence(root).poll()


def test_invalid_ack_refuses_without_overwriting_foreign_file(root: Path) -> None:
    arm(root)
    ack = root / "ack.json"
    ack.write_text('{"malicious":true}')
    ack.chmod(0o600)
    with pytest.raises(pause.WatchdogPauseRefused, match="shape"):
        pause.WatchdogMaintenanceFence(root).poll()
    assert ack.read_text() == '{"malicious":true}'


def test_acked_request_stays_idempotent(root: Path) -> None:
    arm(root)
    fence = pause.WatchdogMaintenanceFence(root)
    assert fence.poll()
    first = (root / "ack.json").stat()
    assert fence.poll()
    second = (root / "ack.json").stat()
    assert (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def test_stale_ack_without_request_cannot_claim_pause(root: Path) -> None:
    arm(root)
    assert pause.WatchdogMaintenanceFence(root).poll()
    (root / "request.json").unlink()
    assert not pause.WatchdogMaintenanceFence(root).poll()
    assert not pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=os.getpid())


def test_readonly_ack_probe_never_creates_lock(root: Path) -> None:
    assert not pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=501)
    assert list(root.iterdir()) == []


def test_unreadable_ack_and_invalid_nonce_are_rejected(root: Path) -> None:
    arm(root)
    assert pause.WatchdogMaintenanceFence(root).poll()
    assert not pause.confirmed_ack(root, nonce="bad", watchdog_pid=os.getpid())
    assert not pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=0)
    assert not pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=True)
    assert not pause.confirmed_ack(
        root, nonce=cast(str, False), watchdog_pid=os.getpid()
    )
    (root / "ack.json").chmod(0o666)
    assert not pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=os.getpid())


def test_short_writes_are_retried_before_ack_publish(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm(root)
    real = os.write
    calls = [0]

    def partial(fd: int, data: bytes) -> int:
        calls[0] += 1
        return real(fd, data[: max(1, len(data) // 2)])

    monkeypatch.setattr(pause.os, "write", partial)
    assert pause.WatchdogMaintenanceFence(root).poll()
    assert calls[0] > 1
    assert pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=os.getpid())


def test_ack_temp_uuid_collision_does_not_delete_foreign_inode(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm(root)
    chosen = "c" * 32
    monkeypatch.setattr(pause.uuid, "uuid4", lambda: SimpleNamespace(hex=chosen))
    foreign = root / (".ack-" + chosen + ".tmp")
    foreign.write_bytes(b"foreign")
    foreign.chmod(0o600)
    with pytest.raises(pause.WatchdogPauseRefused, match="publication"):
        pause.WatchdogMaintenanceFence(root).poll()
    assert foreign.read_bytes() == b"foreign"
    assert not (root / "ack.json").exists()


def test_ack_temporary_path_swap_does_not_delete_replacement(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm(root)
    chosen = "d" * 32
    monkeypatch.setattr(pause.uuid, "uuid4", lambda: SimpleNamespace(hex=chosen))
    expected = root / (".ack-" + chosen + ".tmp")
    calls = [0]

    def fail_after_swap(source, target, **kwargs):
        calls[0] += 1
        expected.rename(root / "orphaned")
        expected.write_bytes(b"FOREIGN REPLACEMENT")
        expected.chmod(0o600)
        raise OSError("synthetic publish refused")

    monkeypatch.setattr(pause.os, "replace", fail_after_swap)
    with pytest.raises(pause.WatchdogPauseRefused, match="publication"):
        pause.WatchdogMaintenanceFence(root).poll()
    assert calls == [1]
    assert expected.read_bytes() == b"FOREIGN REPLACEMENT"
    assert (root / "orphaned").is_file()
    assert not (root / "ack.json").exists()


def test_pause_action_remains_allowed_only_while_request_absent(root: Path) -> None:
    fence = pause.WatchdogMaintenanceFence(root)
    with fence.action() as allowed:
        assert allowed
    arm(root)
    with fence.action() as allowed:
        assert not allowed


def test_controller_request_is_atomic_private_and_not_an_approval(root: Path) -> None:
    pause.request_pause(root, nonce=NONCE, until=time.time() + 75)
    request = root / "request.json"
    assert request.stat().st_mode & 0o777 == 0o600
    assert request.stat().st_nlink == 1
    assert not (root / "ack.json").exists()
    assert pause.WatchdogMaintenanceFence(root).poll()
    assert pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=os.getpid())
    assert not list(root.glob(".request-*.tmp"))


@pytest.mark.parametrize(
    ("nonce", "seconds"),
    [
        ("invalid", 90),
        ("G" * 32, 90),
        ("a" * 31, 90),
        (NONCE, -50),
        (NONCE, 999),
        (NONCE, True),
        (NONCE, 0),
    ],
)
def test_controller_rejects_invalid_request_before_creating_file(
    root: Path, nonce: str, seconds: object
) -> None:
    until = seconds if isinstance(seconds, bool) else time.time() + cast(float, seconds)
    with pytest.raises(pause.WatchdogPauseRefused, match="request invalid"):
        pause.request_pause(root, nonce=nonce, until=cast(float, until))
    assert not (root / "request.json").exists()
    assert not (root / "restart.lock").exists()


def test_controller_cannot_overwrite_existing_pause_request(root: Path) -> None:
    pause.request_pause(root, nonce=NONCE, until=time.time() + 90)
    raw = (root / "request.json").read_bytes()
    with pytest.raises(pause.WatchdogPauseRefused, match="existing"):
        pause.request_pause(root, nonce="b" * 32, until=time.time() + 90)
    assert (root / "request.json").read_bytes() == raw


def test_controller_cannot_arm_while_watchdog_restart_holds_mutex(root: Path) -> None:
    with pause.WatchdogMaintenanceFence(root).action() as allowed:
        assert allowed
        with pytest.raises(pause.WatchdogPauseRefused, match="busy"):
            pause.request_pause(root, nonce=NONCE, until=time.time() + 90)
        assert not (root / "request.json").exists()
    pause.request_pause(root, nonce=NONCE, until=time.time() + 90)


def test_foreign_request_symlink_refuses_creation_without_change(root: Path) -> None:
    other = root / "unowned"
    other.write_bytes(b"valuable")
    request = root / "request.json"
    request.symlink_to(other)
    with pytest.raises(pause.WatchdogPauseRefused, match="inaccessible"):
        pause.request_pause(root, nonce=NONCE, until=time.time() + 90)
    assert request.is_symlink()
    assert other.read_bytes() == b"valuable"


def test_request_temp_name_collision_preserves_foreign_file(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "e" * 32
    foreign = root / (".request-" + token + ".tmp")
    foreign.write_bytes(b"OLD AND FOREIGN")
    foreign.chmod(0o600)
    monkeypatch.setattr(pause.uuid, "uuid4", lambda: SimpleNamespace(hex=token))
    with pytest.raises(pause.WatchdogPauseRefused, match="publication"):
        pause.request_pause(root, nonce=NONCE, until=time.time() + 90)
    assert foreign.read_bytes() == b"OLD AND FOREIGN"
    assert not (root / "request.json").exists()


def test_request_fsync_failure_does_not_leave_unowned_private_file(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actual = os.fsync
    calls = [0]

    def failure(fd: int) -> None:
        calls[0] += 1
        if calls[0] == 1:
            raise OSError("synthetic fsync failure")
        actual(fd)

    with monkeypatch.context() as m:
        m.setattr(pause.os, "fsync", failure)
        with pytest.raises(pause.WatchdogPauseRefused, match="publication"):
            pause.request_pause(root, nonce=NONCE, until=time.time() + 90)
    assert calls == [1]
    assert not (root / "request.json").exists()
    assert not list(root.glob(".request-*.tmp"))


def test_controller_request_and_watchdog_ack_roundtrip_after_release(
    root: Path,
) -> None:
    watchdog = pause.WatchdogMaintenanceFence(root)
    watchdog.poll()
    with watchdog.action() as permitted:
        assert permitted
    pause.request_pause(root, nonce=NONCE, until=time.time() + 40)
    assert watchdog.safely_paused()
    assert pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=os.getpid())
    # A late request is never an acknowledgement by itself.
    (root / "ack.json").unlink()
    assert not pause.confirmed_ack(root, nonce=NONCE, watchdog_pid=os.getpid())


def test_controller_process_cannot_publish_during_other_process_restart(
    root: Path,
) -> None:
    """Prove the same OFD mutex works across process boundaries."""
    code = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from binnacle.companions.service_watchdog_maintenance import "
        "request_pause,WatchdogPauseRefused\n"
        "try:\n request_pause(Path(sys.argv[1]),nonce='a'*32,until=time.time()+75)\n"
        "except WatchdogPauseRefused:\n sys.exit(17)\n"
        "sys.exit(0)\n"
    )
    watchdog = pause.WatchdogMaintenanceFence(root)
    with watchdog.action() as allowed:
        assert allowed
        competitor = subprocess.run(
            [sys.executable, "-c", code, str(root)],
            capture_output=True,
            text=True,
            timeout=9,
            check=False,
        )
        assert competitor.returncode == 17, competitor.stderr
        assert not (root / "request.json").exists()
    controller = subprocess.run(
        [sys.executable, "-c", code, str(root)],
        capture_output=True,
        text=True,
        timeout=9,
        check=False,
    )
    assert controller.returncode == 0, controller.stderr
    assert watchdog.poll()
