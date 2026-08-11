"""Protected, immutable Bootstrap development-workspace profile loading."""

from __future__ import annotations

import grp
import hashlib
import json
import math
import os
import re
import stat
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)

BOOTSTRAP_WORKSPACE_ROOT: Literal["/srv/binnacle-dev/repo"] = "/srv/binnacle-dev/repo"
DEFAULT_WORKSPACE_PROFILE_PATH = Path("/etc/binnacle/workspace-profile.toml")
RIPGREP_BINARY: Literal["/usr/bin/rg"] = "/usr/bin/rg"

_MAX_PROFILE_BYTES = 65_536
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_REQUIRED_RIPGREP_ARGUMENTS = (
    "--no-config",
    "--no-pre",
    "--no-search-zip",
    "--no-follow",
    "--json",
)
_RIPGREP_ENVIRONMENT = ("LANG=C", "LC_ALL=C")
_PROFILE_DIGEST_FORMAT = "binnacle-workspace-profile-v1"


class WorkspaceProfileProtectionError(ValueError):
    """The security-critical workspace profile file is not safely readable."""


class WorkspaceSearchProcessProfile(BaseModel):
    """Closed process-purity contract for the stdin-only ripgrep matcher."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    executable: Literal["/usr/bin/rg"] = RIPGREP_BINARY
    working_directory: Literal["/run/binnacle"] = "/run/binnacle"
    mandatory_arguments: tuple[StrictStr, ...] = _REQUIRED_RIPGREP_ARGUMENTS
    environment: tuple[StrictStr, ...] = _RIPGREP_ENVIRONMENT
    stdin_only: Literal[True] = True
    json_output: Literal[True] = True
    close_fds: Literal[True] = True
    shell: Literal[False] = False
    configuration_allowed: Literal[False] = False
    preprocessors_allowed: Literal[False] = False
    archive_search_allowed: Literal[False] = False
    helper_processes_allowed: Literal[False] = False
    workspace_discovery_authority: Literal[False] = False
    pcre2_allowed: Literal[False] = False

    @field_validator("mandatory_arguments")
    @classmethod
    def _validate_mandatory_arguments(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != _REQUIRED_RIPGREP_ARGUMENTS:
            raise ValueError("ripgrep mandatory arguments do not match the reviewed profile")
        return values

    @field_validator("environment")
    @classmethod
    def _validate_environment(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != _RIPGREP_ENVIRONMENT:
            raise ValueError("ripgrep environment does not match the closed allowlist")
        return values


@dataclass(frozen=True, slots=True)
class WorkspaceProfileSummary:
    """Bounded non-sensitive profile facts suitable for diagnostics and registration."""

    workspace_id: str
    profile_version: str
    profile_sha256: str
    enabled: bool
    root: str
    allow_out_of_band_writers: bool
    allow_submounts: bool
    require_mount_id_verification: bool
    move_enabled: bool
    delete_enabled: bool
    ripgrep_binary: str
    search_process_profile: str


class WorkspaceProfile(BaseModel):
    """Closed owner-controlled profile for the one Bootstrap source workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    workspace_id: StrictStr = Field(min_length=1, max_length=160)
    profile_version: StrictStr = Field(min_length=1, max_length=64)
    enabled: StrictBool = False
    root: Literal["/srv/binnacle-dev/repo"] = BOOTSTRAP_WORKSPACE_ROOT
    protected_prefixes: tuple[StrictStr, ...] = Field(
        default=(".git",),
        min_length=1,
        max_length=32,
    )

    max_path_bytes: StrictInt = Field(default=4_096, ge=1, le=4_096)
    max_path_depth: StrictInt = Field(default=64, ge=1, le=64)
    max_file_mutation_bytes: StrictInt = Field(
        default=4 * 1_024 * 1_024,
        ge=1,
        le=4 * 1_024 * 1_024,
    )
    max_read_chunk_bytes: StrictInt = Field(
        default=1_024 * 1_024,
        ge=1,
        le=1_024 * 1_024,
    )
    max_list_entries: StrictInt = Field(default=4_096, ge=1, le=4_096)
    max_search_files: StrictInt = Field(default=4_096, ge=1, le=4_096)
    max_search_open_fds: StrictInt = Field(default=4_096, ge=1, le=4_096)
    max_search_preflight_bytes: StrictInt = Field(
        default=64 * 1_024 * 1_024,
        ge=1,
        le=64 * 1_024 * 1_024,
    )
    max_search_matches: StrictInt = Field(default=2_000, ge=1, le=2_000)
    max_search_output_bytes: StrictInt = Field(
        default=1_024 * 1_024,
        ge=1,
        le=1_024 * 1_024,
    )
    search_timeout_seconds: StrictFloat = Field(default=5.0, gt=0.0, le=5.0)
    search_preflight_timeout_seconds: StrictFloat = Field(default=5.0, gt=0.0, le=5.0)

    allow_out_of_band_writers: StrictBool = False
    allow_submounts: Literal[False] = False
    require_mount_id_verification: Literal[True] = True
    move_enabled: StrictBool = False
    delete_enabled: StrictBool = False
    search_process: WorkspaceSearchProcessProfile = Field(
        default_factory=WorkspaceSearchProcessProfile
    )

    @field_validator("workspace_id")
    @classmethod
    def _validate_workspace_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("workspace_id is not a canonical identifier")
        return value

    @field_validator("profile_version")
    @classmethod
    def _validate_profile_version(cls, value: str) -> str:
        if _VERSION.fullmatch(value) is None:
            raise ValueError("profile_version is not a canonical version")
        return value

    @field_validator("protected_prefixes")
    @classmethod
    def _validate_protected_prefixes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(_protected_prefix(value) for value in values))
        if len(set(normalized)) != len(normalized):
            raise ValueError("protected_prefixes contains duplicates")
        if ".git" not in normalized:
            raise ValueError("protected_prefixes must include .git")
        for index, value in enumerate(normalized):
            if any(value.startswith(f"{parent}/") for parent in normalized[:index]):
                raise ValueError("protected_prefixes contains an overlapping descendant")
        return normalized

    @field_validator("search_timeout_seconds", "search_preflight_timeout_seconds", mode="before")
    @classmethod
    def _validate_timeouts(cls, value: object) -> object:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("workspace search timeout must be finite")
        return value

    def profile_sha256(self) -> str:
        """Return a deterministic digest of the complete effective profile semantics."""

        projection = {
            "format": _PROFILE_DIGEST_FORMAT,
            "profile": self.model_dump(mode="json"),
        }
        encoded = json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def summary(self) -> WorkspaceProfileSummary:
        """Return only fixed or non-sensitive facts; protected paths/env stay private."""

        return WorkspaceProfileSummary(
            workspace_id=self.workspace_id,
            profile_version=self.profile_version,
            profile_sha256=self.profile_sha256(),
            enabled=self.enabled,
            root=self.root,
            allow_out_of_band_writers=self.allow_out_of_band_writers,
            allow_submounts=self.allow_submounts,
            require_mount_id_verification=self.require_mount_id_verification,
            move_enabled=self.move_enabled,
            delete_enabled=self.delete_enabled,
            ripgrep_binary=self.search_process.executable,
            search_process_profile="stdin-json-no-helper-v1",
        )


