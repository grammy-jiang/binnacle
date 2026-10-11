"""Real SQLite authority/proofs, I0 leases, and native synthetic carriers."""

import ast
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import perf_counter
from unittest.mock import patch

import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.types import Implementation

import binnacle.mcp.job_awareness_hint as module
from binnacle.features.commands.job_awareness.grants import SyntheticAuthority
from binnacle.features.commands.job_awareness.models import (
    BoundaryError,
    ErrorCode,
    Failure,
    HintCarrier,
    ReceiptState,
)
from binnacle.features.commands.job_awareness.receipt_store import ReceiptTransaction
from binnacle.mcp.job_awareness_hint import META_KEY, Schema
from tests.contracts.job_awareness.synthetic_app import (
    Lab,
    Workers,
    app_for,
    in_loop,
    ok,
    original,
)
from tests.unit.core.job_awareness.test_grants import Unregistered

BUSY = Failure(BoundaryError(ErrorCode.BUSY))


@in_loop
async def test_real_synthetic_ledger():
    with Lab() as lab:
        adapter = lab.adapter(enabled=True)
        app, _ = app_for(adapter)
        async with Client(app) as client:
            first = await client.call_tool("synthetic")
            assert "unconfirmed" in first.meta[META_KEY]  # nosec B101 - pytest assertion
            assert lab.payload.reads == 0  # nosec B101 - pytest assertion
            page = ok(
                await adapter.workers.run(
                    lambda stop: lab.service.issue(lab.handle, lab.snapshot, 0),
                    BUSY,
                )
            )
            # Issuing/returning a proof alone does not acknowledge it.
            issued = await client.call_tool("synthetic")
            assert "unconfirmed" in issued.meta[META_KEY]  # nosec B101 - pytest assertion
            foreign = lab.consumer("9" * 32)
            denied = await adapter.workers.run(
                lambda stop: lab.service.acknowledge(
                    foreign, lab.snapshot, (page.proof,)
                ),
                BUSY,
            )
            assert isinstance(denied, Failure)  # nosec B101 - pytest assertion
            tampered = page.proof[:-1] + ("0" if page.proof[-1] != "0" else "1")
            assert isinstance(  # nosec B101 - pytest assertion
                await adapter.workers.run(
                    lambda stop: lab.service.acknowledge(
                        lab.handle, lab.snapshot, (tampered,)
                    ),
                    BUSY,
                ),
                Failure,
            )
            partial = ok(
                await adapter.workers.run(
                    lambda stop: lab.service.acknowledge(
                        lab.handle, lab.snapshot, (page.proof,)
                    ),
                    BUSY,
                )
            )
            assert partial.state is ReceiptState.PARTIAL  # nosec B101 - pytest assertion
            assert (  # nosec B101 - pytest assertion
                "partially confirmed"
                in (await client.call_tool("synthetic")).meta[META_KEY]
            )
            replay = await adapter.workers.run(
                lambda stop: lab.service.acknowledge(
                    lab.handle, lab.snapshot, (page.proof,)
                ),
                BUSY,
            )
            assert ok(replay) == partial  # nosec B101 - pytest assertion
            final = ok(
                await adapter.workers.run(
                    lambda stop: lab.service.issue(lab.handle, lab.snapshot, 16384),
                    BUSY,
                )
            )
            complete = ok(
                await adapter.workers.run(
                    lambda stop: lab.service.acknowledge(
                        lab.handle, lab.snapshot, (final.proof,)
                    ),
                    BUSY,
                )
            )
            assert complete.state is ReceiptState.COMPLETE  # nosec B101 - pytest assertion
            assert META_KEY not in (await client.call_tool("synthetic")).meta  # nosec B101 - pytest assertion
            # A second genuine consumer never inherits the first receipt.
            other = lab.adapter(enabled=True, grant=foreign)
            assert "unconfirmed" in (await other.adapt_bound(original())).meta[META_KEY]  # nosec B101 - pytest assertion
        assert lab.memory.stats().pins == 0  # nosec B101 - pytest assertion
        assert lab.memory.stats().inflight_bytes == 0  # nosec B101 - pytest assertion
        assert lab.memory.stats().cache_bytes == len(lab.data)  # nosec B101 - pytest assertion
        lab.memory.evict_unpinned()
        assert lab.memory.stats().cache_bytes == 0  # nosec B101 - pytest assertion
        await adapter.workers.close()


