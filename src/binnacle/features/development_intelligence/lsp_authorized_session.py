"""P2.5 private admission: bind host roots, P2.4 owner and disk document sync.

Not an MCP tool, manager registry or Pyright adapter. Construction authorizes
exact source scope before a provider could be spawned. P2.6 will supply the
provider reuse/concurrency policy; this facade is deliberately one-shot.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from .lsp_document_sync import AuthorizedDocumentSession
from .lsp_process_owner import PrivatePyrightProcessOwner
from .lsp_workspace_access import AuthorizedWorkspace


class PrivateAuthorizedPyrightWorkspace:
    """Opt-in, private, explicitly trusted one-workspace provider session."""

    def __init__(
        self,
        feature_settings: Any,
        roots_settings: Any,
        requested_file: str | Path,
        *,
        allow_parent_fallback: bool = False,
    ) -> None:
        # RootsSettings.canonical_allowed is a first-use pinned snapshot of
        # operator-granted roots. Never derive authority from Pyright results,
        # repository configuration, LSP capabilities or a client-supplied root.
        operator_roots = tuple(roots_settings.canonical_allowed)
        self.workspace = AuthorizedWorkspace(
            operator_roots,
            requested_file,
            allow_parent_fallback=allow_parent_fallback,
        )
        self.owner = PrivatePyrightProcessOwner(
            feature_settings,
            self.workspace.workspace_root,
            operator_allowed_roots=operator_roots,
        )
        self._used = False

    @property
    def workspace_root(self) -> Path:
        return self.workspace.workspace_root

    @property
    def source_file(self) -> str:
        return self.workspace.source_file

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AuthorizedDocumentSession]:
        if self._used:
            raise RuntimeError("authorized_workspace_session_already_used")
        self._used = True
        try:
            async with (
                self.owner.session() as server,
                AuthorizedDocumentSession(server, self.workspace) as docs,
            ):
                yield docs
        finally:
            await self.owner.aclose()
