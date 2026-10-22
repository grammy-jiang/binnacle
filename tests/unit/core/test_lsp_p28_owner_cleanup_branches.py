"""P2.8 P2.4 owner faults with fake lifecycle and zero process signals.

No subprocess is created. Native POSIX tree/real Pyright tests remain separate.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence import lsp_process_owner as provider
from binnacle.features.development_intelligence.lsp_process_owner import (
    PrivatePyrightProcessOwner,
    ProviderLifecycleError,
)
from binnacle.features.development_intelligence.lsp_process_tree import ProcessCleanup


class FakeHandler:
    def __init__(self, process):
        self.process = process
        self.stop_calls = 0
        self.error_on_stop = False
        self._response_handlers = {}
        self.tasks = {}

    async def stop(self):
        self.stop_calls += 1
        if self.error_on_stop:
            raise OSError("simulated failed LSP stop")
        if self.process is not None:
            self.process.returncode = 0
            self.process = None


class FakeUpstream:
    def __init__(self):
        self.server = FakeHandler(SimpleNamespace(pid=46551, returncode=None))
        self.auto_stop = True
        self.no_process = False
        self.on_start = None

    @asynccontextmanager
    async def start_server(self):
        if self.no_process:
            self.server.process = None
        if self.on_start is not None:
            self.on_start()
        try:
            yield self
        finally:
            if self.auto_stop and self.server.process is not None:
                self.server.process.returncode = 0
                self.server.process = None


class FakeNativeTree:
    def __init__(self):
        self.root = None
        self.members = {}
        self.escaped = set()
        self.observations = 0
        self.cleanup_fault = False

    def capture(self, pid):
        self.root = SimpleNamespace(pid=pid)
        self.members[pid] = self.root

    def observe(self):
        self.observations += 1

    async def cleanup(self):
        if self.cleanup_fault:
            raise OSError("synthetic tree cleanup uncertainty")
        return ProcessCleanup(
            status="observed_clean" if self.root else "cleanup_unverified",
            root_pid=self.root.pid if self.root else None,
            observed_descendants=0,
            escaped_descendants=0,
            remaining=(),
            reason="synthetic no-signals",
        )


@pytest.fixture
def fake_owner_factory(tmp_path, monkeypatch):
    project = (tmp_path / "worktree").resolve()
    project.mkdir()
    profile = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=sys.executable,
                mode="explicit_trust_only",
            )
        },
    )
    tree = FakeNativeTree()
    monkeypatch.setattr(provider, "NativeProviderTree", lambda: tree)

    def factory(*, cleanup_timeout_s=2):
        owner = PrivatePyrightProcessOwner(
            profile, project, cleanup_timeout_s=cleanup_timeout_s
        )
        upstream = FakeUpstream()
        monkeypatch.setattr(owner, "_make_upstream_server", lambda: upstream)
        return owner, upstream, tree

    return factory


@pytest.mark.asyncio
async def test_normal_fake_owner_process_lifetime_and_explicit_stop(fake_owner_factory):
    owner, upstream, tree = fake_owner_factory()
    assert not owner.process_running
    with pytest.raises(ProviderLifecycleError, match="not_active"):
        owner.observe_owned_processes()
    async with owner.session() as active:
        assert active is upstream and owner.process_running
        owner.observe_owned_processes()
        assert tree.observations >= 2
        await owner.aclose()
        assert not owner.process_running and owner.closed
    assert owner.last_exit is not None
    assert owner.last_exit.parent_exited
    assert owner.last_exit.descendants_audited
    assert owner.last_exit.cleanup_unverified is False
    assert upstream.server.stop_calls == 1
    with pytest.raises(ProviderLifecycleError, match="closed"):
        async with owner.session():
            pytest.fail("closed owner restarted")


@pytest.mark.asyncio
async def test_owner_backstop_stops_provider_that_outlived_context(fake_owner_factory):
    owner, upstream, _tree = fake_owner_factory()
    upstream.auto_stop = False
    async with owner.session():
        assert upstream.server.process is not None
    assert upstream.server.stop_calls == 1
    assert owner.last_exit and owner.last_exit.parent_exited
    assert not owner.last_exit.cleanup_unverified
    assert upstream.server.process is None
    assert not owner.active


@pytest.mark.asyncio
async def test_owner_backstop_stop_error_poisoned_without_silent_success(
    fake_owner_factory,
):
    owner, upstream, _tree = fake_owner_factory()
    upstream.auto_stop = False
    upstream.server.error_on_stop = True
    with pytest.raises(ProviderLifecycleError, match="cleanup_unverified"):
        async with owner.session():
            assert owner.process_running
    assert owner.last_exit and owner.last_exit.cleanup_unverified
    assert not owner.active
    with pytest.raises(ProviderLifecycleError, match="unverified"):
        async with owner.session():
            pytest.fail("poisoned owner reopened")


@pytest.mark.asyncio
async def test_tree_cleanup_exception_fail_closes_even_if_parent_stopped(
    fake_owner_factory,
):
    owner, _upstream, tree = fake_owner_factory()
    tree.cleanup_fault = True
    with pytest.raises(ProviderLifecycleError, match="cleanup_unverified"):
        async with owner.session():
            assert owner.process_running
    assert owner.last_exit and owner.last_exit.cleanup_unverified
    assert not owner.active


@pytest.mark.asyncio
async def test_no_spawned_process_is_not_a_clean_owner_exit(fake_owner_factory):
    owner, upstream, _tree = fake_owner_factory()
    upstream.no_process = True
    with pytest.raises(ProviderLifecycleError, match="cleanup_unverified"):
        async with owner.session():
            pytest.fail("missing upstream process accepted")
    assert owner.last_exit and owner.last_exit.cleanup_unverified
    assert not owner.last_exit.parent_exited
    assert not owner.active


@pytest.mark.asyncio
async def test_closed_in_startup_cannot_yield_provider(fake_owner_factory):
    owner, upstream, _tree = fake_owner_factory()
    upstream.on_start = lambda: setattr(owner, "_closed", True)
    with pytest.raises(ProviderLifecycleError, match="closed_during_startup"):
        async with owner.session():
            pytest.fail("late-started provider admitted")
    assert owner.closed and not owner.active
    assert owner.last_exit is not None


@pytest.mark.asyncio
async def test_owner_second_context_while_busy_denied(fake_owner_factory):
    owner, _upstream, _tree = fake_owner_factory()
    async with owner.session():
        with pytest.raises(ProviderLifecycleError, match="busy"):
            async with owner.session():
                pytest.fail("two providers in one owner")
    assert not owner.active


def test_owner_rejects_unavailable_executable_and_non_directory_root(tmp_path):
    root = tmp_path / "worktree"
    root.mkdir()

    def settings(binary):
        return DevelopmentIntelligenceSettings(
            enabled=True,
            profiles={
                "pyright": DevelopmentProviderSettings(
                    enabled=True,
                    source="trusted_absolute",
                    executable=str(binary),
                    mode="explicit_trust_only",
                )
            },
        )

    with pytest.raises(ProviderLifecycleError, match="executable_unavailable"):
        PrivatePyrightProcessOwner(settings("/nonexistent/pyright"), root)
    document = tmp_path / "not-a-directory.py"
    document.write_text("value = 4\n")
    with pytest.raises(ProviderLifecycleError, match="workspace_not_directory"):
        PrivatePyrightProcessOwner(settings(sys.executable), document)
    for invalid in (True, "3", 0, -1, 121):
        with pytest.raises(ValueError, match="cleanup_deadline"):
            PrivatePyrightProcessOwner(
                settings(sys.executable), root, cleanup_timeout_s=invalid
            )


@pytest.mark.asyncio
async def test_aborting_unresponsive_pre_enter_session_marks_cleanup_uncertain(
    fake_owner_factory,
):
    owner, _upstream, _tree = fake_owner_factory(cleanup_timeout_s=0.02)
    started = asyncio.Event()
    release = asyncio.Event()

    async def unresponsive_start():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    task = asyncio.create_task(unresponsive_start())
    await asyncio.wait_for(started.wait(), 1)
    owner._active = True
    owner._entered = False
    owner._session_task = task
    with pytest.raises(ProviderLifecycleError, match="cleanup_unverified"):
        await asyncio.wait_for(owner.aclose(), 0.5)
    assert owner._poisoned and owner.closed
    release.set()
    await asyncio.wait_for(task, 1)


def test_upstream_factory_is_native_library_not_local_pyright_adapter(
    fake_owner_factory, monkeypatch
):
    owner, _upstream, _tree = fake_owner_factory()
    # This P2.8 unit test verifies the original native factory with no
    # provider start; it may import the pinned optional multilspy extra.
    from binnacle.features.development_intelligence.lsp_process_owner import (
        PrivatePyrightProcessOwner as ActualClass,
    )

    server = ActualClass._make_upstream_server(owner)
    assert type(server).__name__ == "PyrightServer"
    assert server.repository_root_path == str(owner._root)
    assert not owner.active and not owner.process_running