@in_loop
async def test_denied_foreign_expired_revoked_and_epoch():
    for reason in (
        "forged",
        "foreign",
        "expired",
        "retired",
        "revoked",
        "retention",
    ):
        with Lab() as lab:
            adapter = lab.adapter(enabled=True)
            if reason == "forged":
                adapter.grant = Unregistered()
            elif reason == "foreign":
                adapter.jobs = (replace(lab.job, job_id="f" * 12),)
            elif reason == "expired":
                lab.wall += 3600000
            elif reason == "retired":
                cold = SyntheticAuthority(lab.authority.store.path, "1" * 32, lab.clock)
                ok(cold.start())
            elif reason == "revoked":
                ok(lab.authority.revoke(lab.handle))
            else:
                lab.wall = lab.snapshot.retained_until_ms
            value = original()
            assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
            assert lab.queries == 0  # nosec B101 - pytest assertion
            if reason != "retention":
                assert lab.catalog_reads == 0  # nosec B101 - pytest assertion


@in_loop
async def test_revocation_between_observation_and_query():
    with Lab() as lab:
        adapter = lab.adapter(enabled=True)
        lab.before_query = lambda: ok(lab.authority.revoke(lab.handle))
        value = original()
        assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
        assert lab.queries == 1  # nosec B101 - pytest assertion
        assert lab.payload.reads == 0  # nosec B101 - pytest assertion


@in_loop
async def test_shared_two_work_admission():
    """Real nested query holds a shared permit; no executor/wait queue exists."""

    with Lab() as lab:
        workers = Workers(lab.budget)
        releases = [Event(), Event()]
        entered = [asyncio.Event(), asyncio.Event()]
        loop = asyncio.get_running_loop()

        def work(index):
            def action(stop):
                assert (  # nosec B101 - pytest assertion
                    lab.service.query(lab.handle, lab.snapshot).value.state
                    is ReceiptState.UNCONFIRMED
                )
                loop.call_soon_threadsafe(entered[index].set)
                assert releases[index].wait(5)  # nosec B101 - pytest assertion
                return index

            return action

        first = asyncio.create_task(workers.run(work(0), BUSY))
        await asyncio.wait_for(entered[0].wait(), 3)
        second = asyncio.create_task(workers.run(work(1), BUSY))
        await asyncio.wait_for(entered[1].wait(), 3)
        try:
            assert await workers.run(lambda stop: pytest.fail("queued"), BUSY) == BUSY  # nosec B101 - pytest assertion
            value = original()
            adapter = lab.adapter(enabled=True)
            assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
            assert adapter.last_meter is None  # nosec B101 - pytest assertion
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert (  # nosec B101 - pytest assertion
                await workers.run(lambda stop: pytest.fail("replacement"), BUSY) == BUSY
            )
            releases[0].set()
            # close waits for actual completion, including the canceled awaiter.
            releases[1].set()
            assert await second == 1  # nosec B101 - pytest assertion
            await workers.close()
            assert not workers.pending  # nosec B101 - pytest assertion
            assert await workers.run(lambda stop: 7, BUSY) == BUSY  # nosec B101 - pytest assertion
        finally:
            for release in releases:
                release.set()
            await workers.close()


@in_loop
async def test_cancelled_awaiter_keeps_worker_permit():
    """Pause inside a real SQLite write while an I0 snapshot lease is pinned."""

    with Lab() as lab:
        workers = Workers(lab.budget)
        release, entered = Event(), asyncio.Event()
        loop = asyncio.get_running_loop()
        issue = ReceiptTransaction.issue_proof

        def blocked(tx, *args):
            issue(tx, *args)
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)  # nosec B101 - pytest assertion

        with patch.object(ReceiptTransaction, "issue_proof", blocked):
            task = asyncio.create_task(
                workers.run(
                    lambda stop: lab.service.issue(lab.handle, lab.snapshot, 0),
                    BUSY,
                )
            )
            await asyncio.wait_for(entered.wait(), 3)
            reservation = lab.budget.reserve()
            assert reservation is not None  # nosec B101 - pytest assertion
            try:
                assert lab.memory.stats().pins == 1  # nosec B101 - pytest assertion
                assert lab.memory.stats().cache_bytes == len(lab.data)  # nosec B101 - pytest assertion
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert lab.memory.stats().pins == 1  # nosec B101 - pytest assertion
                assert (  # nosec B101 - pytest assertion
                    await workers.run(lambda stop: pytest.fail("queued"), BUSY) == BUSY
                )
                lab.memory.evict_unpinned()
                assert lab.memory.stats().cache_bytes == len(lab.data)  # nosec B101 - pytest assertion
            finally:
                release.set()
                reservation.cancel_before_start()
                await workers.close()
        assert lab.memory.stats().pins == 0  # nosec B101 - pytest assertion
        assert (  # nosec B101 - pytest assertion
            ok(lab.service.query(lab.handle, lab.snapshot)).state
            is ReceiptState.UNCONFIRMED
        )


