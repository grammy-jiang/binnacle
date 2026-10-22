"""P2.5 host-root authority and one-shot provider binding (no provider start)."""

from __future__ import annotations

from pathlib import Path

import pytest

from binnacle.config import RootsSettings
from binnacle.config_development_intelligence import DevelopmentIntelligenceSettings
from binnacle.features.development_intelligence.lsp_authorized_session import (
    PrivateAuthorizedPyrightWorkspace,
)
from binnacle.features.development_intelligence.lsp_process_owner import (
    ProviderLifecycleError,
)
from binnacle.features.development_intelligence.lsp_workspace_access import (
    WorkspaceAccessError,
)


@pytest.fixture
def source_and_roots(tmp_path):
    granted = (tmp_path / "operator-granted").resolve()
    worktree = granted / "python-worktree"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: ../../private-metadata\n")
    source = worktree / "main.py"
    source.write_text("value = 42\n", encoding="utf-8")
    roots = RootsSettings(default_root=granted, extra_roots=())
    return roots, source, worktree


def test_authorization_precedes_provider_construction(source_and_roots):
    roots, source, _worktree = source_and_roots
    with pytest.raises(ProviderLifecycleError, match="disabled"):
        PrivateAuthorizedPyrightWorkspace(
            DevelopmentIntelligenceSettings(), roots, source
        )


def test_explicit_host_roots_not_client_selected(source_and_roots, tmp_path):
    roots, source, _worktree = source_and_roots
    denied_roots = RootsSettings(default_root=tmp_path / "different", extra_roots=())
    with pytest.raises(WorkspaceAccessError):
        PrivateAuthorizedPyrightWorkspace(
            DevelopmentIntelligenceSettings(), denied_roots, source
        )
    assert roots.canonical_allowed == (source.parents[1],)


def test_parent_root_fallback_cannot_bypass_disabled_provider(source_and_roots):
    roots, source, worktree = source_and_roots
    assert worktree in source.parents
    with pytest.raises(ProviderLifecycleError, match="disabled"):
        PrivateAuthorizedPyrightWorkspace(
            DevelopmentIntelligenceSettings(),
            roots,
            source,
            allow_parent_fallback=True,
        )


def test_source_path_untrusted_configuration_root_is_not_executable(source_and_roots):
    roots, source, _worktree = source_and_roots
    # No caller-provided workspace root, executable path or LSP argv is accepted.
    with pytest.raises(TypeError):
        PrivateAuthorizedPyrightWorkspace(
            DevelopmentIntelligenceSettings(),
            roots,
            source,
            workspace_root=Path.home(),
        )
