"""P3.1 independent-review remediation: executable authority across all roots.

No subprocess or repository toolchain is launched. Cross-root executable paths
must not pass the same-host MCP read/write authority boundary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_authorized_session import (
    PrivateAuthorizedPyrightWorkspace,
)
from binnacle.features.development_intelligence.lsp_process_owner import (
    PrivatePyrightProcessOwner,
    ProviderLifecycleError,
)
from binnacle.features.development_intelligence.lsp_provider_manager import (
    PrivateProviderManager,
)

pytest_plugins = ("tests.unit.core.test_lsp_p28_owner_cleanup_branches",)


@pytest.fixture
def two_operator_roots(tmp_path):
    project_a = tmp_path / "operator-A"
    project_b = tmp_path / "operator-B"
    for project in (project_a, project_b):
        project.mkdir()
        (project / ".git").write_text("gitdir: ../private/git-metadata\n")
    (project_a / "main.py").write_text("name = 42\n")
    bad_executable = project_b / "bin" / "pyright-langserver"
    bad_executable.parent.mkdir()
    bad_executable.write_text("not a real executable; never launch it\n")
    return project_a, project_b, bad_executable


def settings(binary):
    return DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=str(binary),
                mode="explicit_trust_only",
                languages=("python",),
            )
        },
    )


def test_host_grants_multiple_roots_rejects_other_writable_workspace_binary(
    two_operator_roots,
):
    project_a, project_b, untrusted = two_operator_roots
    with pytest.raises(ProviderLifecycleError, match="inside_operator_root"):
        PrivatePyrightProcessOwner(
            settings(untrusted),
            project_a,
            operator_allowed_roots=(project_a, project_b),
        )


def test_link_outside_allowed_roots_cannot_point_inside_other_writable_root(
    two_operator_roots, tmp_path
):
    project_a, project_b, untrusted = two_operator_roots
    link = tmp_path / "untrusted-provider-external-alias"
    link.symlink_to(untrusted)
    with pytest.raises(ProviderLifecycleError, match="inside_operator_root"):
        PrivatePyrightProcessOwner(
            settings(link), project_a, operator_allowed_roots=(project_a, project_b)
        )


def test_link_inside_other_root_cannot_point_outside_and_claim_trust(
    two_operator_roots,
):
    project_a, project_b, _untrusted = two_operator_roots
    link = project_b / "system-interpreter-link"
    link.symlink_to(Path(sys.executable).resolve())
    with pytest.raises(ProviderLifecycleError, match="inside_operator_root"):
        PrivatePyrightProcessOwner(
            settings(link), project_a, operator_allowed_roots=(project_a, project_b)
        )


def test_empty_or_unrelated_root_authority_refuses_creation(
    two_operator_roots, tmp_path
):
    project_a, project_b, _untrusted = two_operator_roots
    with pytest.raises(ProviderLifecycleError, match="operator_roots_required"):
        PrivatePyrightProcessOwner(
            settings(sys.executable), project_a, operator_allowed_roots=()
        )
    unrelated = tmp_path / "not-granted"
    unrelated.mkdir()
    with pytest.raises(
        ProviderLifecycleError, match="workspace_outside_operator_roots"
    ):
        PrivatePyrightProcessOwner(
            settings(sys.executable), project_a, operator_allowed_roots=(unrelated,)
        )
    with pytest.raises(ProviderLifecycleError, match="operator_root_unavailable"):
        PrivatePyrightProcessOwner(
            settings(sys.executable),
            project_a,
            operator_allowed_roots=(project_a, tmp_path / "missing"),
        )
    with pytest.raises(ProviderLifecycleError, match="operator_root_not_directory"):
        PrivatePyrightProcessOwner(
            settings(sys.executable),
            project_a,
            operator_allowed_roots=(project_a, project_a / "main.py"),
        )
    assert project_b.exists()


def test_absolute_host_system_binary_outside_all_operator_roots_is_eligible(
    two_operator_roots,
):
    project_a, project_b, _untrusted = two_operator_roots
    owner = PrivatePyrightProcessOwner(
        settings(sys.executable),
        project_a,
        operator_allowed_roots=(project_a, project_b),
    )
    assert owner._binary == Path(sys.executable).resolve()
    assert owner._root == project_a
    assert not owner.active
    assert not owner.process_running


def test_lowest_level_owner_requires_host_roots_keyword(two_operator_roots):
    project_a, _project_b, _untrusted = two_operator_roots
    with pytest.raises(TypeError, match="operator_allowed_roots"):
        PrivatePyrightProcessOwner(settings(sys.executable), project_a)


def test_p25_authorized_facade_forwards_all_host_grants(two_operator_roots):
    project_a, project_b, untrusted = two_operator_roots
    roots = RootsSettings(default_root=project_a, extra_roots=(project_b,))
    with pytest.raises(ProviderLifecycleError, match="inside_operator_root"):
        PrivateAuthorizedPyrightWorkspace(
            settings(untrusted), roots, project_a / "main.py"
        )


@pytest.mark.asyncio
async def test_p26_manager_forwards_all_host_grants_before_launch(two_operator_roots):
    project_a, project_b, _untrusted = two_operator_roots
    roots = RootsSettings(default_root=project_a, extra_roots=(project_b,))
    observed = []

    def denied_owner(_feature_settings, root, *, operator_allowed_roots):
        observed.append((root, operator_allowed_roots))
        raise ProviderLifecycleError("fixture_stops_before_process_spawn")

    async with PrivateProviderManager(
        settings(sys.executable), roots, _owner_factory=denied_owner
    ) as manager:
        with pytest.raises(
            ProviderLifecycleError, match="fixture_stops_before_process_spawn"
        ):
            await manager.definition(
                project_a / "main.py",
                line=1,
                column=1,
                expected_symbol="name",
            )
        assert manager.resident_count == manager.pending_count == 0
    assert observed == [(project_a, (project_a, project_b))]


@pytest.mark.asyncio
async def test_owner_explicit_stop_error_poisoned_without_reuse(fake_owner_factory):
    owner, server, _tree = fake_owner_factory()
    server.server.error_on_stop = True
    with pytest.raises(ProviderLifecycleError, match="cleanup_unverified"):
        async with owner.session():
            with pytest.raises(ProviderLifecycleError, match="cleanup_unverified"):
                await owner.aclose()
            assert owner._poisoned
            assert owner.closed
    assert owner.last_exit and owner.last_exit.cleanup_unverified
    assert not owner.active


@pytest.mark.asyncio
async def test_private_fastmcp_client_cannot_launch_provider_from_other_writable_root(
    two_operator_roots, tmp_path
):
    """Actual MCP request exercises root authorization, not tool visibility."""
    from fastmcp import Client

    from binnacle.application import create_application
    from binnacle.config import Settings
    from binnacle.features.development_intelligence.lsp_preview_server import (
        PREVIEW_NAME,
    )
    from tests.command_support import MemoryCommands

    project_a, project_b, untrusted_binary = two_operator_roots
    before = untrusted_binary.read_bytes()
    app_settings = Settings(
        roots=RootsSettings(default_root=project_a, extra_roots=(project_b,)),
    )
    app_settings.jobs.owner = "embedded"
    app_settings.jobs.socket_path = tmp_path / "inert-qa-manager.sock"
    app_settings.development_intelligence = DevelopmentIntelligenceSettings(
        enabled=True,
        discovery_enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=str(untrusted_binary),
                mode="explicit_trust_only",
                languages=("python",),
            )
        },
    )
    app = create_application(
        settings=app_settings,
        token="p31-private-only-token",
        backend=MemoryCommands("p31"),
        _private_lsp_preview_gate=True,
    )
    async with Client(app) as client:
        assert PREVIEW_NAME in [item.name for item in await client.list_tools()]
        answer = await client.call_tool(
            PREVIEW_NAME,
            {
                "source_file": str(project_a / "main.py"),
                "line": 1,
                "column": 1,
                "expected_symbol": "name",
            },
            raise_on_error=False,
        )
        assert answer.is_error
        assert "private_lsp_provider_unavailable" in str(answer)
        assert str(untrusted_binary) not in str(answer)
    assert untrusted_binary.read_bytes() == before
