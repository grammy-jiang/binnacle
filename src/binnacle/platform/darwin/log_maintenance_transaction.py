"""Dormant, crash-durable log-maintenance *evidence* journal.

Records a monotonic sequence of externally verified milestones. This module
never asks launchd to change service state, controls no Jobs/MCP admission,
does not manipulate logs, and can NEVER authorize a production prune.

The exclusive file lease is owned by a local controller process. Its
in-memory write key is intentionally NOT persisted: after SIGKILL, a
new controller or recovery guardian may inspect the journal, but must
not resume appending as the crashed owner. Recovery requires a separately
reviewed, independently authenticated service-restoration protocol.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PHASES = (
    "intent",
    "j7_locked",
    "watchdog_acked",
    "mcp_drained",
    "jobs_drained",
    "guardian_armed",
    "producer_stopped",
    "writer_fds_closed",
    "canonical_verified",
    "raw_pruned",
    "producer_restored",
    "complete",
)
_LABELS = frozenset(
    {
        "system/com.binnacle.mcp",
        "system/com.binnacle.jobs",
        "system/com.binnacle.tunnel",
        "system/com.binnacle.service-watchdog",
        "system/com.binnacle.resource-monitor",
    }
)
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RECORD_BYTES = 4096
_BODY_KEYS = frozenset(
    {
        "version",
        "nonce",
        "controller_generation",
        "owner_pid",
        "owner_key_digest",
        "target",
        "producer_pid",
        "producer_generation",
        "source_dev",
        "source_ino",
        "phase",
        "revision",
        "receipts",
    }
)


class MaintenanceJournalRefused(RuntimeError):
    """Unverifiable journal state; real producer operations must not proceed."""


@dataclass(frozen=True)
class JournalSnapshot:
    """Evidence is NOT authorization to stop a process or remove an archive."""

    nonce: str
    target: str
    owner_pid: int
    controller_generation: str
    producer_pid: int
    producer_generation: str
    source_dev: int
    source_ino: int
    phase: str
    revision: int
    receipts: tuple[tuple[str, str], ...]
    production_authorized: bool = False

    def __post_init__(self) -> None:
        if self.production_authorized:
            raise ValueError("journal evidence never authorizes production mutation")

    @property
    def needs_external_recovery(self) -> bool:
        return self.phase not in ("intent", "complete")

    @property
    def producer_may_be_stopped(self) -> bool:
        # After guardian arming, a controller may have executed bootout but
        # been SIGKILLed before persisting the producer_stopped receipt.
        # The *previous* durable phase is therefore not proof it remained up.
        return (
            _PHASES.index(self.phase) >= _PHASES.index("guardian_armed")
            and self.phase != "complete"
        )


def _hex32(value: Any) -> bool:
    return isinstance(value, str) and _HEX32.fullmatch(value) is not None


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _check_record(record: Any) -> JournalSnapshot:
    if not isinstance(record, dict) or set(record) != _BODY_KEYS | {"digest"}:
        raise MaintenanceJournalRefused("journal record schema untrusted")
    encoded = {key: record[key] for key in _BODY_KEYS}
    digest = record["digest"]
    if not isinstance(digest, str) or _HEX64.fullmatch(digest) is None:
        raise MaintenanceJournalRefused("journal checksum format invalid")
    if hashlib.sha256(_canonical(encoded)).hexdigest() != digest:
        raise MaintenanceJournalRefused("journal checksum mismatch")
    if type(record["version"]) is not int or record["version"] != 1:
        raise MaintenanceJournalRefused("unknown journal version")
    if (
        not _hex32(record["nonce"])
        or not _hex32(record["controller_generation"])
        or not isinstance(record["owner_key_digest"], str)
        or _HEX64.fullmatch(record["owner_key_digest"]) is None
        or not _hex32(record["producer_generation"])
        or not isinstance(record["target"], str)
        or record["target"] not in _LABELS
        or not all(
            _positive(record[name])
            for name in ("owner_pid", "producer_pid", "source_dev", "source_ino")
        )
    ):
        raise MaintenanceJournalRefused("untrusted transaction identity")
    phase, revision, receipts = (
        record["phase"],
        record["revision"],
        record["receipts"],
    )
    if not isinstance(phase, str) or phase not in _PHASES:
        raise MaintenanceJournalRefused("unknown transaction phase")
    step = _PHASES.index(phase)
    if type(revision) is not int or revision != step:
        raise MaintenanceJournalRefused("journal sequence not monotonic")
    if not isinstance(receipts, dict) or set(receipts) != set(_PHASES[1 : step + 1]):
        raise MaintenanceJournalRefused("journal evidence chain incomplete")
    if not all(
        isinstance(value, str) and _HEX64.fullmatch(value)
        for value in receipts.values()
    ):
        raise MaintenanceJournalRefused("journal evidence digest invalid")
    return JournalSnapshot(
        record["nonce"],
        record["target"],
        record["owner_pid"],
        record["controller_generation"],
        record["producer_pid"],
        record["producer_generation"],
        record["source_dev"],
        record["source_ino"],
        phase,
        revision,
        tuple(sorted(receipts.items())),
    )


class MaintenanceTransactionJournal:
    """One lock and one journal inode per pre-created, private transaction root.

    The root must be an absolute, canonical, user-owned 0700 directory named
    txn-<nonce>. The manager never creates the directory or selects a service.
    A distinct root is needed for every new transaction; records are never
    reset and prior crash evidence is never automatically discarded.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._dirfd = -1
        self._lockfd = -1
        self._pid: int | None = None
        self._key: bytes | None = None

    def __enter__(self) -> MaintenanceTransactionJournal:  # noqa: PYI034 - Python 3.10
        if self._dirfd >= 0 or self._pid is not None:
            raise MaintenanceJournalRefused("journal lease already in use")
        if os.getuid() == 0 or os.geteuid() != os.getuid():
            raise MaintenanceJournalRefused("controller journal must be unprivileged")
        if (
            not self.root.is_absolute()
            or self.root.name[:4] != "txn-"
            or not _hex32(self.root.name[4:])
            or self.root.resolve() != self.root
        ):
            raise MaintenanceJournalRefused("journal root not canonical")
        try:
            self._dirfd = os.open(
                self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            self._identity()
            self._lockfd = os.open(
                "transaction.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=self._dirfd,
            )
            self._lock_identity()
            try:
                fcntl.flock(self._lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise MaintenanceJournalRefused("journal lease already owned") from exc
            self._lock_identity()
            self._pid = os.getpid()
            return self
        except OSError as exc:
            self._close()
            raise MaintenanceJournalRefused("journal lease unavailable") from exc
        except BaseException:
            self._close()
            raise

    def _identity(self) -> None:
        opened = os.fstat(self._dirfd)
        named = self.root.lstat()
        if (
            not stat.S_ISDIR(opened.st_mode)
            or opened.st_uid != os.getuid()
            or opened.st_mode & 0o077
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise MaintenanceJournalRefused("journal root identity changed")

    def _lock_identity(self) -> None:
        opened = os.fstat(self._lockfd)
        named = os.stat("transaction.lock", dir_fd=self._dirfd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise MaintenanceJournalRefused("journal lock identity changed")

    def _verify(self) -> None:
        if self._pid is None or self._pid != os.getpid():
            raise MaintenanceJournalRefused("journal owner process changed")
        if self._dirfd < 0 or self._lockfd < 0:
            raise MaintenanceJournalRefused("journal lock not held")
        self._identity()
        self._lock_identity()

    def _read(self) -> dict[str, Any] | None:
        try:
            fd = os.open(
                "transaction.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self._dirfd
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise MaintenanceJournalRefused("journal file inaccessible") from exc
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or not 0 < info.st_size <= _MAX_RECORD_BYTES
            ):
                raise MaintenanceJournalRefused("journal file identity untrusted")
            raw = os.read(fd, _MAX_RECORD_BYTES + 1)
            now = os.fstat(fd)
            named = os.stat(
                "transaction.json", dir_fd=self._dirfd, follow_symlinks=False
            )
            if (
                len(raw) != info.st_size
                or (info.st_dev, info.st_ino) != (now.st_dev, now.st_ino)
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise MaintenanceJournalRefused("journal file changed while reading")
        except OSError as exc:
            raise MaintenanceJournalRefused("journal read incomplete") from exc
        finally:
            os.close(fd)

        def no_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for name, value in pairs:
                if name in result:
                    raise ValueError("duplicate journal field")
                result[name] = value
            return result

        try:
            value = json.loads(raw, object_pairs_hook=no_duplicate)
        except (ValueError, UnicodeDecodeError, TypeError) as exc:
            raise MaintenanceJournalRefused("malformed journal data") from exc
        observed = _check_record(value)
        if observed.nonce != self.root.name[4:]:
            raise MaintenanceJournalRefused("journal transaction root nonce mismatch")
        return value

    def _publish(self, record: dict[str, Any], *, new: bool) -> None:
        data = _canonical(record)
        if not 0 < len(data) <= _MAX_RECORD_BYTES:
            raise MaintenanceJournalRefused("journal record too large")
        name = "." + uuid.uuid4().hex + ".tmp"
        fd = -1
        original: tuple[int, int] | None = None
        try:
            fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=self._dirfd,
            )
            own = os.fstat(fd)
            original = (own.st_dev, own.st_ino)
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise MaintenanceJournalRefused("journal short write")
                view = view[written:]
            os.fsync(fd)
            named = os.stat(name, dir_fd=self._dirfd, follow_symlinks=False)
            if (named.st_dev, named.st_ino) != original:
                raise MaintenanceJournalRefused("journal temporary name changed")
            if new:
                os.link(
                    name,
                    "transaction.json",
                    src_dir_fd=self._dirfd,
                    dst_dir_fd=self._dirfd,
                    follow_symlinks=False,
                )
                os.unlink(name, dir_fd=self._dirfd)
            else:
                os.replace(
                    name,
                    "transaction.json",
                    src_dir_fd=self._dirfd,
                    dst_dir_fd=self._dirfd,
                )
            os.fsync(self._dirfd)
        except OSError as exc:
            raise MaintenanceJournalRefused("journal publication incomplete") from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if original is not None:
                pending: os.stat_result | None
                try:
                    pending = os.stat(name, dir_fd=self._dirfd, follow_symlinks=False)
                except FileNotFoundError:
                    pending = None
                if pending is not None:
                    if (pending.st_dev, pending.st_ino) != original:
                        raise MaintenanceJournalRefused(
                            "foreign journal scratch path cannot be removed"
                        )
                    os.unlink(name, dir_fd=self._dirfd)

    def begin(
        self,
        *,
        nonce: str,
        controller_generation: str,
        target: str,
        producer_pid: int,
        producer_generation: str,
        source_dev: int,
        source_ino: int,
    ) -> JournalSnapshot:
        self._verify()
        if (
            nonce != self.root.name[4:]
            or not _hex32(controller_generation)
            or not isinstance(target, str)
            or target not in _LABELS
            or not _positive(producer_pid)
            or not _hex32(producer_generation)
            or not _positive(source_dev)
            or not _positive(source_ino)
        ):
            raise MaintenanceJournalRefused("initial journal evidence invalid")
        if self._read() is not None:
            raise MaintenanceJournalRefused("journal already exists")
        key = secrets.token_bytes(32)
        body: dict[str, Any] = {
            "version": 1,
            "nonce": nonce,
            "controller_generation": controller_generation,
            "owner_pid": os.getpid(),
            "owner_key_digest": hashlib.sha256(key).hexdigest(),
            "target": target,
            "producer_pid": producer_pid,
            "producer_generation": producer_generation,
            "source_dev": source_dev,
            "source_ino": source_ino,
            "phase": "intent",
            "revision": 0,
            "receipts": {},
        }
        record = {**body, "digest": hashlib.sha256(_canonical(body)).hexdigest()}
        self._publish(record, new=True)
        self._key = key
        return _check_record(record)

    def inspect(self) -> JournalSnapshot | None:
        self._verify()
        record = self._read()
        return _check_record(record) if record is not None else None

    def advance(
        self, *, nonce: str, expected_revision: int, phase: str, receipt_digest: str
    ) -> JournalSnapshot:
        self._verify()
        current = self._read()
        if current is None:
            raise MaintenanceJournalRefused("journal has no begun transaction")
        view = _check_record(current)
        key = self._key
        if (
            key is None
            or not secrets.compare_digest(
                hashlib.sha256(key).hexdigest(), current["owner_key_digest"]
            )
            or current["owner_pid"] != os.getpid()
            or nonce != view.nonce
            or not isinstance(receipt_digest, str)
            or _HEX64.fullmatch(receipt_digest) is None
            or type(expected_revision) is not int
            or phase not in _PHASES[1:]
        ):
            raise MaintenanceJournalRefused("journal advance owner/evidence invalid")
        if view.phase == "complete":
            raise MaintenanceJournalRefused("completed journal is immutable")
        stage = _PHASES.index(phase)
        if (
            stage == view.revision
            and expected_revision == view.revision - 1
            and current["receipts"].get(phase) == receipt_digest
        ):
            return view  # safe exact replay after lost publish acknowledgement
        if stage != view.revision + 1 or expected_revision != view.revision:
            raise MaintenanceJournalRefused("journal revision/phase not next")
        body = {key: value for key, value in current.items() if key != "digest"}
        body["phase"], body["revision"] = phase, stage
        body["receipts"] = {**current["receipts"], phase: receipt_digest}
        record = {**body, "digest": hashlib.sha256(_canonical(body)).hexdigest()}
        self._publish(record, new=False)
        return _check_record(record)

    def _close(self) -> None:
        self._key = None
        self._pid = None
        for attr in ("_lockfd", "_dirfd"):
            fd = getattr(self, attr)
            setattr(self, attr, -1)
            if fd >= 0:
                os.close(fd)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._close()
