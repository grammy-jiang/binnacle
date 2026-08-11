"""Bounded Linux device, system, and trusted-time adapters."""

from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import re
import shlex
import socket
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import anyio

from binnacle.adapters.linux.trusted_time import LinuxTrustedTimeSource as LinuxTrustedTimeSource
from binnacle.domain.system import (
    BinnacleServiceInfo,
    CpuInfo,
    DeviceIdentity,
    DeviceIdentityError,
    FilesystemInfo,
    InspectionError,
    InspectionWarning,
    MemoryInfo,
    SystemSection,
    SystemSnapshot,
)

LOCAL_FILESYSTEM_TYPES = frozenset(
    {
        "btrfs",
        "exfat",
        "ext2",
        "ext3",
        "ext4",
        "f2fs",
        "overlay",
        "ramfs",
        "squashfs",
        "tmpfs",
        "vfat",
        "xfs",
    }
)
_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")
WorkerResult = TypeVar("WorkerResult")


@dataclass(frozen=True, slots=True)
class _Mount:
    mount_point: str
    filesystem_type: str
    source: str | None


@dataclass(slots=True)
class LinuxDeviceIdentityProvider:
    """Derive a stable non-reversible identifier from fixed Linux sources."""

    identity_paths: tuple[Path, ...] = (
        Path("/etc/machine-id"),
        Path("/var/lib/dbus/machine-id"),
    )
    max_bytes: int = 4096

    def get_device_identity(self) -> DeviceIdentity:
        for path in self.identity_paths:
            try:
                raw = _read_bounded(path, self.max_bytes).strip()
            except OSError:
                continue
            if not raw or len(raw) > 256:
                continue
            digest = hashlib.sha256(b"binnacle-device-id-v1\0" + raw).hexdigest()
            return DeviceIdentity(device_id=f"device_{digest[:32]}")
        raise DeviceIdentityError("no stable Linux machine identity source is available")


