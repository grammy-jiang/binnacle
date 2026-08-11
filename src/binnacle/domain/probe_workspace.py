"""Deterministic values for the bounded Phase 5 write-capability probe."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

MAX_PROBE_FILE_BYTES: Final = 65_536
EMPTY_TERMINAL_HISTORY_SHA256: Final = hashlib.sha256(b"[]").hexdigest()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


class ProbeWorkspaceError(ValueError):
    """A probe request or retained probe fact is outside the frozen contract."""


class ProbeOperationKind(StrEnum):
    WRITE = "write"
    CLEANUP = "cleanup"


class ProbeArtifactState(StrEnum):
    RESERVED = "reserved"
    CREATED = "created"
    REMOVED = "removed"
    ABANDONED = "abandoned"
    UNCERTAIN = "uncertain"


class ProbeTargetState(StrEnum):
    ABSENT = "absent"
    EXACT = "exact"
    MISMATCH = "mismatch"


@dataclass(frozen=True, slots=True)
class ProbeRootIdentity:
    digest_sha256: str
    device: int
    inode: int
    owner_uid: int
    owner_gid: int
    mode: int


@dataclass(frozen=True, slots=True)
class ProbeFileObservation:
    state: ProbeTargetState
    file_identity_digest: str | None = None
    content_sha256: str | None = None
    byte_count: int | None = None


@dataclass(frozen=True, slots=True)
class ProbePathLedger:
    relative_path: str
    generation_high_water: int
    terminal_history_count: int
    terminal_history_sha256: str
    active_artifact_id: str | None
    active_generation: int | None
    active_create_operation_id: str | None
    ledger_version: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProbeArtifact:
    artifact_id: str
    relative_path: str
    path_generation: int
    owner_controller_id: str
    owner_controller_epoch: int
    content_sha256: str
    byte_count: int
    state: ProbeArtifactState
    create_operation_id: str
    active_cleanup_operation_id: str | None
    removed_by_cleanup_operation_id: str | None
    created_at: datetime
    updated_at: datetime
    removed_at: datetime | None = None
    file_identity_digest: str | None = None


@dataclass(frozen=True, slots=True)
class ProbePathSnapshot:
    ledger: ProbePathLedger
    terminal_artifacts: tuple[ProbeArtifact, ...]
    active_artifact: ProbeArtifact | None


@dataclass(frozen=True, slots=True)
class ProbeOperationRecord:
    operation_id: str
    probe_operation: ProbeOperationKind
    prepared_binding_id: str
    caller_binding_id: str
    artifact_id: str
    relative_path: str
    expected_content_sha256: str
    expected_byte_count: int | None
    prepared_state_binding_sha256: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProbePreparedState:
    operation: ProbeOperationKind
    relative_path: str
    content_sha256: str
    byte_count: int | None
    artifact_id: str | None
    owner_controller_id: str
    owner_controller_epoch: int
    root_identity_sha256: str
    ledger_version: int
    generation_high_water: int
    terminal_history_count: int
    terminal_history_sha256: str
    active_artifact_id: str | None
    active_generation: int | None
    active_create_operation_id: str | None
    write_reservation_transition: str | None
    cleanup_target_transition: str | None
    cleanup_claim_transition: str | None
    expected_file_identity_digest: str | None


def normalize_probe_path(raw_path: str) -> str:
    """Return the exact one-component NFC path permitted by Phase 5."""

    if not isinstance(raw_path, str) or not raw_path:
        raise ProbeWorkspaceError("probe path must be a non-empty string")
    if unicodedata.normalize("NFC", raw_path) != raw_path:
        raise ProbeWorkspaceError("probe path must already be NFC-normalized")
    if raw_path in {".", "..", ".staging"} or raw_path.startswith(".binnacle-"):
        raise ProbeWorkspaceError("probe path is reserved")
    if any(character in raw_path for character in ("/", "\\", ":", "\0", "\r", "\n")):
        raise ProbeWorkspaceError("probe path must be exactly one safe filename component")
    try:
        encoded = raw_path.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ProbeWorkspaceError("probe path is not valid UTF-8") from exc
    if len(encoded) > 255:
        raise ProbeWorkspaceError("probe filename exceeds 255 UTF-8 bytes")
    return raw_path


def validate_probe_identifier(value: str, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ProbeWorkspaceError(f"{name} is not a bounded identifier")
    return value


def validate_sha256(value: str, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProbeWorkspaceError(f"{name} is not lowercase SHA-256")
    return value


def decode_probe_content(
    *,
    text: str | None,
    encoded_base64: str | None,
    maximum_bytes: int = MAX_PROBE_FILE_BYTES,
) -> bytes:
    """Decode exactly one content representation under the structural limit."""

    if maximum_bytes < 1 or maximum_bytes > MAX_PROBE_FILE_BYTES:
        raise ProbeWorkspaceError("probe maximum byte limit is outside the frozen bound")
    if (text is None) == (encoded_base64 is None):
        raise ProbeWorkspaceError("exactly one of text or base64 is required")
    if text is not None:
        try:
            content = text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ProbeWorkspaceError("probe text is not valid UTF-8") from exc
    else:
        assert encoded_base64 is not None
        try:
            content = base64.b64decode(encoded_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ProbeWorkspaceError("probe base64 content is invalid") from exc
    if len(content) > maximum_bytes:
        raise ProbeWorkspaceError("decoded probe content exceeds the configured limit")
    return content


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def prepared_input_sha256(
    *,
    operation: ProbeOperationKind,
    relative_path: str,
    expected_content_sha256: str,
    byte_count: int | None,
    artifact_id: str | None,
) -> str:
    return canonical_sha256(
        {
            "artifact_id": artifact_id,
            "byte_count": byte_count,
            "content_sha256": validate_sha256(expected_content_sha256, name="content_sha256"),
            "operation": operation.value,
            "relative_path": normalize_probe_path(relative_path),
        }
    )


def maximum_effect_sha256(
    *, operation: ProbeOperationKind, maximum_bytes: int = MAX_PROBE_FILE_BYTES
) -> str:
    if maximum_bytes < 1 or maximum_bytes > MAX_PROBE_FILE_BYTES:
        raise ProbeWorkspaceError("maximum effect exceeds the frozen probe bound")
    effect = (
        {"create_regular_file_count": 1, "decoded_bytes_max": maximum_bytes, "overwrite": False}
        if operation is ProbeOperationKind.WRITE
        else {"exact_artifact_absence_count": 1, "recursive": False}
    )
    return canonical_sha256(
        {"operation": operation.value, "root": "protected-probe-workspace", **effect}
    )


def target_identity_sha256(root_identity_sha256: str, relative_path: str) -> str:
    return canonical_sha256(
        {
            "relative_path": normalize_probe_path(relative_path),
            "root_identity_sha256": validate_sha256(
                root_identity_sha256, name="root_identity_sha256"
            ),
        }
    )


def operation_fingerprint_sha256(
    *,
    operation: ProbeOperationKind,
    prepared_operation_id: str,
    prepared_input_sha256: str,
    relative_path: str,
    expected_content_sha256: str,
    byte_count: int | None,
    artifact_id: str | None,
    target_identity_digest: str,
    maximum_effect_digest: str,
) -> str:
    return canonical_sha256(
        {
            "artifact_id": artifact_id,
            "byte_count": byte_count,
            "content_sha256": validate_sha256(expected_content_sha256, name="content_sha256"),
            "contract_version": "1.1",
            "maximum_effect_sha256": validate_sha256(
                maximum_effect_digest, name="maximum_effect_sha256"
            ),
            "operation": operation.value,
            "overwrite": False if operation is ProbeOperationKind.WRITE else None,
            "prepared_input_sha256": validate_sha256(
                prepared_input_sha256, name="prepared_input_sha256"
            ),
            "prepared_operation_id": validate_probe_identifier(
                prepared_operation_id, name="prepared_operation_id"
            ),
            "relative_path": normalize_probe_path(relative_path),
            "target_identity_sha256": validate_sha256(
                target_identity_digest, name="target_identity_sha256"
            ),
            "tool_name": f"probe_workspace_{operation.value}",
        }
    )


def terminal_history_sha256(artifacts: Sequence[ProbeArtifact]) -> str:
    ordered = sorted(artifacts, key=lambda artifact: artifact.path_generation)
    return canonical_sha256([terminal_artifact_projection(artifact) for artifact in ordered])


def terminal_artifact_projection(artifact: ProbeArtifact) -> Mapping[str, object]:
    if artifact.state not in {ProbeArtifactState.REMOVED, ProbeArtifactState.ABANDONED}:
        raise ProbeWorkspaceError("non-terminal artifact cannot enter terminal history")
    return {
        "active_cleanup_operation_id": artifact.active_cleanup_operation_id,
        "artifact_id": artifact.artifact_id,
        "byte_count": artifact.byte_count,
        "content_sha256": artifact.content_sha256,
        "create_operation_id": artifact.create_operation_id,
        "created_at": _timestamp(artifact.created_at),
        "file_identity_digest": artifact.file_identity_digest,
        "owner_controller_epoch": artifact.owner_controller_epoch,
        "owner_controller_id": artifact.owner_controller_id,
        "path_generation": artifact.path_generation,
        "relative_path": artifact.relative_path,
        "removed_at": None if artifact.removed_at is None else _timestamp(artifact.removed_at),
        "removed_by_cleanup_operation_id": artifact.removed_by_cleanup_operation_id,
        "state": artifact.state.value,
    }


def validate_path_snapshot(snapshot: ProbePathSnapshot) -> None:
    """Verify the independently anchored path history without repairing it."""

    ledger = snapshot.ledger
    normalize_probe_path(ledger.relative_path)
    if ledger.ledger_version < 1 or ledger.generation_high_water < 0:
        raise ProbeWorkspaceError("probe ledger version/high-water is invalid")
    if ledger.terminal_history_count < 0:
        raise ProbeWorkspaceError("probe terminal history count is invalid")
    validate_sha256(ledger.terminal_history_sha256, name="terminal_history_sha256")
    terminal = tuple(sorted(snapshot.terminal_artifacts, key=lambda item: item.path_generation))
    for expected_generation, artifact in enumerate(terminal, start=1):
        _validate_artifact(artifact, ledger.relative_path)
        if artifact.path_generation != expected_generation:
            raise ProbeWorkspaceError("probe terminal history is not contiguous")
        if artifact.state not in {ProbeArtifactState.REMOVED, ProbeArtifactState.ABANDONED}:
            raise ProbeWorkspaceError("probe terminal history contains a live artifact")
        if artifact.active_cleanup_operation_id is not None:
            raise ProbeWorkspaceError("terminal probe artifact retains a cleanup claim")
    if len(terminal) != ledger.terminal_history_count:
        raise ProbeWorkspaceError("probe terminal history count disagrees with ledger")
    if terminal_history_sha256(terminal) != ledger.terminal_history_sha256:
        raise ProbeWorkspaceError("probe terminal history digest disagrees with ledger")

    active = snapshot.active_artifact
    active_fields = (
        ledger.active_artifact_id,
        ledger.active_generation,
        ledger.active_create_operation_id,
    )
    if active is None:
        if any(value is not None for value in active_fields):
            raise ProbeWorkspaceError("probe ledger has incomplete active ownership")
        if ledger.terminal_history_count != ledger.generation_high_water:
            raise ProbeWorkspaceError("stable probe ledger high-water is inconsistent")
        return
    _validate_artifact(active, ledger.relative_path)
    if any(value is None for value in active_fields):
        raise ProbeWorkspaceError("probe ledger active ownership is incomplete")
    if active.path_generation != ledger.generation_high_water:
        raise ProbeWorkspaceError("active probe generation is not the high-water")
    if ledger.terminal_history_count != active.path_generation - 1:
        raise ProbeWorkspaceError("active probe generation has incomplete prior history")
    if (
        ledger.active_artifact_id != active.artifact_id
        or ledger.active_generation != active.path_generation
        or ledger.active_create_operation_id != active.create_operation_id
    ):
        raise ProbeWorkspaceError("active probe ownership disagrees with ledger")
    if active.state in {ProbeArtifactState.REMOVED, ProbeArtifactState.ABANDONED}:
        raise ProbeWorkspaceError("terminal artifact cannot be ledger-active")


def prepared_state_sha256(state: ProbePreparedState) -> str:
    return canonical_sha256(
        {
            "active_artifact_id": state.active_artifact_id,
            "active_create_operation_id": state.active_create_operation_id,
            "active_generation": state.active_generation,
            "artifact_id": state.artifact_id,
            "byte_count": state.byte_count,
            "cleanup_claim_transition": state.cleanup_claim_transition,
            "cleanup_target_transition": state.cleanup_target_transition,
            "content_sha256": state.content_sha256,
            "expected_file_identity_digest": state.expected_file_identity_digest,
            "generation_high_water": state.generation_high_water,
            "ledger_version": state.ledger_version,
            "operation": state.operation.value,
            "owner_controller_epoch": state.owner_controller_epoch,
            "owner_controller_id": state.owner_controller_id,
            "relative_path": state.relative_path,
            "root_identity_sha256": state.root_identity_sha256,
            "terminal_history_count": state.terminal_history_count,
            "terminal_history_sha256": state.terminal_history_sha256,
            "write_reservation_transition": state.write_reservation_transition,
        }
    )


def _validate_artifact(artifact: ProbeArtifact, expected_path: str) -> None:
    validate_probe_identifier(artifact.artifact_id, name="artifact_id")
    if artifact.relative_path != expected_path or artifact.path_generation < 1:
        raise ProbeWorkspaceError("probe artifact path/generation is invalid")
    validate_probe_identifier(artifact.owner_controller_id, name="owner_controller_id")
    validate_probe_identifier(artifact.create_operation_id, name="create_operation_id")
    if artifact.active_cleanup_operation_id is not None:
        validate_probe_identifier(
            artifact.active_cleanup_operation_id,
            name="active_cleanup_operation_id",
        )
    if artifact.removed_by_cleanup_operation_id is not None:
        validate_probe_identifier(
            artifact.removed_by_cleanup_operation_id,
            name="removed_by_cleanup_operation_id",
        )
    if artifact.owner_controller_epoch < 1:
        raise ProbeWorkspaceError("probe artifact owner is invalid")
    validate_sha256(artifact.content_sha256, name="content_sha256")
    if not 0 <= artifact.byte_count <= MAX_PROBE_FILE_BYTES:
        raise ProbeWorkspaceError("probe artifact byte count is invalid")
    if artifact.file_identity_digest is not None:
        validate_sha256(artifact.file_identity_digest, name="file_identity_digest")
    if artifact.updated_at < artifact.created_at or (
        artifact.removed_at is not None
        and (artifact.removed_at < artifact.created_at or artifact.updated_at < artifact.removed_at)
    ):
        raise ProbeWorkspaceError("probe artifact timestamps are not monotonic")

    if artifact.state in {ProbeArtifactState.RESERVED, ProbeArtifactState.UNCERTAIN}:
        exact_shape = (
            artifact.file_identity_digest is None
            and artifact.active_cleanup_operation_id is None
            and artifact.removed_by_cleanup_operation_id is None
            and artifact.removed_at is None
        )
    elif artifact.state is ProbeArtifactState.CREATED:
        exact_shape = (
            artifact.file_identity_digest is not None
            and artifact.removed_by_cleanup_operation_id is None
            and artifact.removed_at is None
        )
    elif artifact.state is ProbeArtifactState.REMOVED:
        exact_shape = (
            artifact.file_identity_digest is not None
            and artifact.active_cleanup_operation_id is None
            and artifact.removed_at is not None
        )
    else:
        exact_shape = (
            artifact.file_identity_digest is None
            and artifact.active_cleanup_operation_id is None
            and artifact.removed_by_cleanup_operation_id is None
            and artifact.removed_at is not None
        )
    if not exact_shape:
        raise ProbeWorkspaceError("probe artifact state shape is inconsistent")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _normalize(value: object) -> object:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {str(key): _normalize(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize(child) for child in value]
    return value


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = [
    "EMPTY_TERMINAL_HISTORY_SHA256",
    "MAX_PROBE_FILE_BYTES",
    "ProbeArtifact",
    "ProbeArtifactState",
    "ProbeFileObservation",
    "ProbeOperationKind",
    "ProbeOperationRecord",
    "ProbePathLedger",
    "ProbePathSnapshot",
    "ProbePreparedState",
    "ProbeRootIdentity",
    "ProbeTargetState",
    "ProbeWorkspaceError",
    "canonical_sha256",
    "content_sha256",
    "decode_probe_content",
    "maximum_effect_sha256",
    "normalize_probe_path",
    "operation_fingerprint_sha256",
    "prepared_input_sha256",
    "prepared_state_sha256",
    "target_identity_sha256",
    "terminal_history_sha256",
    "validate_path_snapshot",
    "validate_probe_identifier",
    "validate_sha256",
]
