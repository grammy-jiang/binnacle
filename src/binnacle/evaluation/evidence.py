"""Safe evidence storage and manifest-inventory verification."""

from __future__ import annotations

import os
import re
import secrets
import stat
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from binnacle.evaluation.digests import sha256_bytes
from binnacle.evaluation.redaction import MAX_EVIDENCE_BYTES, validate_sanitized_evidence

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_INFORMATION_CLASSES = frozenset({"normal-result", "restricted-result"})


@dataclass(frozen=True, slots=True)
class EvidenceFile:
    """One exact sanitized payload included by the evaluation manifest."""

    evidence_id: str
    path: str
    sha256: str
    media_type: str
    information_class: str
    redacted: bool = True

    def as_manifest_value(self) -> dict[str, object]:
        """Return the exact schema-facing evidence inventory object."""

        return {
            "evidence_id": self.evidence_id,
            "path": self.path,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "information_class": self.information_class,
            "redacted": self.redacted,
        }


class EvidenceStore:
    """Write-once evidence payloads rooted under ``workspace/evidence``."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.evidence_root = self.workspace / "evidence"
        self.evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _require_private_evidence_root(self.evidence_root)

    def add_bytes(
        self,
        *,
        evidence_id: str,
        relative_path: str,
        data: bytes,
        media_type: str,
        information_class: str,
        human_reviewed: bool = False,
    ) -> EvidenceFile:
        """Validate and atomically add one sanitized payload without overwriting."""

        _validate_evidence_id(evidence_id)
        relative = _evidence_relative_path(relative_path)
        if information_class not in _INFORMATION_CLASSES:
            raise ValueError("unknown evidence information class")
        if not media_type or len(media_type) > 256:
            raise ValueError("evidence media type is invalid")
        validate_sanitized_evidence(
            data,
            media_type=media_type,
            human_reviewed=human_reviewed,
        )
        parent_descriptor = _open_evidence_parent(
            self.evidence_root,
            relative.parts[:-1],
            create=True,
        )
        temporary_name = f".evidence-{secrets.token_hex(12)}"
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_descriptor,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(
                    temporary_name,
                    relative.name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise FileExistsError("evidence payload already exists") from exc
            os.fsync(parent_descriptor)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            os.close(parent_descriptor)
        return EvidenceFile(
            evidence_id=evidence_id,
            path=f"evidence/{relative.as_posix()}",
            sha256=sha256_bytes(data),
            media_type=media_type,
            information_class=information_class,
        )


def validate_evidence_inventory(
    workspace: Path,
    records: list[Mapping[str, Any]],
    *,
    binary_human_reviewed: bool = False,
) -> tuple[EvidenceFile, ...]:
    """Resolve, re-scan, and re-hash every manifest evidence record."""

    root = workspace.resolve()
    _require_private_evidence_root(root / "evidence")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    validated: list[EvidenceFile] = []
    for record in records:
        evidence_id = record.get("evidence_id")
        path_value = record.get("path")
        digest = record.get("sha256")
        media_type = record.get("media_type")
        information_class = record.get("information_class")
        redacted = record.get("redacted")
        if not isinstance(evidence_id, str):
            raise ValueError("evidence_id is missing")
        _validate_evidence_id(evidence_id)
        if not isinstance(path_value, str) or not path_value.startswith("evidence/"):
            raise ValueError("evidence path must be under evidence/")
        relative = _evidence_relative_path(path_value.removeprefix("evidence/"))
        normalized_path = f"evidence/{relative.as_posix()}"
        if evidence_id in seen_ids or normalized_path in seen_paths:
            raise ValueError("evidence inventory contains duplicate IDs or paths")
        seen_ids.add(evidence_id)
        seen_paths.add(normalized_path)
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("evidence digest is invalid")
        if not isinstance(media_type, str) or not isinstance(information_class, str):
            raise ValueError("evidence metadata is invalid")
        if information_class not in _INFORMATION_CLASSES or redacted is not True:
            raise ValueError("evidence is not marked redacted with a known class")
        data = read_evidence_payload(root / "evidence", relative)
        if sha256_bytes(data) != digest:
            raise ValueError("evidence payload digest mismatch")
        validate_sanitized_evidence(
            data,
            media_type=media_type,
            human_reviewed=binary_human_reviewed,
        )
        validated.append(
            EvidenceFile(
                evidence_id=evidence_id,
                path=normalized_path,
                sha256=digest,
                media_type=media_type,
                information_class=information_class,
            )
        )
    return tuple(validated)


def read_evidence_payload(evidence_root: Path, relative: PurePosixPath) -> bytes:
    """Read one bounded payload through no-follow directory descriptors."""

    _evidence_relative_path(relative.as_posix())
    parent_descriptor: int | None = None
    descriptor: int | None = None
    try:
        parent_descriptor = _open_evidence_parent(
            evidence_root,
            relative.parts[:-1],
            create=False,
        )
        descriptor = os.open(
            relative.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 0 <= metadata.st_size <= MAX_EVIDENCE_BYTES:
            raise ValueError("evidence payload is missing, unsafe, or unbounded")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            data = source.read(MAX_EVIDENCE_BYTES + 1)
        if len(data) > MAX_EVIDENCE_BYTES:
            raise ValueError("evidence payload is unbounded")
        return data
    except OSError as exc:
        raise ValueError("evidence payload is missing or not a regular file") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _open_evidence_parent(
    root: Path,
    parts: tuple[str, ...],
    *,
    create: bool,
) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current = os.open(root, flags)
    try:
        for part in parts:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=current)
            following = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = following
        return current
    except OSError as exc:
        os.close(current)
        raise ValueError("evidence parent path is unsafe") from exc
    except BaseException:
        os.close(current)
        raise


def _require_private_evidence_root(path: Path) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError("evidence directory is missing or unsafe") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ValueError("evidence directory must be private and owned by the evaluator")


def _validate_evidence_id(value: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("evidence_id is not a canonical identifier")


def _evidence_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or "." in path.parts
        or any(not part or part.startswith(".") for part in path.parts)
        or len(path.as_posix()) > 240
    ):
        raise ValueError("evidence path is unsafe")
    return path


__all__ = [
    "EvidenceFile",
    "EvidenceStore",
    "read_evidence_payload",
    "validate_evidence_inventory",
]
