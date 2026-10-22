"""P2.5: authorized disk-to-LSP synchronization via native multilspy APIs.

Binnacle owns source freshness/authorization only. It never implements an LSP
transport or Pyright adapter. Calls use upstream notify.didOpen/didChange/
didClose and upstream send.definition, NOT multilspy's file-reading high-level
helpers that bypass Binnacle's descriptor-relative disk snapshots.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .lsp_session import utf16_offset
from .lsp_workspace_access import (
    AuthorizedWorkspace,
    DiskSnapshot,
    WorkspaceAccessError,
    WorkspaceStaleError,
)
from .lsp_workspace_policy import normalize_locations

_TOKEN = re.compile(r"[^\W\d]\w*", flags=re.UNICODE)
_LSP_LINE_BREAK = re.compile(r"\r\n|\r|\n")
# Local ext4/APFS timestamp updates need not be as fine as time.time_ns().
# Fail closed for recently touched, not-yet-synchronized definition targets.
# Coarser network filesystems and privileged timestamp rewrites remain outside
# P2.5's private correctness claim and need a separate OS/FS evidence gate.
_RECENT_TARGET_GUARD_NS = 25_000_000


class DocumentSyncError(RuntimeError):
    """Unreliable document/transport state: session must not be reused."""


@dataclass(frozen=True)
class _OpenDocument:
    version: int
    snapshot: DiskSnapshot


class AuthorizedDocumentSession:
    """One private provider lifetime; serializes its own document operations.

    A provider manager (P2.6) owns sharing, request scheduling and process
    cooldown. This class is always bound to an already-started upstream server.
    """

    def __init__(
        self,
        server: Any,
        workspace: AuthorizedWorkspace,
        *,
        request_timeout_s: float = 10.0,
        close_timeout_s: float = 5.0,
        max_open_documents: int = 32,
        max_definition_locations: int = 64,
    ) -> None:
        if isinstance(request_timeout_s, bool) or not 0 < request_timeout_s <= 120:
            raise ValueError("invalid_document_request_timeout")
        if isinstance(close_timeout_s, bool) or not 0 < close_timeout_s <= 30:
            raise ValueError("invalid_document_close_timeout")
        if type(max_open_documents) is not int or not 0 < max_open_documents <= 128:
            raise ValueError("invalid_document_residency_limit")
        if (
            type(max_definition_locations) is not int
            or not 0 < max_definition_locations <= 256
        ):
            raise ValueError("invalid_definition_location_limit")
        self.max_open_documents = max_open_documents
        self.max_definition_locations = max_definition_locations
        self.server = server
        self.workspace = workspace
        self.request_timeout_s = float(request_timeout_s)
        self.close_timeout_s = float(close_timeout_s)
        self._lock = asyncio.Lock()
        self._documents: dict[str, _OpenDocument] = {}
        self._entered = False
        self._closed = False
        self._poisoned = False

    @property
    def open_documents(self) -> tuple[str, ...]:
        return tuple(sorted(self._documents))

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    async def __aenter__(self) -> AuthorizedDocumentSession:  # noqa: PYI034
        if self._entered or self._closed:
            raise DocumentSyncError("document_session_not_reusable")
        if not getattr(self.server, "server_started", False):
            raise DocumentSyncError("upstream_provider_not_started")
        actual_root = Path(self.server.repository_root_path).resolve(strict=True)
        if actual_root != self.workspace.workspace_root:
            raise DocumentSyncError("provider_workspace_mismatch")
        # A provider-level manual open_file() may duplicate didOpen and read
        # the project without our file-authority guard. Refuse mixing modes.
        if self.server.open_file_buffers:
            raise DocumentSyncError("unmanaged_upstream_buffers")
        capabilities = getattr(self.server, "capabilities", {})
        if (
            not isinstance(capabilities, dict)
            or capabilities.get("positionEncoding", "utf-16") != "utf-16"
        ):
            raise DocumentSyncError("unsupported_provider_position_encoding")
        self._entered = True
        return self

    @staticmethod
    def _position(contents: str, line: int, column: int, symbol: str) -> dict[str, int]:
        """Human 1-based Python-codepoint position -> LSP UTF-16 position.

        The symbol must match the *exact token at that cursor*. Never search
        for the first equal-looking occurrence elsewhere on the line.
        """
        if (
            type(line) is not int
            or type(column) is not int
            or line <= 0
            or column <= 0
            or not isinstance(symbol, str)
            or not symbol.isidentifier()
            or len(symbol) > 128
        ):
            raise WorkspaceAccessError("invalid_symbol_anchor")
        lines = _LSP_LINE_BREAK.split(contents)
        if line > len(lines):
            raise WorkspaceAccessError("source_line_out_of_range")
        text = lines[line - 1]
        position = column - 1
        if position >= len(text):
            raise WorkspaceAccessError("source_column_out_of_range")
        if not any(
            match.start() <= position < match.end() and match.group() == symbol
            for match in _TOKEN.finditer(text)
        ):
            raise WorkspaceAccessError("symbol_anchor_mismatch")
        return {"line": line - 1, "character": utf16_offset(text, position)}

    def _sync(self, snapshot: DiskSnapshot) -> None:
        old = self._documents.get(snapshot.relative_path)
        if old is None:
            if len(self._documents) >= self.max_open_documents:
                raise WorkspaceAccessError("open_document_limit")
            self.server.server.notify.did_open_text_document(
                {
                    "textDocument": {
                        "uri": snapshot.uri,
                        "languageId": "python",
                        "version": 1,
                        "text": snapshot.contents,
                    }
                }
            )
            self._documents[snapshot.relative_path] = _OpenDocument(1, snapshot)
        elif old.snapshot.sha256 != snapshot.sha256 or (
            old.snapshot.device,
            old.snapshot.inode,
        ) != (snapshot.device, snapshot.inode):
            self.server.server.notify.did_change_text_document(
                {
                    "textDocument": {"uri": snapshot.uri, "version": old.version + 1},
                    "contentChanges": [{"text": snapshot.contents}],
                }
            )
            self._documents[snapshot.relative_path] = _OpenDocument(
                old.version + 1, snapshot
            )
        else:
            # Identical contents still record the newest disk identity/mtime.
            self._documents[snapshot.relative_path] = _OpenDocument(
                old.version, snapshot
            )

    async def definition(
        self,
        relative_file: str,
        *,
        line: int,
        column: int,
        expected_symbol: str,
    ) -> list[dict]:
        if not self._entered or self._closed or self._poisoned:
            raise DocumentSyncError("document_session_not_available")
        async with self._lock:
            if self._closed or self._poisoned:
                raise DocumentSyncError("document_session_not_available")
            if not self.server.server_started:
                self._poisoned = True
                raise DocumentSyncError("provider_stopped_during_session")
            if self.server.open_file_buffers:
                self._poisoned = True
                raise DocumentSyncError("unmanaged_upstream_buffers")
            snapshot = self.workspace.snapshot(relative_file)
            position = self._position(snapshot.contents, line, column, expected_symbol)
            # Disk identity races are a source admission failure, not an LSP
            # notification failure. Only actual notify failures poison state.
            self.workspace.assert_fresh(snapshot)
            try:
                self._sync(snapshot)
            except WorkspaceAccessError:
                raise
            except Exception as exc:
                self._poisoned = True
                raise DocumentSyncError("document_notification_failed") from exc
            request_started_ns = time.time_ns()
            try:
                response = await asyncio.wait_for(
                    self.server.server.send.definition(
                        {
                            "textDocument": {"uri": snapshot.uri},
                            "position": position,
                        }
                    ),
                    timeout=self.request_timeout_s,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                # Even though patched multilspy unregisters cancelled JSON-RPC
                # requests, a late response may reflect an older document.
                # The one-shot owner must be closed before another request.
                self._poisoned = True
                raise
            if self._closed or self._poisoned:
                raise DocumentSyncError("document_session_closed_during_request")
            self.workspace.assert_fresh(snapshot)
            locations = normalize_locations(self.workspace.workspace_root, response)
            if len(locations) > self.max_definition_locations:
                raise WorkspaceAccessError("definition_location_limit")
            safe = []
            targets: dict[str, DiskSnapshot] = {}
            for entry in locations:
                target = targets.get(entry["uri"])
                if target is None:
                    target = self.workspace.snapshot_uri(entry["uri"])
                    targets[entry["uri"]] = target
                current_buffer = self._documents.get(target.relative_path)
                if current_buffer is not None and (
                    current_buffer.snapshot.sha256 != target.sha256
                    or (
                        current_buffer.snapshot.device,
                        current_buffer.snapshot.inode,
                        current_buffer.snapshot.mtime_ns,
                        current_buffer.snapshot.ctime_ns,
                    )
                    != (target.device, target.inode, target.mtime_ns, target.ctime_ns)
                ):
                    # Pyright may still be using a previous didOpen buffer for
                    # a returned target even if it changed before this query.
                    raise WorkspaceStaleError("open_document_buffer_stale")
                if (
                    current_buffer is None
                    and max(target.mtime_ns, target.ctime_ns)
                    >= request_started_ns - _RECENT_TARGET_GUARD_NS
                ):
                    # An unopened target has no pre-request baseline. A recent
                    # timestamp, including the filesystem's coarse clock
                    # uncertainty window, is conservatively stale.
                    raise WorkspaceStaleError(
                        "definition_target_modified_during_request"
                    )
                # LSP recognizes CRLF, CR and LF only. splitlines() also
                # treats U+2028 and form feeds as breaks, shifting positions.
                lines = _LSP_LINE_BREAK.split(target.contents)
                span = entry["range"]
                left, right = span["start"], span["end"]
                for endpoint in (left, right):
                    line_index = endpoint["line"]
                    if line_index >= len(lines) or endpoint["character"] > utf16_offset(
                        lines[line_index], len(lines[line_index])
                    ):
                        raise WorkspaceStaleError("provider_result_range_out_of_date")
                if (left["line"], left["character"]) > (
                    right["line"],
                    right["character"],
                ):
                    raise WorkspaceStaleError("provider_result_range_out_of_date")
                safe.append(
                    {
                        "relativePath": target.relative_path,
                        "uri": target.uri,
                        "range": entry["range"],
                    }
                )
            for target in targets.values():
                self.workspace.assert_fresh(target)
            return safe

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.close_timeout_s)
        except asyncio.TimeoutError as exc:
            self._poisoned = True
            raise DocumentSyncError("document_close_unverified") from exc
        try:
            failure = None
            for document in tuple(self._documents.values()):
                try:
                    if not self.server.server_started:
                        raise RuntimeError("provider not running")
                    self.server.server.notify.did_close_text_document(
                        {"textDocument": {"uri": document.snapshot.uri}}
                    )
                except Exception as exc:  # noqa: BLE001 - drain all close operations
                    self._poisoned = True
                    if failure is None:
                        failure = exc
                finally:
                    self._documents.pop(document.snapshot.relative_path, None)
            if failure is not None:
                raise DocumentSyncError("document_close_unverified") from failure
        finally:
            self._lock.release()

    async def __aexit__(self, _kind, _value, _traceback) -> None:
        await self.aclose()
