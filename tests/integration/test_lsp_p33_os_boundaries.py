"""Disposable OS evidence. Native launch hygiene is NOT a sandbox.

The positive side-effect control is synthetic JS in an operator-selected
installation, never user source. Bubblewrap checks primitives only; Binnacle
has no integrated sandbox launcher and gains no READ eligibility here.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from binnacle.features.development_intelligence.lsp_process_owner import (
    PrivatePyrightProcessOwner,
)
from tests.fixtures.lsp.side_effects import differences, manifest
from tests.unit.core.test_lsp_p31_operator_root_guards import settings


def _opt_in():
    if os.getenv("BINNACLE_PATCHED_MULTILSPY_QA") != "1":
        pytest.skip("explicit synthetic native OS QA required")


@pytest.mark.asyncio
async def test_native_launch_can_write_connect_and_run_short_lived_python(
    tmp_path, monkeypatch
):
    _opt_in()
    native = Path(shutil.which("node") or "").resolve(strict=True)
    install, workspace, cache = (
        tmp_path / name for name in ("install", "workspace", "cache")
    )
    for directory in (install, workspace, cache):
        directory.mkdir()
    (workspace / ".gitignore").write_text(".ignored/\n")
    (install / "node").symlink_to(native)
    report = install / "synthetic-result.json"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(3)
    port = listener.getsockname()[1]
    launcher = install / "pyright-langserver"
    launcher.write_text(
        "#!/usr/bin/env node\n"
        "const fs = require('fs'), cp = require('child_process'), net = require('net');\n"
        "fs.mkdirSync('.ignored'); fs.writeFileSync('.ignored/sentinel', 'fixture');\n"
        f"fs.writeFileSync({json.dumps(str(cache / 'sentinel'))}, 'fixture');\n"
        f"const child = cp.spawnSync({json.dumps(sys.executable)}, ['-I', '-c', 'print(123)'], {{timeout: 2000}});\n"
        f"const out = {json.dumps(str(report))};\n"
        "const result = {python: child.status === 0 && child.stdout.toString().trim() === '123', "
        "secret: 'BINNACLE_P33_FAKE_SECRET' in process.env};\n"
        f"const client = net.createConnection({{host:'127.0.0.1',port:{port}}});\n"
        "client.setTimeout(2000, () => {client.destroy(); process.exitCode = 2;});\n"
        "client.on('connect', () => { result.connected = true; client.destroy(); "
        "fs.writeFileSync(out, JSON.stringify(result)); });\n"
        "client.on('error', () => {process.exitCode = 3;});\n"
    )
    launcher.chmod(0o700)
    before = manifest(workspace)
    monkeypatch.setenv("BINNACLE_P33_FAKE_SECRET", "disposable-fixture-only")
    owner = PrivatePyrightProcessOwner(
        settings(launcher), workspace, operator_allowed_roots=(workspace, cache)
    )
    handler = owner._make_upstream_server().server
    try:
        # Use the actual admitted launch/env boundary without pretending this
        # synthetic program is an LSP peer. All children exit within 2 seconds.
        await handler.start()
        process = handler.process
        assert process is not None
        assert await asyncio.wait_for(process.wait(), 6) == 0
        accepted, _address = listener.accept()
        accepted.close()
    finally:
        listener.close()
        await asyncio.wait_for(handler.stop(), 4)
    assert json.loads(report.read_text()) == {
        "python": True,
        "secret": False,
        "connected": True,
    }
    assert ".ignored/sentinel" in differences(before, manifest(workspace))
    assert (cache / "sentinel").read_text() == "fixture"
    assert handler.process is None and not handler.tasks


@pytest.mark.skipif(
    sys.platform != "linux", reason="Linux namespace primitive evidence"
)
def test_bubblewrap_primitives_deny_workspace_write_and_host_loopback(tmp_path):
    _opt_in()
    bwrap = shutil.which("bwrap")
    assert bwrap, "opted-in Linux audit requires installed bubblewrap"
    workspace, cache = tmp_path / "workspace", tmp_path / "cache"
    workspace.mkdir()
    cache.mkdir()
    (workspace / "input.py").write_text("value = 1\n")
    before = manifest(workspace)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    # Known system interpreter, synthetic code, no user/project execution.
    program = """import json, pathlib, socket, subprocess
result = {}
try:
    pathlib.Path('/workspace/forbidden').write_text('fixture')
    result['workspace_denied'] = False
except OSError:
    result['workspace_denied'] = True
pathlib.Path('/cache/allowed').write_text('fixture')
sock = socket.socket()
sock.settimeout(1)
try:
    sock.connect(('127.0.0.1', PORT))
    result['network_denied'] = False
except OSError:
    result['network_denied'] = True
finally:
    sock.close()
result['child_allowed'] = subprocess.run(['/usr/bin/python3', '-I', '-c', 'pass'], timeout=2).returncode == 0
print(json.dumps(result))
""".replace("PORT", str(port))
    command = [
        bwrap,
        "--unshare-user",
        "--unshare-net",
        "--unshare-pid",
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/usr",
        "/usr",
    ]
    for name in ("bin", "lib", "lib64"):
        path = Path("/") / name
        if path.is_symlink():
            command.extend(["--symlink", os.readlink(path), str(path)])
        elif path.is_dir():
            command.extend(["--ro-bind", str(path), str(path)])
    command += [
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--ro-bind",
        str(workspace),
        "/workspace",
        "--bind",
        str(cache),
        "/cache",
        "--chdir",
        "/workspace",
        "/usr/bin/python3",
        "-I",
        "-c",
        program,
    ]
    try:
        result = subprocess.run(
            command,
            env={"PATH": "/usr/bin"},
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    finally:
        listener.close()
    assert result.returncode == 0, (
        "namespace primitive failed; no isolation claim permitted"
    )
    assert json.loads(result.stdout) == {
        "workspace_denied": True,
        "network_denied": True,
        "child_allowed": True,
    }
    assert manifest(workspace) == before
    assert (cache / "allowed").read_text() == "fixture"
