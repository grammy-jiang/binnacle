"""P2.4 process-tree observation of the real pinned upstream PyrightServer.

This is a PRIVATE integration fixture, not the installed Binnacle MCP tool.
The language server is created solely by multilspy's upstream factory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from anyio import fail_after

from binnacle.features.development_intelligence.lsp_process_tree import (
    NativeProviderTree,
)


@pytest.fixture
def executable():
    if os.environ.get("BINNACLE_PATCHED_MULTILSPY_QA") != "1":
        pytest.skip("opt-in real-provider lifecycle test")
    binary = os.environ.get("PYRIGHT_LSP_TEST_BIN")
    assert binary and Path(binary).is_absolute() and Path(binary).is_file()
    return binary


@pytest.mark.skipif(os.name != "posix", reason="POSIX process owner")
@pytest.mark.asyncio
async def test_native_multilspy_provider_process_tree_lifecycle(executable, tmp_path):
    from multilspy import LanguageServer  # type: ignore[import-untyped]
    from multilspy.multilspy_config import (  # type: ignore[import-untyped]
        Language,
        MultilspyConfig,
    )
    from multilspy.multilspy_logger import (  # type: ignore[import-untyped]
        MultilspyLogger,
    )

    project = (tmp_path / "workspace").resolve()
    project.mkdir()
    source = project / "sample.py"
    source.write_text("value = 42\nresult = value\n", encoding="utf-8")
    original = source.read_bytes()

    server = LanguageServer.create(
        MultilspyConfig(
            code_language=Language.PYTHON,
            python_server="pyright",
            server_binary=executable,
            trace_lsp_communication=False,
        ),
        MultilspyLogger(),
        str(project),
    )
    assert type(server).__name__ == "PyrightServer"
    tree = NativeProviderTree()
    pid = None
    try:
        with fail_after(25):
            async with server.start_server():
                process = server.server.process
                assert process is not None
                pid = process.pid
                tree.capture(pid)
                with server.open_file("sample.py"):
                    found = await server.request_definition("sample.py", 1, 10)
                    assert len(found) == 1
                    assert found[0]["relativePath"] == "sample.py"
                tree.observe()
    finally:
        # Upstream closes the parent on context exit; Binnacle observes and
        # tidies any independently owned descendants without copying adapter.
        evidence = await tree.cleanup()
    assert evidence.root_pid == pid
    assert evidence.status == "observed_clean"
    assert evidence.escaped_descendants == 0
    assert evidence.remaining == ()
    assert server.server.process is None
    assert server.server.tasks == {}
    assert not server.server._response_handlers
    assert source.read_bytes() == original
