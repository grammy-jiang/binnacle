"""E1-a6 (F1, F4): which process is the serving entry, and when it clears.

``binnacle serve`` (the Mac com.binnacle.mcp entry and the Linux prod unit)
marks itself with ``startup_imports.serving_entry()`` and clears the record on
the public ``uvicorn.Server.started``; the uvicorn CLI (the dev unit) keeps the
documented START_CONFIRM_S rule. Every other importer (pytest, ``python -c``,
another ``binnacle`` subcommand, ``python -m binnacle.server``) neither writes
nor clears it. The end-to-end failing and good starts through the real entry
(``cli.main`` with argv0 ``<home>/bin/binnacle``) are in test_r6w3_e1e_fail_fast
(12 mutants) and test_r6w3_e1f_record_processes. Identical on both OSes. Test
homes live under ~/.local/state/bt/e1a6 (0700, exact-path teardown).
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import textwrap
import uuid
from contextlib import suppress
from pathlib import Path

import pytest

from binnacle import startup_imports
from binnacle.startup_imports import (
    record_path,
    serving_entry,
    serving_entry_marked,
)
from tests.unit.core.test_r6w3_e1f_record_processes import (
    free_port,
    plant,
    server_env,
)

REPO = Path(__file__).resolve().parents[3]
SRC = Path(startup_imports.__file__).parent
TEST_ROOT = Path.home() / ".local" / "state" / "bt" / "e1a6"


@pytest.fixture
def home():
    TEST_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(TEST_ROOT, 0o700)
    path = TEST_ROOT / f"se-{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o700)
    yield path
    shutil.rmtree(path)  # exact path this fixture created
    with suppress(OSError):  # only when no other test home remains
        TEST_ROOT.rmdir()


def run_driver(home: Path, code: str, *args: str) -> dict:
    done = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code), str(home), *args],
        cwd=REPO,
        env=server_env(home),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_serving_entry_is_scoped_to_the_run_that_made_it():
    assert not serving_entry_marked()
    with serving_entry():
        assert serving_entry_marked()
    assert not serving_entry_marked()
    with pytest.raises(RuntimeError), serving_entry():
        raise RuntimeError("uvicorn.run failed")
    assert not serving_entry_marked()  # a failed run leaks nothing either


def test_only_the_cli_serve_command_enters_the_serving_entry():
    def callers(name: str) -> set[str]:
        found = set()
        for path in sorted(SRC.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and ast.unparse(node.func) == name:
                    found.add(path.relative_to(SRC).as_posix())
        return found

    assert callers("serving_entry") == {"cli.py"}
    assert callers("serving_entry_marked") == {"server.py"}


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_binnacle_serve_marks_the_entry_while_uvicorn_runs(monkeypatch, system):
    from binnacle import cli
    from binnacle.platform import composition

    seen = []
    monkeypatch.delenv("BINNACLE_SERVICE_ROLE", raising=False)
    monkeypatch.setattr(composition.platform, "system", lambda: system)
    monkeypatch.setattr(
        "uvicorn.run", lambda *a, **k: seen.append((serving_entry_marked(), k))
    )
    cli.serve()
    cli.serve(reload=True)
    assert [marked for marked, _ in seen] == [True, True]
    assert [k["reload"] for _, k in seen] == [False, True]
    assert not serving_entry_marked()


SERVER_STARTED = """
import asyncio, json, sys
from pathlib import Path
from binnacle.startup_imports import record_path, serving_entry
home, port = Path(sys.argv[1]), int(sys.argv[2])
with serving_entry():
    import binnacle.server as server
import uvicorn
record = record_path(home, "mcp-server")
timer = getattr(server.app.router.lifespan_context, "__name__", "") == "_lifespan"

seen = {"started": False, "gone_at_started": False}

async def main():
    srv = uvicorn.Server(uvicorn.Config(
        server.app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio"))
    task = asyncio.ensure_future(srv.serve())
    while not srv.started and not task.done():
        await asyncio.sleep(0.002)
    seen.update(started=srv.started, gone_at_started=not record.exists())
    srv.should_exit = True
    await task

try:
    asyncio.run(main())
except SystemExit:  # a failed bind: uvicorn exits with STARTUP_FAILURE
    seen["exit"] = True
result = dict(seen, timer=timer, gone_at_end=not record.exists())
print(json.dumps(result))
"""


def test_the_record_is_cleared_the_moment_uvicorn_server_started_turns_true(home):
    plant(home, "mcp-server")
    result = run_driver(home, SERVER_STARTED, str(free_port()))
    # Observed at the instant `Server.started` was True: not START_CONFIRM_S later.
    assert result["started"] and result["gone_at_started"], result
    assert not result["timer"], "the marked entry installed the 1 s timer rule"


def test_a_server_that_never_started_keeps_the_record(home):
    import socket

    before = plant(home, "mcp-server")
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        result = run_driver(home, SERVER_STARTED, str(port))
    assert not result["started"] and result.get("exit"), result
    assert record_path(home, "mcp-server").read_bytes() == before


ARGV_PROBE = """
import asyncio, json, sys
from pathlib import Path
home, argv0, rest = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
sys.argv = [argv0, *rest]
import binnacle.server as server
from binnacle.startup_imports import StartupImportFailed, record_path

record = record_path(home, "mcp-server")
planted = record.read_bytes()

async def serve_briefly():
    server.START_CONFIRM_S = 0.05
    async with server.app.router.lifespan_context(server.app):
        await asyncio.sleep(0.6)

asyncio.run(serve_briefly())
cleared = not record.exists()
server._record_import_failure(StartupImportFailed("binnacle.e1g", "ImportError", "x:1"))
written = record.exists() and record.read_bytes() != planted
print(json.dumps({"cleared": cleared, "written": written}))
"""
BIN = "/h/.venv/bin"
VARIANTS = [
    # (argv0, the rest, a serving process?)
    pytest.param(f"{BIN}/uvicorn", ["binnacle.server:app"], True, id="bin-uvicorn"),
    pytest.param(
        "/h/.venv/lib/uvicorn/__main__.py",
        ["binnacle.server:app"],
        True,
        id="m-uvicorn",
    ),
    pytest.param(f"{BIN}/binnacle", ["serve"], False, id="binnacle-serve-unmarked"),
    pytest.param(f"{BIN}/pytest", ["-q"], False, id="pytest"),
    pytest.param("-c", [], False, id="python-c"),
    pytest.param(f"{BIN}/binnacle", ["doctor"], False, id="binnacle-doctor"),
    pytest.param(f"{BIN}/binnacle", [], False, id="binnacle-no-subcommand"),
    pytest.param("/h/src/binnacle/server.py", [], False, id="python-m-binnacle-server"),
    pytest.param(f"{BIN}/uvicorn-not", ["x"], False, id="uvicorn-lookalike"),
]


@pytest.mark.parametrize(("argv0", "rest", "serving"), VARIANTS)
def test_only_a_serving_process_writes_or_clears_the_record(home, argv0, rest, serving):
    # F4 / mutant OM2 (_serving_process() always True): a non-serving importer
    # neither clears the planted record nor replaces it; a serving one does both.
    plant(home, "mcp-server")
    result = run_driver(home, ARGV_PROBE, argv0, json.dumps(rest))
    assert result == {"cleared": serving, "written": serving}, (argv0, rest, result)
