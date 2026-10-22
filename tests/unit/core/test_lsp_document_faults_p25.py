"""Bounded, fail-closed lifecycle behavior for the private document session."""

import asyncio

import pytest

from binnacle.features.development_intelligence.lsp_document_sync import (
    AuthorizedDocumentSession,
    DocumentSyncError,
)
from binnacle.features.development_intelligence.lsp_workspace_access import (
    WorkspaceAccessError,
    WorkspaceStaleError,
)

pytest_plugins = ("tests.unit.core.test_lsp_document_sync_p25",)


@pytest.mark.asyncio
async def test_parallel_requests_are_ordered_and_do_not_reopen(documents):
    server, workspace, notifications, send, _entry = documents
    arrived = asyncio.Event()
    release = asyncio.Event()

    async def hold_first_response():
        if len(send.calls) == 1:
            arrived.set()
            await release.wait()

    send.hook = hold_first_response
    async with AuthorizedDocumentSession(server, workspace) as client:
        first = asyncio.create_task(
            client.definition("main.py", line=2, column=10, expected_symbol="greet")
        )
        await asyncio.wait_for(arrived.wait(), 1)
        second = asyncio.create_task(
            client.definition("main.py", line=2, column=10, expected_symbol="greet")
        )
        await asyncio.sleep(0)
        assert len(send.calls) == 1
        release.set()
        one, two = await asyncio.wait_for(asyncio.gather(first, second), 2)
        assert one == two
        assert len(send.calls) == 2
    assert [name for name, _ in notifications.events] == ["open", "close"]


@pytest.mark.asyncio
async def test_provider_results_must_fit_current_disk_file(documents):
    server, workspace, _notifications, send, _entry = documents
    original = send.definition

    async def mismatched_range(params):
        results = await original(params)
        results[0]["range"]["start"]["line"] = 10000
        return results

    send.definition = mismatched_range
    async with AuthorizedDocumentSession(server, workspace) as client:
        with pytest.raises(WorkspaceStaleError, match="range_out_of_date"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )


@pytest.mark.asyncio
async def test_wrong_position_encoding_denied_before_notifications(documents):
    server, workspace, notifications, _send, _entry = documents
    server.capabilities = {"positionEncoding": "utf-8"}
    with pytest.raises(DocumentSyncError, match="position_encoding"):
        async with AuthorizedDocumentSession(server, workspace):
            pytest.fail("incompatible provider accepted")
    assert notifications.events == []


@pytest.mark.asyncio
async def test_existing_unmanaged_upstream_buffer_is_rejected(documents):
    server, workspace, notifications, _send, _entry = documents
    server.open_file_buffers["preexisting"] = object()
    with pytest.raises(DocumentSyncError, match="unmanaged"):
        async with AuthorizedDocumentSession(server, workspace):
            pytest.fail("second file reader accepted")
    assert notifications.events == []


