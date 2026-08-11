"""Immutable Phase 1 settings and source precedence."""

from __future__ import annotations

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
    """HTTP server settings with fail-closed unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: Literal[1] = 1


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
