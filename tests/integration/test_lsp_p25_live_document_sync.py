"""P2.5 actual pinned Pyright + multilspy + Binnacle disk-authorized sync."""

import os
from pathlib import Path

import pytest
from anyio import fail_after

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_document_sync import (
    AuthorizedDocumentSession,
)
from binnacle.features.development_intelligence.lsp_process_owner import (
    PrivatePyrightProcessOwner,
)
from binnacle.features.development_intelligence.lsp_workspace_access import (
    AuthorizedWorkspace,
    WorkspaceAccessError,
    WorkspaceStaleError,
)


@pytest.fixture
def live_workspace(tmp_path):
    if os.getenv("BINNACLE_PATCHED_MULTILSPY_QA") != "1":
        pytest.skip("Explicit opt-in for real Pyright only")
    binary = os.getenv("PYRIGHT_LSP_TEST_BIN")
    assert binary and Path(binary).is_absolute() and Path(binary).is_file()
    allowed = (tmp_path / "allowed").resolve()
    root = allowed / "my-worktree"
    root.mkdir(parents=True)
    (root / ".git").write_text("gitdir: /test/worktrees/my-worktree\n")
    (root / "lib.py").write_text(
        "def greet(name: str) -> str:\n    return name.upper()\n"
    )
    (root / "app.py").write_text("from lib import greet\nanswer = greet('Ada')\n")
    settings = DevelopmentIntelligenceSettings(
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
    return allowed, root, settings


@pytest.mark.asyncio
async def test_actual_multilspy_did_open_change_close_and_fresh_definition(
    live_workspace,
):
    allowed, root, settings = live_workspace
    workspace = AuthorizedWorkspace((allowed,), root / "app.py")
    owner = PrivatePyrightProcessOwner(
        settings, workspace.workspace_root, operator_allowed_roots=(allowed,)
    )
    before = (root / "lib.py").read_bytes()
    recorded = []
    with fail_after(35):
        async with owner.session() as server:
            assert type(server).__name__ == "PyrightServer"
            for method in (
                "did_open_text_document",
                "did_change_text_document",
                "did_close_text_document",
            ):
                old = getattr(server.server.notify, method)

                def wrap(params, *, method=method, old=old):
                    recorded.append((method, params))
                    return old(params)

                setattr(server.server.notify, method, wrap)
            async with AuthorizedDocumentSession(server, workspace) as docs:
                result = await docs.definition(
                    "app.py", line=2, column=10, expected_symbol="greet"
                )
                assert result == [
                    {
                        "relativePath": "lib.py",
                        "uri": (root / "lib.py").as_uri(),
                        "range": {
                            "start": {"line": 0, "character": 4},
                            "end": {"line": 0, "character": 9},
                        },
                    }
                ]
                (root / "app.py").write_text(
                    "from lib import greet\nanswer = greet('Lin')\n"
                )
                second = await docs.definition(
                    "app.py", line=2, column=10, expected_symbol="greet"
                )
                assert second == result
                assert server.open_file_buffers == {}
                assert docs.open_documents == ("app.py",)
            assert docs.open_documents == ()
    assert [method for method, _ in recorded] == [
        "did_open_text_document",
        "did_change_text_document",
        "did_close_text_document",
    ]
    assert recorded[0][1]["textDocument"]["version"] == 1
    assert recorded[1][1]["textDocument"]["version"] == 2
    assert recorded[1][1]["contentChanges"] == [{"text": (root / "app.py").read_text()}]
    assert (root / "lib.py").read_bytes() == before
    assert owner.last_exit and owner.last_exit.parent_exited
    assert owner.last_exit.pending_requests == 0
    assert owner.last_exit.reader_tasks == 0
    assert not owner.last_exit.cleanup_unverified
    await owner.aclose()


@pytest.mark.asyncio
async def test_actual_provider_no_external_scope_and_bounded_disk_staleness(
    live_workspace, tmp_path
):
    allowed, root, settings = live_workspace
    workspace = AuthorizedWorkspace((allowed,), root / "app.py")
    owner = PrivatePyrightProcessOwner(
        settings, workspace.workspace_root, operator_allowed_roots=(allowed,)
    )
    with fail_after(30):
        async with (
            owner.session() as server,
            AuthorizedDocumentSession(server, workspace) as docs,
        ):
            with pytest.raises(WorkspaceAccessError):
                await docs.definition(
                    "../elsewhere.py", line=1, column=1, expected_symbol="x"
                )
            with pytest.raises(WorkspaceAccessError):
                await docs.definition(
                    "app.py", line=2, column=10, expected_symbol="different"
                )
            first = await docs.definition(
                "app.py", line=2, column=10, expected_symbol="greet"
            )
            assert first[0]["relativePath"] == "lib.py"
            original_method = server.server.send.definition

            async def modified_during_query(params):
                (root / "app.py").write_text(
                    "from lib import greet\nanswer = greet('changed')\n"
                )
                return await original_method(params)

            server.server.send.definition = modified_during_query
            try:
                with pytest.raises(WorkspaceStaleError):
                    await docs.definition(
                        "app.py", line=2, column=10, expected_symbol="greet"
                    )
            finally:
                server.server.send.definition = original_method
            refreshed = await docs.definition(
                "app.py", line=2, column=10, expected_symbol="greet"
            )
            assert refreshed[0]["relativePath"] == "lib.py"
    assert owner.last_exit and not owner.last_exit.cleanup_unverified


@pytest.mark.asyncio
async def test_one_shot_p25_authority_facade_with_real_upstream(live_workspace):
    from binnacle.config import RootsSettings
    from binnacle.features.development_intelligence.lsp_authorized_session import (
        PrivateAuthorizedPyrightWorkspace,
    )

    allowed, root, settings = live_workspace
    scope = PrivateAuthorizedPyrightWorkspace(
        settings,
        RootsSettings(default_root=allowed, extra_roots=()),
        root / "app.py",
    )
    assert scope.workspace_root == root
    assert scope.source_file == "app.py"
    with fail_after(25):
        async with scope.session() as docs:
            definition = await docs.definition(
                "app.py", line=2, column=10, expected_symbol="greet"
            )
            assert definition[0]["relativePath"] == "lib.py"
    assert scope.owner.last_exit and not scope.owner.last_exit.cleanup_unverified
    assert scope.owner.closed
    with pytest.raises(RuntimeError, match="already_used"):
        async with scope.session():
            pytest.fail("one-shot authority was reused")
