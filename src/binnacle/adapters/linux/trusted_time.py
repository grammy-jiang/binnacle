"""Fixed Linux trusted-time observation without clock mutation or shell execution."""

from __future__ import annotations

import hashlib
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from binnacle.domain.trusted_time import TrustedTimeSnapshot


class LinuxTrustedTimeSource:
    def __init__(
        self,
        *,
        boot_id_path: Path = Path("/proc/sys/kernel/random/boot_id"),
        synchronization_marker: Path = Path("/run/systemd/timesync/synchronized"),
    ) -> None:
        self._boot_id_path = boot_id_path
        self._synchronization_marker = synchronization_marker

    async def snapshot(self) -> TrustedTimeSnapshot:
        raw_boot_id = self._boot_id_path.read_text(encoding="ascii").strip()
        boot_digest = hashlib.sha256(
            b"binnacle.boot-id.v1\0" + raw_boot_id.encode("ascii")
        ).hexdigest()
        trusted = False
        try:
            info = self._synchronization_marker.stat(follow_symlinks=False)
            trusted = info.st_size == 0 and not self._synchronization_marker.is_symlink()
        except OSError:
            trusted = False
        return TrustedTimeSnapshot(
            wall_time=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            boot_id_digest=boot_digest,
            wall_time_trusted=trusted and os.name == "posix",
        )
