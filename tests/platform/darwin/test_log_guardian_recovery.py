"""SIGKILL recovery of an isolated launchd writer via an independent fixture guard."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from binnacle.companions import darwin_log_maintenance_guardian as guardian
from binnacle.companions.darwin_log_archive_finalize import ArchiveFinalizeRefused
from binnacle.companions.darwin_log_writer_hold import _running_pid
from tests.platform.darwin.test_log_writer_hold import (
    _fixture,
    _launchctl,
    _remove_fixture_plist,
    _until,
)

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Mac isolated launchd")


def _guardian_plist(tmp_path: Path, *, state: Path) -> tuple[str, Path]:
    label = f"com.binnacle.archiveguardian.{uuid.uuid4().hex[:12]}"
    path = Path("/private/tmp") / (label + ".plist")
    staged = tmp_path / ("tmp-" + label + ".plist")
    args = [
        sys.executable,
        "-u",
        "-m",
        "binnacle.companions.darwin_log_maintenance_guardian",
        "--fixture-state",
        str(state),
        "--max-wait-s",
        "20",
    ]
    source_root = str(Path(__file__).resolve().parents[3] / "src")
    plan = {
        "Label": label,
        "UserName": __import__("pwd").getpwuid(os.getuid()).pw_name,
        "GroupName": __import__("grp").getgrgid(os.getgid()).gr_name,
        "ProgramArguments": args,
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONPATH": source_root,
            "HOME": str(Path.home()),
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "Umask": 0o077,
        "ThrottleInterval": 1,
        "StandardErrorPath": str(tmp_path / "guard.err.log"),
    }
    staged.write_bytes(plistlib.dumps(plan))
    installed = subprocess.run(
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/bin/install",
            "-o",
            "root",
            "-g",
            "wheel",
            "-m",
            "0644",
            str(staged),
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=12,
    )
    staged.unlink()
    assert installed.returncode == 0, installed.stderr
    return label, path


@NATIVE
@pytest.mark.parametrize("restart_guardian", [False, True])
@pytest.mark.parametrize("abort_before_bootout", [False, True])
def test_independent_guardian_recovers_after_controller_sigkill(
    tmp_path: Path,
    restart_guardian: bool,
    abort_before_bootout: bool,
) -> None:
    root, active, label, plist = _fixture(tmp_path)
    target = f"system/{label}"
    guardlabel = ""
    guardplist: Path | None = None
    controller: subprocess.Popen[bytes] | None = None
    guard_root = tmp_path / "guard"
    guard_root.mkdir(mode=0o700)
    state = guard_root / "journal.json"
    lock = guard_root / "lease.lock"
    try:
        assert _launchctl("bootstrap", "system", str(plist)).returncode == 0
        assert _until(lambda: active.exists() and active.stat().st_size > 0)
        old = _running_pid(target)
        raw = root / "mcp.stderr.log.0"
        active.rename(raw)
        raw.chmod(0o600)
        original = raw.read_bytes()

        lock.touch(mode=0o600)
        lock.chmod(0o600)
        nonce = secrets.token_hex(16)
        record = {
            "version": 1,
            "state": "armed",
            "label": label,
            "plist": str(plist),
            "plist_sha256": hashlib.sha256(plist.read_bytes()).hexdigest(),
            "lock": str(lock),
            "nonce": nonce,
            "previous_pid": old,
        }
        guardian._write_record(state, record)
        acquired = guard_root / "held.lock"
        stopped = guard_root / "writer.bootedout"
        controller_script = (
            "import fcntl,os,pathlib,subprocess,sys,time;"
            "lk,held,ready,stopped,target=map(pathlib.Path,sys.argv[1:6]);"
            "abort=sys.argv[6]=='1';"
            "fd=os.open(lk,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX);"
            "held.write_text('locked');"
            "deadline=time.time()+12;"
            "exec('while not ready.exists():\\n"
            '  assert time.time()<deadline, "guardian not ready"\\n'
            "  time.sleep(.05)');"
            "p=subprocess.run(['/usr/bin/sudo','-n','/bin/launchctl',"
            "'bootout',str(target)],capture_output=True) if not abort else None;"
            "assert p is None or p.returncode==0,(p.stderr if p else '');"
            "stopped.write_text('aborted' if abort else 'bootedout');"
            "time.sleep(60)"
        )
        ready = guard_root / ("ready-" + nonce)
        controller = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                controller_script,
                str(lock),
                str(acquired),
                str(ready),
                str(stopped),
                target,
                "1" if abort_before_bootout else "0",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert _until(acquired.exists, 5), "test controller did not lock"
        guardlabel, guardplist = _guardian_plist(tmp_path, state=state)
        assert _launchctl("bootstrap", "system", str(guardplist)).returncode == 0
        assert _until(ready.exists, 9), "independent launchd guardian not ready"
        assert _until(stopped.exists, 9), "controller did not reach fixture checkpoint"
        if abort_before_bootout:
            assert stopped.read_text() == "aborted"
            assert _running_pid(target) == old
        else:
            assert stopped.read_text() == "bootedout"
            assert _launchctl("print", target).returncode == 113

        if restart_guardian:
            old_guardian_pid = _running_pid(f"system/{guardlabel}")
            crashed = _launchctl("kill", "SIGKILL", f"system/{guardlabel}")
            assert crashed.returncode == 0, crashed.stderr

            def new_guardian_generation() -> bool:
                try:
                    return _running_pid(f"system/{guardlabel}") != old_guardian_pid
                except ArchiveFinalizeRefused:
                    # launchd may temporarily report a loaded-but-exited label.
                    return False

            assert _until(
                new_guardian_generation,
                10,
            ), "isolated guardian did not restart after SIGKILL"
            if abort_before_bootout:
                assert _running_pid(target) == old
            else:
                assert _launchctl("print", target).returncode == 113

        controller.kill()  # Only the test-owned controller subprocess.
        controller.wait(timeout=5)
        controller = None
        desired_state = "disarmed" if abort_before_bootout else "recovered"
        assert _until(
            lambda: json.loads(state.read_text()).get("state") == desired_state,
            12,
        ), "guardian failed to preserve or restore test service"
        result = json.loads(state.read_text())
        assert result["outcome"] == (
            "producer-never-stopped" if abort_before_bootout else "bootstrapped"
        )
        if abort_before_bootout:
            assert result["restored_pid"] == old
        else:
            assert result["restored_pid"] != old
        assert _running_pid(target) == result["restored_pid"]
        assert raw.read_bytes() == original
        if abort_before_bootout:
            # The original writer never reopened the new pathname after the
            # GN-style rename, so the rotated inode is still its active log.
            assert not active.exists()
            assert _running_pid(target) == old
        else:
            assert _until(lambda: active.exists() and active.stat().st_size > 0)
    finally:
        if controller is not None and controller.poll() is None:
            controller.kill()
            controller.wait(timeout=6)
        _launchctl("bootout", target)
        assert _until(lambda: _launchctl("print", target).returncode != 0)
        _remove_fixture_plist(plist)
        if guardlabel:
            _launchctl("bootout", f"system/{guardlabel}")
            assert _until(
                lambda: _launchctl("print", f"system/{guardlabel}").returncode != 0
            )
        if guardplist is not None:
            assert guardplist.parent == Path("/private/tmp")
            assert guardplist.name.startswith("com.binnacle.archiveguardian.")
            removed = subprocess.run(
                ["/usr/bin/sudo", "-n", "/bin/rm", "-f", str(guardplist)],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
            assert removed.returncode == 0, removed.stderr


def test_guardian_rejects_production_labels(tmp_path: Path) -> None:
    record = {
        "version": 1,
        "state": "armed",
        "label": "com.binnacle.mcp",
        "plist": "/Library/LaunchDaemons/com.binnacle.mcp.plist",
        "lock": str(tmp_path / "lease.lock"),
        "nonce": "0" * 32,
        "previous_pid": 123,
    }
    with pytest.raises(ArchiveFinalizeRefused, match="fixture"):
        guardian._policy(record, tmp_path)


@pytest.mark.parametrize("value", [-1, 0, None, False, "45"])
def test_guardian_rejects_ambiguous_previous_writer_pid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: object
) -> None:
    monkeypatch.setattr(
        guardian,
        "_FIXTURE_LABEL",
        __import__("re").compile(r"com\.binnacle\.archivefixture\.[a-z0-9]+"),
    )
    label = "com.binnacle.archivefixture.unit1234"
    record = {
        "version": 1,
        "state": "armed",
        "label": label,
        "plist": f"/private/tmp/{label}.plist",
        "lock": str(tmp_path / "lease.lock"),
        "nonce": "1" * 32,
        "previous_pid": value,
    }
    with pytest.raises(ArchiveFinalizeRefused, match="generation"):
        guardian._policy(record, tmp_path)
