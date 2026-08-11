"""SQLite uniqueness is authoritative under concurrent first use."""

from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

import pytest
from tests.phase4_support import intent, operation_runtime, owner

from binnacle.domain.idempotency import (
    IdempotencyKeyMode,
    IdempotencyOutcome,
    validate_and_digest_key,
)
from binnacle.ports.operation_store import CreateOrFindRequest


@pytest.mark.anyio
async def test_concurrent_first_use_creates_one_binding_and_operation(
    tmp_path: Path, repo_root: Path
) -> None:
    async with operation_runtime(tmp_path, repo_root) as (_, store):
        key = validate_and_digest_key(secrets.token_hex(32), IdempotencyKeyMode.CALLER_KEY)
        request = CreateOrFindRequest(key, owner(), intent(), "internal.synthetic", "1.0.0")
        results = await asyncio.gather(*(store.create_or_find(request) for _ in range(12)))
        assert sum(item.outcome is IdempotencyOutcome.CREATED for item in results) == 1
        assert sum(item.outcome is IdempotencyOutcome.RETAINED_OPERATION for item in results) == 11
        operation_ids = {item.operation.operation_id for item in results if item.operation}
        assert len(operation_ids) == 1