@dataclass(slots=True)
class LinuxSystemInspector:
    """Collect only the reviewed fixed set of bounded Linux facts."""

    os_release_path: Path = Path("/etc/os-release")
    uptime_path: Path = Path("/proc/uptime")
    meminfo_path: Path = Path("/proc/meminfo")
    mountinfo_path: Path = Path("/proc/self/mountinfo")
    filesystem_stat_timeout_seconds: float = 2.0
    stat_provider: Callable[[str], os.statvfs_result] = os.statvfs
    max_read_bytes: int = 1_048_576
    max_filesystems: int = 128
    _general_limiter: anyio.CapacityLimiter = field(init=False, repr=False)
    _filesystem_admission: anyio.Semaphore = field(init=False, repr=False)
    _filesystem_tasks: set[asyncio.Task[os.statvfs_result]] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not 0 < self.filesystem_stat_timeout_seconds <= 10:
            raise ValueError("filesystem stat timeout must be in (0, 10]")
        if self.max_read_bytes < 4096:
            raise ValueError("max_read_bytes must be at least 4096")
        if not 1 <= self.max_filesystems <= 128:
            raise ValueError("max_filesystems must be in [1, 128]")
        self._general_limiter = anyio.CapacityLimiter(8)
        self._filesystem_admission = anyio.Semaphore(4)
        self._filesystem_tasks = set()

    async def inspect(self, sections: tuple[SystemSection, ...]) -> SystemSnapshot:
        try:
            hostname = await anyio.to_thread.run_sync(
                socket.gethostname,
                limiter=self._general_limiter,
            )
        except OSError as exc:
            raise InspectionError("hostname collection failed") from exc
        if not hostname:
            raise InspectionError("hostname is unavailable")

        os_summary: str | None = None
        kernel: str | None = None
        architecture: str | None = None
        uptime_seconds: int | None = None
        cpu: CpuInfo | None = None
        memory: MemoryInfo | None = None
        filesystems: tuple[FilesystemInfo, ...] | None = None
        service: BinnacleServiceInfo | None = None
        warnings: list[InspectionWarning] = []

        for section in sections:
            try:
                if section is SystemSection.OS:
                    os_summary = await self._worker(self._read_os_summary)
                elif section is SystemSection.KERNEL:
                    kernel = await self._worker(self._read_kernel)
                elif section is SystemSection.ARCHITECTURE:
                    architecture = await self._worker(self._read_architecture)
                elif section is SystemSection.UPTIME:
                    uptime_seconds = await self._worker(self._read_uptime)
                elif section is SystemSection.CPU:
                    cpu = await self._worker(self._read_cpu)
                elif section is SystemSection.MEMORY:
                    memory = await self._worker(self._read_memory)
                elif section is SystemSection.FILESYSTEMS:
                    filesystems, filesystem_warnings = await self._read_filesystems()
                    warnings.extend(filesystem_warnings)
                elif section is SystemSection.BINNACLE_SERVICE:
                    service = BinnacleServiceInfo(state="unknown")
                    warnings.append(
                        InspectionWarning(
                            code="service_manager_not_integrated",
                            message=("Binnacle service-manager integration is absent in Phase 2."),
                        )
                    )
            except InspectionError:
                raise
            except (OSError, UnicodeError, ValueError) as exc:
                raise InspectionError(f"{section.value} inspection failed") from exc

        return SystemSnapshot(
            hostname=hostname[:255],
            returned_sections=sections,
            os_summary=os_summary,
            kernel=kernel,
            architecture=architecture,
            uptime_seconds=uptime_seconds,
            cpu=cpu,
            memory=memory,
            filesystems=filesystems,
            binnacle_service=service,
            warnings=tuple(warnings),
        )

    async def _worker(
        self,
        function: Callable[[], WorkerResult],
    ) -> WorkerResult:
        return await anyio.to_thread.run_sync(function, limiter=self._general_limiter)

    def _read_os_summary(self) -> str:
        text = _read_bounded(self.os_release_path, min(self.max_read_bytes, 65536)).decode("utf-8")
        selected: dict[str, str] = {}
        for line in text.splitlines():
            key, separator, raw_value = line.partition("=")
            if separator and key in {"PRETTY_NAME", "NAME", "VERSION"}:
                values = shlex.split(raw_value, posix=True)
                selected[key] = " ".join(values)
        summary = selected.get("PRETTY_NAME")
        if summary is None:
            summary = " ".join(value for key in ("NAME", "VERSION") if (value := selected.get(key)))
        if not summary:
            raise InspectionError("OS release summary is unavailable")
        return summary[:256]

    @staticmethod
    def _read_kernel() -> str:
        value = platform.uname().release
        if not value:
            raise InspectionError("kernel release is unavailable")
        return value[:256]

    @staticmethod
    def _read_architecture() -> str:
        value = platform.machine()
        if not value:
            raise InspectionError("machine architecture is unavailable")
        return value[:64]

    def _read_uptime(self) -> int:
        text = _read_bounded(self.uptime_path, 4096).decode("ascii")
        try:
            value = int(float(text.split(maxsplit=1)[0]))
        except (IndexError, ValueError) as exc:
            raise InspectionError("Linux uptime is invalid") from exc
        if value < 0:
            raise InspectionError("Linux uptime is negative")
        return value

    @staticmethod
    def _read_cpu() -> CpuInfo:
        count = os.cpu_count()
        if count is None or count < 1:
            raise InspectionError("CPU count is unavailable")
        return CpuInfo(count=count)

    def _read_memory(self) -> MemoryInfo:
        text = _read_bounded(self.meminfo_path, min(self.max_read_bytes, 65536)).decode("ascii")
        values: dict[str, int] = {}
        for line in text.splitlines():
            key, separator, remainder = line.partition(":")
            if not separator or key not in {"MemTotal", "MemAvailable"}:
                continue
            fields = remainder.split()
            if len(fields) != 2 or fields[1] != "kB":
                raise InspectionError(f"Linux memory field {key} is invalid")
            try:
                kibibytes = int(fields[0])
            except ValueError as exc:
                raise InspectionError(f"Linux memory field {key} is invalid") from exc
            if kibibytes < 0:
                raise InspectionError(f"Linux memory field {key} is negative")
            values[key] = kibibytes * 1024
        if set(values) != {"MemTotal", "MemAvailable"}:
            raise InspectionError("required Linux memory fields are unavailable")
        return MemoryInfo(
            total_bytes=values["MemTotal"],
            available_bytes=values["MemAvailable"],
        )

    async def _read_filesystems(
        self,
    ) -> tuple[tuple[FilesystemInfo, ...], tuple[InspectionWarning, ...]]:
        mounts = await anyio.to_thread.run_sync(
            self._parse_mountinfo, limiter=self._general_limiter
        )
        eligible = sorted(
            (mount for mount in mounts if mount.filesystem_type in LOCAL_FILESYSTEM_TYPES),
            key=lambda mount: mount.mount_point,
        )
        omitted = len(eligible) != len(mounts)
        truncated = len(eligible) > self.max_filesystems
        selected = eligible[: self.max_filesystems]
        filesystems: list[FilesystemInfo] = []
        for mount in selected:
            try:
                stat = await self._bounded_filesystem_stat(mount.mount_point)
            except TimeoutError as exc:
                raise InspectionError("filesystem capacity query timed out") from exc
            total = stat.f_frsize * stat.f_blocks
            available = stat.f_frsize * stat.f_bavail
            if total < 0 or available < 0:
                raise InspectionError("filesystem capacity result is negative")
            filesystems.append(
                FilesystemInfo(
                    mount_point=mount.mount_point[:1024],
                    filesystem_type=mount.filesystem_type[:64],
                    source=mount.source[:512] if mount.source is not None else None,
                    total_bytes=total,
                    available_bytes=available,
                )
            )

        warnings: list[InspectionWarning] = []
        if omitted:
            warnings.append(
                InspectionWarning(
                    code="filesystem_nonlocal_omitted",
                    message="Non-local, userspace, remote, or unknown filesystems were omitted.",
                )
            )
        if truncated:
            warnings.append(
                InspectionWarning(
                    code="filesystem_list_truncated",
                    message=(
                        "The bounded filesystem result was truncated to "
                        f"{self.max_filesystems} entries."
                    ),
                )
            )
        return tuple(filesystems), tuple(warnings)

    async def _bounded_filesystem_stat(self, mount_point: str) -> os.statvfs_result:
        try:
            self._filesystem_admission.acquire_nowait()
        except anyio.WouldBlock as exc:
            raise InspectionError("filesystem capacity admission is exhausted") from exc

        task = asyncio.create_task(self._run_filesystem_stat(mount_point))
        self._filesystem_tasks.add(task)
        task.add_done_callback(self._finish_filesystem_task)
        with anyio.fail_after(self.filesystem_stat_timeout_seconds):
            return await asyncio.shield(task)

    def _finish_filesystem_task(
        self,
        task: asyncio.Task[os.statvfs_result],
    ) -> None:
        self._filesystem_tasks.discard(task)
        _consume_task_result(task)

    async def _run_filesystem_stat(self, mount_point: str) -> os.statvfs_result:
        try:
            return await anyio.to_thread.run_sync(
                self.stat_provider,
                mount_point,
            )
        finally:
            self._filesystem_admission.release()

    def _parse_mountinfo(self) -> tuple[_Mount, ...]:
        text = _read_bounded(self.mountinfo_path, self.max_read_bytes).decode("utf-8")
        mounts: list[_Mount] = []
        for line in text.splitlines():
            before, separator, after = line.partition(" - ")
            before_fields = before.split()
            after_fields = after.split()
            if not separator or len(before_fields) < 5 or len(after_fields) < 2:
                raise InspectionError("Linux mountinfo contains an invalid record")
            mount_point = _decode_mount_field(before_fields[4])
            filesystem_type = after_fields[0]
            source_value = _decode_mount_field(after_fields[1])
            if not mount_point or not filesystem_type:
                raise InspectionError("Linux mountinfo contains an empty field")
            source = None if source_value == "none" else source_value
            mounts.append(
                _Mount(
                    mount_point=mount_point,
                    filesystem_type=filesystem_type,
                    source=source,
                )
            )
        if not mounts:
            raise InspectionError("Linux mountinfo contains no records")
        return tuple(mounts)


def _read_bounded(path: Path, maximum_bytes: int) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(maximum_bytes + 1)
    if len(value) > maximum_bytes:
        raise InspectionError(f"fixed Linux source exceeds {maximum_bytes} bytes")
    return value


def _decode_mount_field(value: str) -> str:
    return _MOUNT_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _consume_task_result(task: asyncio.Task[WorkerResult]) -> None:
    """Retrieve an abandoned bounded worker result to suppress task warnings."""

    with suppress(asyncio.CancelledError, Exception):
        task.result()
