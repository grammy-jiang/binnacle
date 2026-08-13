"""Exact manifest verification for the independently installed broker runtime."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

DEFAULT_PRIVILEGED_INSTALL_ROOT: Final = Path("/opt/binnacle-privileged")
PRIVILEGED_ARTIFACT_MANIFEST: Final = "artifact-manifest.json"
_FORMAT_VERSION: Final = "binnacle-privileged-artifact-v1"
_MAX_MANIFEST_BYTES: Final = 1_048_576
_MAX_ENTRIES: Final = 4_096
_MAX_FILE_BYTES: Final = 134_217_728
_MAX_TOTAL_BYTES: Final = 536_870_912
_CHUNK_BYTES: Final = 1_048_576


class PrivilegedArtifactError(RuntimeError):
    """The installed root runtime differs from its reviewed immutable manifest."""


@dataclass(frozen=True, slots=True)
class PrivilegedArtifactFile:
    path: str
    mode: str
    byte_count: int
    sha256: str

    def __post_init__(self) -> None:
        _require_relative_path(self.path)
        if self.mode not in {"0644", "0755"}:
            raise PrivilegedArtifactError("privileged artifact file mode is unsupported")
        if not 0 <= self.byte_count <= _MAX_FILE_BYTES:
            raise PrivilegedArtifactError("privileged artifact file size is outside the limit")
        _require_sha256(self.sha256)


@dataclass(frozen=True, slots=True)
class PrivilegedArtifactManifest:
    format_version: str
    directories: tuple[str, ...]
    files: tuple[PrivilegedArtifactFile, ...]

    def __post_init__(self) -> None:
        if self.format_version != _FORMAT_VERSION:
            raise PrivilegedArtifactError("privileged artifact format is incompatible")
        if len(self.directories) + len(self.files) > _MAX_ENTRIES:
            raise PrivilegedArtifactError("privileged artifact entry limit exceeded")
        if self.directories != tuple(sorted(set(self.directories))):
            raise PrivilegedArtifactError("privileged artifact directories are not canonical")
        for path in self.directories:
            _require_relative_path(path)
        file_paths = tuple(item.path for item in self.files)
        if file_paths != tuple(sorted(set(file_paths))):
            raise PrivilegedArtifactError("privileged artifact files are not canonical")
        if set(self.directories) & set(file_paths):
            raise PrivilegedArtifactError("privileged artifact path has two kinds")
        if PRIVILEGED_ARTIFACT_MANIFEST in file_paths:
            raise PrivilegedArtifactError("privileged manifest may not inventory itself")
        if sum(item.byte_count for item in self.files) > _MAX_TOTAL_BYTES:
            raise PrivilegedArtifactError("privileged artifact total size exceeds the limit")

    @property
    def build_sha256(self) -> str:
        return hashlib.sha256(_canonical_manifest_bytes(self)).hexdigest()


@dataclass(frozen=True, slots=True)
class PrivilegedArtifactVerificationSettings:
    root: Path = DEFAULT_PRIVILEGED_INSTALL_ROOT
    expected_owner_uid: int = 0
    expected_owner_gid: int = 0
    require_fixed_root: bool = True

    def __post_init__(self) -> None:
        if self.require_fixed_root and self.root != DEFAULT_PRIVILEGED_INSTALL_ROOT:
            raise PrivilegedArtifactError("privileged artifact root is not the protected path")
        if (
            not self.root.is_absolute()
            or self.root != Path(os.path.normpath(str(self.root)))
            or min(self.expected_owner_uid, self.expected_owner_gid) < 0
        ):
            raise PrivilegedArtifactError("privileged artifact verification settings are invalid")


def verify_privileged_artifact(
    *,
    expected_build_sha256: str,
    settings: PrivilegedArtifactVerificationSettings | None = None,
) -> PrivilegedArtifactManifest:
    """Verify one exact root-owned tree without changing any installed path."""

    _require_sha256(expected_build_sha256)
    settings = settings or PrivilegedArtifactVerificationSettings()
    _verify_root(settings)

    manifest = _load_manifest(settings)
    if manifest.build_sha256 != expected_build_sha256:
        raise PrivilegedArtifactError("privileged artifact build digest differs")
    observed_directories, observed_files = _enumerate_tree(settings)
    if observed_directories != manifest.directories:
        raise PrivilegedArtifactError("privileged artifact directory set differs")
    if observed_files != tuple(item.path for item in manifest.files):
        raise PrivilegedArtifactError("privileged artifact file set differs")
    for item in manifest.files:
        _verify_file(settings, item)
    return manifest


def write_privileged_artifact_manifest(
    *,
    settings: PrivilegedArtifactVerificationSettings,
) -> PrivilegedArtifactManifest:
    """Create one new canonical manifest in an unprivileged staging tree."""

    if settings.require_fixed_root or settings.root == DEFAULT_PRIVILEGED_INSTALL_ROOT:
        raise PrivilegedArtifactError("authoritative installed artifacts may not be self-blessed")
    _verify_root(settings)
    manifest_path = settings.root / PRIVILEGED_ARTIFACT_MANIFEST
    try:
        manifest_path.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise PrivilegedArtifactError("privileged staging manifest is unavailable") from exc
    else:
        raise PrivilegedArtifactError("privileged staging manifest already exists")
    directories, file_paths = _enumerate_tree(settings)
    manifest = PrivilegedArtifactManifest(
        format_version=_FORMAT_VERSION,
        directories=directories,
        files=tuple(_describe_file(settings, path) for path in file_paths),
    )
    content = _canonical_manifest_bytes(manifest) + b"\n"
    if len(content) > _MAX_MANIFEST_BYTES:
        raise PrivilegedArtifactError("privileged artifact manifest exceeds the limit")
    descriptor = -1
    created = False
    try:
        descriptor = os.open(
            manifest_path,
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o644,
        )
        created = True
        os.fchmod(descriptor, 0o644)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("manifest write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        root_descriptor = os.open(
            settings.root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(root_descriptor)
        finally:
            os.close(root_descriptor)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if created:
            with suppress(OSError):
                manifest_path.unlink()
        raise PrivilegedArtifactError("privileged staging manifest could not be published") from exc
    return manifest


def _verify_root(settings: PrivilegedArtifactVerificationSettings) -> None:
    root_metadata = _lstat(settings.root, "privileged artifact root")
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_ISLNK(root_metadata.st_mode)
        or _identity_mode(root_metadata)
        != (
            settings.expected_owner_uid,
            settings.expected_owner_gid,
            0o755,
        )
    ):
        raise PrivilegedArtifactError("privileged artifact root ownership or mode is unsafe")


def _load_manifest(
    settings: PrivilegedArtifactVerificationSettings,
) -> PrivilegedArtifactManifest:
    path = settings.root / PRIVILEGED_ARTIFACT_MANIFEST
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
            != (settings.expected_owner_uid, settings.expected_owner_gid, 0o644)
            or not 1 <= metadata.st_size <= _MAX_MANIFEST_BYTES
        ):
            raise PrivilegedArtifactError("privileged artifact manifest is unsafe")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(_MAX_MANIFEST_BYTES + 1)
    except PrivilegedArtifactError:
        raise
    except OSError as exc:
        raise PrivilegedArtifactError("privileged artifact manifest is unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise PrivilegedArtifactError("privileged artifact manifest exceeds the limit")
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_constant,
        )
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise PrivilegedArtifactError("privileged artifact manifest is invalid JSON") from exc
    manifest = _manifest_from_document(document)
    if raw != _canonical_manifest_bytes(manifest) + b"\n":
        raise PrivilegedArtifactError("privileged artifact manifest bytes are not canonical")
    return manifest


def _manifest_from_document(value: object) -> PrivilegedArtifactManifest:
    if not isinstance(value, dict) or set(value) != {"directories", "files", "format_version"}:
        raise PrivilegedArtifactError("privileged artifact manifest fields are not exact")
    format_version = value["format_version"]
    directories = value["directories"]
    files = value["files"]
    if (
        not isinstance(format_version, str)
        or not isinstance(directories, list)
        or not isinstance(files, list)
        or len(directories) + len(files) > _MAX_ENTRIES
        or not all(isinstance(item, str) for item in directories)
    ):
        raise PrivilegedArtifactError("privileged artifact manifest shape is invalid")
    parsed_files: list[PrivilegedArtifactFile] = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"byte_count", "mode", "path", "sha256"}:
            raise PrivilegedArtifactError("privileged artifact file fields are not exact")
        byte_count = item["byte_count"]
        if isinstance(byte_count, bool) or not isinstance(byte_count, int):
            raise PrivilegedArtifactError("privileged artifact file size is invalid")
        if not all(isinstance(item[name], str) for name in ("mode", "path", "sha256")):
            raise PrivilegedArtifactError("privileged artifact file value is invalid")
        parsed_files.append(
            PrivilegedArtifactFile(
                path=item["path"],
                mode=item["mode"],
                byte_count=byte_count,
                sha256=item["sha256"],
            )
        )
    return PrivilegedArtifactManifest(
        format_version=format_version,
        directories=tuple(directories),
        files=tuple(parsed_files),
    )


def _enumerate_tree(
    settings: PrivilegedArtifactVerificationSettings,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    directories: list[str] = []
    files: list[str] = []
    pending: list[tuple[Path, PurePosixPath | None]] = [(settings.root, None)]
    entries_seen = 0
    while pending:
        directory, relative_parent = pending.pop()
        try:
            iterator = os.scandir(directory)
        except OSError as exc:
            raise PrivilegedArtifactError("privileged artifact tree is unavailable") from exc
        with iterator:
            for entry in iterator:
                entries_seen += 1
                if entries_seen > _MAX_ENTRIES + 1:
                    raise PrivilegedArtifactError("privileged artifact entry limit exceeded")
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
                    raise PrivilegedArtifactError(
                        "privileged artifact entry is unavailable"
                    ) from exc
                if stat.S_ISLNK(metadata.st_mode):
                    raise PrivilegedArtifactError("privileged artifact contains a symlink")
                if stat.S_ISDIR(metadata.st_mode):
                    if _identity_mode(metadata) != (
                        settings.expected_owner_uid,
                        settings.expected_owner_gid,
                        0o755,
                    ):
                        raise PrivilegedArtifactError(
                            "privileged artifact directory ownership or mode is unsafe"
                        )
                    directories.append(relative_text)
                    pending.append((Path(entry.path), relative))
                elif stat.S_ISREG(metadata.st_mode):
                    if relative_text != PRIVILEGED_ARTIFACT_MANIFEST:
                        files.append(relative_text)
                else:
                    raise PrivilegedArtifactError("privileged artifact entry type is unsupported")
    return tuple(sorted(directories)), tuple(sorted(files))


def _verify_file(
    settings: PrivilegedArtifactVerificationSettings,
    expected: PrivilegedArtifactFile,
) -> None:
    mode, byte_count, digest = _file_facts(settings, expected.path)
    if mode != expected.mode or byte_count != expected.byte_count or digest != expected.sha256:
        raise PrivilegedArtifactError("privileged artifact file identity differs")


def _describe_file(
    settings: PrivilegedArtifactVerificationSettings,
    path: str,
) -> PrivilegedArtifactFile:
    mode, byte_count, digest = _file_facts(settings, path)
    return PrivilegedArtifactFile(
        path=path,
        mode=mode,
        byte_count=byte_count,
        sha256=digest,
    )


def _file_facts(
    settings: PrivilegedArtifactVerificationSettings,
    path: str,
) -> tuple[str, int, str]:
    descriptor = -1
    try:
        descriptor = os.open(
            settings.root / path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != settings.expected_owner_uid
            or metadata.st_gid != settings.expected_owner_gid
            or mode not in {0o644, 0o755}
            or not 0 <= metadata.st_size <= _MAX_FILE_BYTES
        ):
            raise PrivilegedArtifactError("privileged artifact file identity differs")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, _CHUNK_BYTES):
            digest.update(chunk)
        return f"{mode:04o}", metadata.st_size, digest.hexdigest()
    except PrivilegedArtifactError:
        raise
    except OSError as exc:
        raise PrivilegedArtifactError("privileged artifact file is unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _canonical_manifest_bytes(manifest: PrivilegedArtifactManifest) -> bytes:
    document = {
        "directories": list(manifest.directories),
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
    }
    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _object_from_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate privileged artifact manifest field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def _require_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise PrivilegedArtifactError("privileged artifact path is invalid") from exc
    if (
        not value
        or encoded_length > 512
        or path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\0" in value
        or "\n" in value
    ):
        raise PrivilegedArtifactError("privileged artifact path is invalid")


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise PrivilegedArtifactError("privileged artifact SHA-256 digest is invalid")


def _lstat(path: Path, name: str) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise PrivilegedArtifactError(f"{name} is unavailable") from exc


def _identity_mode(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)


__all__ = [
    "DEFAULT_PRIVILEGED_INSTALL_ROOT",
    "PRIVILEGED_ARTIFACT_MANIFEST",
    "PrivilegedArtifactError",
    "PrivilegedArtifactFile",
    "PrivilegedArtifactManifest",
    "PrivilegedArtifactVerificationSettings",
    "verify_privileged_artifact",
    "write_privileged_artifact_manifest",
]
