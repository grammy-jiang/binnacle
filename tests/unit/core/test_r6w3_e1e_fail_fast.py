"""E1-a4: a required start-up import failure aborts start-up (12 mutants).

One mutant per class (ImportError, Exception, SystemExit) for the MCP server
(started as the uvicorn CLI and as the real `binnacle serve` entry) and both
job managers. Each runs in a child process that adds a synthetic
required module (``binnacle.e1e_mutant``) whose body raises, then starts the
real entry. Each asserts: exit ``EX_STARTUP_IMPORT``, no socket bound and no
lock taken (``socket.bind``/``fcntl.flock`` are recorded), exactly one
``event=startup_import_failed`` line naming the module, the exception type and
the raising frame without the message text, and the durable doctor record.
E1-a5/a6: the record is written by the real entry point under the configured state
root (the parent of ``jobs.dir``), never under XDG_STATE_HOME or HOME.
Test homes live under ~/.local/state/bt/e1a6 (0700, exact-path teardown).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

from binnacle import startup_imports
from binnacle.diagnostics.doctor_provenance import check_startup_imports
from binnacle.provenance import runtime_provenance
from binnacle.startup_imports import (
    EX_STARTUP_IMPORT,
    MANAGER_MODULES,
    OPTIONAL_MODULES,
    manager_entry_closure_allowed,
)

TEST_ROOT = Path.home() / ".local" / "state" / "bt" / "e1a6"
SECRET = "e1e-secret-message-text"
MUTANT = "binnacle.e1e_mutant"
BODIES = {
    "ImportError": f"raise ImportError({SECRET!r})\n",
    "RuntimeError": f"raise RuntimeError({SECRET!r})\n",
    "SystemExit": f"raise SystemExit({SECRET!r})\n",
}
ENTRIES = {
    "server": (
        "mcp-server",
        (
            # What `python -m uvicorn binnacle.server:app` runs: the serving process.
            "import runpy\n"
            "sys.argv = [home + '/uvicorn/__main__.py', 'binnacle.server:app',"
            " '--host', '127.0.0.1', '--port', str(PORT), '--log-level', 'warning']\n"
            "runpy.run_module('uvicorn', run_name='__main__')\n"
        ),
    ),
    "binnacle-serve": (
        "mcp-server",
        (
            # What the Mac com.binnacle.mcp and the Linux prod unit run: the REAL
            # entry (`binnacle serve`), not a uvicorn-CLI emulation (E1-a6, F1).
            "sys.argv = [home + '/bin/binnacle', 'serve', '--host', '127.0.0.1',"
            " '--port', str(PORT)]\n"
            "from binnacle import cli\n"
            "cli.main()\n"
        ),
    ),
    "linux-manager": (
        "job-manager",
        ("from binnacle.features.commands import job_manager\njob_manager.main()\n"),
    ),
    "darwin-manager": (
        "job-manager",
        (
            "from binnacle.platform.darwin import job_manager_entry\n"
            "raise SystemExit(job_manager_entry.main([]))\n"
        ),
    ),
}
DRIVER = textwrap.dedent(
    """
    import fcntl, importlib.abc, importlib.util, socket, sys
    home, mutant_file, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
    PORT = port
    marks = open(home + "/marks.txt", "a", buffering=1)
    real_bind, real_flock = socket.socket.bind, fcntl.flock
    def bind(self, address):
        marks.write("bind\\n")
        return real_bind(self, address)
    def flock(fd, op):
        marks.write("flock\\n")
        return real_flock(fd, op)
    socket.socket.bind, fcntl.flock = bind, flock

    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "binnacle.e1e_mutant":
                return importlib.util.spec_from_file_location(name, mutant_file)
            return None
    sys.meta_path.insert(0, Finder())

    from binnacle import startup_imports as su
    runtime, manager = su.runtime_module_names, su.manager_module_names
    su.runtime_module_names = lambda s=None: runtime(s) + ("binnacle.e1e_mutant",)
    su.manager_module_names = lambda s=None: manager(s) + ("binnacle.e1e_mutant",)
    """
)


@pytest.fixture
def home():
    TEST_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(TEST_ROOT, 0o700)
    path = TEST_ROOT / f"ff-{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o700)
    yield path
    shutil.rmtree(path)  # exact path this fixture created


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("error_class", sorted(BODIES))
@pytest.mark.parametrize("entry", sorted(ENTRIES))
def test_required_import_failure_aborts_start_up(home, entry, error_class):
    process, start = ENTRIES[entry]
    mutant = home / "e1e_mutant.py"
    mutant.write_text(BODIES[error_class], encoding="utf-8")
    driver = home / "driver.py"
    driver.write_text(DRIVER + start, encoding="utf-8")
    port = _free_port()
    config = home / "config.toml"  # the configured state root is home/state
    config.write_text(
        f'[jobs]\ndir = "{home / "state" / "jobs"}"\nowner = "embedded"\n'
        f'socket_path = "{home / "j.sock"}"\n',
        encoding="utf-8",
    )
    token = home / "token"
    token.write_text("Bearer e1e\n", encoding="utf-8")
    token.chmod(0o600)
    config.write_text(
        config.read_text(encoding="utf-8") + f'[auth]\ntoken_file = "{token}"\n',
        encoding="utf-8",
    )
    decoy = home / "xdg"  # XDG_STATE_HOME is not the record's root any more
    env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
    env.update(BINNACLE_CONFIG_FILE=str(config), XDG_STATE_HOME=str(decoy))
    env.pop("PYTHONSTARTUP", None)
    result = subprocess.run(
        [sys.executable, str(driver), str(home), str(mutant), str(port)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == EX_STARTUP_IMPORT, output[-4000:]
    lines = [
        line for line in output.splitlines() if "event=startup_import_failed" in line
    ]
    assert len(lines) == 1, output[-4000:]
    assert f"module={MUTANT}" in lines[0]
    assert f"error_class={error_class}" in lines[0]
    assert f"process={process}" in lines[0]
    assert "at=" in lines[0] and "e1e_mutant.py:1" in lines[0], lines[0]
    assert SECRET not in output and "Traceback" not in output, output[-4000:]
    marks = (home / "marks.txt").read_text(encoding="utf-8").split()
    assert "bind" not in marks and "flock" not in marks, marks
    with socket.socket() as probe:  # the server port was never bound
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    record_dir = home / "state" / "startup-import"
    record = json.loads((record_dir / f"{process}.json").read_text(encoding="utf-8"))
    assert set(record) == {
        "process",
        "time",
        "revision",
        "module",
        "error_class",
        "where",
    }, record
    assert record["module"] == MUTANT and record["error_class"] == error_class
    assert record["process"] == process
    assert record["revision"] == runtime_provenance().revision
    assert SECRET not in json.dumps(record)
    assert not decoy.exists(), "the record followed XDG_STATE_HOME"
    (check,) = check_startup_imports(record_dir)
    assert check.status == "fail" and MUTANT in check.detail, check


def test_package_init_failure_in_the_import_loop_aborts(monkeypatch):
    # RE1-F1: a package __init__ that raises is not skipped. The server set is a
    # frozen literal (SD-90) that names the packages, so the loop imports them.
    def boom(name):
        raise SystemExit("walk")

    monkeypatch.setattr(startup_imports.importlib, "import_module", boom)
    with pytest.raises(startup_imports.StartupImportFailed) as caught:
        startup_imports.import_runtime_modules()
    assert caught.value.code == EX_STARTUP_IMPORT
    assert caught.value.error_class == "SystemExit"
    assert caught.value.module == startup_imports.runtime_module_names()[0]


def test_optional_allowlist_is_pinned_empty():
    # No module may fail and report itself unavailable at call time today.
    assert OPTIONAL_MODULES == ()


def test_manager_entry_closure_exception_is_linux_only():
    # RE1-F4 (mutant OM6): Darwin rejects binnacle.mcp in the manager set.
    assert manager_entry_closure_allowed("Darwin") == ()
    assert set(manager_entry_closure_allowed("Linux")) == {
        "binnacle.mcp",
        "binnacle.mcp.callctx",
    }
    darwin = MANAGER_MODULES["Darwin"]
    assert not [
        n for n in darwin if n == "binnacle.mcp" or n.startswith("binnacle.mcp.")
    ]


def test_linux_manager_entry_configures_logging_only_in_main():
    # RE1-F5: importing the entry (the Linux server does) leaves root logging alone.
    source = (
        Path(startup_imports.__file__).parent / "features/commands/job_manager.py"
    ).read_text(encoding="utf-8")
    assert "logging.basicConfig(" not in source
    assert 'process="job-manager",\n        log_format=LOG_FORMAT,' in source


AT_CASES = [
    # (module name, body or None for an absent module, error class, where)
    ("re1a4_syntax", "x = 1\ndef broken(:\n", "SyntaxError", "re1a4_syntax.py:2"),
    (
        "re1a4_nested",
        "x = 1\nimport re1a4_absent_dep\n",
        "ModuleNotFoundError",
        "re1a4_nested.py:2",
    ),
    (
        "re1a4_raises",
        "raise RuntimeError('secret')\n",
        "RuntimeError",
        "re1a4_raises.py:1",
    ),
    ("binnacle.re1a4_absent", None, "ModuleNotFoundError", "binnacle.re1a4_absent:0"),
]


@pytest.mark.parametrize(("name", "body", "error_class", "where"), AT_CASES)
def test_at_names_the_raising_source_never_a_frozen_frame(
    tmp_path, monkeypatch, name, body, error_class, where
):
    # STEER-02: skip importlib/frozen frames and this module's own frame.
    if body is not None:
        (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(startup_imports.StartupImportFailed) as caught:
        startup_imports._required_import(name)
    assert caught.value.where == where
    assert caught.value.error_class == error_class
    assert "<frozen" not in caught.value.where


@pytest.mark.parametrize(("name", "body", "error_class", "where"), AT_CASES[:2])
def test_a_required_module_that_is_missing_or_unparsable_logs_its_own_location(
    tmp_path, monkeypatch, caplog, name, body, error_class, where
):
    # Through the start-up loop: a REQUIRED module with a SyntaxError, and a
    # required module whose own import (ModuleNotFoundError) is missing.
    (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(
        startup_imports, "runtime_module_names", lambda _s=None: (name,)
    )
    with (
        caplog.at_level("ERROR", logger="binnacle.startup_imports"),
        pytest.raises(startup_imports.StartupImportFailed),
    ):
        startup_imports.import_runtime_modules()
    (line,) = [m for m in caplog.messages if "event=startup_import_failed" in m]
    assert f"module={name} error_class={error_class} at={where} exit=70" in line
    assert "<frozen" not in line and "importlib" not in line


def test_a_missing_required_binnacle_module_is_named_by_its_module(monkeypatch):
    # No file to open: at= is the module's own name, never an importlib frame.
    missing = "binnacle.re1a6_never_existed"
    monkeypatch.setattr(
        startup_imports, "runtime_module_names", lambda _s=None: (missing,)
    )
    with pytest.raises(startup_imports.StartupImportFailed) as caught:
        startup_imports.import_runtime_modules()
    assert (caught.value.module, caught.value.error_class) == (
        missing,
        "ModuleNotFoundError",
    )
    assert caught.value.where == f"{missing}:0"
