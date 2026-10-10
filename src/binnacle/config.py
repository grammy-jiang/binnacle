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
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    ModelWrapValidatorHandler,
    PrivateAttr,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from binnacle.auto_background_shell import shell_policy_code

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

    _canonical_source: tuple[Path, ...] | None = PrivateAttr(default=None)
    _canonical_snapshot: tuple[Path, ...] | None = PrivateAttr(default=None)

    @property
    def allowed(self) -> tuple[Path, ...]:
        return (self.default_root, *self.extra_roots)

    @property
    def canonical_allowed(self) -> tuple[Path, ...]:
        """Bind root aliases on first use; symlink retargeting is not new authority.

        A model field mutation intentionally defines new root configuration and
        invalidates the snapshot. Changing a symlink without changing the
        configured path does not. Factory settings are copied independently.
        """
        configured = self.allowed
        if self._canonical_snapshot is None or configured != self._canonical_source:
            resolved = tuple(root.expanduser().resolve() for root in configured)
            self._canonical_snapshot = resolved
            self._canonical_source = configured
        return self._canonical_snapshot


class AuthSettings(BaseModel):
    token_file: Path = Field(
        default_factory=lambda: Path.home() / ".config" / "binnacle" / "token",
        description="Bearer token shared by the server, test client, and tunnel.",
    )


class ServeSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class TokenizerTelemetrySettings(BaseModel):
    """Optional model-tokenizer accounting in tool-result telemetry."""

    enabled: bool = Field(
        False,
        description="Count result payload tokens for matching clients.",
    )
    encoding: str = Field(
        "o200k_base",
        min_length=1,
        description="tiktoken encoding used for result-payload accounting.",
    )
    client_prefixes: tuple[str, ...] = Field(
        default=("openai-mcp",),
        min_length=1,
        description="Client-name prefixes whose results receive tokenizer counts.",
    )


class TelemetrySettings(BaseModel):
    tokenizer: TokenizerTelemetrySettings = Field(
        default_factory=TokenizerTelemetrySettings
    )


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

    exact_execution: Literal["materialized", "streaming"] = Field(
        "streaming",
        description="Exact-search ingestion backend; streaming is the optimized path.",
    )
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
    adaptive_discovery_enabled: bool = Field(
        False,
        description="Summarize broad budget-bound content searches by ranked file.",
    )
    adaptive_detailed_files: int = Field(30, ge=1, le=100)
    adaptive_total_files: int = Field(200, ge=1, le=1_000)
    adaptive_representative_matches: int = Field(2, ge=1, le=5)
    adaptive_snippet_chars: int = Field(180, ge=40, le=1_000)

    @model_validator(mode="after")
    def validate_adaptive_file_counts(self) -> "SearchTextSettings":
        if self.adaptive_total_files < self.adaptive_detailed_files:
            raise ValueError(
                "search_text.adaptive_total_files must be >= adaptive_detailed_files"
            )
        return self


class EditFileSettings(BaseModel):
    snippet_context_lines: int = 4


@dataclass(frozen=True)
class AutoBackgroundMatch:
    client_prefix: str
    pattern: str
    match_start: int
    match_end: int


# Sections of [run_command] that no longer exist. A host configuration that
# still has one keeps loading: the section is ignored and named once in a
# startup WARNING (event=config_warning). shadow_prediction: the run_command
# shadow-prediction experiment, removed 2026-09-27.
REMOVED_RUN_COMMAND_SECTIONS = ("shadow_prediction",)

# Top-level sections that no longer exist, handled the same way.
# indexed_context: the search_text '@context' indexed-discovery pilot, removed
# 2026-09-28 after its retrieval benchmark failed (docs/indexed-context-pilot.md).
REMOVED_SECTIONS = ("indexed_context",)

# Keys of [jobs] that no longer exist, handled the same way.
# blocking_wall_budget_s_by_client: the chat-mode scheduling v2 blocking-wall
# guard, never enabled on this host, removed 2026-09-27.
REMOVED_JOBS_KEYS = ("blocking_wall_budget_s_by_client",)


