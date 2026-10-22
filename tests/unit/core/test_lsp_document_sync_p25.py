"""Private document synchronization with an upstream LSP send/notify facade."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from binnacle.features.development_intelligence.lsp_document_sync import (
    AuthorizedDocumentSession,
    DocumentSyncError,
)
from binnacle.features.development_intelligence.lsp_workspace_access import (
    AuthorizedWorkspace,
    WorkspaceAccessError,
    WorkspaceStaleError,
)


class Notifications:
    def __init__(self):
        self.events = []

    def did_open_text_document(self, params):
        self.events.append(("open", params))

    def did_change_text_document(self, params):
        self.events.append(("change", params))

    def did_close_text_document(self, params):
        self.events.append(("close", params))


class Send:
    def __init__(self, target):
        self.target = target
        self.calls = []
        self.hook = None

    async def definition(self, params):
        self.calls.append(params)
        if self.hook:
            await self.hook()
        return [
            {
                "uri": self.target.as_uri(),
                "range": {
                    "start": {"line": 0, "character": 4},
                    "end": {"line": 0, "character": 9},
                },
            }
        ]


@pytest.fixture
def documents(tmp_path):
    allowed = (tmp_path / "allowed").resolve()
    project = allowed / "example-project"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    entry = project / "main.py"
    entry.write_text("from lib import greet\nresult = greet('Ada')\n")
    target = project / "lib.py"
    target.write_text("def greet(name: str) -> str:\n    return name\n")
    # The private result gate conservatively rejects freshly touched unopened
    # targets within a 25ms local filesystem timestamp uncertainty window.
    time.sleep(0.035)
    workspace = AuthorizedWorkspace((allowed,), entry)
    notice = Notifications()
    send = Send(target)
    server = SimpleNamespace(
        repository_root_path=str(project),
        server_started=True,
        open_file_buffers={},
        server=SimpleNamespace(notify=notice, send=send),
    )
    return server, workspace, notice, send, entry


@pytest.mark.asyncio
async def test_open_then_reuse_then_close_sends_one_open(documents):
    server, workspace, notice, send, _entry = documents
    async with AuthorizedDocumentSession(server, workspace) as client:
        first = await client.definition(
            "main.py", line=2, column=10, expected_symbol="greet"
        )
        second = await client.definition(
            "main.py", line=2, column=10, expected_symbol="greet"
        )
        assert first == second
        assert first[0]["relativePath"] == "lib.py"
        assert client.open_documents == ("main.py",)
    assert [event for event, _ in notice.events] == ["open", "close"]
    assert notice.events[0][1]["textDocument"]["version"] == 1
    assert len(send.calls) == 2
    assert client.open_documents == ()
    assert server.open_file_buffers == {}  # no implicit upstream file reads


@pytest.mark.asyncio
async def test_change_sends_full_content_versioned_update(documents):
    server, workspace, notice, _send, entry = documents
    async with AuthorizedDocumentSession(server, workspace) as client:
        await client.definition("main.py", line=2, column=10, expected_symbol="greet")
        entry.write_text("from lib import greet\nresult = greet('Lin')\n")
        await client.definition("main.py", line=2, column=10, expected_symbol="greet")
        await client.definition("main.py", line=2, column=10, expected_symbol="greet")
    assert [name for name, _ in notice.events] == ["open", "change", "close"]
    changed = notice.events[1][1]
    assert changed["textDocument"]["version"] == 2
    assert changed["contentChanges"] == [{"text": entry.read_text()}]


@pytest.mark.asyncio
async def test_explicit_unicode_and_repeated_token_anchor(documents):
    server, workspace, notice, send, entry = documents
    entry.write_text('marker = "🧭"; greet = greet\n')
    text = entry.read_text().splitlines()[0]
    first = text.index("greet") + 1
    last = text.rindex("greet") + 1
    async with AuthorizedDocumentSession(server, workspace) as client:
        await client.definition("main.py", line=1, column=last, expected_symbol="greet")
        assert (
            send.calls[-1]["position"]["character"] == last
        )  # emoji consumes 2 UTF-16 units
        await client.definition(
            "main.py", line=1, column=first, expected_symbol="greet"
        )
        assert send.calls[-1]["position"]["character"] == first
        with pytest.raises(WorkspaceAccessError, match="mismatch"):
            await client.definition(
                "main.py", line=1, column=first, expected_symbol="other"
            )
    assert len(send.calls) == 2
    assert [e for e, _ in notice.events] == ["open", "close"]


@pytest.mark.asyncio
async def test_disk_modified_during_request_is_stale(documents):
    server, workspace, _notice, send, entry = documents

    async def change_source():
        entry.write_text("from lib import greet\nresult = greet('changed')\n")

    send.hook = change_source
    async with AuthorizedDocumentSession(server, workspace) as client:
        with pytest.raises(WorkspaceStaleError):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
        send.hook = None
        value = await client.definition(
            "main.py", line=2, column=10, expected_symbol="greet"
        )
        assert value[0]["relativePath"] == "lib.py"


@pytest.mark.asyncio
async def test_unavailable_provider_or_wrong_root_refused(documents, tmp_path):
    server, workspace, _notice, _send, _entry = documents
    server.repository_root_path = str(tmp_path)
    with pytest.raises(DocumentSyncError, match="mismatch"):
        async with AuthorizedDocumentSession(server, workspace):
            pytest.fail("wrong root started")
    server.repository_root_path = str(workspace.workspace_root)
    server.server_started = False
    with pytest.raises(DocumentSyncError, match="not_started"):
        async with AuthorizedDocumentSession(server, workspace):
            pytest.fail("stopped provider started")


@pytest.mark.asyncio
async def test_timeouts_do_not_prevent_balanced_close(documents):
    server, workspace, notice, send, _entry = documents

    async def never_respond():
        await asyncio.Event().wait()

    send.hook = never_respond
    async with AuthorizedDocumentSession(
        server, workspace, request_timeout_s=0.05
    ) as client:
        with pytest.raises(asyncio.TimeoutError):
            await client.definition(
                "main.py", line=2, column=10, expected_symbol="greet"
            )
    assert [event for event, _ in notice.events] == ["open", "close"]
    assert client.open_documents == ()
