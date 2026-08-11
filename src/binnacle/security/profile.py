"""Strict common configuration for a selected controller security profile."""

from __future__ import annotations

import grp
import ipaddress
import os
import re
import stat
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from binnacle.domain.controller import ControllerProfileKind, ControllerProfileSummary

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_PROFILE_BYTES = 65_536


class ControllerProfileProtectionError(ValueError):
    """The security-critical profile file has unsafe ownership or permissions."""


class ControllerBoundaryProfile(BaseModel):
    """Non-secret common fields frozen before a concrete auth adapter is wired."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(min_length=1, max_length=160)
    profile_version: str = Field(min_length=1, max_length=64)
    kind: ControllerProfileKind
    canonical_resource_uri: str = Field(min_length=1, max_length=2048)
    required_scopes: frozenset[str] = Field(min_length=1, max_length=32)
    allowed_hosts: tuple[str, ...] = Field(min_length=1, max_length=32)
    allowed_origins: tuple[str, ...] = Field(default=(), max_length=32)
    allow_missing_origin: bool = False
    clock_skew_seconds: int = Field(default=60, ge=0, le=300)

    @field_validator("profile_id")
    @classmethod
    def _validate_profile_id(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("profile_id is not a canonical identifier")
        return value

    @field_validator("profile_version")
    @classmethod
    def _validate_profile_version(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("profile_version is not a canonical identifier")
        return value

    @field_validator("required_scopes")
    @classmethod
    def _validate_scopes(cls, value: frozenset[str]) -> frozenset[str]:
        if any(_SCOPE.fullmatch(scope) is None or "*" in scope for scope in value):
            raise ValueError("required_scopes contains a non-canonical scope")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def _validate_hosts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            normalized.append(_normalize_authority(value))
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_hosts contains duplicates")
        return tuple(normalized)

    @field_validator("allowed_origins")
    @classmethod
    def _validate_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("allowed_origins contains a non-canonical HTTPS origin")
            normalized.append(f"https://{_normalize_authority(parsed.netloc)}")
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_origins contains duplicates")
        return tuple(normalized)

    @model_validator(mode="after")
    def _validate_resource_uri(self) -> ControllerBoundaryProfile:
        parsed = urlsplit(self.canonical_resource_uri)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/mcp"
            or parsed.query
            or parsed.fragment
            or parsed.netloc.casefold() not in self.allowed_hosts
            or self.canonical_resource_uri != f"https://{parsed.netloc.casefold()}/mcp"
        ):
            raise ValueError("canonical_resource_uri must be an allowed exact HTTPS /mcp URI")
        return self

    def summary(self) -> ControllerProfileSummary:
        """Return the safe subset supplied to authentication/authorization code."""

        return ControllerProfileSummary(
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            kind=self.kind,
            required_scopes=self.required_scopes,
            canonical_resource_uri=self.canonical_resource_uri,
        )


def load_controller_boundary_profile(
    path: Path,
    *,
    require_protected: bool = True,
) -> ControllerBoundaryProfile:
    """Load a protected TOML profile without consulting environment variables."""

    descriptor = _open_profile_file(path, require_protected=require_protected)
    with os.fdopen(descriptor, "rb") as profile_file:
        values = tomllib.load(profile_file)
    return ControllerBoundaryProfile.model_validate(values)


def _open_profile_file(path: Path, *, require_protected: bool) -> int:
    """Open the checked inode itself so a path swap cannot redirect the read."""

    descriptor: int | None = None
    try:
        path_metadata = path.stat(follow_symlinks=False)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise ControllerProfileProtectionError(
            "controller profile protection is unavailable"
        ) from exc
    try:
        if (
            path_metadata.st_dev != metadata.st_dev
            or path_metadata.st_ino != metadata.st_ino
            or not stat.S_ISREG(metadata.st_mode)
            or not 0 <= metadata.st_size <= _MAX_PROFILE_BYTES
        ):
            raise ControllerProfileProtectionError("controller profile file is unsafe")
        if require_protected:
            try:
                expected_group = grp.getgrnam("binnacle").gr_gid
            except KeyError as exc:
                raise ControllerProfileProtectionError(
                    "controller profile protection is unavailable"
                ) from exc
            mode = stat.S_IMODE(metadata.st_mode)
            if metadata.st_uid != 0 or metadata.st_gid != expected_group or mode & ~0o640:
                raise ControllerProfileProtectionError(
                    "controller profile file is not root:binnacle 0640"
                )
    except (OSError, ControllerProfileProtectionError):
        os.close(descriptor)
        raise
    return descriptor


def _normalize_authority(value: str) -> str:
    if (
        not value
        or len(value) > 255
        or not value.isascii()
        or any(not 0x21 <= ord(character) < 0x7F for character in value)
    ):
        raise ValueError("authority is not bounded canonical ASCII")
    parsed = urlsplit(f"https://{value}/")
    if (
        parsed.netloc != value
        or parsed.path != "/"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
    ):
        raise ValueError("authority is not a canonical host and optional port")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("authority port is invalid") from exc
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("authority port is invalid")
    hostname = parsed.hostname.casefold()
    if ":" in hostname:
        try:
            normalized_host = f"[{ipaddress.IPv6Address(hostname).compressed}]"
        except ipaddress.AddressValueError as exc:
            raise ValueError("authority IPv6 address is invalid") from exc
    else:
        if (
            len(hostname) > 253
            or hostname.endswith(".")
            or any(_DNS_LABEL.fullmatch(label) is None for label in hostname.split("."))
        ):
            raise ValueError("authority host name is invalid")
        normalized_host = hostname
    return f"{normalized_host}:{port}" if port is not None else normalized_host


__all__ = [
    "ControllerBoundaryProfile",
    "ControllerProfileProtectionError",
    "load_controller_boundary_profile",
]
