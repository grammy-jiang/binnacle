"""P3.3 real Pyright + Binnacle owner: opt-in minimal subprocess env.

This protects against inadvertent parent *environment* disclosure, not file
reads, network, subprocess spawning, kernel-level confinement or README safety.
The only synthetic secret used here is created inside this test case.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from binnacle.config_development_intelligence import (
    DevelopmentIntelligenceSettings,
    DevelopmentProviderSettings,
)
from binnacle.features.development_intelligence.lsp_document_sync import (
    AuthorizedDocumentSession,
)
from binnacle.features.development_intelligence.lsp_process_owner import (
    _PYRIGHT_PARENT_ENV_KEYS,
    PrivatePyrightProcessOwner,
)
from binnacle.features.development_intelligence.lsp_workspace_access import (
    AuthorizedWorkspace,
)

_MARKER = "BINNACLE_P33_SYNTHETIC_SECRET_SENTINEL_ONLY"


def test_private_pyright_parent_env_has_only_minimal_public_runtime_keys():
    assert _PYRIGHT_PARENT_ENV_KEYS == (
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
    )
    assert not {
        "HOME",
        "NODE_OPTIONS",
        "PYTHONPATH",
        "SSH_AUTH_SOCK",
        "HTTP_PROXY",
    } & set(_PYRIGHT_PARENT_ENV_KEYS)
    assert all(
        "KEY" not in key and "TOKEN" not in key for key in _PYRIGHT_PARENT_ENV_KEYS
    )


@pytest.mark.asyncio
async def test_real_private_pyright_drops_synthetic_parent_secret_but_defines_symbol(
    tmp_path, monkeypatch
):
    if os.getenv("BINNACLE_PATCHED_MULTILSPY_QA") != "1":
        pytest.skip("real host-provided Pyright requires explicit private QA")
    binary = os.environ.get("PYRIGHT_LSP_TEST_BIN")
    assert binary and Path(binary).is_absolute() and Path(binary).is_file()
    allowed = (tmp_path / "allowed").resolve()
    project = allowed / "synthetic-repo"
    project.mkdir(parents=True)
    (project / ".git").write_text("gitdir: /fixture-only\n")
    (project / "lib.py").write_text(
        "def greet(name: str) -> str:\n    return name.upper()\n"
    )
    source = project / "main.py"
    source.write_text("from lib import greet\nresult = greet('Ada')\n")
    root = AuthorizedWorkspace((allowed,), source)
    settings = DevelopmentIntelligenceSettings(
        enabled=True,
        profiles={
            "pyright": DevelopmentProviderSettings(
                enabled=True,
                source="trusted_absolute",
                executable=binary,
                mode="explicit_trust_only",
                languages=("python",),
            )
        },
    )
    monkeypatch.setenv(_MARKER, "synthetic-only-not-a-credential")
    # Values are disposable. Inheriting NODE_OPTIONS would execute this hook.
    hook = tmp_path / "synthetic-preload.js"
    marker = tmp_path / "preload-executed"
    import json

    hook.write_text(
        "require('fs').writeFileSync(" + json.dumps(str(marker)) + ", 'fixture');"
    )
    monkeypatch.setenv("NODE_OPTIONS", "--require=" + str(hook))
    for key in (
        "NODE_PATH",
        "PYTHONPATH",
        "PYTHONHOME",
        "SSH_AUTH_SOCK",
        "HTTP_PROXY",
        "HOME",
        "TMPDIR",
    ):
        monkeypatch.setenv(key, str(tmp_path / "synthetic-unused"))
    observed = []
    original_spawn = asyncio.create_subprocess_exec

    async def audit_launch(*args, **kwargs):
        if "--stdio" in args:
            passed = kwargs.get("env")
            # No other inherited environment keys or values are inspected.
            observed.append(
                isinstance(passed, dict)
                and _MARKER not in passed
                and set(passed).issubset(set(_PYRIGHT_PARENT_ENV_KEYS) | {"PATH"})
            )
        return await original_spawn(*args, **kwargs)

    owner = PrivatePyrightProcessOwner(
        settings, root.workspace_root, operator_allowed_roots=(allowed,)
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(asyncio, "create_subprocess_exec", audit_launch)
        async with owner.session() as server:
            assert server.server.process is not None
            assert server.server.process_launch_info.inherited_environment_keys == (
                _PYRIGHT_PARENT_ENV_KEYS
            )
            async with AuthorizedDocumentSession(server, root) as doc:
                locations = await doc.definition(
                    "main.py", line=2, column=10, expected_symbol="greet"
                )
                assert locations and locations[0]["relativePath"] == "lib.py"
    assert observed == [True]
    assert not marker.exists()
    assert owner.last_exit and owner.last_exit.parent_exited
    assert not owner.last_exit.cleanup_unverified
