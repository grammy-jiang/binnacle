"""Operator-managed offline Ed25519 reviewer registry and replay ledger for P3.6.

The registry is read only from an explicit, symlink-free, operator-owned path
outside every evidence root. Nothing here generates keys, enrolls signers,
downloads data or grants authority; with no configured registry every
operation refuses. Trust rests on filesystem ownership, which cannot be proven
from inside a same-user agent sandbox (see the P3.6 trusted-registry note).
"""

from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import Field, ValidationError

from scripts.lsp_p36_evidence import Digest, Record, Text
from scripts.lsp_p36_secure_io import (
    PathPolicy,
    PathRefused,
    open_directory,
    read_file,
)

REGISTRY_ENV = "BINNACLE_P36_TRUST_REGISTRY"
REGISTRY_SCHEMA = "binnacle.p36.trust-registry/1"
MAX_REGISTRY_BYTES = 64 * 1024
MAX_LEDGER_BYTES = 1024 * 1024
Stage = Literal["P3.3", "P3.4", "P3.5"]
Stamp = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")]
_TOKEN = object()


class RegistryRefused(ValueError):
    """Fixed non-sensitive denial identifier."""


def parse_utc(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise RegistryRefused("registry_timestamp_invalid") from exc


def json_no_duplicates(raw: bytes, reason: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        out: dict[str, object] = {}
        for name, value in items:
            if name in out:
                raise RegistryRefused(reason)
            out[name] = value
        return out

    def reject(_: str) -> object:
        raise RegistryRefused(reason)

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, RegistryRefused):
            raise
        raise RegistryRefused(reason) from exc


class RegistryKey(Record):
    """One reviewer key; the principal and stages are operator assertions."""

    key_id: Digest
    public_key_b64: Annotated[str, Field(min_length=44, max_length=44)]
    principal: Text
    stages: Annotated[tuple[Stage, ...], Field(min_length=1, max_length=3)]
    not_before_utc: Stamp
    not_after_utc: Stamp
    state: Literal["active", "retired", "revoked"]
    state_changed_at_utc: Stamp | None = None
    supersedes: Digest | None = None

    def public_key(self) -> bytes:
        try:
            raw = base64.b64decode(self.public_key_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RegistryRefused("registry_key_invalid") from exc
        if len(raw) != 32 or hashlib.sha256(raw).hexdigest() != self.key_id:
            raise RegistryRefused("registry_key_id_mismatch")
        return raw


class RegistryDocument(Record):
    registry_schema: Literal["binnacle.p36.trust-registry/1"]
    registry_id: Text
    serial: Annotated[int, Field(ge=1, le=2**31)]
    issued_at_utc: Stamp
    producer_principals: Annotated[tuple[Text, ...], Field(max_length=32)] = ()
    keys: Annotated[tuple[RegistryKey, ...], Field(min_length=1, max_length=32)]


def _validate_document(doc: RegistryDocument) -> None:
    ids = [key.key_id for key in doc.keys]
    if len(set(ids)) != len(ids):
        raise RegistryRefused("registry_duplicate_key")
    by_id = {key.key_id: key for key in doc.keys}
    pubs = {key.public_key() for key in doc.keys}
    if len(pubs) != len(ids):
        raise RegistryRefused("registry_duplicate_key")
    for key in doc.keys:
        if parse_utc(key.not_before_utc) >= parse_utc(key.not_after_utc):
            raise RegistryRefused("registry_validity_invalid")
        if (key.state == "active") != (key.state_changed_at_utc is None):
            raise RegistryRefused("registry_state_invalid")
        if key.state_changed_at_utc is not None:
            parse_utc(key.state_changed_at_utc)
        if key.principal in doc.producer_principals:
            raise RegistryRefused("registry_reviewer_is_producer")
        if key.supersedes is not None:
            old = by_id.get(key.supersedes)
            if old is None or old.key_id == key.key_id or old.state == "active":
                raise RegistryRefused("registry_rotation_invalid")
    parse_utc(doc.issued_at_utc)


class TrustRegistry:
    """Loader-produced registry view; direct construction is refused."""

    def __init__(
        self,
        token: object,
        doc: RegistryDocument,
        sha256: str,
        owner_uid: int,
    ) -> None:
        if token is not _TOKEN:
            raise RegistryRefused("registry_not_loaded_from_operator_path")
        self.doc = doc
        self.sha256 = sha256
        self.owner_is_current_user = owner_uid == os.geteuid()
        self._keys = {key.key_id: key for key in doc.keys}

    def resolve(
        self, key_id: str, stage: str, issued: datetime, now: datetime
    ) -> RegistryKey:
        """Return the key only when state, validity window and role allow it."""
        key = self._keys.get(key_id)
        if key is None:
            raise RegistryRefused("signer_key_unknown")
        if key.state == "revoked":
            raise RegistryRefused("signer_key_revoked")
        if not (
            parse_utc(key.not_before_utc) <= issued <= parse_utc(key.not_after_utc)
            and now <= parse_utc(key.not_after_utc)
        ):
            raise RegistryRefused("signer_key_outside_validity")
        if key.state == "retired" and (
            key.state_changed_at_utc is None
            or issued >= parse_utc(key.state_changed_at_utc)
        ):
            raise RegistryRefused("signer_key_retired")
        if stage not in key.stages:
            raise RegistryRefused("signer_role_unauthorized")
        return key


def load_trust_registry(
    path: str | Path | None,
    *,
    policy: PathPolicy,
    expected_registry_id: str,
    min_serial: int = 1,
) -> TrustRegistry:
    """Load the operator registry; no configured path means fail closed."""
    chosen = path if path is not None else os.environ.get(REGISTRY_ENV)
    if not chosen:
        raise RegistryRefused("trust_registry_not_configured")
    if type(min_serial) is not int or min_serial < 1:
        raise RegistryRefused("registry_serial_policy_invalid")
    try:
        found = read_file(chosen, policy, MAX_REGISTRY_BYTES)
    except PathRefused as exc:
        raise RegistryRefused(f"registry_path_{exc}") from exc
    try:
        json_no_duplicates(found.data, "registry_duplicate_json_key")
        doc = RegistryDocument.model_validate_json(found.data)
    except ValidationError as exc:
        raise RegistryRefused("registry_schema_invalid") from exc
    if doc.registry_id != expected_registry_id:
        raise RegistryRefused("registry_id_mismatch")
    if doc.serial < min_serial:
        raise RegistryRefused("registry_rollback_refused")
    _validate_document(doc)
    return TrustRegistry(_TOKEN, doc, hashlib.sha256(found.data).hexdigest(), found.uid)


def replay_key(registry_id: str, run_id: str, stage: str) -> str:
    material = f"P3.6-REPLAY-V1\x00{registry_id}\x00{run_id}\x00{stage}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ReplayLedger(Protocol):
    persistent: bool

    def seen(self, key: str) -> bool: ...

    def record(self, keys: list[str]) -> None: ...


class MemoryReplayLedger:
    """Process-local ledger: audit re-checks only, no cross-run protection."""

    persistent = False

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, key: str) -> bool:
        return key in self._seen

    def record(self, keys: list[str]) -> None:
        if self._seen.intersection(keys) or len(set(keys)) != len(keys):
            raise RegistryRefused("review_replay_detected")
        self._seen.update(keys)


class FileReplayLedger:
    """Append-only, locked ledger in a private directory (0700, process-owned)."""

    persistent = True

    def __init__(self, path: str | Path, policy: PathPolicy) -> None:
        text = os.fspath(path)
        directory, _, name = text.rpartition("/")
        if not directory or not name or name in (".", ".."):
            raise RegistryRefused("ledger_path_invalid")
        self._dir, self._name, self._policy = directory, name, policy

    def _open(self) -> tuple[int, int]:
        try:
            dir_fd = open_directory(self._dir, self._policy)
        except PathRefused as exc:
            raise RegistryRefused(f"ledger_path_{exc}") from exc
        try:
            info = os.fstat(dir_fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise RegistryRefused("ledger_directory_not_private")
            fd = os.open(
                self._name,
                os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=dir_fd,
            )
        except OSError as exc:
            os.close(dir_fd)
            raise RegistryRefused("ledger_unreadable") from exc
        except RegistryRefused:
            os.close(dir_fd)
            raise
        return dir_fd, fd

    def _entries(self, fd: int) -> set[str]:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_size > MAX_LEDGER_BYTES
        ):
            raise RegistryRefused("ledger_file_unsafe")
        raw = os.pread(fd, MAX_LEDGER_BYTES, 0)
        lines = raw.decode("ascii", errors="replace").split("\n")
        entries = {line for line in lines if line}
        if any(len(line) != 64 or line.strip("0123456789abcdef") for line in entries):
            raise RegistryRefused("ledger_file_corrupt")
        return entries

    def seen(self, key: str) -> bool:
        dir_fd, fd = self._open()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            return key in self._entries(fd)
        finally:
            os.close(fd)
            os.close(dir_fd)

    def record(self, keys: list[str]) -> None:
        dir_fd, fd = self._open()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if self._entries(fd).intersection(keys) or len(set(keys)) != len(keys):
                raise RegistryRefused("review_replay_detected")
            os.write(fd, "".join(f"{key}\n" for key in keys).encode("ascii"))
            os.fsync(fd)
        finally:
            os.close(fd)
            os.close(dir_fd)
