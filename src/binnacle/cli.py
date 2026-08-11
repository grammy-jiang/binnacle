"""Typer/Rich delivery adapter for the Phase 1 skeleton."""

from __future__ import annotations

import asyncio
import json
import sys
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from binnacle import distribution_version
from binnacle.adapters.mcp import run_http_server
from binnacle.composition import compose_application
from binnacle.config import BinnacleSettings, load_settings
from binnacle.domain.runtime import PackageIdentity

app = typer.Typer(help="Binnacle executable project skeleton.", no_args_is_help=True)
config_app = typer.Typer(help="Validate Binnacle configuration.")
app.add_typer(config_app, name="config")


class OutputMode(StrEnum):
    """Supported CLI rendering intentions."""

    HUMAN = "human"
    AGENT = "agent"
    JSON = "json"


def _identity() -> PackageIdentity:
    return PackageIdentity(distribution_name="binnacle", version=distribution_version())


def _render_identity(identity: PackageIdentity, output: OutputMode) -> None:
    if output is OutputMode.JSON:
        typer.echo(
            json.dumps(
                {
                    "distribution_name": identity.distribution_name,
                    "version": identity.version,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    elif output is OutputMode.AGENT:
        typer.echo(f"distribution_name={identity.distribution_name} version={identity.version}")
    else:
        Console(file=sys.stdout, color_system=None).print(
            f"[bold]Binnacle[/bold] {identity.version}"
        )


def _render_valid_settings(settings: BinnacleSettings, output: OutputMode) -> None:
    if output is OutputMode.JSON:
        typer.echo(
            json.dumps(
                {
                    "runtime_profile": settings.runtime_profile,
                    "server": settings.server.model_dump(),
                    "status": "valid",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    elif output is OutputMode.AGENT:
        typer.echo(
            "status=valid "
            f"runtime_profile={settings.runtime_profile} "
            f"host={settings.server.host} port={settings.server.port} "
            f"workers={settings.server.workers}"
        )
    else:
        Console(file=sys.stdout, color_system=None).print(
            f"[green]Configuration valid[/green]: {settings.server.host}:{settings.server.port}"
        )


def _load_or_exit(
    *,
    config_path: Path | None,
    cli_overrides: dict[str, object] | None = None,
) -> BinnacleSettings:
    try:
        return load_settings(config_path=config_path, cli_overrides=cli_overrides)
    except ValidationError as exc:
        typer.echo(f"Configuration error: {_safe_validation_summary(exc)}", err=True)
        raise typer.Exit(code=2) from exc
    except tomllib.TOMLDecodeError as exc:
        typer.echo("Configuration error: invalid TOML syntax", err=True)
        raise typer.Exit(code=2) from exc
    except OSError as exc:
        typer.echo("Configuration error: configuration file could not be read", err=True)
        raise typer.Exit(code=2) from exc


def _safe_validation_summary(error: ValidationError) -> str:
    """Render locations and reasons without echoing untrusted input values."""

    summaries: list[str] = []
    for detail in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = ".".join(str(part) for part in detail["loc"]) or "configuration"
        summaries.append(f"{location}: {detail['msg']}")
    return "; ".join(summaries)


@app.command("version")
def version_command(
    output: Annotated[
        OutputMode,
        typer.Option("--output", help="Output intention."),
    ] = OutputMode.HUMAN,
) -> None:
    """Report package identity without inspecting host state."""

    _render_identity(_identity(), output)


@config_app.command("validate")
def config_validate_command(
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Explicit TOML configuration path."),
    ] = None,
    output: Annotated[
        OutputMode,
        typer.Option("--output", help="Output intention."),
    ] = OutputMode.HUMAN,
) -> None:
    """Validate settings without mutating any file."""

    _render_valid_settings(_load_or_exit(config_path=config_path), output)


@app.command("serve")
def serve_command(
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Explicit TOML configuration path."),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option("--host", help="Explicit HTTP bind host."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", min=1, max=65535, help="Explicit HTTP bind port."),
    ] = None,
) -> None:
    """Start the zero-tool FastMCP HTTP skeleton."""

    server_overrides: dict[str, object] = {}
    if host is not None:
        server_overrides["host"] = host
    if port is not None:
        server_overrides["port"] = port
    cli_overrides: dict[str, object] | None = None
    if server_overrides:
        cli_overrides = {"server": server_overrides}

    settings = _load_or_exit(config_path=config_path, cli_overrides=cli_overrides)
    composed = compose_application(settings=settings)
    try:
        run_http_server(application=composed.application, settings=settings.server)
    finally:
        asyncio.run(composed.close())


def main() -> None:
    """Invoke the canonical Typer application."""

    app()
