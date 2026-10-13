"""Isolated launchd fixture tests: never boot out or restart a Binnacle service."""

from __future__ import annotations

import bz2
import grp
import os
import plistlib
import pwd
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from binnacle.companions import darwin_log_archive_finalize as finish
from binnacle.companions import darwin_log_writer_hold as writer

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="macOS launchd only")


def _fixture(tmp_path: Path) -> tuple[Path, Path, str, Path]:
    root = tmp_path / "private-logs"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    source = root / "mcp.stderr.log"
    label = f"com.binnacle.archivefixture.{uuid.uuid4().hex[:12]}"
    plist = Path("/private/tmp") / f"{label}.plist"
    staging = tmp_path / f"{label}.staging"
    payload = {
        "Label": label,
        "UserName": pwd.getpwuid(os.getuid()).pw_name,
        "GroupName": grp.getgrgid(os.getgid()).gr_name,
        "ProgramArguments": [
            sys.executable,
            "-u",
            "-c",
            "import os,time;os.write(2,b'fixture started\\n');time.sleep(120)",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "Umask": 0o077,
        "StandardErrorPath": str(source),
        "StandardOutPath": str(root / "mcp.stdout.log"),
        "ThrottleInterval": 1,
    }
    staging.write_bytes(plistlib.dumps(payload))
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
            str(staging),
            str(plist),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=12,
    )
    staging.unlink()
    if installed.returncode:
        pytest.fail(f"isolated launchd fixture install failed: {installed.stderr}")

    return root, source, label, plist


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/sudo", "-n", "/bin/launchctl", *args],
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )


def _until(predicate, duration: float = 10) -> bool:
    end = time.monotonic() + duration
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def _remove_fixture_plist(plist: Path) -> None:
    assert plist.name.startswith("com.binnacle.archivefixture.")
    assert plist.parent == Path("/private/tmp")
    result = subprocess.run(
        ["/usr/bin/sudo", "-n", "/bin/rm", "-f", str(plist)],
        capture_output=True,
        text=True,
        check=False,
        timeout=12,
    )
    assert result.returncode == 0, result.stderr


@NATIVE
def test_real_launchd_bootout_holds_writer_then_restores_after_finalization(
    tmp_path: Path,
) -> None:
    root, active, label, plist = _fixture(tmp_path)
    domain = "system"
    target = f"{domain}/{label}"
    try:
        assert _launchctl("bootstrap", domain, str(plist)).returncode == 0
        assert _until(lambda: active.exists() and active.stat().st_size > 0)
        raw = root / "mcp.stderr.log.0"
        active.rename(raw)
        raw.chmod(0o600)
        data = raw.read_bytes()
        assert b"fixture started" in data
        # GN rename-only: the writer remains on the original, rotated inode.
        hold = writer.LaunchdFixtureWriterHold(
            label=label, plist=plist, log_root=root, name=raw.name
        )
        result = finish.finalize_archive(root, raw.name, hold=hold, min_free_bytes=0)
        assert result.producer == "system/com.binnacle.mcp"
        assert not raw.exists()
        assert bz2.decompress((root / result.canonical).read_bytes()) == data
        assert _until(lambda: active.exists() and active.stat().st_size > 0)
        assert _launchctl("print", target).returncode == 0
    finally:
        _launchctl("bootout", target)
        assert _until(lambda: _launchctl("print", target).returncode != 0)
        _remove_fixture_plist(plist)


@NATIVE
def test_unexpected_writer_fd_blocks_pruning_and_restores_launchd(
    tmp_path: Path,
) -> None:
    root, active, label, plist = _fixture(tmp_path)
    domain = "system"
    target = f"{domain}/{label}"
    extra: subprocess.Popen[bytes] | None = None
    try:
        assert _launchctl("bootstrap", domain, str(plist)).returncode == 0
        assert _until(lambda: active.exists() and active.stat().st_size > 0)
        raw = root / "mcp.stderr.log.0"
        active.rename(raw)
        raw.chmod(0o600)
        # Independent external process, outside the launchd fixture's lifetime.
        extra = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                (
                    "import os,sys,time;"
                    "fd=os.open(sys.argv[1],os.O_WRONLY|os.O_APPEND);"
                    "os.write(fd,b'external-writer\\n');time.sleep(30)"
                ),
                str(raw),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert _until(lambda: b"external-writer" in raw.read_bytes())
        hold = writer.LaunchdFixtureWriterHold(
            label=label, plist=plist, log_root=root, name=raw.name, wait_s=0.4
        )
        with pytest.raises(finish.ArchiveFinalizeRefused, match="writable"):
            finish.finalize_archive(root, raw.name, hold=hold, min_free_bytes=0)
        assert raw.exists()
        assert not (root / (raw.name + ".bz2")).exists()
        assert _launchctl("print", target).returncode == 0
        assert extra.poll() is None
    finally:
        if extra is not None and extra.poll() is None:
            extra.terminate()
            extra.wait(timeout=10)
        _launchctl("bootout", target)
        assert _until(lambda: _launchctl("print", target).returncode != 0)
        _remove_fixture_plist(plist)


@NATIVE
def test_hold_prevents_keepalive_relaunch_during_held_window(tmp_path: Path) -> None:
    root, active, label, plist = _fixture(tmp_path)
    domain = "system"
    target = f"{domain}/{label}"
    try:
        assert _launchctl("bootstrap", domain, str(plist)).returncode == 0
        assert _until(lambda: active.exists() and active.stat().st_size > 0)
        raw = root / "mcp.stderr.log.0"
        active.rename(raw)
        raw.chmod(0o600)
        hold = writer.LaunchdFixtureWriterHold(
            label=label, plist=plist, log_root=root, name=raw.name
        )
        with hold:
            assert _launchctl("print", target).returncode == 113
            time.sleep(1.2)  # longer than fixture's throttle interval
            assert _launchctl("print", target).returncode == 113
            hold.verify(raw.name, raw.stat())
        assert _launchctl("print", target).returncode == 0
        assert raw.exists()  # no finalizer called, so raw is retained
    finally:
        _launchctl("bootout", target)
        assert _until(lambda: _launchctl("print", target).returncode != 0)
        _remove_fixture_plist(plist)


