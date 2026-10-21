"""Opt-in multilspy v0.1.1 + Pyright 1.1.413 real stdio integration tests.

Skipped unless optional multilspy and PYRIGHT_LSP_TEST_BIN are available.
Never download, install, or launch providers during normal Binnacle tests.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from binnacle.features.development_intelligence.multilspy_pyright import (
    PyrightOptions,
    create_pyright_adapter,
)

BIN_NAME = "PYRIGHT_LSP_TEST_BIN"


@pytest.fixture
def pyright_executable() -> Path:
    optional_path = os.environ.get(BIN_NAME)
    if not optional_path:
        pytest.skip(f"{BIN_NAME} not configured; no auto-install or discovery")
    executable = Path(optional_path)
    if not executable.is_file() or not executable.is_absolute():
        pytest.skip("explicit Pyright binary is absent")
    return executable


def _optional_upstream():
    multilspy = pytest.importorskip("multilspy", reason="optional package disabled")
    from multilspy.multilspy_config import Language, MultilspyConfig
    from multilspy.multilspy_logger import MultilspyLogger

    assert multilspy is not None
    return MultilspyConfig(code_language=Language.PYTHON), MultilspyLogger()


def test_real_multilspy_pyright_navigation_diagnostics_and_cleanup(
    tmp_path: Path, pyright_executable: Path
) -> None:
    config, logger = _optional_upstream()
    root = tmp_path / "project"
    root.mkdir()
    file = root / "example.py"
    original = (
        "def greet(name: str) -> str:\n    return 123\n\nanswer = greet('world')\n"
    )
    file.write_text(original, encoding="utf-8")
    (root / "pyrightconfig.json").write_text(
        '{"typeCheckingMode":"strict","include":["example.py"]}\n'
    )
    adapter = create_pyright_adapter(
        config,
        logger,
        root,
        executable=pyright_executable,
        options=PyrightOptions(
            type_checking_mode="standard", diagnostic_mode="openFilesOnly"
        ),
    )
    assert adapter.server.process is None

    async def exercise() -> None:
        async with adapter.start_server():
            assert adapter.capabilities.get("positionEncoding", "utf-16") == "utf-16"
            definition = await asyncio.wait_for(
                adapter.request_definition("example.py", 3, 11), 6
            )
            assert len(definition) == 1
            assert definition[0]["relativePath"] == "example.py"
            assert definition[0]["range"]["start"]["line"] == 0
            references = await asyncio.wait_for(
                adapter.request_references("example.py", 0, 4), 6
            )
            assert len(references) >= 1
            assert all(r["relativePath"] == "example.py" for r in references)
            hover = await asyncio.wait_for(
                adapter.request_hover("example.py", 3, 11), 6
            )
            assert hover is not None
            symbols = await asyncio.wait_for(
                adapter.request_document_symbols("example.py"), 6
            )
            assert isinstance(symbols, tuple)

            # Ignore stale empty didClose diagnostics from earlier queries,
            # then leave this source open until a current diagnostic arrives.
            while not adapter.diagnostics.empty():
                adapter.diagnostics.get_nowait()
            with adapter.open_file("example.py"):
                observed: set[str] = set()
                for _ in range(12):
                    notification = await adapter.next_diagnostics(timeout_s=2)
                    if notification.get("uri") != file.as_uri():
                        continue
                    for entry in notification.get("diagnostics", []):
                        if isinstance(entry, dict):
                            code = entry.get("code")
                            if isinstance(code, str):
                                observed.add(code)
                    if "reportReturnType" in observed:
                        break
                assert "reportReturnType" in observed

    asyncio.run(asyncio.wait_for(exercise(), timeout=30))
    assert adapter.server.process is None
    assert file.read_text(encoding="utf-8") == original


def test_real_multilspy_pyright_rejects_outside_workspace(
    tmp_path: Path, pyright_executable: Path
) -> None:
    config, logger = _optional_upstream()
    root = tmp_path / "root"
    root.mkdir()
    private = tmp_path / "outside.py"
    private.write_text("secret = 1\n")
    (root / "symlink.py").symlink_to(private)
    adapter = create_pyright_adapter(
        config, logger, root, executable=pyright_executable
    )
    # Do not start a language server for a denied path.
    for target in ("../outside.py", "symlink.py", str(private)):
        with pytest.raises(ValueError), adapter.open_file(target):
            raise AssertionError("untrusted file unexpectedly opened")
    assert adapter.server.process is None


def test_fake_server_uses_custom_python_adapter_not_jedi(
    tmp_path: Path, pyright_executable: Path
) -> None:
    # All external binaries remain pinned and preconfigured by this test.
    # Fake protocol smoke for future language-specific extensions is already
    # provided by the P1 fixture suite; no need to duplicate its process owner.
    config, logger = _optional_upstream()
    adapter = create_pyright_adapter(
        config, logger, tmp_path, executable=pyright_executable
    )
    assert adapter.__class__.__name__ == "PyrightAdapter"
    assert adapter.language_id == "python"
    assert adapter.server.process_launch_info.cmd[-1] == "--stdio"
    assert adapter.server.process is None
