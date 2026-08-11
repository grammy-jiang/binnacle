"""SQLite authoritative retained-payload metadata repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from binnacle.adapters.sqlite.engine import DatabaseRuntime
from binnacle.adapters.sqlite.models import PayloadObjectModel
from binnacle.domain.payload import PayloadKind, PayloadLifecycle, PayloadMetadata


class SqlitePayloadMetadataRepository:
    def __init__(self, runtime: DatabaseRuntime) -> None:
        self._runtime = runtime

    async def create(self, metadata: PayloadMetadata) -> None:
        async with self._runtime.session_factory() as session, session.begin():
            session.add(
                PayloadObjectModel(
                    payload_id=metadata.payload_id,
                    operation_id=metadata.operation_id,
                    controller_id=metadata.controller_id,
                    controller_epoch=metadata.controller_epoch,
                    kind=metadata.kind.value,
                    lifecycle=metadata.lifecycle.value,
                    relative_path=metadata.relative_path,
                    media_type=metadata.media_type,
                    encoding=metadata.encoding,
                    decoded_byte_count=metadata.decoded_byte_count,
                    sha256=metadata.sha256,
                    truncated=metadata.truncated,
                    information_class=metadata.information_class,
                    retention_class=metadata.retention_class,
                    created_at=metadata.created_at,
                    completed_at=metadata.completed_at,
                    expires_at=metadata.expires_at,
                    last_access_at=metadata.last_access_at,
                )
            )

    async def get(self, payload_id: str) -> PayloadMetadata | None:
        async with self._runtime.session_factory() as session:
            model = await session.get(PayloadObjectModel, payload_id)
            return None if model is None else self._metadata(model)

    async def list_all(self) -> tuple[PayloadMetadata, ...]:
        async with self._runtime.session_factory() as session:
            rows = (
                await session.execute(
                    select(PayloadObjectModel).order_by(PayloadObjectModel.payload_id)
                )
            ).scalars()
            return tuple(self._metadata(row) for row in rows)

    async def update_building_size(self, payload_id: str, byte_count: int) -> PayloadMetadata:
        async with self._runtime.session_factory() as session, session.begin():
            model = await session.get(PayloadObjectModel, payload_id)
            if model is None or model.lifecycle != PayloadLifecycle.BUILDING.value:
                raise RuntimeError("payload is not building")
            if byte_count < model.decoded_byte_count:
                raise RuntimeError("payload size cannot move backward")
            model.decoded_byte_count = byte_count
            return self._metadata(model)

    async def complete(self, payload_id: str, *, byte_count: int, sha256: str) -> PayloadMetadata:
        async with self._runtime.session_factory() as session, session.begin():
            model = await session.get(PayloadObjectModel, payload_id)
            if model is None:
                raise RuntimeError("payload was not registered")
            if model.lifecycle == PayloadLifecycle.COMPLETE.value:
                if model.decoded_byte_count != byte_count or model.sha256 != sha256:
                    raise RuntimeError("payload finalization conflicts with retained metadata")
                return self._metadata(model)
            if model.lifecycle != PayloadLifecycle.BUILDING.value:
                raise RuntimeError("payload cannot be finalized from current lifecycle")
            model.lifecycle = PayloadLifecycle.COMPLETE.value
            model.decoded_byte_count = byte_count
            model.sha256 = sha256
            model.completed_at = datetime.now(UTC)
            return self._metadata(model)

    async def fail(self, payload_id: str) -> PayloadMetadata:
        async with self._runtime.session_factory() as session, session.begin():
            model = await session.get(PayloadObjectModel, payload_id)
            if model is None:
                raise RuntimeError("payload was not registered")
            if model.lifecycle == PayloadLifecycle.COMPLETE.value:
                raise RuntimeError("complete payload cannot be marked failed")
            model.lifecycle = PayloadLifecycle.FAILED.value
            return self._metadata(model)

    async def controller_bytes(self, controller_id: str, controller_epoch: int) -> int:
        async with self._runtime.session_factory() as session:
            value = (
                await session.execute(
                    select(func.coalesce(func.sum(PayloadObjectModel.decoded_byte_count), 0)).where(
                        PayloadObjectModel.controller_id == controller_id,
                        PayloadObjectModel.controller_epoch == controller_epoch,
                        PayloadObjectModel.lifecycle.in_(
                            (PayloadLifecycle.BUILDING.value, PayloadLifecycle.COMPLETE.value)
                        ),
                    )
                )
            ).scalar_one()
            return int(value)

    @staticmethod
    def _metadata(model: PayloadObjectModel) -> PayloadMetadata:
        def utc(value: datetime | None) -> datetime | None:
            if value is None:
                return None
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

        return PayloadMetadata(
            payload_id=model.payload_id,
            operation_id=model.operation_id,
            controller_id=model.controller_id,
            controller_epoch=model.controller_epoch,
            kind=PayloadKind(model.kind),
            lifecycle=PayloadLifecycle(model.lifecycle),
            relative_path=model.relative_path,
            media_type=model.media_type,
            encoding=model.encoding,
            decoded_byte_count=model.decoded_byte_count,
            sha256=model.sha256,
            truncated=model.truncated,
            information_class=model.information_class,
            retention_class=model.retention_class,
            created_at=utc(model.created_at) or model.created_at,
            completed_at=utc(model.completed_at),
            expires_at=utc(model.expires_at),
            last_access_at=utc(model.last_access_at),
        )
