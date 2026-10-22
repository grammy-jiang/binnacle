"""Native opt-in Pyright/Bubblewrap owner; synthetic data only, never READ GO."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import socket
import subprocess
from pathlib import Path

import pytest

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_linux_bwrap import (
    build_private_bwrap_launch,
)
from binnacle.features.development_intelligence.lsp_process_owner import (
    PrivatePyrightProcessOwner,
    ProviderLifecycleError,
)


def _native() -> tuple[Path, Path]:
    if os.getenv("BINNACLE_P33_BWRAP_QA") != "1":
        pytest.skip("explicit native rootless Bubblewrap QA only")
    assert platform.system() == "Linux", "opt-in Linux QA cannot run on Darwin"
    launcher = os.environ.get("PYRIGHT_LSP_TEST_BIN")
    assert launcher and Path(launcher).is_absolute(), "explicit absolute Pyright bin"
    selected = Path(launcher)
    assert selected.is_file() and selected.read_bytes().startswith(
        b"#!/usr/bin/env node\n"
    )
    node = (selected.parent / "node").resolve(strict=True)
    assert node.is_file() and node.read_bytes()[:4] == b"\x7fELF"
    return selected, node


def _settings(binary: Path) -> DevelopmentIntelligenceSettings:
    return DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=str(binary),
                mode="explicit_trust_only",
                languages=("python",),
            )
        },
    )


@pytest.mark.asyncio
async def test_real_pyright_owner_inside_rootless_bubblewrap(tmp_path):
    launcher, _node = _native()
    workspace = tmp_path / "admitted" / "synthetic"
    workspace.mkdir(parents=True)
    source = workspace / "symbols.py"
    source.write_text(
        "class FixtureGreeting:\n    def message(self) -> str:\n        return 'ok'\n",
        encoding="utf-8",
    )
    original = source.read_bytes()
    owner = PrivatePyrightProcessOwner(
        _settings(launcher),
        workspace,
        operator_allowed_roots=(workspace,),
        cleanup_timeout_s=8,
        sandbox_mode="linux_bwrap_experimental",
    )
    try:
        async with asyncio.timeout(16):
            async with owner.session() as server:
                process = server.server.process
                assert process is not None and process.returncode is None
                argv = server.server.process_launch_info.cmd
                assert argv[0] == "/usr/bin/bwrap"
                assert argv[1] == "--unshare-all"
                assert "--new-session" not in argv
                assert "--clearenv" in argv
                mounts = [
                    argv[i + 1 : i + 3]
                    for i, value in enumerate(argv[:-2])
                    if value == "--ro-bind"
                ]
                assert [str(workspace), str(workspace)] in mounts
                symbols = await asyncio.wait_for(
                    server.request_document_symbols("symbols.py"), 8
                )
                assert symbols
    finally:
        assert source.read_bytes() == original
        assert sorted(path.name for path in workspace.iterdir()) == ["symbols.py"]
    evidence = owner.last_exit
    assert evidence is not None
    assert evidence.parent_exited and not evidence.cleanup_unverified
    assert evidence.descendants_audited and evidence.observed_descendants
    assert not evidence.lingering_descendants
    assert not evidence.escaped_descendants
    assert evidence.containment_verified is False


@pytest.mark.asyncio
async def test_private_bwrap_owner_drops_parent_node_options(tmp_path, monkeypatch):
    launcher, _node = _native()
    workspace = tmp_path / "synthetic"
    workspace.mkdir()
    (workspace / "fixture.py").write_text("class SandboxProbe:\\n    pass\\n")
    # If inherited, this synthetic preload would execute before any LSP
    # initialize. The sandbox cannot see the hook and must clear NODE_OPTIONS.
    hook = tmp_path / "never-inherited-preload.js"
    marker = tmp_path / "poison-executed"
    hook.write_text(
        "require('fs').writeFileSync(" + json.dumps(str(marker)) + ", 'wrong');"
    )
    monkeypatch.setenv("NODE_OPTIONS", f"--require={hook}")
    monkeypatch.setenv("NODE_PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    owner = PrivatePyrightProcessOwner(
        _settings(launcher),
        workspace,
        operator_allowed_roots=(workspace,),
        sandbox_mode="linux_bwrap_experimental",
    )
    async with asyncio.timeout(15):
        async with owner.session() as server:
            assert await asyncio.wait_for(
                server.request_document_symbols("fixture.py"), 7
            )
    assert not marker.exists()
    assert owner.last_exit is not None
    assert not owner.last_exit.cleanup_unverified
    assert not owner.last_exit.escaped_descendants


def test_real_bwrap_denies_synthetic_side_effects_and_host_loopback(tmp_path):
    selected, node = _native()
    workspace = tmp_path / "synthetic"
    workspace.mkdir()
    source = workspace / "main.py"
    source.write_text("value = 17\n")
    sibling = tmp_path / "synthetic-private-token"
    sibling.write_text("fixture-sentinel-only\n")
    original = source.read_bytes()
    argv = build_private_bwrap_launch(
        node=node, launcher=selected.resolve(), workspace=workspace
    )
    assert argv[-4] == "--"
    # This is only a test of mount/network properties: replace the final
    # trusted Pyright entrypoint with controlled synthetic JavaScript.
    command = argv[:-3] + ["/opt/trusted-node", "-e"]
    check_code = (
        "const fs=require('fs');let r={};"
        f"try{{fs.writeFileSync({json.dumps(str(workspace / 'forbidden'))},'x');"
        "r.write='unexpected'}catch(e){r.write=e.code};"
        f"try{{fs.readFileSync({json.dumps(str(sibling))});"
        "r.sibling='unexpected'}catch(e){r.sibling=e.code};"
        "process.stdout.write(JSON.stringify(r));"
    )
    write = subprocess.run(
        command + [check_code],
        capture_output=True,
        timeout=7,
        check=False,
        env={"PATH": "/usr/bin"},
    )
    assert write.returncode == 0
    witness = json.loads(write.stdout)
    assert witness["write"] in ("EROFS", "EACCES", "EPERM")
    assert witness["sibling"] in ("ENOENT", "EACCES", "EPERM")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    with listener:
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            accepted, _address = listener.accept()
            accepted.close()
        wire = (
            "const c=require('net').connect({host:'127.0.0.1',port:"
            + str(port)
            + "});c.on('connect',()=>{process.stdout.write('CONNECTED');"
            "c.destroy()});c.on('error',e=>process.stdout.write(e.code));"
            "setTimeout(()=>c.destroy(),800)"
        )
        result = subprocess.run(
            command + [wire],
            capture_output=True,
            timeout=7,
            check=False,
            env={"PATH": "/usr/bin"},
        )
    assert result.returncode == 0
    assert result.stdout != b"CONNECTED"
    assert source.read_bytes() == original
    assert not (workspace / "forbidden").exists()
    assert sibling.read_text() == "fixture-sentinel-only\n"


def test_real_private_owner_fails_closed_on_mismatched_platform(tmp_path, monkeypatch):
    selected, _node = _native()
    workspace = tmp_path / "synthetic"
    workspace.mkdir()
    import binnacle.features.development_intelligence.lsp_linux_bwrap as policy

    monkeypatch.setattr(policy.platform, "system", lambda: "Darwin")
    owner = PrivatePyrightProcessOwner(
        _settings(selected),
        workspace,
        operator_allowed_roots=(workspace,),
        sandbox_mode="linux_bwrap_experimental",
    )
    with pytest.raises(
        ProviderLifecycleError, match="experimental_linux_sandbox_launch_denied"
    ):
        owner._make_upstream_server()
    assert not owner.active and owner.last_exit is None
