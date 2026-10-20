"""Telemetry configuration; full capture is explicitly opt-in per host."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class FullCaptureSettings(BaseModel):
    """Capture complete MCP middleware requests and results to private files."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    directory: Path = Field(
        default_factory=lambda: (
            Path.home() / ".local" / "state" / "binnacle" / "full-capture"
        )
    )
    fsync: bool = False

    @model_validator(mode="after")
    def validate_directory(self) -> "FullCaptureSettings":
        if self.enabled and not self.directory.expanduser().is_absolute():
            raise ValueError("telemetry.full_capture.directory must be absolute")
        return self


class TelemetrySettings(BaseModel):
    tokenizer: TokenizerTelemetrySettings = Field(
        default_factory=TokenizerTelemetrySettings
    )
    full_capture: FullCaptureSettings = Field(default_factory=FullCaptureSettings)