def load_workspace_profile(
    path: Path = DEFAULT_WORKSPACE_PROFILE_PATH,
    *,
    require_protected: bool = True,
) -> WorkspaceProfile:
    """Load one descriptor-bound protected TOML profile without env/CLI merging."""

    descriptor = _open_profile_file(path, require_protected=require_protected)
    with os.fdopen(descriptor, "rb") as profile_file:
        values = tomllib.load(profile_file)
    return WorkspaceProfile.model_validate(values)


def _open_profile_file(path: Path, *, require_protected: bool) -> int:
    """Open and validate the checked inode itself so path swaps cannot redirect reads."""

    descriptor: int | None = None
    try:
        path_metadata = path.stat(follow_symlinks=False)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise WorkspaceProfileProtectionError(
            "workspace profile protection is unavailable"
        ) from exc
    try:
        if (
            path_metadata.st_dev != metadata.st_dev
            or path_metadata.st_ino != metadata.st_ino
            or not stat.S_ISREG(metadata.st_mode)
            or not 0 < metadata.st_size <= _MAX_PROFILE_BYTES
        ):
            raise WorkspaceProfileProtectionError("workspace profile file is unsafe")
        if require_protected:
            try:
                expected_group = grp.getgrnam("binnacle").gr_gid
            except KeyError as exc:
                raise WorkspaceProfileProtectionError(
                    "workspace profile protection is unavailable"
                ) from exc
            if (
                metadata.st_uid != 0
                or metadata.st_gid != expected_group
                or stat.S_IMODE(metadata.st_mode) != 0o640
            ):
                raise WorkspaceProfileProtectionError(
                    "workspace profile file is not root:binnacle mode 0640"
                )
    except (OSError, WorkspaceProfileProtectionError):
        os.close(descriptor)
        raise
    return descriptor


def _protected_prefix(value: str) -> str:
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("protected prefix must already be NFC-normalized")
    if (
        not value
        or value.startswith(("/", "\\"))
        or "\\" in value
        or any(character in value for character in ("\0", "\r", "\n"))
        or len(value.encode("utf-8")) > 512
    ):
        raise ValueError("protected prefix is not a bounded relative path")
    components = value.split("/")
    if (
        len(components) > 16
        or any(component in {"", ".", ".."} for component in components)
        or any(len(component.encode("utf-8")) > 255 for component in components)
        or (len(components[0]) >= 2 and components[0][1] == ":")
    ):
        raise ValueError("protected prefix has invalid path components")
    return value


__all__ = [
    "BOOTSTRAP_WORKSPACE_ROOT",
    "DEFAULT_WORKSPACE_PROFILE_PATH",
    "RIPGREP_BINARY",
    "WorkspaceProfile",
    "WorkspaceProfileProtectionError",
    "WorkspaceProfileSummary",
    "WorkspaceSearchProcessProfile",
    "load_workspace_profile",
]
