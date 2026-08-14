"""Protected durable pre-effect audit-obligation marker protocol."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from pathlib import Path

from binnacle.adapters.audit.canonical import canonicalize
from binnacle.ports.audit import AuditObligation

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


class AuditObligationError(RuntimeError):
    pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class FileAuditObligationStore:
    def __init__(self, directory: Path, *, bytes_max: int = 4096) -> None:
        self._directory = directory
        self._bytes_max = bytes_max

    async def initialize(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o750)
        if self._directory.is_symlink() or not self._directory.is_dir():
            raise AuditObligationError("audit obligation directory is unsafe")
        # The service group needs traversal/read access, while group/other write
        # remains forbidden and individual obligation markers remain mode 0600.
        os.chmod(self._directory, 0o750)  # nosec B103

    def _final_path(self, obligation_id: str) -> Path:
        if not _IDENTIFIER.fullmatch(obligation_id):
            raise AuditObligationError("invalid audit obligation identifier")
        return self._directory / f"{obligation_id}.json"

    async def publish(self, obligation: AuditObligation) -> None:
        if obligation.schema_version != "1" or obligation.running_state_version < 1:
            raise AuditObligationError("invalid audit obligation")
        final_path = self._final_path(obligation.obligation_id)
        value = {
            "schema_version": obligation.schema_version,
            "obligation_id": obligation.obligation_id,
            "operation_id": obligation.operation_id,
            "running_state_version": obligation.running_state_version,
        }
        payload = canonicalize(value)
        if len(payload) > self._bytes_max:
            raise AuditObligationError("audit obligation exceeds maximum bytes")
        temporary = self._directory / f".tmp-{secrets.token_hex(16)}"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            written = 0
            while written < len(payload):
                written += os.write(descriptor, payload[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, final_path, follow_symlinks=False)
            os.unlink(temporary)
            _fsync_directory(self._directory)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    async def remove(self, obligation_id: str) -> None:
        path = self._final_path(obligation_id)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise AuditObligationError("audit obligation path is unsafe")
        path.unlink()
        _fsync_directory(self._directory)

    async def scan(self) -> tuple[AuditObligation, ...]:
        obligations: list[AuditObligation] = []
        seen: set[str] = set()
        for path in sorted(self._directory.iterdir(), key=lambda item: item.name):
            if path.name.startswith(".tmp-"):
                raise AuditObligationError("incomplete audit obligation marker exists")
            if path.suffix != ".json":
                raise AuditObligationError("unexpected audit obligation directory entry")
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise AuditObligationError("unsafe audit obligation entry")
            if info.st_size > self._bytes_max:
                raise AuditObligationError("audit obligation exceeds maximum bytes")
            try:
                value = json.loads(path.read_bytes())
                obligation = AuditObligation(
                    schema_version=value["schema_version"],
                    obligation_id=value["obligation_id"],
                    operation_id=value["operation_id"],
                    running_state_version=value["running_state_version"],
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise AuditObligationError("malformed audit obligation") from exc
            if canonicalize(value) != path.read_bytes():
                raise AuditObligationError("audit obligation is not canonical")
            if path != self._final_path(obligation.obligation_id):
                raise AuditObligationError("audit obligation filename/content mismatch")
            if obligation.obligation_id in seen:
                raise AuditObligationError("duplicate audit obligation identifier")
            seen.add(obligation.obligation_id)
            obligations.append(obligation)
        return tuple(obligations)
