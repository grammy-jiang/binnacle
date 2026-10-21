"""P2.4 private upstream owner + OS process-tree cleanup on Mac and Linux.

An intentionally synthetic LSP peer is launched by the real patched multilspy
PyrightServer factory; this test never introduces a Binnacle Pyright adapter.
"""

from __future__ import annotations

import asyncio
import json
import os
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

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process tests")


@pytest.fixture
def standalone_lsp_with_child(tmp_path: Path) -> Path:
    peer = tmp_path / "synthetic_lsp_peer.py"
    peer.write_text(
        "import json, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "ready = Path(sys.argv[1])\n"
        "escaped = sys.argv[2] == 'escaped'\n"
        "child = subprocess.Popen([sys.executable, '-u', '-c', 'import time;time.sleep(30)'], "
        "start_new_session=escaped, stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "ready.write_text(json.dumps({'child':child.pid,'escaped':escaped}))\n"
        "def recv():\n"
        "    length = None\n"
        "    while True:\n"
        "        line = sys.stdin.buffer.readline()\n"
        "        if not line: return None\n"
        "        if line == b'\\r\\n': break\n"
        "        if line.lower().startswith(b'content-length:'):\n"
        "            length = int(line.split(b':',1)[1])\n"
        "    if length is None: return None\n"
        "    return json.loads(sys.stdin.buffer.read(length))\n"
        "def send(value):\n"
        "    body = json.dumps(value).encode()\n"
        "    sys.stdout.buffer.write(('Content-Length: %d\\r\\n\\r\\n' % len(body)).encode()+body)\n"
        "    sys.stdout.buffer.flush()\n"
        "while (msg := recv()) is not None:\n"
        "    method = msg.get('method')\n"
        "    if method == 'exit': break\n"
        "    if 'id' not in msg: continue\n"
        "    result = {'capabilities': {'positionEncoding':'utf-16', "
        "'definitionProvider':True,'referencesProvider':True,"
        "'hoverProvider':True,'completionProvider':True,"
        "'documentSymbolProvider':True,'workspaceSymbolProvider':True,"
        "'textDocumentSync':1}} if method == 'initialize' else None\n"
        "    send({'jsonrpc':'2.0','id':msg['id'],'result':result})\n",
        encoding="utf-8",
    )
    return peer


@pytest.mark.asyncio
@pytest.mark.parametrize("escaped", [False, True])
async def test_owner_backstop_observes_and_reaps_actual_provider_descendant(
    standalone_lsp_with_child: Path, tmp_path: Path, escaped: bool
):
    import psutil
    from multilspy import LanguageServer
    from multilspy.multilspy_config import Language, MultilspyConfig
    from multilspy.multilspy_logger import MultilspyLogger

    root = tmp_path / "trusted-workspace"
    root.mkdir()
    ready = tmp_path / "child.json"
    profile = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=sys.executable,
                mode="explicit_trust_only",
                languages=("python",),
            )
        },
    )
    owner = PrivatePyrightProcessOwner(profile, root)

    def real_upstream_factory():
        server = LanguageServer.create(
            MultilspyConfig(
                code_language=Language.PYTHON,
                python_server="pyright",
                server_binary=sys.executable,
            ),
            MultilspyLogger(),
            str(root),
        )
        assert type(server).__name__ == "PyrightServer"
        # Test-only redirected stdio peer; production always uses the audited
        # configured pyright-langserver binary and no command override.
        server.server.process_launch_info.cmd = [
            sys.executable,
            "-u",
            str(standalone_lsp_with_child),
            str(ready),
            "escaped" if escaped else "group",
        ]
        return server

    owner._make_upstream_server = real_upstream_factory
    created_child = None
    try:

        async def exercise():
            async with owner.session() as server:
                assert server.server.process is not None
                while not ready.is_file():
                    await asyncio.sleep(0.01)
                info = json.loads(ready.read_text())
                nonlocal created_child
                created_child = psutil.Process(info["child"])
                owner.observe_owned_processes()
                assert info["child"] in owner._tree.members
                assert owner._tree.root.pid == server.server.process.pid

        if escaped:
            with pytest.raises(ProviderLifecycleError, match="cleanup_unverified"):
                await asyncio.wait_for(exercise(), timeout=20)
        else:
            await asyncio.wait_for(exercise(), timeout=20)
        assert owner.last_exit is not None
        assert owner.last_exit.parent_exited
        assert owner.last_exit.pending_requests == 0
        assert owner.last_exit.reader_tasks == 0
        assert bool(owner.last_exit.escaped_descendants) is escaped
        assert owner.last_exit.cleanup_unverified is escaped
        assert not owner.last_exit.containment_verified
        assert created_child is not None
        try:
            child_alive = (
                created_child.is_running()
                and created_child.status() != psutil.STATUS_ZOMBIE
            )
        except psutil.NoSuchProcess:
            child_alive = False
        assert not child_alive
        if escaped:
            with pytest.raises(ProviderLifecycleError, match="unverified"):
                async with owner.session():
                    pytest.fail("escaped provider should poison the owner")
    finally:
        await owner.aclose()
        # The test itself must not leave runnable descendants if assertions fail.
        if created_child is not None and created_child.is_running():
            try:
                if created_child.status() != psutil.STATUS_ZOMBIE:
                    created_child.kill()
            except psutil.NoSuchProcess:
                pass