@pytest.mark.asyncio
async def test_failure_during_did_open_poisoned_and_fails_closed(documents):
    server, workspace, _notifications, _send, _entry = documents

    def broken_open(_params):
        raise RuntimeError("test notification rejected")

    server.server.notify.did_open_text_document = broken_open
    async with AuthorizedDocumentSession(server, workspace) as client:
        with pytest.raises(DocumentSyncError, match="notification_failed"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
        assert client.poisoned
        with pytest.raises(DocumentSyncError, match="not_available"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
        assert client.open_documents == ()


@pytest.mark.asyncio
async def test_close_attempt_releases_all_local_document_state_on_failure(documents):
    server, workspace, notifications, _send, _entry = documents
    client = AuthorizedDocumentSession(server, workspace)
    await client.__aenter__()
    await client.definition("main.py", line=2, column=10, expected_symbol="greet")

    def broken_close(_params):
        raise RuntimeError("test transport closed")

    server.server.notify.did_close_text_document = broken_close
    with pytest.raises(DocumentSyncError, match="close_unverified"):
        await client.aclose()
    assert client.poisoned
    assert client.open_documents == ()
    assert len(notifications.events) == 1
    await client.aclose()  # repeat close is idempotent and does not re-notify


@pytest.mark.asyncio
async def test_completed_session_cannot_be_reentered(documents):
    server, workspace, _notifications, _send, _entry = documents
    client = AuthorizedDocumentSession(server, workspace)
    async with client:
        pass
    with pytest.raises(DocumentSyncError, match="not_reusable"):
        async with client:
            pytest.fail("reentered completed provider session")


@pytest.mark.asyncio
async def test_definition_target_modified_during_request_is_not_fresh(documents):
    server, workspace, _notifications, send, _entry = documents

    async def update_target():
        send.target.write_text(
            "def greet(name: str) -> str:\n    return name.title()\n"
        )

    send.hook = update_target
    async with AuthorizedDocumentSession(server, workspace) as client:
        with pytest.raises(WorkspaceStaleError, match="target_modified"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )


@pytest.mark.asyncio
async def test_closing_while_request_is_active_is_bounded_and_poisoned(documents):
    server, workspace, _notifications, send, _entry = documents
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed():
        entered.set()
        await release.wait()

    send.hook = delayed
    client = AuthorizedDocumentSession(server, workspace, close_timeout_s=0.05)
    await client.__aenter__()
    task = asyncio.create_task(
        client.definition("main.py", line=2, column=10, expected_symbol="greet")
    )
    await asyncio.wait_for(entered.wait(), 1)
    with pytest.raises(DocumentSyncError, match="close_unverified"):
        await client.aclose()
    assert client.poisoned
    release.set()
    with pytest.raises(DocumentSyncError, match="closed_during_request"):
        await asyncio.wait_for(task, 1)
    assert client.open_documents == ("main.py",)  # owner must stop provider


@pytest.mark.asyncio
async def test_open_document_limit_refuses_additional_source(documents):
    server, workspace, notices, _send, _entry = documents
    client = AuthorizedDocumentSession(server, workspace, max_open_documents=1)
    async with client:
        await client.definition("main.py", line=2, column=10, expected_symbol="greet")
        with pytest.raises(WorkspaceAccessError, match="open_document_limit"):
            await client.definition("lib.py", line=1, column=5, expected_symbol="greet")
    assert [event for event, _ in notices.events] == ["open", "close"]


@pytest.mark.asyncio
async def test_location_count_cap_never_returns_unbounded_data(documents):
    server, workspace, _notices, send, _entry = documents
    original = send.definition

    async def multiple(params):
        item = (await original(params))[0]
        return [item, item]

    send.definition = multiple
    async with AuthorizedDocumentSession(
        server, workspace, max_definition_locations=1
    ) as client:
        with pytest.raises(WorkspaceAccessError, match="location_limit"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )


@pytest.mark.asyncio
async def test_open_definition_target_changed_before_other_request_is_stale(documents):
    server, workspace, notifications, send, _entry = documents
    async with AuthorizedDocumentSession(server, workspace) as client:
        initial = await client.definition(
            "lib.py", line=1, column=5, expected_symbol="greet"
        )
        assert initial[0]["relativePath"] == "lib.py"
        # The target remains open in multilspy, with its original buffer.
        send.target.write_text(
            "def greet(name: str) -> str:\n    return name.title()\n"
        )
        with pytest.raises(WorkspaceStaleError, match="open_document_buffer_stale"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
        # Refreshing the target through the same authorized document session
        # sends didChange and makes the target trustworthy for later requests.
        refreshed = await client.definition(
            "lib.py", line=1, column=5, expected_symbol="greet"
        )
        assert refreshed[0]["relativePath"] == "lib.py"
        resolved = await client.definition(
            "main.py", line=2, column=10, expected_symbol="greet"
        )
        assert resolved == initial
    assert any(event == "change" for event, _payload in notifications.events)


def test_lsp_line_rules_do_not_treat_unicode_separators_as_newlines():
    text = 'quoted = "one\u2028two"; greet = greet\r\n'
    anchor = text.index("greet") + 1
    assert AuthorizedDocumentSession._position(text, 1, anchor, "greet") == {
        "line": 0,
        "character": anchor - 1,
    }
    assert AuthorizedDocumentSession._position("a = 1\r\ngreet = 2", 2, 1, "greet") == {
        "line": 1,
        "character": 0,
    }
    with pytest.raises(WorkspaceAccessError, match="source_column_out_of_range"):
        AuthorizedDocumentSession._position("greet = 1\n", 2, 1, "greet")


@pytest.mark.asyncio
async def test_timeout_poisoned_session_never_accepts_second_request(documents):
    server, workspace, _notifications, send, _entry = documents

    async def wait_forever():
        await asyncio.Event().wait()

    send.hook = wait_forever
    async with AuthorizedDocumentSession(
        server, workspace, request_timeout_s=0.05
    ) as client:
        with pytest.raises(asyncio.TimeoutError):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
        assert client.poisoned
        with pytest.raises(DocumentSyncError, match="not_available"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
        assert len(send.calls) == 1


@pytest.mark.asyncio
async def test_cancellation_poisoned_session_and_closes_documents(documents):
    server, workspace, notifications, send, _entry = documents
    entered = asyncio.Event()

    async def until_cancelled():
        entered.set()
        await asyncio.Event().wait()

    send.hook = until_cancelled
    async with AuthorizedDocumentSession(server, workspace) as client:
        task = asyncio.create_task(
            client.definition("main.py", line=2, column=10, expected_symbol="greet")
        )
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.poisoned
        with pytest.raises(DocumentSyncError, match="not_available"):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
    assert [event for event, _ in notifications.events] == ["open", "close"]
