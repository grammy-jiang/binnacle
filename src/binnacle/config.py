"""Immutable Phase 1 settings and source precedence."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class ServerSettings(BaseModel):
    """Bounded loopback HTTP server settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: Literal[1] = 1
    max_request_bytes: int = Field(default=1_048_576, ge=65_536, le=4_194_304)
    graceful_shutdown_seconds: float = Field(default=10.0, gt=0, le=60)
    filesystem_stat_timeout_seconds: float = Field(default=2.0, gt=0, le=10)


class LoggingSettings(BaseModel):
    """Ordinary diagnostic logging settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["console", "json"] = "console"


class BinnacleSettings(BaseSettings):
    """Immutable settings snapshot for the executable skeleton."""

    model_config = SettingsConfigDict(
        frozen=True,
        extra="forbid",
        env_prefix="BINNACLE_",
        env_nested_delimiter="__",
    )

    runtime_profile: Literal["development"] = "development"
    server: ServerSettings = Field(default_factory=ServerSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Give environment values priority over TOML-backed init values."""

        del cls, settings_cls, dotenv_settings, file_secret_settings
        return env_settings, init_settings


class EnvironmentNamespaceError(ValueError):
    """The reserved ``BINNACLE_*`` namespace contains an unknown setting name."""

    def __init__(self) -> None:
        super().__init__("unknown BINNACLE_* environment setting")


class _ExplicitSettings(BinnacleSettings):
    """Validate an already resolved snapshot without re-reading the environment."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del cls, settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)


def _merge_mappings(
    base: Mapping[str, object], override: Mapping[str, object]
) -> dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_mappings(current, value)
        else:
            merged[key] = value
    return merged


def _known_environment_names(
    model: type[BaseModel],
    *,
    path: tuple[str, ...] = (),
) -> frozenset[str]:
    return frozenset(
        ("BINNACLE_" + "__".join(field_path)).casefold()
        for field_path in _setting_field_paths(model, path=path)
    )


def setting_field_paths() -> frozenset[tuple[str, ...]]:
    """Return the finite model-owned paths safe to render in diagnostics."""

    return _setting_field_paths(BinnacleSettings)


def _setting_field_paths(
    model: type[BaseModel],
    *,
    path: tuple[str, ...] = (),
) -> frozenset[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for field_name, field in model.model_fields.items():
        field_path = (*path, field_name)
        paths.add(field_path)
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths.update(_setting_field_paths(annotation, path=field_path))
    return frozenset(paths)


def _validate_environment_namespace(environment: Mapping[str, str]) -> None:
    known = _known_environment_names(BinnacleSettings)
    if any(
        name.casefold().startswith("binnacle_") and name.casefold() not in known
        for name in environment
    ):
        raise EnvironmentNamespaceError


def load_settings(
    *,
    config_path: Path | None = None,
    cli_overrides: Mapping[str, object] | None = None,
) -> BinnacleSettings:
    """Load defaults, TOML, environment, then explicit CLI overrides."""

    toml_values: dict[str, object] = {}
    if config_path is not None:
        with config_path.open("rb") as config_file:
            toml_values = tomllib.load(config_file)

    _validate_environment_namespace(os.environ)

    # Collect every source as raw input first.  Validating an intermediate TOML/env
    # snapshot would incorrectly reject a lower-priority invalid value even when an
    # explicit CLI value replaces it.
    environment_values = EnvSettingsSource(BinnacleSettings)()
    values = _merge_mappings(toml_values, environment_values)
    if cli_overrides:
        values = _merge_mappings(values, cli_overrides)
    return _ExplicitSettings(
        **values  # type: ignore[arg-type]  # Pydantic validates the merged snapshot.
    )
