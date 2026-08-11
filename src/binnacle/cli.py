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
from pydantic_settings import SettingsError
from rich.console import Console

from binnacle import distribution_version
from binnacle.adapters.mcp import run_http_server
from binnacle.adapters.sqlite.engine import DatabaseRuntimeSettings
from binnacle.adapters.sqlite.migrations import upgrade_database
from binnacle.adapters.verification import (
    KernelVerificationPaths,
    verify_database_read_only,
    verify_operation_kernel_read_only,
)
from binnacle.application.reconciliation import (
    AuditObligationClosure,
    AuditRecoveryService,
)
from binnacle.composition import compose_application, compose_operation_kernel
from binnacle.config import (
    BinnacleSettings,
    EnvironmentNamespaceError,
    load_settings,
    setting_field_paths,
)
from binnacle.domain.runtime import PackageIdentity

app = typer.Typer(help="Binnacle executable project skeleton.", no_args_is_help=True)
config_app = typer.Typer(help="Validate Binnacle configuration.")
database_app = typer.Typer(help="Manage the stopped-service durable database.")
kernel_app = typer.Typer(help="Verify the internal durable-operation kernel.")
audit_app = typer.Typer(help="Verify or explicitly recover the local audit journal.")
app.add_typer(config_app, name="config")
app.add_typer(database_app, name="db")
app.add_typer(kernel_app, name="kernel")
app.add_typer(audit_app, name="audit")


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
    except EnvironmentNamespaceError as exc:
        typer.echo("Configuration error: unknown BINNACLE_* environment setting", err=True)
        raise typer.Exit(code=2) from exc
    except SettingsError as exc:
        typer.echo(f"Configuration error: {_safe_settings_error_summary(exc)}", err=True)
        raise typer.Exit(code=2) from exc
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
        location = _safe_validation_location(detail["loc"])
        summaries.append(f"{location}: {detail['msg']}")
    return "; ".join(summaries)


def _safe_validation_location(location: tuple[int | str, ...]) -> str:
    """Render only model-owned path segments, never source-controlled keys."""

    normalized = tuple(str(part) for part in location)
    known_paths = setting_field_paths()
    if normalized in known_paths:
        return ".".join(normalized)
    safe_prefix = max(
        (
            path
            for path in known_paths
            if len(path) < len(normalized) and normalized[: len(path)] == path
        ),
        key=len,
        default=(),
    )
    if safe_prefix:
        return ".".join((*safe_prefix, "<unknown>"))
    return "configuration.<unknown>"


def _safe_settings_error_summary(error: SettingsError) -> str:
    """Identify a known field without echoing source data from parse errors."""

    message = str(error)
    for field_name in BinnacleSettings.model_fields:
        if f'field "{field_name}"' in message:
            return f"{field_name}: invalid environment value"
    return "invalid environment value"


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


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _database_runtime_settings(settings: BinnacleSettings) -> DatabaseRuntimeSettings:
    return DatabaseRuntimeSettings(
        path=settings.database.path,
        runtime_directory=Path("/run/binnacle"),
        busy_timeout_ms=settings.database.busy_timeout_ms,
        wal_autocheckpoint_pages=settings.database.wal_autocheckpoint_pages,
        verify_runtime_directory=True,
    )


@database_app.command("upgrade")
def database_upgrade_command(
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Explicit protected TOML configuration path."),
    ] = None,
) -> None:
    """Upgrade the stopped-service SQLite database under the exclusive runtime lock."""

    settings = _load_or_exit(config_path=config_path)
    try:
        upgrade_database(
            _database_runtime_settings(settings),
            project_root=_project_root(),
        )
    except Exception as exc:
        typer.echo(f"Database upgrade failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Database upgraded to 0001_durable_operation_kernel")


