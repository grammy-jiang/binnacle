"""Synthetic-only launch authority regressions; never execute project code."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
from pathlib import Path

import pytest

from binnacle.features.development_intelligence.lsp_process_owner import (
    PrivatePyrightProcessOwner,
    ProviderLifecycleError,
)
from tests.unit.core.test_lsp_p31_operator_root_guards import settings


@pytest.fixture
def installation(tmp_path):
    trusted = tmp_path / "operator-selected-install"
    a, b = tmp_path / "root-a", tmp_path / "root-b"
    for directory in (trusted, a, b):
        directory.mkdir()
    launcher = trusted / "pyright-langserver"
    launcher.write_text("#!/usr/bin/env node\n// synthetic, never executed\n")
    launcher.chmod(0o700)
    return trusted, a, b, launcher


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "inside",
        "link-in",
        "double-slash",
        "link-out",
        "directory-link",
        "transit-link",
        "script",
        "not-executable",
    ],
)
def test_node_admission_denies_unsafe_interpreter_before_spawn(installation, case):
    trusted, a, b, launcher = installation
    node = trusted / "node"
    target = b / "node"
    target.write_bytes(b"\x7fELFsynthetic never executed")
    target.chmod(0o700)
    if case == "inside":
        # Selecting a trusted launcher from a directory that is itself granted
        # must be rejected too, even when the launcher links outside it.
        link = b / "pyright-langserver"
        link.symlink_to(launcher)
        launcher = link
    elif case == "link-in":
        node.symlink_to(target)
    elif case == "double-slash":
        node.symlink_to("/" + str(target))
    elif case == "link-out":
        safe = trusted / "native-node"
        safe.write_bytes(b"\x7fELFsynthetic")
        safe.chmod(0o700)
        target.unlink()
        target.symlink_to(safe)
        node.symlink_to(target)
    elif case == "directory-link":
        directory = trusted / "alias"
        directory.symlink_to(b, target_is_directory=True)
        node.symlink_to(directory / "node")
    elif case == "transit-link":
        # A mutable intermediate link can redirect a final trusted target.
        bridge = b / "bridge"
        bridge.symlink_to(trusted, target_is_directory=True)
        safe = trusted / "native-node"
        safe.write_bytes(b"\x7fELFsynthetic")
        safe.chmod(0o700)
        node.symlink_to(bridge / "native-node")
    elif case == "script":
        node.write_text("#!/usr/bin/env python\n")
        node.chmod(0o700)
    elif case == "not-executable":
        node.write_bytes(b"\x7fELFsynthetic")
    with pytest.raises(ProviderLifecycleError):
        owner = PrivatePyrightProcessOwner(
            settings(launcher), a, operator_allowed_roots=(a, b)
        )
        owner._make_upstream_server()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path_case", ["direct", "directory-symlink", "node-symlink", "empty-relative"]
)
async def test_real_pyright_ignores_writable_root_path(
    tmp_path, monkeypatch, path_case
):
    if os.getenv("BINNACLE_PATCHED_MULTILSPY_QA") != "1":
        pytest.skip("explicit synthetic real Pyright QA required")
    binary = Path(os.environ["PYRIGHT_LSP_TEST_BIN"])
    native = Path(shutil.which("node") or "").resolve(strict=True)
    assert binary.is_absolute() and native.is_file()
    assert binary.read_bytes().startswith(b"#!/usr/bin/env node\n")
    trusted, a, b = (tmp_path / name for name in ("trusted", "root-a", "root-b"))
    for directory in (trusted, a, b):
        directory.mkdir()
    launcher = trusted / "pyright-langserver"
    launcher.symlink_to(binary)
    (trusted / "node").symlink_to(native)
    (a / "main.py").write_text("value = 123\n")
    marker = tmp_path / "hijack-marker"
    malicious = b / "node"
    malicious.write_text(
        "#!/bin/sh\nprintf hijacked > " + shlex.quote(str(marker)) + "\nexit 45\n"
    )
    malicious.chmod(0o700)
    prefix = b
    if path_case == "directory-symlink":
        prefix = tmp_path / "bin-alias"
        prefix.symlink_to(b, target_is_directory=True)
    elif path_case == "node-symlink":
        prefix = tmp_path / "bin-alias"
        prefix.mkdir()
        (prefix / "node").symlink_to(malicious)
    elif path_case == "empty-relative":
        (a / "node").symlink_to(malicious)
    poisoned = str(prefix) if path_case != "empty-relative" else ":."
    monkeypatch.setenv("PATH", poisoned)
    owner = PrivatePyrightProcessOwner(
        settings(launcher), a, operator_allowed_roots=(a, b), cleanup_timeout_s=3
    )
    try:
        async with asyncio.timeout(12):
            async with owner.session() as server:
                assert server.server.process is not None
                result = await server.request_document_symbols("main.py")
                assert result
    finally:
        assert not marker.exists(), "writable-root Node executed"
    assert owner.last_exit and owner.last_exit.parent_exited
    assert not owner.last_exit.cleanup_unverified


@pytest.mark.parametrize(
    "case", ["launcher-retarget", "node-retarget", "launcher-format", "node-cycle"]
)
def test_launch_rechecks_selected_files_without_path_fallback(installation, case):
    trusted, a, b, launcher = installation
    native = trusted / "native-node"
    native.write_bytes(b"\x7fELFsynthetic never executed")
    native.chmod(0o700)
    node = trusted / "node"
    node.symlink_to(native)
    alias = trusted / "selected-launcher"
    alias.symlink_to(launcher)
    owner = PrivatePyrightProcessOwner(
        settings(alias), a, operator_allowed_roots=(a, b)
    )
    if case == "launcher-retarget":
        other = trusted / "other-launcher"
        other.write_bytes(launcher.read_bytes())
        other.chmod(0o700)
        alias.unlink()
        alias.symlink_to(other)
    elif case == "node-retarget":
        other = b / "node"
        other.write_bytes(native.read_bytes())
        other.chmod(0o700)
        node.unlink()
        node.symlink_to(other)
    elif case == "launcher-format":
        launcher.write_text("#!/usr/bin/env -S node --require unsafe\n")
    elif case == "node-cycle":
        node.unlink()
        node.symlink_to(node.name)
    with pytest.raises(ProviderLifecycleError):
        owner._make_upstream_server()


@pytest.mark.parametrize("changed", ["cmd", "env"])
def test_unexpected_upstream_launch_contract_fails_closed(
    installation, monkeypatch, changed
):
    from multilspy import LanguageServer  # type: ignore[import-untyped]

    trusted, a, b, launcher = installation
    node = trusted / "node"
    node.write_bytes(b"\x7fELFsynthetic never executed")
    node.chmod(0o700)
    create = LanguageServer.create

    def changed_factory(*args, **kwargs):
        server = create(*args, **kwargs)
        launch = server.server.process_launch_info
        if changed == "cmd":
            launch.cmd.append("--unexpected")
        else:
            launch.env["NODE_OPTIONS"] = "synthetic"
        return server

    monkeypatch.setattr(LanguageServer, "create", changed_factory)
    owner = PrivatePyrightProcessOwner(
        settings(launcher), a, operator_allowed_roots=(a, b)
    )
    with pytest.raises(ProviderLifecycleError, match="launch_contract_changed"):
        owner._make_upstream_server()


def test_unreadable_launcher_fails_with_sanitized_admission_error(installation):
    _trusted, a, b, launcher = installation
    owner = PrivatePyrightProcessOwner(
        settings(launcher), a, operator_allowed_roots=(a, b)
    )
    launcher.chmod(0o100)
    try:
        with pytest.raises(
            ProviderLifecycleError, match="^pyright_launch_admission_failed$"
        ):
            owner._make_upstream_server()
    finally:
        launcher.chmod(0o700)
