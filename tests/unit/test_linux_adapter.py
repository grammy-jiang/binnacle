"""Tests for bounded, fixed-source Linux read adapters."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import anyio
import pytest

from binnacle.adapters.linux import (
    LinuxDeviceIdentityProvider,
    LinuxSystemInspector,
    _decode_mount_field,
    _read_bounded,
)
from binnacle.domain.system import DeviceIdentityError, InspectionError, SystemSection


@dataclass(frozen=True)
class _Stat:
    f_frsize: int = 4096
    f_blocks: int = 10
    f_bavail: int = 4


def _stat_result(
    *,
    fragment_size: int = 4096,
    blocks: int = 10,
    available: int = 4,
) -> os.statvfs_result:
    return cast(
        os.statvfs_result,
        _Stat(f_frsize=fragment_size, f_blocks=blocks, f_bavail=available),
    )


def _make_inspector(
    tmp_path: Path,
    *,
    mountinfo: str = "36 25 0:32 / / rw - ext4 /dev/root rw\n",
    stat_provider: Callable[[str], os.statvfs_result] | None = None,
    timeout: float = 2.0,
    max_filesystems: int = 128,
) -> LinuxSystemInspector:
    os_release = tmp_path / "os-release"
    uptime = tmp_path / "uptime"
    meminfo = tmp_path / "meminfo"
    mounts = tmp_path / "mountinfo"
    os_release.write_text('PRETTY_NAME="Fixture Linux 1"\n', encoding="utf-8")
    uptime.write_text("123.75 42.0\n", encoding="ascii")
    meminfo.write_text(
        "MemTotal: 1024 kB\nMemAvailable: 512 kB\n",
        encoding="ascii",
    )
    mounts.write_text(mountinfo, encoding="utf-8")
    return LinuxSystemInspector(
        os_release_path=os_release,
        uptime_path=uptime,
        meminfo_path=meminfo,
        mountinfo_path=mounts,
        filesystem_stat_timeout_seconds=timeout,
        stat_provider=stat_provider or (lambda _path: _stat_result()),
        max_filesystems=max_filesystems,
    )


def test_device_identity_is_stable_one_way_digest(tmp_path: Path) -> None:
    identity_path = tmp_path / "machine-id"
    identity_path.write_text("raw-machine-id\n", encoding="ascii")
    provider = LinuxDeviceIdentityProvider(identity_paths=(identity_path,))

    first = provider.get_device_identity()
    second = provider.get_device_identity()
    expected = hashlib.sha256(b"binnacle-device-id-v1\0" + b"raw-machine-id").hexdigest()[:32]

    assert first == second
    assert first.device_id == f"device_{expected}"
    assert "raw-machine-id" not in first.device_id


def test_device_identity_uses_reviewed_fallback(tmp_path: Path) -> None:
    fallback = tmp_path / "fallback-id"
    fallback.write_text("fallback", encoding="ascii")
    provider = LinuxDeviceIdentityProvider(identity_paths=(tmp_path / "missing", fallback))

    assert provider.get_device_identity().device_id.startswith("device_")


def test_device_identity_rejects_empty_or_unbounded_sources(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    too_long = tmp_path / "too-long"
    empty.write_bytes(b" \n")
    too_long.write_bytes(b"a" * 257)

    with pytest.raises(DeviceIdentityError, match="no stable Linux"):
        LinuxDeviceIdentityProvider(identity_paths=(empty, too_long)).get_device_identity()


def test_device_identity_fails_closed_on_oversized_fixed_source(tmp_path: Path) -> None:
    identity_path = tmp_path / "machine-id"
    identity_path.write_bytes(b"12345")

    with pytest.raises(InspectionError, match="exceeds 4 bytes"):
        LinuxDeviceIdentityProvider(
            identity_paths=(identity_path,),
            max_bytes=4,
        ).get_device_identity()


@pytest.mark.anyio
async def test_inspector_collects_all_sections_and_omits_nonlocal_mounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def stat_provider(path: str) -> os.statvfs_result:
        calls.append(path)
        return _stat_result()

    mountinfo = (
        "36 25 0:32 / / rw - ext4 /dev/root rw\n"
        "37 25 0:33 / /mnt/space\\040name rw - tmpfs none rw\n"
        "38 25 0:34 / /mnt/nfs rw - nfs server:/export rw\n"
        "39 25 0:35 / /mnt/fuse rw - fuse.sshfs remote rw\n"
    )
    inspector = _make_inspector(
        tmp_path,
        mountinfo=mountinfo,
        stat_provider=stat_provider,
    )
    monkeypatch.setattr("binnacle.adapters.linux.socket.gethostname", lambda: "fixture-pi")
    monkeypatch.setattr(
        "binnacle.adapters.linux.platform.machine",
        lambda: "aarch64",
    )

    snapshot = await inspector.inspect(tuple(SystemSection))

    assert snapshot.hostname == "fixture-pi"
    assert snapshot.os_summary == "Fixture Linux 1"
    assert snapshot.uptime_seconds == 123
    assert snapshot.cpu is not None and snapshot.cpu.count >= 1
    assert snapshot.memory is not None
    assert snapshot.memory.total_bytes == 1024 * 1024
    assert snapshot.filesystems is not None
    assert [item.mount_point for item in snapshot.filesystems] == ["/", "/mnt/space name"]
    assert calls == ["/", "/mnt/space name"]
    assert snapshot.binnacle_service is not None
    assert {warning.code for warning in snapshot.warnings} == {
        "filesystem_nonlocal_omitted",
        "service_manager_not_integrated",
    }


@pytest.mark.anyio
async def test_inspector_truncates_local_filesystems_explicitly(tmp_path: Path) -> None:
    mountinfo = "".join(
        f"{index} 25 0:{index} / /mnt/{index:03d} rw - ext4 /dev/{index} rw\n"
        for index in range(1, 4)
    )
    inspector = _make_inspector(
        tmp_path,
        mountinfo=mountinfo,
        max_filesystems=2,
    )

    snapshot = await inspector.inspect((SystemSection.FILESYSTEMS,))

    assert snapshot.filesystems is not None
    assert len(snapshot.filesystems) == 2
    assert snapshot.warnings[0].code == "filesystem_list_truncated"
    assert "2 entries" in snapshot.warnings[0].message


@pytest.mark.anyio
async def test_filesystem_capacity_timeout_is_bounded(tmp_path: Path) -> None:
    def slow_stat(_path: str) -> os.statvfs_result:
        time.sleep(0.05)
        return _stat_result()

    inspector = _make_inspector(
        tmp_path,
        stat_provider=slow_stat,
        timeout=0.001,
    )
    started = time.monotonic()

    with pytest.raises(InspectionError, match="timed out"):
        await inspector.inspect((SystemSection.FILESYSTEMS,))

    assert time.monotonic() - started < 0.04


@pytest.mark.anyio
async def test_timed_out_filesystem_workers_remain_admission_bounded(
    tmp_path: Path,
) -> None:
    release = threading.Event()
    four_started = threading.Event()
    lock = threading.Lock()
    calls = 0
    active = 0
    peak = 0

    def blocking_stat(_path: str) -> os.statvfs_result:
        nonlocal calls, active, peak
        with lock:
            calls += 1
            active += 1
            peak = max(peak, active)
            if active == 4:
                four_started.set()
        release.wait(timeout=1)
        with lock:
            active -= 1
        return _stat_result()

    inspector = _make_inspector(
        tmp_path,
        stat_provider=blocking_stat,
        timeout=0.005,
    )
    failures: list[str] = []

    async def inspect_filesystems() -> None:
        try:
            await inspector.inspect((SystemSection.FILESYSTEMS,))
        except InspectionError as exc:
            failures.append(str(exc))

    async with anyio.create_task_group() as task_group:
        for _ in range(4):
            task_group.start_soon(inspect_filesystems)
        try:
            assert await anyio.to_thread.run_sync(four_started.wait, 1)
            task_group.start_soon(inspect_filesystems)
            with anyio.fail_after(1):
                while "filesystem capacity admission is exhausted" not in failures:
                    await anyio.sleep(0)
        finally:
            release.set()

    assert calls == 4
    assert peak == 4
    assert "filesystem capacity admission is exhausted" in failures


@pytest.mark.anyio
async def test_negative_filesystem_capacity_is_rejected(tmp_path: Path) -> None:
    inspector = _make_inspector(
        tmp_path,
        stat_provider=lambda _path: _stat_result(blocks=-1),
    )

    with pytest.raises(InspectionError, match="negative"):
        await inspector.inspect((SystemSection.FILESYSTEMS,))


@pytest.mark.anyio
async def test_filesystem_os_error_is_normalized(tmp_path: Path) -> None:
    def failing_stat(_path: str) -> os.statvfs_result:
        raise OSError("private mount detail")

    inspector = _make_inspector(tmp_path, stat_provider=failing_stat)

    with pytest.raises(InspectionError, match="filesystems inspection failed"):
        await inspector.inspect((SystemSection.FILESYSTEMS,))


@pytest.mark.anyio
async def test_hostname_failures_are_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspector = _make_inspector(tmp_path)
    monkeypatch.setattr("binnacle.adapters.linux.socket.gethostname", lambda: "")
    with pytest.raises(InspectionError, match="hostname is unavailable"):
        await inspector.inspect(())

    def fail_hostname() -> str:
        raise OSError("private hostname detail")

    monkeypatch.setattr("binnacle.adapters.linux.socket.gethostname", fail_hostname)
    with pytest.raises(InspectionError, match="hostname collection failed"):
        await inspector.inspect(())


def test_os_release_pretty_name_and_fallback_are_bounded(tmp_path: Path) -> None:
    inspector = _make_inspector(tmp_path)
    assert inspector._read_os_summary() == "Fixture Linux 1"

    inspector.os_release_path.write_text(
        'NAME="Fixture"\nVERSION="2 LTS"\n',
        encoding="utf-8",
    )
    assert inspector._read_os_summary() == "Fixture 2 LTS"

    inspector.os_release_path.write_text("ID=fixture\n", encoding="utf-8")
    with pytest.raises(InspectionError, match="summary is unavailable"):
        inspector._read_os_summary()


@pytest.mark.parametrize("value", ["", "not-a-number", "-1.0 0"])
def test_invalid_uptime_is_rejected(tmp_path: Path, value: str) -> None:
    inspector = _make_inspector(tmp_path)
    inspector.uptime_path.write_text(value, encoding="ascii")

    with pytest.raises(InspectionError, match="uptime"):
        inspector._read_uptime()


@pytest.mark.parametrize(
    "value",
    [
        "MemTotal: 10 MB\nMemAvailable: 5 kB\n",
        "MemTotal: -1 kB\nMemAvailable: 5 kB\n",
        "MemTotal: 10 kB\n",
        "MemTotal: invalid kB\nMemAvailable: 5 kB\n",
    ],
)
def test_invalid_memory_sources_are_rejected(tmp_path: Path, value: str) -> None:
    inspector = _make_inspector(tmp_path)
    inspector.meminfo_path.write_text(value, encoding="ascii")

    with pytest.raises(InspectionError, match="memory"):
        inspector._read_memory()


def test_cpu_kernel_and_architecture_require_truthful_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("binnacle.adapters.linux.os.cpu_count", lambda: None)
    with pytest.raises(InspectionError, match="CPU count"):
        LinuxSystemInspector._read_cpu()

    monkeypatch.setattr("binnacle.adapters.linux.platform.machine", lambda: "")
    with pytest.raises(InspectionError, match="architecture"):
        LinuxSystemInspector._read_architecture()

    @dataclass(frozen=True)
    class Uname:
        release: str = ""

    monkeypatch.setattr("binnacle.adapters.linux.platform.uname", Uname)
    with pytest.raises(InspectionError, match="kernel release"):
        LinuxSystemInspector._read_kernel()


@pytest.mark.parametrize("mountinfo", ["", "invalid record\n"])
def test_invalid_mountinfo_is_rejected(tmp_path: Path, mountinfo: str) -> None:
    inspector = _make_inspector(tmp_path, mountinfo=mountinfo)

    with pytest.raises(InspectionError, match="mountinfo"):
        inspector._parse_mountinfo()


def test_fixed_file_reads_and_mount_escapes_are_bounded(tmp_path: Path) -> None:
    path = tmp_path / "fixed"
    path.write_bytes(b"12345")

    assert _read_bounded(path, 5) == b"12345"
    with pytest.raises(InspectionError, match="exceeds 4 bytes"):
        _read_bounded(path, 4)
    assert _decode_mount_field("/space\\040here\\134path") == "/space here\\path"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"filesystem_stat_timeout_seconds": 0.0},
        {"filesystem_stat_timeout_seconds": 11.0},
        {"max_read_bytes": 4095},
        {"max_filesystems": 0},
        {"max_filesystems": 129},
    ],
)
def test_inspector_rejects_invalid_internal_bounds(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        LinuxSystemInspector(**kwargs)  # type: ignore[arg-type]