def test_refuses_non_fixture_label_even_with_production_name(tmp_path: Path) -> None:
    with pytest.raises(finish.ArchiveFinalizeRefused, match="test-owned"):
        writer.LaunchdFixtureWriterHold(
            label="com.binnacle.mcp",
            plist=tmp_path / "mcp.plist",
            log_root=tmp_path,
            name="mcp.stderr.log.0",
        )


@pytest.mark.parametrize(
    ("rows", "code", "reason"),
    [
        ("p123\nf3\naw\nn/private/tmp/log\n", 0, "writable"),
        ("p123\nf3\nau\nn/private/tmp/log\n", 0, "writable"),
        ("p123\nf3\nn/private/tmp/log\n", 0, "unknown"),
        ("p123\nf3\nax\nn/private/tmp/log\n", 0, "unknown"),
        ("malformed\n", 0, "format"),
        ("", 2, "unprovable"),
        ("", 1, None),
        ("p123\nf3\nar\nn/private/tmp/log\n", 0, None),
    ],
)
def test_fail_closed_lsof_descriptor_parsing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rows: str,
    code: int,
    reason: str | None,
) -> None:
    def fake_run(args: list[str], timeout: float = 12):
        return subprocess.CompletedProcess(args, code, rows, "")

    monkeypatch.setattr(writer, "_run", fake_run)
    if reason is None:
        writer._no_writer_fds(tmp_path / "sample.log")
    else:
        with pytest.raises(finish.ArchiveFinalizeRefused, match=reason):
            writer._no_writer_fds(tmp_path / "sample.log")


@NATIVE
def test_launchd_partial_bootout_error_still_restores_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing launchctl command is not evidence the producer stayed loaded."""
    root, active, label, plist = _fixture(tmp_path)
    target = f"system/{label}"
    actual_run = writer._run
    try:
        assert _launchctl("bootstrap", "system", str(plist)).returncode == 0
        assert _until(lambda: active.exists() and active.stat().st_size > 0)
        raw = root / "mcp.stderr.log.0"
        active.rename(raw)
        raw.chmod(0o600)
        before = writer._running_pid(target)

        def partial_error(args: list[str], timeout: float = 12):
            observed = actual_run(args, timeout)
            if args[-2:] == ["bootout", target]:
                assert observed.returncode == 0
                return subprocess.CompletedProcess(args, 1, "", "synthetic failure")
            return observed

        with monkeypatch.context() as m:
            m.setattr(writer, "_run", partial_error)
            with pytest.raises(
                finish.ArchiveFinalizeRefused, match="refused producer bootout"
            ):
                finish.finalize_archive(
                    root,
                    raw.name,
                    hold=writer.LaunchdFixtureWriterHold(
                        label=label, plist=plist, log_root=root, name=raw.name
                    ),
                    min_free_bytes=0,
                )
        assert raw.exists()
        assert not (root / (raw.name + ".bz2")).exists()
        assert _until(lambda: writer._running_pid(target) != before)
    finally:
        _launchctl("bootout", target)
        assert _until(lambda: _launchctl("print", target).returncode != 0)
        _remove_fixture_plist(plist)


@NATIVE
def test_failure_to_unlink_raw_keeps_verified_archive_and_restores_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash-like failure after canonical link may leave two *matching* copies."""
    root, active, label, plist = _fixture(tmp_path)
    target = f"system/{label}"
    try:
        assert _launchctl("bootstrap", "system", str(plist)).returncode == 0
        assert _until(lambda: active.exists() and active.stat().st_size > 0)
        raw = root / "mcp.stderr.log.0"
        active.rename(raw)
        raw.chmod(0o600)
        original = raw.read_bytes()
        real_unlink = writer.os.unlink

        def fail_raw_unlink(path, *args, **kwargs):
            if str(path) == raw.name:
                raise PermissionError("synthetic crash before raw removal")
            return real_unlink(path, *args, **kwargs)

        with monkeypatch.context() as m:
            m.setattr(finish.os, "unlink", fail_raw_unlink)
            with pytest.raises(finish.ArchiveFinalizeRefused, match="refused"):
                finish.finalize_archive(
                    root,
                    raw.name,
                    hold=writer.LaunchdFixtureWriterHold(
                        label=label, plist=plist, log_root=root, name=raw.name
                    ),
                    min_free_bytes=0,
                )
        assert raw.read_bytes() == original
        assert bz2.decompress((root / (raw.name + ".bz2")).read_bytes()) == original
        assert _launchctl("print", target).returncode == 0
    finally:
        _launchctl("bootout", target)
        assert _until(lambda: _launchctl("print", target).returncode != 0)
        _remove_fixture_plist(plist)


@NATIVE
def test_actual_lsof_sees_writable_fds_and_allows_closed_file(tmp_path: Path) -> None:
    raw = tmp_path / "lsof.log"
    raw.write_bytes(b"hello")
    fd = os.open(raw, os.O_WRONLY | os.O_APPEND)
    try:
        with pytest.raises(finish.ArchiveFinalizeRefused, match="writable"):
            writer._no_writer_fds(raw)
    finally:
        os.close(fd)
    writer._no_writer_fds(raw)
