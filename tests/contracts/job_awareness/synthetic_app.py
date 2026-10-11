"""Isolated controller and native app; all bytes and credentials are synthetic."""

import asyncio
import hashlib
import tempfile
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from enum import Enum
from functools import partial, wraps
from pathlib import Path
from threading import Event, Thread
from types import TracebackType
from typing import Any, Protocol, TypeVar
from unittest.mock import patch

import pytest
import uvloop
from fastmcp import FastMCP
from fastmcp.tools.base import Tool, ToolResult
from mcp.types import TextContent

from binnacle.features.commands.job_awareness.grants import (
    SyntheticAuthority,
    TrustedClock,
)
from binnacle.features.commands.job_awareness.hint_policy import select_candidates
from binnacle.features.commands.job_awareness.hint_render import render_hint
from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    HintCarrier,
    JobRef,
    Observation,
    ObservationState,
    OutputSnapshot,
    PrincipalClaims,
    RenderedHint,
    Scope,
    SourceKind,
    Success,
    TerminalKind,
    TerminalOutcome,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.observation import JobObserver
from binnacle.features.commands.job_awareness.ports import (
    HandleAuthorityPort,
    JobObservationPort,
    ReceiptQueryPort,
)
from binnacle.features.commands.job_awareness.proofs import (
    SyntheticProofService,
    WorkerBudget,
)
from binnacle.features.commands.job_awareness.snapshots import (
    SnapshotMemory,
    SnapshotStore,
    TrustedCatalog,
)
from binnacle.mcp.job_awareness_hint import HintAdapter, HintBindings, witnessed_tool
from binnacle.mcp.job_awareness_hint import Workers as WorkerPort
from tests.contracts.job_awareness.test_hint_schema_support import (
    SyntheticHintAdapter,
    assert_adapter_import_topology,
    callback_trap,
)
from tests.contracts.job_awareness.test_hint_version_support import ExecutionCarrier

__all__ = [
    "SCHEMA",
    "Admission",
    "Lab",
    "Payload",
    "Permit",
    "Workers",
    "app_for",
    "assert_adapter_import_topology",
    "callback_trap",
    "check_explicit_bindings",
    "in_loop",
    "ok",
    "original",
    "worker_lifetime_negative_control",
    "worker_port",
]

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def in_loop(func):
    """Keep focused native tests on the same uvloop runner with less nesting."""

    @wraps(func)
    def run(*args, **kwargs):
        return uvloop.run(func(*args, **kwargs))

    return run


def ok(result):
    assert isinstance(result, Success), result  # nosec B101 - pytest assertion
    return result.value


def original():
    return ToolResult(
        content=[TextContent(type="text", text="Synthetic result")],
        structured_content={"ok": True},
        meta={"existing": "kept"},
    )


class Payload:
    def __init__(self, data):
        self.data, self.reads = data, 0

    def read(self, length):
        self.reads += 1
        assert length == len(self.data)  # nosec B101 - pytest assertion
        return Success(self.data)