@in_loop
async def test_event_loop_progress_during_blocking_work():
    with Lab() as lab:
        adapter = lab.adapter(enabled=True)
        release, entered = Event(), asyncio.Event()
        loop = asyncio.get_running_loop()

        def blocked():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)  # nosec B101 - pytest assertion

        lab.before_query = blocked
        task = asyncio.create_task(adapter.adapt_bound(original()))
        await asyncio.wait_for(entered.wait(), 3)
        started = perf_counter()
        sentinel = asyncio.Event()
        for _ in range(100):
            sentinel.clear()
            loop.call_soon(sentinel.set)
            await sentinel.wait()
        elapsed = perf_counter() - started
        assert not task.done()  # nosec B101 - pytest assertion
        assert not release.is_set()  # nosec B101 - pytest assertion
        release.set()
        assert META_KEY in (await task).meta  # nosec B101 - pytest assertion
        print(f"event_loop_100_callbacks_seconds={elapsed:.6f}")


@in_loop
async def test_submission_and_worker_failure_release_once():
    with Lab() as lab:
        workers = Workers(lab.budget)
        with patch(
            "tests.contracts.job_awareness.synthetic_app.Thread.start",
            side_effect=RuntimeError,
        ):
            assert await workers.run(lambda stop: 1, BUSY) == BUSY  # nosec B101 - pytest assertion

        def fail(stop):
            raise RuntimeError("synthetic worker failure")

        with pytest.raises(RuntimeError, match="synthetic worker"):
            await workers.run(fail, BUSY)
        permits = [lab.budget.reserve(), lab.budget.reserve()]
        assert all(p is not None for p in permits)  # nosec B101 - pytest assertion
        assert lab.budget.reserve() is None  # nosec B101 - pytest assertion
        for permit in permits:
            assert permit.cancel_before_start()  # nosec B101 - pytest assertion
            assert not permit.cancel_before_start()  # nosec B101 - pytest assertion
        await workers.close()


@in_loop
async def test_asgi_protocol_carriers_and_spoofed_identity():
    for protocol in ("2025-06-18", "2026-07-28"):
        for carrier in (HintCarrier.META, HintCarrier.TEXT):
            for authorized in (True, False):
                with Lab() as lab:
                    adapter = lab.adapter(
                        enabled=True,
                        carrier=carrier,
                        grant=lab.handle if authorized else Unregistered(),
                    )
                    result, seen, raw = await native_wire(adapter, original(), protocol)
                    assert len(seen) == 1  # nosec B101 - pytest assertion
                    assert not result.is_error  # nosec B101 - pytest assertion
                    assert result.structured_content == {"ok": True}  # nosec B101 - pytest assertion
                    text = json.dumps(json.loads(raw))
                    assert ("Binnacle job reminder" in text) is authorized  # nosec B101 - pytest assertion
                    assert "synthetic-secret-canary" not in text  # nosec B101 - pytest assertion
                    assert "ja1_" not in text if not authorized else True  # nosec B101 - pytest assertion
                    assert len(raw) < 263168  # nosec B101 - pytest assertion
                    if not authorized:
                        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion


@in_loop
async def test_original_job_status_schema_on_separate_native_app():
    # Read the frozen schema without constructing a production backend.
    tree = ast.parse(
        Path("src/binnacle/features/commands/tools/job_status.py").read_text()
    )
    schema = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "OUTPUT_SCHEMA" for t in n.targets)
    )
    Schema(schema)

    with Lab() as lab:
        value = original()
        value.structured_content = {"jobs": []}
        adapter = lab.adapter(enabled=True, schema=schema)
        app, _ = app_for(adapter, value, schema=schema)
        async with Client(app) as client:
            result = await client.call_tool("synthetic")
        assert result.structured_content == {"jobs": []}  # nosec B101 - pytest assertion
        assert META_KEY in result.meta  # nosec B101 - pytest assertion
        for field in ("jobs", "processes"):
            adapter = lab.adapter(enabled=True, schema=schema)
            value.structured_content = {field: [{}] * 10000}
            old_reads = lab.catalog_reads, lab.queries
            assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
            assert (lab.catalog_reads, lab.queries) == old_reads  # nosec B101 - pytest assertion


