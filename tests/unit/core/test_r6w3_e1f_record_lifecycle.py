"""E1-a5 (SD-84 RULING 1): the start-up import record's lifecycle, in process.

Importing binnacle.server, or calling the import functions, never touches the
record. Only the real entry points write it (on a failure) and clear it (after
a successful start of the same process). The record lives under the configured
state root, holds no message text, and ``doctor`` marks an older revision's
record STALE. Identical assertions on both OSes. Test homes live under
~/.local/state/bt/e1a6 (0700, exact-path teardown).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import threading
import time
import types
import uuid
from contextlib import suppress
from pathlib import Path

import pytest

from binnacle import startup_imports
from binnacle.diagnostics.doctor_provenance import check_startup_imports
from binnacle.features.commands import job_manager
from binnacle.platform.darwin import job_manager_entry
from binnacle.startup_imports import (
    StartupImportFailed,
    clear_record,
    import_manager_modules,
    import_runtime_modules,
    record_dir,
    record_path,
    record_start_failure,
    state_root_of,
)

SRC = Path(startup_imports.__file__).parent
TEST_ROOT = Path.home() / ".local" / "state" / "bt" / "e1a6"
FAILURE = StartupImportFailed("binnacle.x", "ImportError", "binnacle/x.py:3")


@pytest.fixture
def home():
    TEST_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(TEST_ROOT, 0o700)
    path = TEST_ROOT / f"lc-{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o700)
    yield path
    shutil.rmtree(path)  # exact path this fixture created
    with suppress(OSError):  # only when no other test home remains
        TEST_ROOT.rmdir()


def plant(root: Path, process: str = "job-manager") -> bytes:
    assert record_start_failure(process, FAILURE, root)
    return record_path(root, process).read_bytes()


def survives(import_fn, root: Path) -> None:
    before = plant(root)
    import_fn()
    assert record_path(root, "job-manager").read_bytes() == before, "record changed"


def test_an_import_never_touches_the_record(home, monkeypatch):
    monkeypatch.setattr(startup_imports, "runtime_module_names", lambda _s=None: ())
    monkeypatch.setattr(startup_imports, "manager_module_names", lambda _s=None: ())
    survives(import_manager_modules, home)
    survives(import_runtime_modules, home)
    survives(lambda: import_manager_modules(process="mcp-server"), home)


def test_a_failing_import_does_not_write_without_an_entry_callback(home, monkeypatch):
    monkeypatch.setattr(
        startup_imports, "manager_module_names", lambda _s=None: ("binnacle.e1f_nope",)
    )
    with pytest.raises(StartupImportFailed):
        import_manager_modules()
    assert not record_dir(home).exists()
    seen = []
    with pytest.raises(StartupImportFailed):
        import_manager_modules(on_failure=seen.append)  # the entry's own hook
    assert [f.module for f in seen] == ["binnacle.e1f_nope"]
    assert not record_dir(home).exists()


def test_a_clear_on_import_mutant_is_caught(home, monkeypatch):
    monkeypatch.setattr(startup_imports, "manager_module_names", lambda _s=None: ())
    real = startup_imports.import_manager_modules

    def clearing_mutant():  # the E1-a4 defect: the import cleared the record
        result = real()
        clear_record("job-manager", home)
        return result

    survives(real, home)
    with pytest.raises(FileNotFoundError):
        survives(clearing_mutant, home)  # the survival check kills the mutant


def _callers(name: str) -> set[str]:
    found = set()
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and ast.unparse(node.func) == name:
                found.add(path.relative_to(SRC).as_posix())
    return found


def test_only_the_entry_points_write_or_clear_the_record():
    entries = {
        "server.py",
        "features/commands/job_manager.py",
        "platform/darwin/job_manager_entry.py",
    }
    assert _callers("clear_record") == entries
    # The guarded process entry writes an import-failure record before
    # its usual manager module can be imported (R6W3-01). No other source
    # may write or clear these records.
    assert _callers("record_start_failure") == entries | {"manager_bootstrap.py"}
    library = ast.parse((SRC / "startup_imports.py").read_text(encoding="utf-8"))
    for node in library.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "_fail_fast",
            "_required_import",
            "import_runtime_modules",
            "import_manager_modules",
            "runtime_module_names",
            "manager_module_names",
        }:
            body = ast.unparse(node)
            for writer in ("record_start_failure", "clear_record", "record_path"):
                assert writer not in body, (node.name, writer)


def test_the_library_has_no_home_or_xdg_default():
    source = (SRC / "startup_imports.py").read_text(encoding="utf-8")
    assert "Path.home" not in source and "XDG_STATE_HOME" not in source


def test_the_record_follows_the_configured_state_root(home, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "decoy"))
    jobs_dir = home / "custom" / "jobs"
    root = state_root_of(jobs_dir)
    assert root == home / "custom"
    assert record_start_failure("job-manager", FAILURE, root)
    assert record_path(root, "job-manager").parent == home / "custom" / "startup-import"
    assert not (home / "decoy").exists()
    assert (record_dir(root).stat().st_mode & 0o777) == 0o700


def test_the_record_has_the_pinned_fields_and_no_message(home):
    failure = StartupImportFailed("binnacle.x", "RuntimeError", "binnacle/x.py:9")
    failure.args = ("secret message text",)  # a message must never be recorded
    record_start_failure("mcp-server", failure, home)
    data = json.loads(record_path(home, "mcp-server").read_text(encoding="utf-8"))
    assert set(data) == {
        "process",
        "time",
        "revision",
        "module",
        "error_class",
        "where",
    }
    assert data["process"] == "mcp-server" and data["where"] == "binnacle/x.py:9"
    assert "secret" not in json.dumps(data)
    time.strptime(data["time"], "%Y-%m-%dT%H:%M:%SZ")  # UTC timestamp


def test_doctor_marks_an_older_revision_stale_and_the_current_one_fail(home):
    plant(home, "job-manager")
    directory = record_dir(home)
    # A different *verified Git revision*, not arbitrary free text, proves
    # the record belongs to another checkout. Unknown never means STALE.
    record = record_path(home, "job-manager")
    payload = json.loads(record.read_text("utf-8"))
    payload["revision"] = "a" * 12
    record.write_text(json.dumps(payload), encoding="utf-8")
    now = time.time() + 90
    (current,) = check_startup_imports(directory, revision="b" * 12, now=now)
    stale_rev = payload["revision"]
    (older,) = check_startup_imports(directory, revision="c" * 12, now=now)
    (same,) = check_startup_imports(directory, revision=stale_rev, now=now)
    assert same.status == "fail" and f"revision={stale_rev}" in same.detail
    assert 85 <= int(re.search(r"age=(\d+)s", same.detail).group(1)) <= 110
    for check in (current, older):
        assert check.status == "warn" and check.detail.startswith("STALE:")
        assert f"revision={stale_rev}" in check.detail
        assert "running revision=" in check.detail


def test_doctor_is_ok_without_a_record_and_unreadable_is_fail(home):
    assert [c.status for c in check_startup_imports(home / "absent")] == ["ok"]
    directory = record_dir(home)
    directory.mkdir(parents=True)
    (directory / "x.json").write_text("{not json", encoding="utf-8")
    assert [c.status for c in check_startup_imports(directory)] == ["fail"]


def test_a_stale_endpoint_does_not_clear_only_this_process_publishing_does(home):
    root = home / "run"
    root.mkdir(mode=0o700)
    sock = root / "jobs.sock"
    auth = root / "jobs.sock.auth"
    lease = types.SimpleNamespace(generation="mine")
    cleared, stop = threading.Event(), threading.Event()
    other = {"pid": os.getpid() + 1, "generation": "mine", "key": "k"}
    auth.write_text(json.dumps(other), encoding="utf-8")  # an earlier incarnation
    thread = job_manager_entry.clear_record_when_published(
        sock, lease, stop, cleared.set
    )
    assert not cleared.wait(0.4)
    auth.write_text(json.dumps({**other, "pid": os.getpid()}), encoding="utf-8")
    assert cleared.wait(5)
    thread.join(5)
    # a stop before publication ends the watcher without clearing
    auth.unlink()
    again, stopped = threading.Event(), threading.Event()
    thread = job_manager_entry.clear_record_when_published(
        sock, lease, stopped, again.set
    )
    stopped.set()
    thread.join(5)
    assert not again.is_set() and not thread.is_alive()


def _linux_main_env(monkeypatch, home, socket_path):
    settings = types.SimpleNamespace(
        jobs=types.SimpleNamespace(dir=home / "jobs", socket_path=socket_path)
    )
    monkeypatch.setattr(job_manager, "get_settings", lambda: settings)
    monkeypatch.setattr(job_manager, "import_manager_modules", lambda **_: ())
    monkeypatch.setattr(job_manager, "_boot_id", lambda: "boot")
    return plant(home)


def test_linux_manager_clears_only_after_the_socket_is_bound(home, monkeypatch):
    sock = home / "j.sock"
    before = _linux_main_env(monkeypatch, home, sock)
    seen = {}
    monkeypatch.setattr(job_manager.JobManager, "prepare", lambda self: 0)

    def notify():  # bound, announced, but the record is still there
        seen["bound"] = sock.exists()
        seen["kept"] = record_path(home, "job-manager").read_bytes() == before

    monkeypatch.setattr(job_manager, "_notify_systemd_ready", notify)
    monkeypatch.setattr(
        job_manager._ThreadingUnixServer, "serve_forever", lambda *a, **k: None
    )
    job_manager.main()
    assert seen == {"bound": True, "kept": True}
    assert not record_path(home, "job-manager").exists()  # cleared after the bind


def test_linux_manager_keeps_the_record_when_start_fails_before_the_bind(
    home, monkeypatch
):
    sock = home / "j.sock"
    before = _linux_main_env(monkeypatch, home, sock)

    def refuse(self):
        raise RuntimeError("job manager already answers")

    monkeypatch.setattr(job_manager.JobManager, "prepare", refuse)
    with pytest.raises(RuntimeError):
        job_manager.main()
    assert record_path(home, "job-manager").read_bytes() == before
    monkeypatch.setattr(
        job_manager,
        "get_settings",
        lambda: types.SimpleNamespace(
            jobs=types.SimpleNamespace(dir=home / "jobs", socket_path=None)
        ),
    )
    with pytest.raises(RuntimeError):
        job_manager.main()  # no socket resolved: still before any bind
    assert record_path(home, "job-manager").read_bytes() == before


def _darwin_main_env(monkeypatch, home):
    entry = job_manager_entry
    settings = types.SimpleNamespace(
        jobs=types.SimpleNamespace(
            dir=home / "jobs", socket_path=home / "j.sock", keep_newest=5
        ),
        run_command=types.SimpleNamespace(wait_max_s=5),
    )
    lease = types.SimpleNamespace(generation="gen-1")
    for name, value in {
        "import_manager_modules": lambda: (),
        "inherited_fds_cloexec": lambda: None,
        "read_config": lambda: settings,
        "require_socket_path": lambda path: None,
        "open_service_lease": lambda **_: lease,
        "boot_id": lambda: "boot",
        "compose_owner": lambda boot: types.SimpleNamespace(reaper_running=True),
        "provisioner_stop": lambda *_: True,
    }.items():
        monkeypatch.setattr(entry, name, value)
    monkeypatch.setattr(
        entry,
        "DarwinJobManager",
        lambda **_: types.SimpleNamespace(owner_instance_id="o"),
    )
    monkeypatch.setattr(entry.signal, "signal", lambda *a: None)
    monkeypatch.setattr(entry.os, "waitid", lambda *a: None, raising=False)
    return plant(home)


def test_darwin_manager_clears_only_after_this_process_publishes(home, monkeypatch):
    before = _darwin_main_env(monkeypatch, home)
    seen = {}

    def serve(manager, *, socket_path, lease, stop):
        time.sleep(0.3)  # started, not yet published: the record must stay
        seen["kept"] = record_path(home, "job-manager").read_bytes() == before
        auth = socket_path.with_name(socket_path.name + ".auth")
        auth.write_text(
            json.dumps({"pid": os.getpid(), "generation": lease.generation}),
            encoding="utf-8",
        )
        deadline = time.monotonic() + 5
        while record_path(home, "job-manager").exists() and time.monotonic() < deadline:
            time.sleep(0.02)

    monkeypatch.setattr(job_manager_entry, "serve_job_manager", serve)
    assert job_manager_entry.main([]) == 0
    assert seen == {"kept": True}
    assert not record_path(home, "job-manager").exists()


def test_darwin_manager_keeps_the_record_when_start_fails_before_publishing(
    home, monkeypatch
):
    before = _darwin_main_env(monkeypatch, home)

    def serve(manager, *, socket_path, lease, stop):
        time.sleep(0.3)
        raise RuntimeError("job_manager_start_failed")

    monkeypatch.setattr(job_manager_entry, "serve_job_manager", serve)
    assert job_manager_entry.main([]) == job_manager_entry.EX_FAILED
    assert record_path(home, "job-manager").read_bytes() == before
