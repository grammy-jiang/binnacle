"""Explicit stopped-service Alembic migration coordination."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from binnacle.adapters.sqlite.engine import DatabaseRuntimeSettings, acquire_runtime_lock


def upgrade_database(settings: DatabaseRuntimeSettings, *, project_root: Path) -> None:
    lock = acquire_runtime_lock(
        settings.runtime_directory,
        lock_name="database-writer.lock",
        verify_directory=settings.verify_runtime_directory,
    )
    try:
        config = Config(project_root / "alembic.ini")
        config.set_main_option("script_location", str(project_root / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.path}")
        command.upgrade(config, "head")
    finally:
        lock.close()


def current_revision(settings: DatabaseRuntimeSettings, *, project_root: Path) -> None:
    config = Config(project_root / "alembic.ini")
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.path}")
    command.current(config)
