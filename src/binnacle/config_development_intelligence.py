"""Strict opt-in configuration for the future Development Intelligence child.

P2.0 is configuration-only: no tool registration, provider discovery, process
creation, workspace probing, or safety/READ permission derives from this model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

FEATURE_SECTION = "development_intelligence"
FEATURE_ENV_PREFIX = "BINNACLE_DEVELOPMENT_INTELLIGENCE__"

ProviderName = Literal[
    "pyright",
    "typescript",
    "clangd",
    "rust_analyzer",
    "marksman",
    "bash",
    "make",
    "yaml",
    "json",
]
ProviderSource = Literal["service_path", "trusted_absolute"]
ProviderMode = Literal["benchmark_only", "explicit_trust_only"]


def feature_section_near_miss(key: str) -> bool:
    """Catch feature table/env typos without changing other legacy settings."""
    normalized = key.casefold().replace("-", "_")
    if normalized == FEATURE_SECTION:
        return False
    return bool(get_close_matches(normalized, [FEATURE_SECTION], n=1, cutoff=0.77))


def reject_feature_near_misses(
    data: Mapping[str, Any], known_fields: Mapping[str, Any], environ: Mapping[str, str]
) -> None:
    """Feature-only unknown section guard, preserving legacy foreign keys."""
    top_level = sorted(
        str(key)
        for key in data
        if key not in known_fields and feature_section_near_miss(str(key))
    )
    env_keys = sorted(
        name
        for name in environ
        if name.startswith("BINNACLE_")
        and feature_section_near_miss(name.removeprefix("BINNACLE_").split("__", 1)[0])
    )
    if top_level or env_keys:
        raise ValueError(
            "unknown development_intelligence-like config: "
            + ", ".join((*top_level, *env_keys))
        )


def _boolean_fields(data: Any, keys: tuple[str, ...]) -> Any:
    """Accept only TOML bools or canonical 'true'/'false' env strings."""
    if not isinstance(data, Mapping):
        return data
    values = dict(data)
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value in ("true", "false"):
            values[key] = value == "true"
    return values


class DevelopmentProviderSettings(BaseModel):
    """Inert provider declaration; binaries are NOT resolved at config load."""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    source: ProviderSource = "service_path"
    executable: str | None = Field(default=None, max_length=4096)
    argv: tuple[str, ...] = Field(default=(), max_length=64)
    env: dict[str, str] = Field(default_factory=dict, max_length=32)
    languages: tuple[str, ...] = Field(default=(), max_length=16)
    mode: ProviderMode = "benchmark_only"

    @model_validator(mode="before")
    @classmethod
    def _normalise_env_bool(cls, data: Any) -> Any:
        return _boolean_fields(data, ("enabled",))

    @model_validator(mode="after")
    def validate_profile(self) -> DevelopmentProviderSettings:
        if self.source == "service_path":
            if self.executable is not None and not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.executable
            ):
                raise ValueError("service_path executable must be a bare name")
        elif (
            self.executable is None
            or not Path(self.executable).is_absolute()
            or "\x00" in self.executable
        ):
            raise ValueError("trusted_absolute executable must be an absolute path")
        if self.source == "trusted_absolute" and self.mode != "explicit_trust_only":
            raise ValueError("trusted_absolute requires explicit_trust_only mode")
        if any("\x00" in arg for arg in self.argv):
            raise ValueError("provider argv must not contain NUL bytes")
        if any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
            or key
            in {
                "PATH",
                "PYTHONPATH",
                "NODE_PATH",
                "LD_PRELOAD",
                "DYLD_INSERT_LIBRARIES",
            }
            or "\x00" in value
            for key, value in self.env.items()
        ):
            raise ValueError("provider env overrides contain forbidden keys/values")
        if any(
            re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name) is None
            for name in self.languages
        ):
            raise ValueError("provider languages must be explicit stable identifiers")
        return self


class DevelopmentIntelligenceSettings(BaseModel):
    """Disabled default, validated even if not mounted or in active use."""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    discovery_enabled: StrictBool = False
    max_resident_servers: int = Field(default=2, ge=1, le=8, strict=True)
    request_timeout_s: float = Field(default=30.0, gt=0, le=120)
    idle_timeout_s: float = Field(default=120.0, ge=0, le=3600)
    profiles: dict[ProviderName, DevelopmentProviderSettings] = Field(
        default_factory=dict, max_length=16
    )

    @model_validator(mode="before")
    @classmethod
    def _normalise_env_bools(cls, data: Any) -> Any:
        values = _boolean_fields(data, ("enabled", "discovery_enabled"))
        if isinstance(values, dict):
            count = values.get("max_resident_servers")
            if isinstance(count, str) and re.fullmatch(r"[1-9][0-9]*", count):
                values["max_resident_servers"] = int(count)
        return values

    @model_validator(mode="after")
    def validate_enablement(self) -> DevelopmentIntelligenceSettings:
        if self.discovery_enabled and not self.enabled:
            raise ValueError(
                "development_intelligence.discovery_enabled requires enabled=true"
            )
        return self
