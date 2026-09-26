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
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
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


@dataclass(frozen=True)
class AutoBackgroundMatch:
    client_prefix: str
    pattern: str
    match_start: int
    match_end: int


class RunCommandShadowPredictionSettings(BaseModel):
    enabled: bool = False
    predictors: tuple[Literal["memory", "rules", "judge"], ...] = ()
    memory_min_samples: int = Field(2, ge=1, le=100)
    memory_max_keys: int = Field(4096, ge=16, le=100_000)
    memory_samples_per_key: int = Field(32, ge=1, le=1024)
    memory_dir: Path = Field(
        default_factory=lambda: (
            Path.home() / ".local" / "state" / "binnacle" / "run-command-prediction"
        )
    )
    judge_enabled: bool = False
    judge_endpoint: str = "https://api.cerebras.ai/v1/chat/completions"
    judge_model: str = "gpt-oss-120b"
    judge_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    judge_timeout_ms: int = Field(800, ge=100, le=10_000)
    judge_minute_budget: int = Field(4, ge=0, le=5)
    judge_hour_budget: int = Field(120, ge=0, le=150)
    judge_day_budget: int = Field(2_000, ge=0, le=2_400)
    judge_cache_ttl_s: int = Field(86_400, ge=0, le=2_592_000)
    judge_complex_chain_threshold: int = Field(2, ge=0, le=100)
    judge_complex_length_threshold: int = Field(800, ge=1, le=100_000)
    sanitized_command_max_chars: int = Field(1200, ge=100, le=10_000)
    judge_workers: int = Field(2, ge=1, le=8)
    judge_api_key_file: Path | None = None


class JudgeBudget:
    """Process-local shadow-judge request budget."""

    def __init__(
        self,
        settings: RunCommandShadowPredictionSettings,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._events: list[float] = []
        self._paused_until = 0.0
        self._limits = (
            (60.0, settings.judge_minute_budget),
            (3600.0, settings.judge_hour_budget),
            (86400.0, settings.judge_day_budget),
        )

    def take(self) -> bool:
        now = self._clock()
        with self._lock:
            if now < self._paused_until:
                return False
            self._events = [stamp for stamp in self._events if now - stamp < 86400]
            for window_s, limit in self._limits:
                used = sum(now - stamp < window_s for stamp in self._events)
                if limit <= 0 or used >= limit:
                    return False
            self._events.append(now)
            return True

    def pause_for(self, seconds: float | None) -> None:
        delay = 60.0 if seconds is None else max(0.0, min(float(seconds), 86400.0))
        with self._lock:
            self._paused_until = max(self._paused_until, self._clock() + delay)


def run_command_cerebras_transport(
    url: str, headers: dict[str, str], body: bytes, timeout_s: float
) -> tuple[int, bytes, Mapping[str, str]]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # nosec B310
            return int(response.status), response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        response_headers = dict(exc.headers.items()) if exc.headers else {}
        return int(exc.code), exc.read(), response_headers


def run_command_cerebras_reset_seconds(headers: Mapping[str, str]) -> float:
    lowered = {str(key).lower(): str(value).strip() for key, value in headers.items()}
    value = lowered.get("retry-after") or lowered.get("x-ratelimit-reset-requests")
    if not value:
        return 60.0
    try:
        raw = float(value)
    except ValueError:
        units = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
        parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", value.lower())
        if not parts:
            return 60.0
        return max(0.0, sum(float(number) * units[unit] for number, unit in parts))
    if raw > 1_000_000_000:
        return max(0.0, raw - time.time())
    return max(0.0, raw)


def read_cerebras_api_key(settings: RunCommandShadowPredictionSettings) -> str:
    if key := os.environ.get("CEREBRAS_API_KEY"):
        return key
    path = settings.judge_api_key_file
    if path is None:
        raise RuntimeError("missing_api_key")
    if path.stat().st_mode & 0o777 != 0o600:
        raise RuntimeError("unsafe_key_file_mode")
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("missing_api_key")
    return key


class RunCommandSettings(BaseModel):
    """run_command wait policy (spec docs/tools/run_command.md §3)."""

    shadow_prediction: RunCommandShadowPredictionSettings = Field(
        default_factory=RunCommandShadowPredictionSettings
    )
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
                for pattern in patterns:
                    matched = re.search(pattern, command)
                    if matched is not None:
                        start, end = matched.span()
                        return AutoBackgroundMatch(prefix, pattern, start, end)
                return None
        return None

    def should_auto_background(self, client: str | None, command: str) -> bool:
        return self.match_auto_background(client, command) is not None


def _default_jobs_socket() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path(f"/run/user/{os.getuid()}")
    return base / "binnacle" / "jobs.sock"


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
    socket_path: Path = Field(
        default_factory=_default_jobs_socket,
        description="Private AF_UNIX socket for binnacle-jobs.service.",
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
    blocking_wall_budget_s_by_client: dict[str, int] = Field(
        default_factory=dict,
        description="Client-name PREFIX -> cumulative blocking-wall budget in seconds.",
    )

    @model_validator(mode="after")
    def validate_blocking_wall_budgets(self) -> "JobsSettings":
        for client, budget in self.blocking_wall_budget_s_by_client.items():
            if not client.strip():
                raise ValueError(
                    "jobs.blocking_wall_budget_s_by_client keys must be non-empty "
                    "and not whitespace-only"
                )
            if not 1 <= budget <= 3600:
                raise ValueError(
                    "jobs.blocking_wall_budget_s_by_client budgets must be in 1..3600"
                )
        return self

    def blocking_wall_budget_for_client(self, client: str | None) -> int | None:
        if client is None:
            return None
        matches = (
            prefix
            for prefix in self.blocking_wall_budget_s_by_client
            if client.startswith(prefix)
        )
        prefix = max(matches, key=len, default=None)
        if prefix is None:
            return None
        return self.blocking_wall_budget_s_by_client[prefix]


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
