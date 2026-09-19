"""Runtime configuration for binnacle (pydantic-settings).

One Settings object holds every tunable: the path roots, the token file,
serve defaults, and each tool's limits. Defaults reproduce the measured
ChatGPT constraints from docs/agent-toolset-design.md §5-§7; override them
per deployment, highest priority first:

1. environment variables -- prefix ``BINNACLE_``, nested with ``__``
   (``BINNACLE_SEARCH_TEXT__TIMEOUT_S=30``)
2. a TOML file at ``~/.config/binnacle/config.toml`` (or the path in
   ``BINNACLE_CONFIG_FILE``)
3. the defaults below

Modules read these values at import, so a change applies on the next
server start -- the same restart model the systemd deployment already has.
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

CONFIG_FILE_ENV = "BINNACLE_CONFIG_FILE"
DEFAULT_CONFIG_FILE = Path.home() / ".config" / "binnacle" / "config.toml"


class RootsSettings(BaseModel):
    """Where the file tools and run_command may operate (design §6.7)."""

    default_root: Path = Field(
        default_factory=lambda: Path.home() / "Projects",
        description="Relative paths resolve against this root.",
    )
    extra_roots: tuple[Path, ...] = Field(
        default=(Path("/tmp"),),
        description="Additional allowed roots beside default_root.",
    )

    @property
    def allowed(self) -> tuple[Path, ...]:
        return (self.default_root, *self.extra_roots)


class AuthSettings(BaseModel):
    token_file: Path = Field(
        default_factory=lambda: Path.home() / ".config" / "binnacle" / "token",
        description="Bearer token shared by the server, test client, and tunnel.",
    )


class ServeSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class ReadFileSettings(BaseModel):
    """read_file windowing (spec docs/tools/read_file.md)."""

    max_lines: int = Field(2_000, description="Line ceiling per call.")
    max_chars: int = Field(24_000, description="Content chars per call.")
    max_line_chars: int = Field(2_000, description="Per-line clip.")
    max_file_bytes: int = Field(20 * 1024 * 1024, description="Stat guard.")


class ListFilesSettings(BaseModel):
    """list_files caps (spec docs/tools/list_files.md)."""

    max_results_default: int = 200
    max_results_cap: int = 2_000
    rg_timeout_s: int = 20


class SearchTextSettings(BaseModel):
    """search_text caps and auto-context (spec docs/tools/search_text.md)."""

    max_results_default: int = 100
    max_results_cap: int = 1_000
    timeout_s: int = 20
    max_line_chars: int = 2_000
    result_max_bytes: int = Field(
        65_536,
        ge=4_096,
        description="Maximum UTF-8 bytes in one structured search result.",
    )
    auto_context_single: int = Field(
        50, description="Context lines each side for exactly 1 match."
    )
    auto_context_few: int = Field(15, description="For 2-3 matches.")


class IndexedContextSettings(BaseModel):
    """Development-pilot settings for ``search_text('@context ...')``."""

    enabled: bool = Field(
        False,
        description="Enable explicit @context indexed repository discovery.",
    )
    index_dir: Path = Field(
        default_factory=lambda: Path.home() / ".cache" / "binnacle" / "indexes",
        description="Persistent per-worktree SQLite index directory.",
    )
    relation_items: int = Field(8, ge=1, le=20)
    lexical_items: int = Field(2, ge=0, le=10)
    snippet_chars: int = Field(700, ge=120, le=4_000)
    package_max_bytes: int = Field(8_500, ge=2_000, le=32_000)
    max_open_indexes: int = Field(2, ge=1, le=16)
    reconcile_on_query: bool = Field(
        True,
        description="Reconcile the persistent index against the live worktree before each @context query.",
    )


class EditFileSettings(BaseModel):
    snippet_context_lines: int = 4


class RunCommandSettings(BaseModel):
    """run_command wait-not-kill bounds (spec docs/tools/run_command.md §3)."""

    wait_default_s: int = 30
    wait_max_s: int = Field(
        50, description="Below ChatGPT's hard 60 s client cap (design §5)."
    )


class JobsSettings(BaseModel):
    """Disk-backed job store (spec docs/tools/run_command.md §6)."""

    dir: Path = Field(
        default_factory=lambda: Path.home() / ".local" / "state" / "binnacle" / "jobs",
        description="Job spool; survives reloads.",
    )
    keep_newest: int = Field(
        50,
        ge=1,
        description="Base job-directory retention window; older running jobs are spared.",
    )
    listing_history_limit: int = Field(
        20, ge=0, description="Non-running jobs returned by a no-id job_status listing."
    )
    listing_command_preview_chars: int = Field(
        160,
        ge=40,
        description="Command source characters retained across head+tail listing previews.",
    )
    max_output_chars: int = Field(24_000, description="Head+tail clip per call.")
    warmup_s: float = Field(1.0, description="Wait before background return.")
    quiet_after_s: int = Field(
        30, description="A running job with no output this long is quiet=true."
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BINNACLE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    roots: RootsSettings = Field(default_factory=RootsSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    serve: ServeSettings = Field(default_factory=ServeSettings)
    read_file: ReadFileSettings = Field(default_factory=ReadFileSettings)
    list_files: ListFilesSettings = Field(default_factory=ListFilesSettings)
    search_text: SearchTextSettings = Field(default_factory=SearchTextSettings)
    indexed_context: IndexedContextSettings = Field(
        default_factory=IndexedContextSettings
    )
    edit_file: EditFileSettings = Field(default_factory=EditFileSettings)
    run_command: RunCommandSettings = Field(default_factory=RunCommandSettings)
    jobs: JobsSettings = Field(default_factory=JobsSettings)
    rg_bin: str = Field("rg", description="ripgrep binary for list/search.")
    client_tools: dict[str, tuple[str, ...]] = Field(
        default={
            "openai-mcp": (
                "read_file",
                "list_files",
                "search_text",
                "run_command",
                "job_status",
                "stop_job",
            ),
        },
        description=(
            "Client-name PREFIX -> the tools that client is served. A client "
            "matching no prefix gets every tool; a matching client gets "
            "exactly this list, so a new tool must be added here to reach it. "
            "ChatGPT edits via run_command scripts (measured 2026-09-02), so "
            "its structured edit tools are left off. ChatGPT identifies as "
            "'openai-mcp' on legacy sessions and 'openai-mcp(ChatGPT)' on "
            "modern discovery -- the prefix covers both."
        ),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml_file = Path(os.environ.get(CONFIG_FILE_ENV, DEFAULT_CONFIG_FILE))
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=toml_file),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