@database_app.command("status")
def database_status_command(
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Explicit protected TOML configuration path."),
    ] = None,
    output: Annotated[
        OutputMode,
        typer.Option("--output", help="Output intention."),
    ] = OutputMode.HUMAN,
) -> None:
    """Read the stopped-service schema revision and durability pragmas."""

    settings = _load_or_exit(config_path=config_path)
    try:
        status = verify_database_read_only(
            database_path=settings.database.path,
            runtime_directory=Path("/run/binnacle"),
            busy_timeout_ms=settings.database.busy_timeout_ms,
            wal_autocheckpoint_pages=settings.database.wal_autocheckpoint_pages,
        )
    except Exception as exc:
        typer.echo(f"Database status failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=1) from exc
    value = {
        "status": "pass",
        "revision": status.revision,
        "journal_mode": status.journal_mode,
        "synchronous": status.synchronous,
        "foreign_keys": status.foreign_keys,
        "busy_timeout_ms": status.busy_timeout_ms,
        "wal_autocheckpoint_pages": status.wal_autocheckpoint_pages,
    }
    if output is OutputMode.JSON:
        typer.echo(json.dumps(value, sort_keys=True, separators=(",", ":")))
    elif output is OutputMode.AGENT:
        typer.echo(
            f"status=pass revision={status.revision} journal_mode={status.journal_mode} "
            f"synchronous={status.synchronous} foreign_keys={status.foreign_keys}"
        )
    else:
        typer.echo(
            f"Database {status.revision}; journal={status.journal_mode}; "
            f"synchronous={status.synchronous}; foreign_keys={status.foreign_keys}"
        )


async def _kernel_health(settings: BinnacleSettings) -> dict[str, object]:
    schema = json.loads(
        (_project_root() / "schemas/audit/audit-event.schema.json").read_text(encoding="utf-8")
    )
    if not isinstance(schema, dict):
        raise RuntimeError("audit schema is not an object")
    report = await verify_operation_kernel_read_only(
        paths=KernelVerificationPaths(
            database=settings.database.path,
            audit=settings.audit.directory,
            payload=settings.payload.directory,
            runtime=Path("/run/binnacle"),
        ),
        audit_schema=schema,
        busy_timeout_ms=settings.database.busy_timeout_ms,
        wal_autocheckpoint_pages=settings.database.wal_autocheckpoint_pages,
    )
    return report.as_dict()


@kernel_app.command("verify")
def kernel_verify_command(
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Explicit protected TOML configuration path."),
    ] = None,
    output: Annotated[
        OutputMode,
        typer.Option("--output", help="Output intention."),
    ] = OutputMode.HUMAN,
) -> None:
    """Read and verify all internal kernel stores without migrating or repairing them."""

    settings = _load_or_exit(config_path=config_path)
    try:
        health = asyncio.run(_kernel_health(settings))
    except Exception as exc:
        typer.echo(f"Kernel verification failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=1) from exc
    if output is OutputMode.JSON:
        typer.echo(json.dumps(health, sort_keys=True, separators=(",", ":")))
    elif output is OutputMode.AGENT:
        typer.echo(
            f"availability={health['availability']} "
            f"audit_sequence={health['audit_sequence']} "
            f"obligation_count={health['obligation_count']}"
        )
    else:
        typer.echo(
            f"Kernel {health['availability']}; audit sequence {health['audit_sequence']}; "
            f"obligations {health['obligation_count']}"
        )
    if health["availability"] != "available":
        raise typer.Exit(code=1)


@audit_app.command("verify")
def audit_verify_command(
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Explicit protected TOML configuration path."),
    ] = None,
    output: Annotated[
        OutputMode,
        typer.Option("--output", help="Output intention."),
    ] = OutputMode.HUMAN,
) -> None:
    """Verify the authoritative journal and report recovery-control state."""

    settings = _load_or_exit(config_path=config_path)
    try:
        health = asyncio.run(_kernel_health(settings))
    except Exception as exc:
        typer.echo(f"Audit verification failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=1) from exc
    value = {
        "status": (
            "pass"
            if health["audit_healthy"]
            and health["audit_obligation_count"] == 0
            and not health["audit_failure_latched"]
            else "fail"
        ),
        "audit_sequence": health["audit_sequence"],
        "obligation_count": health["audit_obligation_count"],
        "matched_obligations": health["audit_obligation_matched"],
        "unmatched_obligations": health["audit_obligation_unmatched"],
        "audit_failure_generation": health["audit_failure_generation"],
        "audit_recovered_generation": health["audit_recovered_generation"],
    }
    if output is OutputMode.JSON:
        typer.echo(json.dumps(value, sort_keys=True, separators=(",", ":")))
    elif output is OutputMode.AGENT:
        typer.echo(
            f"status={value['status']} audit_sequence={value['audit_sequence']} "
            f"obligations={value['obligation_count']} matched={value['matched_obligations']} "
            f"unmatched={value['unmatched_obligations']}"
        )
    else:
        typer.echo(
            f"Audit {value['status']}; sequence {value['audit_sequence']}; "
            f"obligations {value['obligation_count']} "
            f"({value['matched_obligations']} matched, "
            f"{value['unmatched_obligations']} unmatched)"
        )
    if value["status"] != "pass":
        raise typer.Exit(code=1)


def _load_audit_closures(path: Path) -> tuple[int, tuple[AuditObligationClosure, ...]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        generation = value["generation"]
        rows = value["closures"]
        if not isinstance(generation, int) or generation < 1 or not isinstance(rows, list):
            raise ValueError
        closures = tuple(
            AuditObligationClosure(
                obligation_id=row["obligation_id"],
                effect_outcome=row["effect_outcome"],
                evidence_sha256=row["evidence_sha256"],
            )
            for row in rows
            if isinstance(row, dict)
        )
        if len(closures) != len(rows):
            raise ValueError
        return generation, closures
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid audit recovery closure file") from exc


async def _recover_audit(
    settings: BinnacleSettings,
    generation: int,
    closures: tuple[AuditObligationClosure, ...],
) -> str:
    kernel = await compose_operation_kernel(settings=settings, project_root=_project_root())
    try:
        return await AuditRecoveryService(
            store=kernel.store,
            obligations=kernel.obligations,
            audit=kernel.audit,
        ).recover(generation=generation, closures=closures)
    finally:
        await kernel.close()


@audit_app.command("recover")
def audit_recover_command(
    generation: Annotated[
        int,
        typer.Option("--generation", min=1, help="Exact active audit-failure generation."),
    ],
    closure_file: Annotated[
        Path,
        typer.Option(
            "--closure-file",
            help="Protected operator-reviewed exact-generation obligation closure JSON.",
        ),
    ],
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Explicit protected TOML configuration path."),
    ] = None,
) -> None:
    """Explicitly close one exact latched audit-failure generation while stopped."""

    settings = _load_or_exit(config_path=config_path)
    try:
        closure_generation, closures = _load_audit_closures(closure_file)
        if closure_generation != generation:
            raise ValueError("closure generation does not match requested generation")
        evidence = asyncio.run(_recover_audit(settings, generation, closures))
    except Exception as exc:
        typer.echo(f"Audit recovery failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Audit generation {generation} recovered; evidence sha256={evidence}")


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
    """Start the loopback-only read-only MCP compatibility server."""

    server_overrides: dict[str, object] = {}
    if host is not None:
        server_overrides["host"] = host
    if port is not None:
        server_overrides["port"] = port
    cli_overrides: dict[str, object] | None = None
    if server_overrides:
        cli_overrides = {"server": server_overrides}

    settings = _load_or_exit(config_path=config_path, cli_overrides=cli_overrides)
    if settings.server.host not in {"127.0.0.1", "::1"}:
        typer.echo(
            "Configuration error: Phase 2 MCP server requires canonical loopback bind",
            err=True,
        )
        raise typer.Exit(code=2)
    composed = compose_application(settings=settings)
    try:
        run_http_server(application=composed.application, settings=settings.server)
    finally:
        asyncio.run(composed.close())


def main() -> None:
    """Invoke the canonical Typer application."""

    app()
