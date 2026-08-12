"""SQLite async runtime, durability pragmas, and writer/migration lock."""

from __future__ import annotations

import fcntl
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DatabaseRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseRuntimeSettings:
    path: Path
    runtime_directory: Path
    busy_timeout_ms: int = 5000
    wal_autocheckpoint_pages: int = 1000
    expected_revision: str = "0004_execution_operations"
    verify_runtime_directory: bool = True


@dataclass(slots=True)
class RuntimeLock:
    path: Path
    descriptor: int

    def close(self) -> None:
        if self.descriptor < 0:
            return
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)
        self.descriptor = -1


@dataclass(slots=True)
class DatabaseRuntime:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    runtime_lock: RuntimeLock
    settings: DatabaseRuntimeSettings


@dataclass(frozen=True, slots=True)
class DatabaseHealth:
    healthy: bool
    revision: str | None
    journal_mode: str
    synchronous: int
    foreign_keys: int
    busy_timeout_ms: int
    wal_autocheckpoint_pages: int


def verify_runtime_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise DatabaseRuntimeError(
            "runtime directory is absent; start the systemd service to recreate it"
        ) from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise DatabaseRuntimeError("runtime directory is unsafe")
    if stat.S_IMODE(info.st_mode) & 0o027:
        raise DatabaseRuntimeError("runtime directory permissions are broader than 0750")
    if info.st_uid != os.geteuid():
        raise DatabaseRuntimeError("runtime directory is not owned by the current service identity")
    if info.st_gid != os.getegid():
        raise DatabaseRuntimeError("runtime directory group is not the service primary group")


def acquire_runtime_lock(
    runtime_directory: Path,
    *,
    lock_name: str,
    verify_directory: bool,
) -> RuntimeLock:
    if verify_directory:
        verify_runtime_directory(runtime_directory)
    else:
        runtime_directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    path = runtime_directory / lock_name
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o640)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise DatabaseRuntimeError(
            "database writer or maintenance process is already active"
        ) from exc
    return RuntimeLock(path, descriptor)


def acquire_existing_runtime_lock(runtime_directory: Path) -> RuntimeLock:
    """Acquire the stopped-service lock without creating or repairing any path."""

    verify_runtime_directory(runtime_directory)
    path = runtime_directory / "database-writer.lock"
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise DatabaseRuntimeError("database writer lock is absent") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_gid != os.getegid()
        or stat.S_IMODE(info.st_mode) & 0o027
    ):
        raise DatabaseRuntimeError("database writer lock is unsafe")
    descriptor = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise DatabaseRuntimeError(
            "database writer or maintenance process is already active"
        ) from exc
    return RuntimeLock(path, descriptor)


async def create_database_runtime(settings: DatabaseRuntimeSettings) -> DatabaseRuntime:
    if settings.busy_timeout_ms < 100 or settings.busy_timeout_ms > 60_000:
        raise DatabaseRuntimeError("database busy timeout is outside the safe range")
    if settings.wal_autocheckpoint_pages < 100 or settings.wal_autocheckpoint_pages > 100_000:
        raise DatabaseRuntimeError("WAL autocheckpoint is outside the safe range")
    if settings.path.is_symlink():
        raise DatabaseRuntimeError("database path may not be a symlink")
    settings.path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    runtime_lock = acquire_runtime_lock(
        settings.runtime_directory,
        lock_name="database-writer.lock",
        verify_directory=settings.verify_runtime_directory,
    )
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{settings.path}",
        pool_pre_ping=True,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_connection(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute(f"PRAGMA busy_timeout={settings.busy_timeout_ms}")
            cursor.execute(f"PRAGMA wal_autocheckpoint={settings.wal_autocheckpoint_pages}")
        finally:
            cursor.close()

    return DatabaseRuntime(
        engine=engine,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        runtime_lock=runtime_lock,
        settings=settings,
    )


async def verify_database_runtime(runtime: DatabaseRuntime) -> DatabaseHealth:
    async with runtime.engine.connect() as connection:
        foreign_keys = int((await connection.execute(text("PRAGMA foreign_keys"))).scalar_one())
        journal_mode = str((await connection.execute(text("PRAGMA journal_mode"))).scalar_one())
        synchronous = int((await connection.execute(text("PRAGMA synchronous"))).scalar_one())
        busy_timeout = int((await connection.execute(text("PRAGMA busy_timeout"))).scalar_one())
        checkpoint = int((await connection.execute(text("PRAGMA wal_autocheckpoint"))).scalar_one())
        revision_result = await connection.execute(text("SELECT version_num FROM alembic_version"))
        revision = revision_result.scalar_one_or_none()
    healthy = (
        foreign_keys == 1
        and journal_mode.casefold() == "wal"
        and synchronous == 2
        and busy_timeout == runtime.settings.busy_timeout_ms
        and checkpoint == runtime.settings.wal_autocheckpoint_pages
        and revision == runtime.settings.expected_revision
    )
    return DatabaseHealth(
        healthy=healthy,
        revision=revision,
        journal_mode=journal_mode,
        synchronous=synchronous,
        foreign_keys=foreign_keys,
        busy_timeout_ms=busy_timeout,
        wal_autocheckpoint_pages=checkpoint,
    )


async def close_database_runtime(runtime: DatabaseRuntime) -> None:
    try:
        await runtime.engine.dispose()
    finally:
        runtime.runtime_lock.close()