@in_loop
async def test_exhaustion_during_copy_schema_and_carrier():
    with Lab() as lab:
        for phase in ("copy", "schema", "carrier"):
            adapter, value = lab.adapter(enabled=True), original()
            walk, render = module.walk, adapter.bindings.render

            def exhausted_walk(value, meter, *, walk=walk, copy=False, **kwargs):
                if copy:
                    meter.total = 4194304
                return walk(value, meter, copy=copy, **kwargs)

            def exhausted_schema(value, meter):
                meter.total = 4194304
                return True

            def exhausted_carrier(*args, adapter=adapter, render=render):
                adapter.last_meter.total = 4194304
                return render(*args)

            target, name, replacement = {
                "copy": (module, "walk", exhausted_walk),
                "schema": (adapter.schema, "valid", exhausted_schema),
                "carrier": (
                    adapter,
                    "bindings",
                    replace(adapter.bindings, render=exhausted_carrier),
                ),
            }[phase]
            with patch.object(target, name, replacement):
                assert await adapter.adapt_bound(value) is value  # nosec B101 - pytest assertion
            assert adapter.last_meter.total == 4194304  # nosec B101 - pytest assertion
            assert lab.queries == (1 if phase == "carrier" else 0)  # nosec B101 - pytest assertion


@pytest.mark.parametrize("protocol", ["2025-06-18", "2026-07-28"])
@pytest.mark.parametrize("payload", ["float", "metadata", "unicode"])
@pytest.mark.parametrize("size", [261900, 262143, 262144, 262145])
@in_loop
async def test_raw_native_wire_limits_both_protocols(protocol, payload, size, tmp_path):
    with Lab() as lab:
        value = original()
        value.structured_content = {
            "values": [1e-5] * 1000
            if payload == "float"
            else ["é" * 1000]
            if payload == "unicode"
            else [0],
            "padding": ["a" * 60000] * 4 + [""],
        }
        disabled = lab.adapter(schema={"type": "object"})
        _, _, initial = await native_wire(disabled, value, protocol)
        value.structured_content["padding"][-1] = "a" * (size - len(initial))
        _, _, raw_original = await native_wire(disabled, value, protocol)
        assert len(raw_original) == size  # nosec B101 - pytest assertion
        if payload == "float":
            assert (  # nosec B101 - pytest assertion
                b"0.00001" if protocol == "2025-06-18" else b"1e-05"
            ) in raw_original
        assert (b"io.modelcontextprotocol/serverInfo" in raw_original) is (  # nosec B101 - pytest assertion
            protocol == "2026-07-28"
        )
        (tmp_path / "original.json").write_bytes(raw_original)
        adapter = lab.adapter(enabled=True, schema={"type": "object"})
        adapted = await adapter.adapt_bound(value)
        result, _, raw_final = await native_wire(adapter, value, protocol)
        (tmp_path / "final.json").write_bytes(raw_final)
        print(
            f"{protocol} {payload}: original={len(raw_original)} final={len(raw_final)} reads={lab.catalog_reads}/{lab.queries}"
        )
        if size > 262144 or adapted is value:
            assert (adapted is value, lab.catalog_reads, lab.queries) == (True, 0, 0)  # nosec B101 - pytest assertion
            assert META_KEY not in result.meta  # nosec B101 - pytest assertion
            assert json.loads(raw_final) == json.loads(raw_original)  # nosec B101 - pytest assertion
        else:
            assert lab.catalog_reads == lab.queries == 2  # nosec B101 - pytest assertion
            assert META_KEY in result.meta  # nosec B101 - pytest assertion
            assert len(raw_final) <= 263168 and len(raw_final) - size <= 1024  # nosec B101 - pytest assertion


async def native_wire(adapter, value, protocol):
    """Capture the native result substring; never reserialize parsed numbers."""

    app, seen = app_for(adapter, value, schema={"type": "object"})
    http_app = app.http_app(stateless_http=True, json_response=True)
    responses = []

    async def record(response):
        body = await response.aread()
        if body and "content" in json.loads(body).get("result", {}):
            raw = body[body.index(b'"result":') + len(b'"result":') : -1]
            assert json.loads(raw) == json.loads(body)["result"]  # nosec B101 - pytest assertion
            responses.append(raw)

    def factory(**kwargs):
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=http_app),
            event_hooks={"response": [record]},
            **kwargs,
        )

    async with http_app.router.lifespan_context(http_app):
        transport = StreamableHttpTransport(
            "http://synthetic/mcp",
            httpx_client_factory=factory,
            headers={
                "authorization": "Bearer synthetic-shared",
                "x-chat-id": "spoofed-chat",
            },
        )
        with patch("mcp.client.session.LATEST_HANDSHAKE_VERSION", "2025-06-18"):
            async with Client(
                transport,
                mode="legacy" if protocol == "2025-06-18" else protocol,
                cache=False,
                client_info=Implementation(name="openai-mcp", version="spoofed"),
            ) as client:
                result = await client.call_tool(
                    "synthetic", meta={"chat_id": "spoofed-chat"}
                )
                assert client.protocol_version == protocol  # nosec B101 - pytest assertion
    assert len(seen) == len(responses) == 1  # nosec B101 - pytest assertion
    return result, seen, responses[0]