class RunCommandSettings(BaseModel):
    """run_command wait policy (spec docs/tools/run_command.md §3)."""

    wait_default_s: int = 30
    wait_max_s: int = Field(
        50, description="Below ChatGPT's hard 60 s client cap (design §5)."
    )
    auto_background_patterns: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description=(
            "Client-name PREFIX -> regexes that make matching commands use the "
            "background warm-up when the caller omits background."
        ),
    )
    auto_background_evidence_retention_days: int = Field(
        0,
        ge=0,
        le=365,
        description=(
            "Days to retain private full-command evidence for automatic-background "
            "matches; 0 disables evidence capture."
        ),
    )
    auto_background_evidence_dir: Path = Field(
        default_factory=lambda: (
            Path.home() / ".local" / "state" / "binnacle" / "run-command-evidence"
        ),
        description="Private local evidence directory for automatic-background matches.",
    )

    _removed_sections: tuple[str, ...] = PrivateAttr(default=())

    @model_validator(mode="wrap")
    @classmethod
    def _drop_removed_sections(
        cls,
        data: Any,
        handler: ModelWrapValidatorHandler["RunCommandSettings"],
    ) -> "RunCommandSettings":
        if isinstance(data, cls):
            return handler(data)
        removed: tuple[str, ...] = ()
        if isinstance(data, Mapping):
            removed = tuple(
                name for name in REMOVED_RUN_COMMAND_SECTIONS if name in data
            )
            if removed:
                data = {k: v for k, v in data.items() if k not in removed}
        model = handler(data)
        model._removed_sections = removed
        return model

    @property
    def removed_sections(self) -> tuple[str, ...]:
        """Removed [run_command] sections the configuration still has."""
        return self._removed_sections

    @model_validator(mode="after")
    def validate_auto_background_patterns(self) -> "RunCommandSettings":
        for client, patterns in self.auto_background_patterns.items():
            if not client:
                raise ValueError(
                    "run_command.auto_background_patterns keys must be non-empty"
                )
            for pattern in patterns:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ValueError(
                        f"invalid run_command auto-background regex for {client!r}: {pattern!r}"
                    ) from exc
        return self

    def match_auto_background(
        self, client: str | None, command: str
    ) -> AutoBackgroundMatch | None:
        if not client:
            return None
        for prefix, patterns in self.auto_background_patterns.items():
            if client.startswith(prefix):
                # Avoid shell lexing when no configured regex matches the
                # original source. This is the common fast path.
                searchable: str | None = None
                for pattern in patterns:
                    if re.search(pattern, command) is None:
                        continue
                    # Here-doc data and comments are not executable shell
                    # commands. Keep offsets for the existing evidence log.
                    if searchable is None:
                        searchable = shell_policy_code(command)
                    matched = re.search(pattern, searchable)
                    if matched is not None:
                        start, end = matched.span()
                        return AutoBackgroundMatch(prefix, pattern, start, end)
                return None
        return None

    def should_auto_background(self, client: str | None, command: str) -> bool:
        return self.match_auto_background(client, command) is not None


class JobsSettings(BaseModel):
    """Disk-backed job store and local ownership backend."""

    owner: Literal["auto", "embedded", "manager"] = Field(
        "auto",
        description=(
            "Process owner for run_command jobs. auto uses the manager in a "
            "binnacle-setup managed deployment and embedded otherwise; explicit "
            "embedded remains the rollback/test path."
        ),
    )
    socket_path: Path | None = Field(
        None,
        description="Private AF_UNIX socket for binnacle-jobs.service; resolved at Linux host composition.",
    )
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

    _removed_keys: tuple[str, ...] = PrivateAttr(default=())

    @model_validator(mode="wrap")
    @classmethod
    def _drop_removed_keys(
        cls,
        data: Any,
        handler: ModelWrapValidatorHandler["JobsSettings"],
    ) -> "JobsSettings":
        if isinstance(data, cls):
            return handler(data)
        removed: tuple[str, ...] = ()
        if isinstance(data, Mapping):
            removed = tuple(name for name in REMOVED_JOBS_KEYS if name in data)
            if removed:
                data = {k: v for k, v in data.items() if k not in removed}
        model = handler(data)
        model._removed_keys = removed
        return model

    @property
    def removed_keys(self) -> tuple[str, ...]:
        """Removed [jobs] keys the configuration still has."""
        return self._removed_keys


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BINNACLE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    roots: RootsSettings = Field(default_factory=RootsSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    serve: ServeSettings = Field(default_factory=ServeSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)
    read_file: ReadFileSettings = Field(default_factory=ReadFileSettings)
    list_files: ListFilesSettings = Field(default_factory=ListFilesSettings)
    search_text: SearchTextSettings = Field(default_factory=SearchTextSettings)
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

    _removed_sections: tuple[str, ...] = PrivateAttr(default=())

    @model_validator(mode="wrap")
    @classmethod
    def _drop_removed_sections(
        cls,
        data: Any,
        handler: ModelWrapValidatorHandler["Settings"],
    ) -> "Settings":
        if isinstance(data, cls):
            return handler(data)
        removed: tuple[str, ...] = ()
        if isinstance(data, Mapping):
            removed = tuple(name for name in REMOVED_SECTIONS if name in data)
            if removed:
                data = {k: v for k, v in data.items() if k not in removed}
        model = handler(data)
        model._removed_sections = removed
        return model

    @property
    def removed_sections(self) -> tuple[str, ...]:
        """Removed top-level sections the configuration still has."""
        return self._removed_sections

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
    """Compose the configured native default when building a host application."""
    settings = Settings()
    if settings.jobs.socket_path is None:
        from binnacle.platform.composition import create_runtime_paths

        settings.jobs.socket_path = create_runtime_paths().jobs_socket
    return settings
