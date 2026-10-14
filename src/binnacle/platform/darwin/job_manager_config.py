"""Manager configuration: the ``binnacle.config`` keys the job manager reads.

Split from ``job_manager_entry`` (MS1); behavior unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

CONFIG_FILE_ENV = "BINNACLE_CONFIG_FILE"
# env_nested_delimiter overrides, and the runtime root the client would not share
_OVERRIDES = ("BINNACLE_JOBS__", "BINNACLE_RUN_COMMAND__", "BINNACLE_RUNTIME_DIR")


class _Jobs(BaseModel):
    socket_path: Path | None = None
    dir: Path = Field(
        default_factory=lambda: Path.home() / ".local" / "state" / "binnacle" / "jobs"
    )
    keep_newest: int = Field(50, ge=1)
    maintenance_fence_dir: Path | None = None


class _RunCommand(BaseModel):
    wait_max_s: int = 50


class ManagerConfig(BaseSettings):
    """The ``binnacle.config`` keys the manager needs, from the config file only.

    Layering forbids ``binnacle.platform`` importing ``binnacle.config`` (the
    top-level acyclic contract), so these keys and defaults are restated with
    the same TOML source and pinned to ``Settings`` by tests.
    """

    model_config = SettingsConfigDict(extra="ignore")

    jobs: _Jobs = Field(default_factory=_Jobs)
    run_command: _RunCommand = Field(default_factory=_RunCommand)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        default = Path.home() / ".config" / "binnacle" / "config.toml"
        toml_file = Path(os.environ.get(CONFIG_FILE_ENV, default))
        return (TomlConfigSettingsSource(settings_cls, toml_file=toml_file),)


def read_config() -> ManagerConfig:
    """Refuse environment overrides: the config file is the only input."""
    if any(name.startswith(_OVERRIDES) for name in os.environ):
        raise ValueError("job manager settings come from the config file only")
    return ManagerConfig()
