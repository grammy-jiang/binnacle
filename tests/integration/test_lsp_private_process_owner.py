"""P2.4 private Binnacle process owner with the pinned multilspy fork.

No production MCP registration, no Binnacle Pyright adapter, no live project
writes. Real Pyright integration is explicitly opt-in; when enabled, missing
binaries fail instead of silently skipping. Workspace authority is P2.5.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_process_owner import (
    PrivatePyrightProcessOwner,
    ProviderLifecycleError,
)


@pytest.fixture
def valid_owner_profile():
    binary = os.environ.get("PYRIGHT_LSP_TEST_BIN")
    if os.environ.get("BINNACLE_PATCHED_MULTILSPY_QA") != "1":
        pytest.skip("Explicit real upstream Pyright QA opt-in required")
    assert binary, "Opt-in requires PYRIGHT_LSP_TEST_BIN"
    assert Path(binary).is_absolute() and Path(binary).is_file()
    return DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=binary,
                mode="explicit_trust_only",
                languages=("python",),
            )
        },
    )


@pytest.fixture
def workspace(tmp_path):
    root = (tmp_path / "private-project 🧭").resolve()
    root.mkdir()
    (root / "sample.py").write_text("count = 42\nanswer = count\n", encoding="utf-8")
    return root


def test_owner_module_import_does_not_eagerly_load_multilspy():
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys;"
                "import binnacle.features.development_intelligence.lsp_process_owner;"
                "assert 'multilspy' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_owner_requires_strict_explicit_trust_and_approved_profile(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(ProviderLifecycleError, match="disabled"):
        PrivatePyrightProcessOwner(DevelopmentIntelligenceSettings(), root)

    invalid = DevelopmentIntelligenceSettings(enabled=True)
    with pytest.raises(ProviderLifecycleError, match="disabled"):
        PrivatePyrightProcessOwner(invalid, root)

    candidate = tmp_path / "fake-binary"
    candidate.write_text("not executed", encoding="utf-8")
    untrusted = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="service_path",
                executable="pyright-langserver",
                mode="benchmark_only",
            )
        },
    )
    with pytest.raises(ProviderLifecycleError, match="explicit_trust"):
        PrivatePyrightProcessOwner(untrusted, root)

    unsupported = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=str(candidate),
                mode="explicit_trust_only",
                argv=("--unsafe-extra",),
            )
        },
    )
    with pytest.raises(ProviderLifecycleError, match="unaudited"):
        PrivatePyrightProcessOwner(unsupported, root)


@pytest.mark.asyncio
async def test_real_parent_lifecycle_and_sequential_reuse(
    valid_owner_profile, workspace
):
    owner = PrivatePyrightProcessOwner(valid_owner_profile, workspace)
    assert not owner.active and owner.last_exit is None
    original = (workspace / "sample.py").read_bytes()
    observed = []
    for _ in range(2):
        async with owner.session() as server:
            assert owner.active
            assert server.__class__.__name__ == "PyrightServer"
            process = server.server.process
            observed.append(process)
            assert process is not None and process.returncode is None
            with server.open_file("sample.py"):
                response = await asyncio.wait_for(
                    server.request_definition("sample.py", 1, 10), timeout=8
                )
                assert len(response) == 1
                assert response[0]["relativePath"] == "sample.py"
        assert not owner.active
        assert owner.last_exit is not None
        assert owner.last_exit.parent_exited
        assert owner.last_exit.pending_requests == 0
        assert owner.last_exit.reader_tasks == 0
        assert not owner.last_exit.cleanup_unverified
        assert owner.last_exit.descendants_audited
        assert owner.last_exit.lingering_descendants == ()
        assert not owner.last_exit.containment_verified  # OS escape proof not available
    assert observed[0] is not observed[1]
    assert all(p.returncode is not None for p in observed)
    assert (workspace / "sample.py").read_bytes() == original
    await owner.aclose()
    assert owner.closed


@pytest.mark.asyncio
async def test_real_cancelled_body_terminates_upstream_provider(
    valid_owner_profile, workspace
):
    owner = PrivatePyrightProcessOwner(valid_owner_profile, workspace)
    entered = asyncio.Event()
    never = asyncio.Event()

    async def work():
        async with owner.session() as server:
            assert server.server.process is not None
            entered.set()
            await never.wait()

    task = asyncio.create_task(work())
    await asyncio.wait_for(entered.wait(), 15)
    assert owner.active
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 20)
    assert not owner.active
    assert owner.last_exit is not None and owner.last_exit.parent_exited
    assert not owner.last_exit.cleanup_unverified


@pytest.mark.asyncio
async def test_real_body_exception_keeps_error_and_closes_process(
    valid_owner_profile, workspace
):
    owner = PrivatePyrightProcessOwner(valid_owner_profile, workspace)
    with pytest.raises(RuntimeError, match="expected fixture exception"):
        async with owner.session() as server:
            assert server.server.process is not None
            raise RuntimeError("expected fixture exception")
    assert owner.last_exit is not None
    assert owner.last_exit.parent_exited
    assert not owner.last_exit.cleanup_unverified


@pytest.mark.asyncio
async def test_owner_denies_concurrent_context_until_registry_is_built(
    valid_owner_profile, workspace
):
    owner = PrivatePyrightProcessOwner(valid_owner_profile, workspace)
    async with owner.session():
        with pytest.raises(ProviderLifecycleError, match="busy"):
            async with owner.session():
                pytest.fail("simultaneous providers must not be launched")
        assert owner.active
    assert owner.last_exit is not None and owner.last_exit.parent_exited


@pytest.mark.asyncio
async def test_owner_aclose_blocks_future_start(valid_owner_profile, workspace):
    owner = PrivatePyrightProcessOwner(valid_owner_profile, workspace)
    await owner.aclose()
    assert owner.closed
    with pytest.raises(ProviderLifecycleError, match="closed"):
        async with owner.session():
            pytest.fail("closed manager launched a provider")
    assert owner.last_exit is None


@pytest.mark.asyncio
async def test_aclose_while_session_active_reaps_process(
    valid_owner_profile, workspace
):
    owner = PrivatePyrightProcessOwner(valid_owner_profile, workspace)
    entered = asyncio.Event()
    block = asyncio.Event()
    observed = {}

    async def run():
        async with owner.session() as server:
            observed["process"] = server.server.process
            entered.set()
            await block.wait()

    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 15)
    await asyncio.wait_for(owner.aclose(), 20)
    assert owner.closed
    assert observed["process"].returncode is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 20)
    assert not owner.active
    assert owner.last_exit is not None
    assert owner.last_exit.parent_exited
    assert not owner.last_exit.cleanup_unverified
    with pytest.raises(ProviderLifecycleError, match="closed"):
        async with owner.session():
            pytest.fail("closed owner reopened")


@pytest.mark.asyncio
async def test_crashed_provider_does_not_remain_active(valid_owner_profile, workspace):
    owner = PrivatePyrightProcessOwner(valid_owner_profile, workspace)
    from multilspy.lsp_protocol_handler.server import Error

    # Crash can race either with the reader (LSP Error) or with stdin drain
    # (ConnectionResetError). Both must release process and request state.
    with pytest.raises((Error, ConnectionResetError, BrokenPipeError)):
        async with owner.session() as server:
            process = server.server.process
            assert process is not None
            process.terminate()
            await asyncio.wait_for(process.wait(), 8)
            await asyncio.wait_for(server.request_definition("sample.py", 1, 10), 3)
    assert not owner.active
    assert owner.last_exit is not None and owner.last_exit.parent_exited
    assert owner.last_exit.pending_requests == 0


def test_process_cleanup_deadline_validation(valid_owner_profile, workspace):
    for invalid in (-1, 0, 121, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="cleanup_deadline"):
            PrivatePyrightProcessOwner(
                valid_owner_profile, workspace, cleanup_timeout_s=invalid
            )


def test_rejects_pyright_executable_inside_untrusted_workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    binary = root / "pretend-pyright"
    binary.write_text("not launched", encoding="utf-8")
    profile = DevelopmentIntelligenceSettings(
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
    with pytest.raises(ProviderLifecycleError, match="inside_workspace"):
        PrivatePyrightProcessOwner(profile, root)

    # Even a trusted-looking external absolute symlink must not execute a
    # target rooted in the requested project.
    external_symlink = tmp_path / "provider-link"
    external_symlink.symlink_to(binary)
    via_symlink = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=str(external_symlink),
                mode="explicit_trust_only",
            )
        },
    )
    with pytest.raises(ProviderLifecycleError, match="inside_workspace"):
        PrivatePyrightProcessOwner(via_symlink, root)


@pytest.mark.asyncio
async def test_nonresponsive_initialization_fails_closed_without_leaking_parent(
    tmp_path,
):
    """A spawn before failed initialize must be reaped and poison the owner."""
    from multilspy import LanguageServer
    from multilspy.multilspy_config import Language, MultilspyConfig
    from multilspy.multilspy_logger import MultilspyLogger

    root = tmp_path / "workspace"
    root.mkdir()
    silent = tmp_path / "silent-init.py"
    silent.write_text(
        "import time\ntime.sleep(30)\n",
        encoding="utf-8",
    )
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
    owner = PrivatePyrightProcessOwner(profile, root, cleanup_timeout_s=15)
    server = LanguageServer.create(
        MultilspyConfig(
            code_language=Language.PYTHON,
            python_server="pyright",
            server_binary=sys.executable,
        ),
        MultilspyLogger(),
        str(root),
    )
    server.server.process_launch_info.cmd = [sys.executable, "-u", str(silent)]
    server._initialize_timeout_seconds = 0.08
    actual_start = server.server.start
    captured = []

    async def tracked_start():
        await actual_start()
        captured.append(server.server.process)

    server.server.start = tracked_start
    owner._make_upstream_server = lambda: server
    with pytest.raises(ProviderLifecycleError, match="cleanup_unverified"):
        async with owner.session():
            pytest.fail("Nonresponsive server must never enter the context")
    assert len(captured) == 1
    assert captured[0].returncode is not None
    assert server.server.process is None
    assert not server.server.tasks
    assert not server.server._response_handlers
    assert owner.last_exit is not None and owner.last_exit.cleanup_unverified
    assert not owner.last_exit.descendants_audited
    assert not owner.active
    with pytest.raises(ProviderLifecycleError, match="unverified"):
        async with owner.session():
            pytest.fail("Failed initialization must prevent unsafe reuse")
