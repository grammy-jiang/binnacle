"""Private Binnacle acceptance of the ACTUAL patched multilspy PyrightServer.

This suite intentionally DOES NOT call Binnacle's duplicate PyrightAdapter.
With explicit opt-in, a wrong source checkout/binary FAILS rather than skips.
It covers the inherited upstream API plus downstream admission through a
private in-memory FastMCP application. Nothing is registered in production.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest
from anyio import fail_after

from binnacle.config_development_intelligence import DevelopmentIntelligenceSettings
from binnacle.features.development_intelligence.lsp_session import utf16_offset
from binnacle.features.development_intelligence.multilspy_pyright import (
    _authorized_file,
    normalize_locations,
)

EXPECTED_UPSTREAM_SHA = "b5325f19c7b77317bd4ab7c1ff3c6bb8fa5b8f1b"
OPT_IN = "BINNACLE_PATCHED_MULTILSPY_QA"
SOURCE_ENV = "BINNACLE_MULTILSPY_SOURCE_DIR"
BINARY_ENV = "PYRIGHT_LSP_TEST_BIN"


@pytest.fixture(scope="module")
def patched_upstream():
    if os.environ.get(OPT_IN) != "1":
        pytest.skip(f"Run with {OPT_IN}=1 for mandatory pinned upstream acceptance")
    source_value = os.environ.get(SOURCE_ENV)
    binary_value = os.environ.get(BINARY_ENV)
    assert source_value, f"{SOURCE_ENV} is required for a real acceptance run"
    assert binary_value, f"{BINARY_ENV} is required for a real acceptance run"

    source = Path(source_value).resolve(strict=True)
    binary = Path(binary_value)
    assert binary.is_absolute() and binary.is_file(), "real Pyright binary required"
    revision = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    ).stdout.strip()
    assert revision == EXPECTED_UPSTREAM_SHA, "Wrong multilspy source revision"
    import inspect

    from multilspy.language_servers.pyright_language_server.pyright_server import (
        PyrightServer,
    )

    assert Path(inspect.getfile(PyrightServer)).resolve().is_relative_to(source), (
        "Detected installed/PyPI multilspy instead of source under test"
    )
    return binary, PyrightServer


@pytest.fixture
def disposable_workspace(tmp_path: Path):
    root = (tmp_path / "allowed workspace 🧭").resolve()
    root.mkdir()
    files = {
        "lib.py": (
            "def greet(name: str) -> str:\n"
            "    return name.upper()\n\n"
            "class Worker:\n"
            "    def process(self) -> int:\n"
            "        return 3\n"
        ),
        "app.py": (
            "from lib import greet, Worker\n\n"
            "first = greet('Ada')\n"
            "worker = Worker()\n"
            "result = worker.process()\n"
        ),
        "unicode.py": "from lib import greet\nmarker = '🧭'; value = greet('Lin')\n",
        "bad.py": "def bad_result() -> str:\n    return 123\n",
    }
    for name, value in files.items():
        (root / name).write_text(value, encoding="utf-8")
    (root / "pyrightconfig.json").write_text(
        '{"typeCheckingMode":"standard","include":["."]}\n', encoding="utf-8"
    )
    return root


def _original_bytes(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}


def _new_native_server(root: Path, patched_upstream):
    binary, cls = patched_upstream
    from multilspy import LanguageServer
    from multilspy.multilspy_config import Language, MultilspyConfig
    from multilspy.multilspy_logger import MultilspyLogger

    server = LanguageServer.create(
        MultilspyConfig(
            code_language=Language.PYTHON,
            python_server="pyright",
            server_binary=str(binary),
            trace_lsp_communication=False,
        ),
        MultilspyLogger(),
        str(root),
    )
    assert type(server) is cls  # NOT Binnacle subclass or a JediServer
    assert server.server.process is None
    assert server.server.process_launch_info.cmd == [str(binary), "--stdio"]
    return server


async def _request_definition_with_binnacle_policy(
    server, root: Path, relative: str, line: int, column: int
):
    safe_relative, _ = _authorized_file(root, relative)
    results = await server.request_definition(safe_relative, line, column)
    # Upstream normalized result remains untrusted. Validate every returned URI.
    return normalize_locations(
        root, [{"uri": result["uri"], "range": result["range"]} for result in results]
    )


def test_patched_factory_is_original_upstream_and_jedi_default(
    patched_upstream, disposable_workspace
):
    _new_native_server(disposable_workspace, patched_upstream)
    from multilspy import LanguageServer
    from multilspy.language_servers.jedi_language_server.jedi_server import JediServer
    from multilspy.multilspy_config import Language, MultilspyConfig
    from multilspy.multilspy_logger import MultilspyLogger

    jedi = LanguageServer.create(
        MultilspyConfig(code_language=Language.PYTHON),
        MultilspyLogger(),
        str(disposable_workspace),
    )
    assert isinstance(jedi, JediServer)
    assert jedi.server.process is None
    assert DevelopmentIntelligenceSettings().enabled is False


@pytest.mark.asyncio
async def test_real_upstream_navigation_hover_completions_and_unicode(
    patched_upstream, disposable_workspace
):
    root = disposable_workspace
    original = _original_bytes(root)
    server = _new_native_server(root, patched_upstream)
    with fail_after(40):
        async with server.start_server():
            with (
                server.open_file("lib.py"),
                server.open_file("app.py"),
                server.open_file("unicode.py"),
            ):
                loc = await _request_definition_with_binnacle_policy(
                    server, root, "app.py", 2, 10
                )
                assert len(loc) == 1
                assert loc[0]["relativePath"] == "lib.py"
                assert loc[0]["range"]["start"] == {"line": 0, "character": 4}

                refs = await server.request_references("lib.py", 0, 6)
                assert any(item["relativePath"] == "app.py" for item in refs)
                assert all(
                    Path(item["absolutePath"]).is_relative_to(root) for item in refs
                )

                hover = await server.request_hover("app.py", 2, 10)
                assert hover and "greet" in str(hover["contents"])
                symbols, _ = await server.request_document_symbols("lib.py")
                assert {"greet", "Worker"} <= {item["name"] for item in symbols}

                # Inherited high-level completion: previously broken by isIncomplete.
                completion = await server.request_completions(
                    "app.py", 4, len("result = worker.")
                )
                assert "process" in {item["completionText"] for item in completion}

                unicode_line = (
                    (root / "unicode.py").read_text(encoding="utf-8").splitlines()[1]
                )
                unicode_column = utf16_offset(
                    unicode_line, unicode_line.index("greet") + 1
                )
                assert unicode_column > unicode_line.index("greet") + 1
                unicode_defs = await _request_definition_with_binnacle_policy(
                    server, root, "unicode.py", 1, unicode_column
                )
                assert len(unicode_defs) == 1
                assert unicode_defs[0]["relativePath"] == "lib.py"
    assert server.server.process is None and not server.server_started
    assert _original_bytes(root) == original


@pytest.mark.asyncio
async def test_real_upstream_diagnostics_and_readonly_rename(
    patched_upstream, disposable_workspace
):
    root = disposable_workspace
    original = _original_bytes(root)
    server = _new_native_server(root, patched_upstream)
    with fail_after(40):
        async with server.start_server():
            refuse = server.server.on_request_handlers["workspace/applyEdit"]
            assert await refuse(
                {"edit": {"changes": {"file:///tmp/dont-write": []}}}
            ) == {
                "applied": False,
                "failureReason": "multilspy Pyright client is read-only",
            }
            with (
                server.open_file("lib.py"),
                server.open_file("app.py"),
                server.open_file("bad.py"),
            ):
                proposal = await server.server.send.rename(
                    {
                        "textDocument": {"uri": (root / "lib.py").as_uri()},
                        "position": {"line": 0, "character": 5},
                        "newName": "salute",
                    }
                )
                assert isinstance(proposal, dict) and proposal.get("documentChanges")
                assert len(proposal["documentChanges"]) >= 2
                codes = set()
                for _ in range(20):
                    try:
                        notification = await server.next_diagnostics(timeout=1)
                    except asyncio.TimeoutError:
                        continue
                    if notification.get("uri") != (root / "bad.py").as_uri():
                        continue
                    codes.update(
                        str(entry.get("code"))
                        for entry in notification.get("diagnostics", [])
                        if isinstance(entry, dict)
                    )
                    if "reportReturnType" in codes:
                        break
                assert "reportReturnType" in codes
    assert server.server.process is None
    assert _original_bytes(root) == original


@pytest.mark.asyncio
async def test_binnacle_path_admission_before_any_upstream_call(
    patched_upstream, disposable_workspace, tmp_path
):
    root = disposable_workspace
    outside = tmp_path / "secret.py"
    outside.write_text("PRIVATE_SOURCE = True\n", encoding="utf-8")
    (root / "outside_link.py").symlink_to(outside)
    server = _new_native_server(root, patched_upstream)
    assert server.server.process is None
    for forbidden in ("../secret.py", str(outside), "outside_link.py"):
        with pytest.raises(ValueError):
            await _request_definition_with_binnacle_policy(
                server, root, forbidden, 0, 0
            )
    with pytest.raises(ValueError):
        normalize_locations(
            root,
            [
                {
                    "uri": outside.as_uri(),
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 1},
                    },
                }
            ],
        )
    assert server.server.process is None


@pytest.mark.asyncio
async def test_normal_server_error_exits_without_leaking_child(
    patched_upstream, disposable_workspace
):
    server = _new_native_server(disposable_workspace, patched_upstream)
    process = None
    with pytest.raises(RuntimeError, match="intentional test failure"):
        async with server.start_server():
            process = server.server.process
            assert process is not None
            raise RuntimeError("intentional test failure")
    assert process is not None and process.returncode is not None
    assert server.server.process is None
    assert server.server.tasks == {}


@pytest.mark.asyncio
async def test_real_high_level_null_and_incomplete_positions(
    patched_upstream, disposable_workspace
):
    root = disposable_workspace
    server = _new_native_server(root, patched_upstream)
    with fail_after(25):
        async with server.start_server():
            assert await server.request_definition("app.py", 1, 0) == []
            assert await server.request_references("app.py", 1, 0) == []
            assert await server.request_hover("app.py", 1, 0) is None
            assert await server.request_completions("app.py", 1, 0) is not None
    assert server.server.process is None


@pytest.mark.asyncio
async def test_provider_can_restart_without_stale_diagnostics(
    patched_upstream, disposable_workspace
):
    root = disposable_workspace
    before = _original_bytes(root)
    server = _new_native_server(root, patched_upstream)
    for cycle in range(3):
        with fail_after(25):
            async with server.start_server():
                with server.open_file("app.py"):
                    definitions = await _request_definition_with_binnacle_policy(
                        server, root, "app.py", 2, 9
                    )
                    assert len(definitions) == 1
                if cycle == 0:
                    server.diagnostics.put_nowait({"uri": "file:///obsolete.py"})
                    server.diagnostics_dropped = True
                else:
                    assert not any(
                        item.get("uri") == "file:///obsolete.py"
                        for item in list(server.diagnostics._queue)
                    )
                    assert not server.diagnostics_dropped
        assert server.server.process is None
        assert server.server.tasks == {}
        assert not server.open_file_buffers
    assert _original_bytes(root) == before


@pytest.mark.asyncio
async def test_cancelling_context_body_cleans_provider(
    patched_upstream, disposable_workspace
):
    root = disposable_workspace
    server = _new_native_server(root, patched_upstream)
    ready = asyncio.Event()
    block = asyncio.Event()

    async def worker():
        async with server.start_server():
            ready.set()
            await block.wait()

    task = asyncio.create_task(worker())
    await asyncio.wait_for(ready.wait(), timeout=12)
    assert server.server.process is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=20)
    assert server.server.process is None
    assert server.server.tasks == {}
    assert not server.server_started
