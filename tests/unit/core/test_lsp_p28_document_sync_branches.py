"""P2.8 document lifecycle/validation branches with an in-memory LSP facade."""

from __future__ import annotations

import asyncio

import pytest

from binnacle.features.development_intelligence.lsp_document_sync import (
    AuthorizedDocumentSession,
    DocumentSyncError,
)
from binnacle.features.development_intelligence.lsp_workspace_access import (
    WorkspaceStaleError,
)

pytest_plugins = ("tests.unit.core.test_lsp_document_sync_p25",)


@pytest.mark.parametrize(
    "options",
    [
        {"request_timeout_s": 0},
        {"request_timeout_s": True},
        {"close_timeout_s": -1},
        {"close_timeout_s": True},
        {"max_open_documents": 0},
        {"max_open_documents": True},
        {"max_definition_locations": 0},
        {"max_definition_locations": 257},
    ],
)
def test_invalid_document_limits_not_accepted(documents, options):
    server, workspace, *_ = documents
    with pytest.raises(ValueError, match="invalid_(document|definition)_"):
        AuthorizedDocumentSession(server, workspace, **options)


@pytest.mark.asyncio
async def test_unentered_document_query_and_stopped_provider_refuse(documents):
    server, workspace, notices, _send, _entry = documents
    client = AuthorizedDocumentSession(server, workspace)
    with pytest.raises(DocumentSyncError, match="not_available"):
        await client.definition("main.py", line=2, column=10, expected_symbol="greet")
    async with client:
        server.server_started = False
        with pytest.raises(DocumentSyncError, match="provider_stopped"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
        assert client.poisoned
    assert notices.events == []


@pytest.mark.asyncio
async def test_previously_unmanaged_document_added_mid_session_poisoned(documents):
    server, workspace, _notices, _send, _entry = documents
    async with AuthorizedDocumentSession(server, workspace) as client:
        server.open_file_buffers["untracked"] = object()
        with pytest.raises(DocumentSyncError, match="unmanaged_upstream_buffers"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
        assert client.poisoned
        server.open_file_buffers.clear()


@pytest.mark.asyncio
async def test_late_query_after_close_refused_inside_document_lock(documents):
    server, workspace, _notices, _send, _entry = documents
    client = AuthorizedDocumentSession(server, workspace)
    await client.__aenter__()
    await client._lock.acquire()
    task = asyncio.create_task(
        client.definition("main.py", line=2, column=10, expected_symbol="greet")
    )
    await asyncio.sleep(0)
    client._closed = True
    client._lock.release()
    with pytest.raises(DocumentSyncError, match="not_available"):
        await asyncio.wait_for(task, 1)


@pytest.mark.asyncio
async def test_nonmonotone_definition_range_rejected(documents):
    server, workspace, _notice, send, _entry = documents

    async def reversed_location(_args):
        return [
            {
                "uri": send.target.as_uri(),
                "range": {
                    "start": {"line": 1, "character": 7},
                    "end": {"line": 0, "character": 1},
                },
            }
        ]

    send.definition = reversed_location
    async with AuthorizedDocumentSession(server, workspace) as client:
        with pytest.raises(WorkspaceStaleError, match="range_out_of_date"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )


@pytest.mark.asyncio
async def test_same_target_references_do_not_resnapshot_on_each_result(
    documents, monkeypatch
):
    server, workspace, _notice, send, _entry = documents
    original_snapshot_uri = workspace.snapshot_uri
    visited = []

    def snapshot_once(uri):
        visited.append(uri)
        return original_snapshot_uri(uri)

    async def duplicates(_args):
        result = {
            "uri": send.target.as_uri(),
            "range": {
                "start": {"line": 0, "character": 4},
                "end": {"line": 0, "character": 9},
            },
        }
        return [result, result]

    monkeypatch.setattr(workspace, "snapshot_uri", snapshot_once)
    send.definition = duplicates
    async with AuthorizedDocumentSession(server, workspace) as client:
        results = await client.definition(
            "main.py", line=2, column=10, expected_symbol="greet"
        )
        assert len(results) == 2 and len(visited) == 1


@pytest.mark.asyncio
async def test_close_when_provider_disappeared_is_fail_closed(documents):
    server, workspace, notices, _send, _entry = documents
    client = AuthorizedDocumentSession(server, workspace)
    await client.__aenter__()
    await client.definition("main.py", line=2, column=10, expected_symbol="greet")
    server.server_started = False
    with pytest.raises(DocumentSyncError, match="close_unverified"):
        await client.aclose()
    assert client.poisoned and client.open_documents == ()
    assert [name for name, _ in notices.events] == ["open"]


@pytest.mark.asyncio
async def test_did_change_transport_error_poisoned_and_does_not_reuse(documents):
    server, workspace, notice, _send, entry = documents
    async with AuthorizedDocumentSession(server, workspace) as client:
        await client.definition("main.py", line=2, column=10, expected_symbol="greet")
        entry.write_text("from lib import greet\nresult = greet('Lin')\n")

        def failed_notification(_params):
            raise OSError("synthetic pipe went away")

        server.server.notify.did_change_text_document = failed_notification
        with pytest.raises(DocumentSyncError, match="document_notification_failed"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
        assert client.poisoned
    assert [name for name, _ in notice.events] == ["open", "close"]