class Lab:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="i22-synthetic-")
        self.wall, self.mono = 1000, 0
        self.clock = TrustedClock(lambda: self.wall, lambda: self.mono)
        self.authority = SyntheticAuthority(
            Path(self.temp.name) / "ledger.sqlite", "1" * 32, self.clock
        )
        ok(self.authority.start())
        self.job = JobRef("ja1_" + "5" * 32, "6" * 12, "g1_" + "7" * 32)
        self.data = b"synthetic-secret-canary /private/path\x00\xff" * 500
        self.snapshot = OutputSnapshot(
            self.job,
            hashlib.sha256(self.data).hexdigest(),
            len(self.data),
            TerminalOutcome(TerminalKind.EXIT_CODE, 1),
            1,
            800000,
            SourceKind.CONTROLLER_SEALED_SYNTHETIC,
            "8" * 32,
        )
        self.handle = self.consumer("4" * 32)
        ok(
            self.authority.store.controller_transaction(
                lambda tx: tx.register_snapshot(self.snapshot, self.data)
            )
        )
        self.catalog = TrustedCatalog()
        self.payload = Payload(self.data)
        ok(
            self.catalog.register(
                Observation(
                    self.job,
                    ObservationState.TERMINAL,
                    self.snapshot.terminal,
                    self.snapshot,
                ),
                self.payload,
            )
        )
        self.memory = SnapshotMemory()
        self.reader = SnapshotStore(
            self.authority, self.catalog, lambda: self.wall, memory=self.memory
        )
        self.observer = JobObserver(self.authority, self.catalog, lambda: self.wall)
        self.budget = WorkerBudget()
        self.service = SyntheticProofService(
            self.authority, self.reader, workers=self.budget
        )
        self.catalog_reads = self.queries = 0
        self.before_query = lambda: None

    def consumer(self, consumer, *, jobs=None):
        credential = ok(
            self.authority.register_principal(
                PrincipalClaims("1" * 32, "2" * 32, "3" * 32, consumer)
            )
        )
        principal = ok(self.authority.verify_principal(credential))
        capability = ok(
            self.authority.issue_grant(
                principal, (self.job,) if jobs is None else jobs, frozenset(Scope)
            )
        )
        return ok(self.authority.verify(credential, capability, Scope.OBSERVE))

    def observe(self, grant, job):
        self.catalog_reads += 1
        return self.observer.observe(grant, job)

    def query(self, grant, snapshot):
        self.queries += 1
        self.before_query()
        return self.service.query(grant, snapshot)

    def adapter(
        self,
        *,
        enabled=False,
        carrier=HintCarrier.META,
        schema=None,
        grant=None,
        exclusive=True,
    ) -> SyntheticHintAdapter:
        authority: HandleAuthorityPort = self.authority
        observer: JobObservationPort = self
        receipts: ReceiptQueryPort = self
        bindings = HintBindings(
            check=lambda grant, job, scopes: authority.check(grant, job, scopes),
            observe=lambda grant, job: observer.observe(grant, job),
            select=partial(select_candidates, authority=authority, receipts=receipts),
            render=render_hint,
            hint_type=RenderedHint,
            grant_type=VerifiedRunGrant,
            job_type=JobRef,
            success_type=Success,
            observe_scope=Scope.OBSERVE,
            authorized=AuthorityDecision.AUTHORIZED,
            meta=HintCarrier.META,
            text=HintCarrier.TEXT,
        )
        return SyntheticHintAdapter(
            bindings=bindings,
            grant=self.handle if grant is None else grant,
            jobs=(self.job,),
            tool=Tool(
                name="synthetic",
                parameters={},
                output_schema=SCHEMA if schema is None else schema,
            ),
            workers=Workers(self.budget),
            server_info={"name": "I2-2 synthetic only", "version": "synthetic"},
            enabled=enabled,
            carrier=carrier,
            exclusive=exclusive,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.temp.cleanup()


def app_for(adapter, result=None, *, error=None, schema=SCHEMA):
    """The only registration point. No public Binnacle app is imported."""
    app = FastMCP("I2-2 synthetic only", version="synthetic")
    adapter.server_info = app._mcp_server.server_info_stamp
    seen = []

    def synthetic() -> ToolResult:
        if error is not None:
            raise error
        return result if result is not None else original()

    tool = app.add_tool(
        witnessed_tool(synthetic, name="synthetic", output_schema=schema)
    )
    bound_adapter = replace(adapter, tool=tool)

    app.add_middleware(ExecutionCarrier(app, bound_adapter, seen))
    return app, seen


T = TypeVar("T")


class Permit(Protocol):
    def cancel_before_start(self) -> bool: ...
    def __enter__(self) -> object: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class Admission(Protocol):
    def reserve(self) -> Permit | None: ...


class Workers:
    """Zero waiting queue; the actual worker owns its permit through cleanup."""

    def __init__(self, admission: Admission):
        self.admission = admission
        self.pending: set[asyncio.Future[Any]] = set()
        self.closed = False

    async def run(self, action: Callable[[Event], T], busy: T) -> T:
        if self.closed or (permit := self.admission.reserve()) is None:
            return busy
        loop = asyncio.get_running_loop()
        done: asyncio.Future[tuple[bool, Any]] = loop.create_future()
        stop = Event()

        def finish(outcome: tuple[bool, Any]) -> None:
            self.pending.discard(done)
            done.set_result(outcome)

        def work() -> None:
            outcome: tuple[bool, Any]
            try:
                with permit:
                    outcome = (True, action(stop))
            except BaseException as exc:  # noqa: BLE001 - deliver after worker cleanup
                outcome = (False, exc)
            loop.call_soon_threadsafe(finish, outcome)

        self.pending.add(done)
        try:
            Thread(target=work, name="synthetic-awareness").start()
        except Exception:  # noqa: BLE001 - submission failure preserves original
            self.pending.discard(done)
            permit.cancel_before_start()
            return busy
        try:
            success, value = await asyncio.shield(done)
        except asyncio.CancelledError:
            stop.set()
            raise
        if not success:
            raise value
        return value

    async def close(self) -> None:
        """Drain actual workers; cancellation does not detach them or reopen admission."""
        self.closed = True
        if self.pending:
            await asyncio.shield(asyncio.gather(*self.pending))


def worker_port(budget: WorkerBudget):
    admission: Admission = budget
    port: WorkerPort = Workers(admission)
    return port


def worker_lifetime_negative_control():
    """An insecure cancel-release adapter must fail the real SQLite barrier test."""

    from tests.contracts.job_awareness.test_hint_receipt_integration import (
        test_cancelled_awaiter_keeps_worker_permit as cancellation_probe,
    )

    real_run = Workers.run

    async def unsafe(self, action, busy):
        try:
            return await real_run(self, action, busy)
        except asyncio.CancelledError:
            self.admission._semaphore.release()
            raise

    with (
        patch.object(Workers, "run", unsafe),
        pytest.raises(pytest.fail.Exception, match="queued"),
    ):
        cancellation_probe()


async def check_explicit_bindings():
    """Real services remain composed; malformed boundary values must suppress."""

    with Lab() as lab:
        binding = lab.adapter().bindings
        assert binding.select.func is select_candidates  # nosec B101 - pytest assertion
        assert binding.render is render_hint  # nosec B101 - pytest assertion
        assert binding.success_type is Success  # nosec B101 - pytest assertion
        assert binding.grant_type is VerifiedRunGrant and binding.job_type is JobRef  # nosec B101 - pytest assertion
        with pytest.raises(FrozenInstanceError):
            binding.render = lambda *args: None
        for name, value in (
            ("check", None),
            ("observe", None),
            ("select", None),
            ("render", None),
            ("hint_type", None),
            ("grant_type", None),
            ("job_type", None),
            ("success_type", None),
            ("observe_scope", "observe"),
            ("authorized", "authorized"),
            ("meta", "META"),
            ("text", "TEXT"),
            ("text", binding.meta),
            ("text", Scope.READ),
        ):
            with pytest.raises(ValueError, match="invalid hint bindings"):
                replace(binding, **{name: value})
        with pytest.raises(ValueError, match="explicit hint bindings"):
            replace(lab.adapter(), bindings=None)
        assert HintAdapter.__dataclass_fields__["enabled"].default is False  # nosec B101 - pytest assertion
        alien = Enum("AlienCarrier", {"META": "META"})
        for name, value in (
            ("grant", object()),
            ("jobs", [lab.job]),
            ("jobs", (object(),)),
            ("jobs", (lab.job,) * 9),
            ("jobs", ()),
            ("carrier", "META"),
            ("carrier", alien.META),
            ("enabled", "true"),
            ("exclusive", 1),
            ("server_info", None),
            ("server_info", object()),
            ("server_info", {"name": "x" * 65537}),
        ):
            adapter, result = lab.adapter(enabled=True), original()
            setattr(adapter, name, value)
            assert await adapter.adapt(result) is result  # nosec B101 - pytest assertion
            assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion
        foreign_job = replace(lab.job, job_id="f" * 12)
        foreign = Observation(
            foreign_job,
            ObservationState.TERMINAL,
            lab.snapshot.terminal,
            replace(lab.snapshot, job=foreign_job, seal_id="a" * 32),
        )
        for response in (None, object(), Success(object()), Success(foreign)):
            result = original()
            with patch.object(lab, "observe", return_value=response):
                assert await lab.adapter(enabled=True).adapt(result) is result  # nosec B101 - pytest assertion
            assert lab.queries == lab.payload.reads == 0  # nosec B101 - pytest assertion
        # Both jobs are authorized, but the observer must match the requested job.
        broad = lab.consumer("9" * 32, jobs=(lab.job, foreign_job))
        ok(lab.catalog.register(foreign, lab.payload))
        adapter = lab.adapter(enabled=True, grant=broad)
        adapter.bindings = replace(
            adapter.bindings, observe=lambda grant, job: lab.observe(grant, foreign_job)
        )
        result = original()
        assert await adapter.adapt(result) is result  # nosec B101 - pytest assertion
        assert lab.queries == 0  # nosec B101 - pytest assertion
