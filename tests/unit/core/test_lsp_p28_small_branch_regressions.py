"""P2.8 missing normal/error branches, without relaxing coverage requirements.

No actual provider process or untrusted filesystem operations are required.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from binnacle.config import RootsSettings
from binnacle.features.development_intelligence import lsp_authorized_session
from binnacle.features.development_intelligence.lsp_manager_cooldown import (
    record_failure,
)
from binnacle.features.development_intelligence.lsp_manager_shutdown import (
    abort_cold_start,
    finish_manager_close,
)
from binnacle.features.development_intelligence.lsp_manager_types import (
    Cooldown,
    ManagedProvider,
)
from binnacle.features.development_intelligence.lsp_policy import (
    server_request_reply,
)
from binnacle.features.development_intelligence.lsp_wire import (
    LspFrameDecoder,
    LspProtocolError,
)
from binnacle.features.development_intelligence.lsp_workspace_access import (
    AuthorizedWorkspace,
)


@pytest.fixture
def authorized_source(tmp_path):
    grant = (tmp_path / "approved").resolve()
    project = grant / "source"
    project.mkdir(parents=True)
    (project / ".git").write_text("gitdir: ../.git/worktrees/source\n")
    source = project / "simple.py"
    source.write_text("value = 1\n")
    return RootsSettings(default_root=grant, extra_roots=()), source


@pytest.mark.asyncio
async def test_one_shot_workspace_facade_lifecycle_and_failure_cleanup(
    authorized_source, monkeypatch
):
    roots, source = authorized_source
    events = []

    class Owner:
        def __init__(self, _settings, root, *, operator_allowed_roots):
            self.root = root
            assert root.is_relative_to(operator_allowed_roots[0])

        @asynccontextmanager
        async def session(self):
            events.append("owner-enter")
            yield SimpleNamespace(server_started=True)
            events.append("owner-exit")

        async def aclose(self):
            events.append("owner-close")

    class Docs:
        def __init__(self, server, workspace):
            assert server.server_started
            self.workspace = workspace

        async def __aenter__(self):
            events.append("docs-enter")
            return self

        async def __aexit__(self, _kind, _value, _tb):
            events.append("docs-exit")

    monkeypatch.setattr(lsp_authorized_session, "PrivatePyrightProcessOwner", Owner)
    monkeypatch.setattr(lsp_authorized_session, "AuthorizedDocumentSession", Docs)
    facade = lsp_authorized_session.PrivateAuthorizedPyrightWorkspace(
        object(), roots, source
    )
    assert facade.workspace_root == source.parent
    assert facade.source_file == "simple.py"
    async with facade.session() as documents:
        assert isinstance(documents, Docs)
    assert events == [
        "owner-enter",
        "docs-enter",
        "docs-exit",
        "owner-exit",
        "owner-close",
    ]
    with pytest.raises(RuntimeError, match="already_used"):
        async with facade.session():
            pytest.fail("one-shot manager reentered")


@pytest.mark.asyncio
async def test_one_shot_facade_closes_owner_on_error(authorized_source, monkeypatch):
    roots, source = authorized_source
    observed = []

    class BrokenOwner:
        def __init__(self, *_args, operator_allowed_roots):
            assert operator_allowed_roots == roots.canonical_allowed

        @asynccontextmanager
        async def session(self):
            observed.append("starting")
            raise RuntimeError("simulated private provider failure")
            yield  # keep a real async contextmanager generator

        async def aclose(self):
            observed.append("closed")

    monkeypatch.setattr(
        lsp_authorized_session, "PrivatePyrightProcessOwner", BrokenOwner
    )
    facade = lsp_authorized_session.PrivateAuthorizedPyrightWorkspace(
        object(), roots, source
    )
    with pytest.raises(RuntimeError, match="simulated"):
        async with facade.session():
            pytest.fail("failed provider returned")
    assert observed == ["starting", "closed"]


def _provider(index: int, *, fatal: bool = False, error: str | None = None):
    key = Path("/test-keys") / str(index), (1, index), "pyright"
    return ManagedProvider(
        # Cooldown is pure bookkeeping and never dereferences workspace.
        key=key,
        workspace=cast(AuthorizedWorkspace, object()),
        owner=None,
        fatal=fatal,
        error=error,
    )


def test_cooldown_expired_unrelated_key_and_oldest_prune():
    current = _provider(400)
    stale = _provider(1)
    registry = {stale.key: Cooldown(2.0, 3, "stale")}
    record_failure(registry, current, now=3.0, base_seconds=2.0, max_seconds=20.0)
    assert stale.key not in registry
    assert registry[current.key].failures == 1
    assert registry[current.key].until == 5.0

    registry = {
        item.key: Cooldown(float(10 + number), 1, "previous")
        for number in range(128)
        for item in [_provider(number)]
    }
    next_entry = _provider(129)
    record_failure(registry, next_entry, now=1.0, base_seconds=2, max_seconds=8)
    assert len(registry) == 128
    assert _provider(0).key not in registry
    assert next_entry.key in registry


def test_fatal_cooldown_and_consecutive_backoff_are_preserved():
    entry = _provider(5, fatal=True, error="cleanup_unverified")
    registry = {}
    record_failure(registry, entry, now=10.0, base_seconds=1, max_seconds=8)
    assert registry[entry.key].fatal
    assert registry[entry.key].until == float("inf")
    entry.fatal = False
    record_failure(registry, entry, now=100.0, base_seconds=1, max_seconds=8)
    assert registry[entry.key].failures == 2
    assert registry[entry.key].until == 102.0


@pytest.mark.asyncio
async def test_shutdown_aborted_owner_close_marks_cleanup_unverified():
    entered = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()

    class BlockedOwner:
        async def aclose(self):
            entered.set()
            await release.wait()
            closed.set()

    entry = SimpleNamespace(owner=BlockedOwner(), fatal=False, error=None)
    waiter = asyncio.create_task(abort_cold_start(entry, seconds=2))
    await asyncio.wait_for(entered.wait(), 1)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert entry.fatal and entry.error == "provider_cleanup_unverified"
    release.set()
    await asyncio.wait_for(closed.wait(), 1)


@pytest.mark.asyncio
async def test_shutdown_worker_timeout_cancels_laggards_and_reports_uncertainty():
    begun = asyncio.Event()

    async def blocked_worker():
        begun.set()
        await asyncio.Event().wait()

    worker = asyncio.create_task(blocked_worker())
    await asyncio.wait_for(begun.wait(), 1)
    entry = SimpleNamespace(
        worker=worker,
        stop=asyncio.Event(),
        state="ready",
        finished=asyncio.Event(),
        fatal=False,
    )
    manager = SimpleNamespace(
        _sweeper=None,
        _lock=asyncio.Lock(),
        _entries={"one": entry},
        _callers=set(),
        _shutdown_timeout=0.03,
        _unsafe_cleanup=False,
        _history=[],
        _closed=False,
        _shutdown=None,
    )
    result = await asyncio.wait_for(finish_manager_close(manager), 1)
    assert worker.cancelled() and entry.stop.is_set()
    assert result.instances_stopped == 0 and result.cleanup_unverified
    assert manager._closed


@pytest.mark.parametrize(
    "message",
    [
        {"id": 1, "method": ""},
        {"id": 1, "method": []},
    ],
)
def test_invalid_server_method_is_never_processed(message):
    with pytest.raises(LspProtocolError, match="invalid_server_request_method"):
        server_request_reply(message)


def test_configuration_wrong_container_is_refused_and_message_not_executed():
    reply = server_request_reply(
        {"id": 2, "method": "workspace/configuration", "params": 3}
    )
    assert reply["error"]["code"] == -32602
    progress = server_request_reply(
        {"id": "token", "method": "window/showMessageRequest"}
    )
    assert progress == {"jsonrpc": "2.0", "id": "token", "result": None}


@pytest.mark.parametrize(
    "header,code",
    [
        (b"", "empty_header"),
        (b"Bad Header: 5", "invalid_header"),
        (b"Content-Length: 1\x01", "invalid_header_value"),
    ],
)
def test_frame_bad_header_rejected(header, code):
    decoder = LspFrameDecoder()
    with pytest.raises(LspProtocolError, match=code):
        decoder.feed(header + b"\r\n\r\n{}")


def test_decoder_constructor_bounds_and_nonbyte_fragment():
    with pytest.raises(ValueError, match="invalid_lsp_frame_limits"):
        LspFrameDecoder(max_header=12)
    with pytest.raises(TypeError, match="frame_fragment_must_be_bytes"):
        LspFrameDecoder().feed("not binary")
