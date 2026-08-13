"""Read-only verification of complete protected Phase 9 runtime slots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Final, Protocol

from binnacle.domain.privileged import canonical_timestamp
from binnacle.domain.privileged_observation import (
    PrivilegedObservationError,
    RuntimeSlotRole,
    RuntimeSlotState,
    VerifiedRuntimeSlot,
)

DEFAULT_RUNTIME_ROOT: Final = Path("/srv/binnacle-runtime")
RUNTIME_SLOT_MANIFEST: Final = "slot-manifest.json"
_FORMAT_VERSION: Final = "binnacle-runtime-slot-v1"
_SLOTS_DIRECTORY: Final = "slots"
_CURRENT_SELECTOR: Final = "current"
_SLOT_ID_RE: Final = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_MAX_MANIFEST_BYTES: Final = 2_097_152
_MAX_FILE_BYTES: Final = 2_147_483_648
_CHUNK_BYTES: Final = 1_048_576


class RuntimeSlotVerificationError(RuntimeError):
    """A retained slot or selector differs from its complete immutable evidence."""


@dataclass(frozen=True, slots=True)
class RuntimeSlotFile:
    path: str
    mode: str
    byte_count: int
    sha256: str

    def __post_init__(self) -> None:
        _require_relative_path(self.path)
        if self.mode not in {"0440", "0550"}:
            raise RuntimeSlotVerificationError("runtime slot file mode is unsupported")
        if not 0 <= self.byte_count <= _MAX_FILE_BYTES:
            raise RuntimeSlotVerificationError("runtime slot file size is outside the limit")
        _require_sha256(self.sha256, "runtime slot file")


@dataclass(frozen=True, slots=True)
class RuntimeSlotManifest:
    """Immutable material receipt; role and state are publication-time facts only."""

    format_version: str
    slot_id: str
    slot_generation: int
    role: RuntimeSlotRole
    state: RuntimeSlotState
    source_sha256: str
    environment_sha256: str
    config_sha256: str
    policy_sha256: str
    manifest_sha256: str
    service_definition_sha256: str
    deployed_peer_set_sha256: str
    migration_heads_sha256: str
    layout_sha256: str
    candidate_verification_sha256: str
    completed_at: datetime
    directories: tuple[str, ...]
    files: tuple[RuntimeSlotFile, ...]

    def __post_init__(self) -> None:
        if self.format_version != _FORMAT_VERSION:
            raise RuntimeSlotVerificationError("runtime slot manifest format is incompatible")
        _require_slot_id(self.slot_id)
        if self.slot_generation < 1:
            raise RuntimeSlotVerificationError("runtime slot generation is invalid")
        for value, name in (
            (self.source_sha256, "runtime slot source"),
            (self.environment_sha256, "runtime slot environment"),
            (self.config_sha256, "runtime slot config"),
            (self.policy_sha256, "runtime slot policy"),
            (self.manifest_sha256, "runtime slot manifest identity"),
            (self.service_definition_sha256, "runtime slot service definition"),
            (self.deployed_peer_set_sha256, "runtime slot deployed-peer set"),
            (self.migration_heads_sha256, "runtime slot migration heads"),
            (self.layout_sha256, "runtime slot layout"),
            (self.candidate_verification_sha256, "runtime slot candidate verification"),
        ):
            _require_sha256(value, name)
        try:
            canonical_timestamp(self.completed_at)
        except ValueError as exc:
            raise RuntimeSlotVerificationError("runtime slot completion time is invalid") from exc
        if self.directories != tuple(sorted(set(self.directories))):
            raise RuntimeSlotVerificationError("runtime slot directories are not canonical")
        for path in self.directories:
            _require_relative_path(path)
        file_paths = tuple(item.path for item in self.files)
        if file_paths != tuple(sorted(set(file_paths))):
            raise RuntimeSlotVerificationError("runtime slot files are not canonical")
        if set(self.directories) & set(file_paths):
            raise RuntimeSlotVerificationError("runtime slot path has two kinds")
        if RUNTIME_SLOT_MANIFEST in file_paths:
            raise RuntimeSlotVerificationError("runtime slot manifest may not inventory itself")

    @property
    def complete_manifest_sha256(self) -> str:
        content = canonical_runtime_slot_manifest_bytes(self)
        return hashlib.sha256(content[:-1]).hexdigest()

    @property
    def byte_count(self) -> int:
        return sum(item.byte_count for item in self.files)

    @property
    def inode_count(self) -> int:
        return len(self.directories) + len(self.files)


@dataclass(frozen=True, slots=True)
class RuntimeSlotInspectionSettings:
    runtime_root: Path = DEFAULT_RUNTIME_ROOT
    expected_owner_uid: int = 0
    expected_group_gid: int = 0
    maximum_slot_bytes: int = 100_000_000_000
    maximum_slot_inodes: int = 10_000_000
    maximum_retained_slots: int = 16
    require_fixed_root: bool = True

    def __post_init__(self) -> None:
        if self.require_fixed_root and self.runtime_root != DEFAULT_RUNTIME_ROOT:
            raise RuntimeSlotVerificationError("runtime root is not the protected path")
        if (
            not self.runtime_root.is_absolute()
            or self.runtime_root != Path(os.path.normpath(str(self.runtime_root)))
            or min(self.expected_owner_uid, self.expected_group_gid) < 0
            or not 1_048_576 <= self.maximum_slot_bytes <= 100_000_000_000
            or not 1_000 <= self.maximum_slot_inodes <= 10_000_000
            or not 3 <= self.maximum_retained_slots <= 16
        ):
            raise RuntimeSlotVerificationError("runtime slot settings are invalid")


class RuntimeSlotLifecycleReader(Protocol):
    """Read transactionally authoritative mutable slot roles from broker evidence."""

    async def get_runtime_slot(self, slot_id: str) -> VerifiedRuntimeSlot | None: ...

    async def lkg_runtime_slot(self) -> VerifiedRuntimeSlot | None: ...


class FilesystemRuntimeSlotMaterialInspector:
    """Verify immutable slot material and its publication-time role declaration."""

    def __init__(self, settings: RuntimeSlotInspectionSettings) -> None:
        self._settings = settings

    async def inspect(self, slot_id: str) -> VerifiedRuntimeSlot:
        return self.inspect_sync(slot_id)

    async def current(self) -> VerifiedRuntimeSlot | None:
        return self.current_sync()

    def current_sync(self) -> VerifiedRuntimeSlot | None:
        slot_id = self._selector_slot_id()
        return None if slot_id is None else self.inspect_sync(slot_id)

    async def published_lkg(self) -> VerifiedRuntimeSlot | None:
        return self.published_lkg_sync()

    def published_lkg_sync(self) -> VerifiedRuntimeSlot | None:
        matches = [slot for slot in self._inspect_all() if slot.state is RuntimeSlotState.LKG]
        if len(matches) > 1:
            raise RuntimeSlotVerificationError("multiple published LKG slots exist")
        return matches[0] if matches else None

    def inspect_sync(self, slot_id: str) -> VerifiedRuntimeSlot:
        _require_slot_id(slot_id)
        self._verify_root()
        slot_path = self._settings.runtime_root / _SLOTS_DIRECTORY / slot_id
        slot_metadata = _lstat(slot_path, "runtime slot")
        if (
            not stat.S_ISDIR(slot_metadata.st_mode)
            or stat.S_ISLNK(slot_metadata.st_mode)
            or _identity_mode(slot_metadata)
            != (
                self._settings.expected_owner_uid,
                self._settings.expected_group_gid,
                0o550,
            )
        ):
            raise RuntimeSlotVerificationError("runtime slot ownership or mode is unsafe")
        manifest = self._load_manifest(slot_path)
        if manifest.slot_id != slot_id:
            raise RuntimeSlotVerificationError("runtime slot manifest identity differs")
        if manifest.byte_count > self._settings.maximum_slot_bytes:
            raise RuntimeSlotVerificationError("runtime slot byte ceiling exceeded")
        if manifest.inode_count > self._settings.maximum_slot_inodes:
            raise RuntimeSlotVerificationError("runtime slot inode ceiling exceeded")
        directories, files = self._enumerate_slot(slot_path)
        if directories != manifest.directories:
            raise RuntimeSlotVerificationError("runtime slot directory set differs")
        if files != tuple(item.path for item in manifest.files):
            raise RuntimeSlotVerificationError("runtime slot file set differs")
        for expected in manifest.files:
            self._verify_file(slot_path, expected)
        try:
            return VerifiedRuntimeSlot(
                slot_id=manifest.slot_id,
                slot_generation=manifest.slot_generation,
                slot_path=f"/srv/binnacle-runtime/slots/{manifest.slot_id}",
                role=manifest.role,
                state=manifest.state,
                source_sha256=manifest.source_sha256,
                environment_sha256=manifest.environment_sha256,
                config_sha256=manifest.config_sha256,
                policy_sha256=manifest.policy_sha256,
                manifest_sha256=manifest.manifest_sha256,
                service_definition_sha256=manifest.service_definition_sha256,
                deployed_peer_set_sha256=manifest.deployed_peer_set_sha256,
                migration_heads_sha256=manifest.migration_heads_sha256,
                layout_sha256=manifest.layout_sha256,
                candidate_verification_sha256=manifest.candidate_verification_sha256,
                complete_manifest_sha256=manifest.complete_manifest_sha256,
                byte_count=manifest.byte_count,
                inode_count=manifest.inode_count,
                completed_at=manifest.completed_at,
            )
        except PrivilegedObservationError as exc:
            raise RuntimeSlotVerificationError("runtime slot manifest is contradictory") from exc

    def _verify_root(self) -> None:
        root = self._settings.runtime_root
        slots = root / _SLOTS_DIRECTORY
        for path, name in ((root, "runtime root"), (slots, "runtime slots root")):
            metadata = _lstat(path, name)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or _identity_mode(metadata)
                != (
                    self._settings.expected_owner_uid,
                    self._settings.expected_group_gid,
                    0o750,
                )
            ):
                raise RuntimeSlotVerificationError(f"{name} ownership or mode is unsafe")

    def _load_manifest(self, slot_path: Path) -> RuntimeSlotManifest:
        path = slot_path / RUNTIME_SLOT_MANIFEST
        descriptor = -1
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or _identity_mode(metadata)
                != (
                    self._settings.expected_owner_uid,
                    self._settings.expected_group_gid,
                    0o440,
                )
                or not 1 <= metadata.st_size <= _MAX_MANIFEST_BYTES
            ):
                raise RuntimeSlotVerificationError("runtime slot manifest is unsafe")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                raw = stream.read(_MAX_MANIFEST_BYTES + 1)
        except RuntimeSlotVerificationError:
            raise
        except OSError as exc:
            raise RuntimeSlotVerificationError("runtime slot manifest is unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise RuntimeSlotVerificationError("runtime slot manifest exceeds the limit")
        try:
            document = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_object_from_pairs,
                parse_constant=_reject_constant,
            )
        except (RecursionError, UnicodeDecodeError, ValueError) as exc:
            raise RuntimeSlotVerificationError("runtime slot manifest is invalid JSON") from exc
        manifest = _manifest_from_document(document)
        if raw != canonical_runtime_slot_manifest_bytes(manifest):
            raise RuntimeSlotVerificationError("runtime slot manifest bytes are not canonical")
        return manifest

    def _enumerate_slot(self, slot_path: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
        directories: list[str] = []
        files: list[str] = []
        pending: list[tuple[Path, PurePosixPath | None]] = [(slot_path, None)]
        entries_seen = 0
        while pending:
            directory, relative_parent = pending.pop()
            try:
                iterator = os.scandir(directory)
            except OSError as exc:
                raise RuntimeSlotVerificationError("runtime slot tree is unavailable") from exc
            with iterator:
                for entry in iterator:
                    entries_seen += 1
                    if entries_seen > self._settings.maximum_slot_inodes + 1:
                        raise RuntimeSlotVerificationError("runtime slot inode ceiling exceeded")
                    relative = (
                        PurePosixPath(entry.name)
                        if relative_parent is None
                        else relative_parent / entry.name
                    )
                    relative_text = str(relative)
                    _require_relative_path(relative_text)
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        raise RuntimeSlotVerificationError(
                            "runtime slot entry is unavailable"
                        ) from exc
                    if stat.S_ISLNK(metadata.st_mode):
                        raise RuntimeSlotVerificationError("runtime slot contains a symlink")
                    if stat.S_ISDIR(metadata.st_mode):
                        if _identity_mode(metadata) != (
                            self._settings.expected_owner_uid,
                            self._settings.expected_group_gid,
                            0o550,
                        ):
                            raise RuntimeSlotVerificationError(
                                "runtime slot directory ownership or mode is unsafe"
                            )
                        directories.append(relative_text)
                        pending.append((Path(entry.path), relative))
                    elif stat.S_ISREG(metadata.st_mode):
                        if relative_text != RUNTIME_SLOT_MANIFEST:
                            files.append(relative_text)
                    else:
                        raise RuntimeSlotVerificationError("runtime slot entry type is unsupported")
        return tuple(sorted(directories)), tuple(sorted(files))

    def _verify_file(self, slot_path: Path, expected: RuntimeSlotFile) -> None:
        descriptor = -1
        try:
            descriptor = os.open(
                slot_path / expected.path,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            metadata = os.fstat(descriptor)
            mode = stat.S_IMODE(metadata.st_mode)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self._settings.expected_owner_uid
                or metadata.st_gid != self._settings.expected_group_gid
                or f"{mode:04o}" != expected.mode
                or metadata.st_size != expected.byte_count
            ):
                raise RuntimeSlotVerificationError("runtime slot file identity differs")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, _CHUNK_BYTES):
                digest.update(chunk)
            if digest.hexdigest() != expected.sha256:
                raise RuntimeSlotVerificationError("runtime slot file digest differs")
        except RuntimeSlotVerificationError:
            raise
        except OSError as exc:
            raise RuntimeSlotVerificationError("runtime slot file is unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _selector_slot_id(self) -> str | None:
        self._verify_root()
        selector = self._settings.runtime_root / _CURRENT_SELECTOR
        try:
            metadata = selector.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise RuntimeSlotVerificationError("runtime selector is unavailable") from exc
        if (
            not stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != self._settings.expected_owner_uid
            or metadata.st_gid != self._settings.expected_group_gid
        ):
            raise RuntimeSlotVerificationError("runtime selector identity is unsafe")
        try:
            target = os.readlink(selector)
        except OSError as exc:
            raise RuntimeSlotVerificationError("runtime selector target is unavailable") from exc
        path = PurePosixPath(target)
        if (
            path.is_absolute()
            or len(path.parts) != 2
            or path.parts[0] != _SLOTS_DIRECTORY
            or str(path) != target
        ):
            raise RuntimeSlotVerificationError("runtime selector target is invalid")
        slot_id = path.parts[1]
        _require_slot_id(slot_id)
        return slot_id

    def _inspect_all(self) -> tuple[VerifiedRuntimeSlot, ...]:
        self._verify_root()
        slots_root = self._settings.runtime_root / _SLOTS_DIRECTORY
        slot_ids: list[str] = []
        try:
            iterator = os.scandir(slots_root)
        except OSError as exc:
            raise RuntimeSlotVerificationError("runtime slots root is unavailable") from exc
        with iterator:
            for entry in iterator:
                if len(slot_ids) >= self._settings.maximum_retained_slots:
                    raise RuntimeSlotVerificationError("retained runtime slot ceiling exceeded")
                _require_slot_id(entry.name)
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise RuntimeSlotVerificationError("runtime slot is unavailable") from exc
                if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                    raise RuntimeSlotVerificationError("runtime slot entry type is unsupported")
                slot_ids.append(entry.name)
        return tuple(self.inspect_sync(slot_id) for slot_id in sorted(slot_ids))


class RetainedRuntimeSlotInspector:
    """Bind immutable filesystem material to atomic broker-owned lifecycle truth."""

    def __init__(
        self,
        material: FilesystemRuntimeSlotMaterialInspector,
        lifecycle: RuntimeSlotLifecycleReader,
    ) -> None:
        self._material = material
        self._lifecycle = lifecycle

    async def inspect(self, slot_id: str) -> VerifiedRuntimeSlot:
        material = await self._material.inspect(slot_id)
        retained = await self._lifecycle.get_runtime_slot(slot_id)
        if retained is None:
            raise RuntimeSlotVerificationError(
                "runtime slot has no authoritative lifecycle evidence"
            )
        return self._bind_lifecycle(material, retained)

    async def current(self) -> VerifiedRuntimeSlot | None:
        material = await self._material.current()
        return None if material is None else await self.inspect(material.slot_id)

    async def lkg(self) -> VerifiedRuntimeSlot | None:
        retained = await self._lifecycle.lkg_runtime_slot()
        if retained is None:
            return None
        material = await self._material.inspect(retained.slot_id)
        return self._bind_lifecycle(material, retained)

    @staticmethod
    def _bind_lifecycle(
        material: VerifiedRuntimeSlot,
        retained: VerifiedRuntimeSlot,
    ) -> VerifiedRuntimeSlot:
        rebound = replace(material, role=retained.role, state=retained.state)
        if rebound != retained:
            raise RuntimeSlotVerificationError(
                "runtime slot material differs from retained lifecycle evidence"
            )
        return retained


class FilesystemRuntimeSlotInspector(RetainedRuntimeSlotInspector):
    """Verify filesystem material under broker-authoritative mutable lifecycle truth."""

    def __init__(
        self,
        settings: RuntimeSlotInspectionSettings,
        lifecycle: RuntimeSlotLifecycleReader,
    ) -> None:
        super().__init__(FilesystemRuntimeSlotMaterialInspector(settings), lifecycle)


def _manifest_from_document(value: object) -> RuntimeSlotManifest:
    expected = {
        "candidate_verification_sha256",
        "completed_at",
        "config_sha256",
        "deployed_peer_set_sha256",
        "directories",
        "environment_sha256",
        "files",
        "format_version",
        "layout_sha256",
        "manifest_sha256",
        "migration_heads_sha256",
        "policy_sha256",
        "role",
        "service_definition_sha256",
        "slot_generation",
        "slot_id",
        "source_sha256",
        "state",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise RuntimeSlotVerificationError("runtime slot manifest fields are not exact")
    directories = value["directories"]
    files = value["files"]
    generation = value["slot_generation"]
    if (
        not isinstance(directories, list)
        or not all(isinstance(item, str) for item in directories)
        or not isinstance(files, list)
        or isinstance(generation, bool)
        or not isinstance(generation, int)
    ):
        raise RuntimeSlotVerificationError("runtime slot manifest shape is invalid")
    parsed_files: list[RuntimeSlotFile] = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"byte_count", "mode", "path", "sha256"}:
            raise RuntimeSlotVerificationError("runtime slot file fields are not exact")
        size = item["byte_count"]
        if isinstance(size, bool) or not isinstance(size, int):
            raise RuntimeSlotVerificationError("runtime slot file size is invalid")
        if not all(isinstance(item[name], str) for name in ("mode", "path", "sha256")):
            raise RuntimeSlotVerificationError("runtime slot file value is invalid")
        parsed_files.append(
            RuntimeSlotFile(
                path=item["path"],
                mode=item["mode"],
                byte_count=size,
                sha256=item["sha256"],
            )
        )
    text_fields = expected - {"directories", "files", "slot_generation"}
    if not all(isinstance(value[name], str) for name in text_fields):
        raise RuntimeSlotVerificationError("runtime slot manifest value is invalid")
    try:
        role = RuntimeSlotRole(value["role"])
        state = RuntimeSlotState(value["state"])
        completed_at = datetime.fromisoformat(value["completed_at"])
    except (TypeError, ValueError) as exc:
        raise RuntimeSlotVerificationError("runtime slot manifest enum or time is invalid") from exc
    manifest = RuntimeSlotManifest(
        format_version=value["format_version"],
        slot_id=value["slot_id"],
        slot_generation=generation,
        role=role,
        state=state,
        source_sha256=value["source_sha256"],
        environment_sha256=value["environment_sha256"],
        config_sha256=value["config_sha256"],
        policy_sha256=value["policy_sha256"],
        manifest_sha256=value["manifest_sha256"],
        service_definition_sha256=value["service_definition_sha256"],
        deployed_peer_set_sha256=value["deployed_peer_set_sha256"],
        migration_heads_sha256=value["migration_heads_sha256"],
        layout_sha256=value["layout_sha256"],
        candidate_verification_sha256=value["candidate_verification_sha256"],
        completed_at=completed_at,
        directories=tuple(directories),
        files=tuple(parsed_files),
    )
    if canonical_timestamp(manifest.completed_at) != value["completed_at"]:
        raise RuntimeSlotVerificationError("runtime slot completion time is not canonical")
    return manifest


def canonical_runtime_slot_manifest_bytes(manifest: RuntimeSlotManifest) -> bytes:
    document = {
        "candidate_verification_sha256": manifest.candidate_verification_sha256,
        "completed_at": canonical_timestamp(manifest.completed_at),
        "config_sha256": manifest.config_sha256,
        "deployed_peer_set_sha256": manifest.deployed_peer_set_sha256,
        "directories": list(manifest.directories),
        "environment_sha256": manifest.environment_sha256,
        "files": [
            {
                "byte_count": item.byte_count,
                "mode": item.mode,
                "path": item.path,
                "sha256": item.sha256,
            }
            for item in manifest.files
        ],
        "format_version": manifest.format_version,
        "layout_sha256": manifest.layout_sha256,
        "manifest_sha256": manifest.manifest_sha256,
        "migration_heads_sha256": manifest.migration_heads_sha256,
        "policy_sha256": manifest.policy_sha256,
        "role": manifest.role.value,
        "service_definition_sha256": manifest.service_definition_sha256,
        "slot_generation": manifest.slot_generation,
        "slot_id": manifest.slot_id,
        "source_sha256": manifest.source_sha256,
        "state": manifest.state.value,
    }
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _object_from_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate runtime slot manifest field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def _require_slot_id(value: str) -> None:
    if _SLOT_ID_RE.fullmatch(value) is None or ".." in value:
        raise RuntimeSlotVerificationError("runtime slot identity is invalid")


def _require_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise RuntimeSlotVerificationError("runtime slot path is invalid") from exc
    if (
        not value
        or encoded_length > 512
        or path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\0" in value
        or "\n" in value
    ):
        raise RuntimeSlotVerificationError("runtime slot path is invalid")


def _require_sha256(value: str, name: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise RuntimeSlotVerificationError(f"{name} digest is invalid")


def _lstat(path: Path, name: str) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise RuntimeSlotVerificationError(f"{name} is unavailable") from exc


def _identity_mode(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)


__all__ = [
    "DEFAULT_RUNTIME_ROOT",
    "RUNTIME_SLOT_MANIFEST",
    "FilesystemRuntimeSlotInspector",
    "FilesystemRuntimeSlotMaterialInspector",
    "RetainedRuntimeSlotInspector",
    "RuntimeSlotFile",
    "RuntimeSlotInspectionSettings",
    "RuntimeSlotLifecycleReader",
    "RuntimeSlotManifest",
    "RuntimeSlotVerificationError",
    "canonical_runtime_slot_manifest_bytes",
]
