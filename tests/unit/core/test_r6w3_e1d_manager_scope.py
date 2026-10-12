"""E1-a3: a job manager imports only its pinned manager-scoped set.

E1B-R1: importing the whole runtime tree doubled the Darwin manager's RSS for
code it never runs. ``startup_imports.MANAGER_MODULES`` pins, per OS, the
manager entry's start-up closure plus every binnacle module it imports lazily
while serving; the MCP server keeps the whole tree (E1). Each host runs its own
manager entry: identical assertions on both OSes. Test homes live under
~/.local/state/bt/e1d (0700), removed by exact path.
"""

import ast
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import pytest

from binnacle.startup_imports import (
    _EXCLUDED_BY_OS,
    MANAGER_ENTRY_CLOSURE_ALLOWED,
    MANAGER_EXCLUDED,
    MANAGER_MODULES,
    manager_module_names,
    runtime_module_names,
)
from tests.unit.core.test_r6w3_e1b_manager_imports import (
    late_imports,
    private_home,  # noqa: F401 - the shared 0700 home fixture
    running_manager,
)

SRC = Path(__file__).resolve().parents[3] / "src" / "binnacle"


def _under(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_manager_set_leaves_out_the_mcp_tree_and_the_other_os(system):
    names = MANAGER_MODULES[system]
    assert list(names) == sorted(set(names))
    assert set(names) - {"binnacle"} <= set(runtime_module_names(system))
    assert not [name for name in names if "tools" in name.split(".")]
    assert not [name for name in names if _under(name, _EXCLUDED_BY_OS[system])]
    excluded = [name for name in names if _under(name, MANAGER_EXCLUDED)]
    assert set(excluded) <= set(MANAGER_ENTRY_CLOSURE_ALLOWED), excluded
    # The one allowed exception is imported by the Linux entry module itself.
    entry = (SRC / "features/commands/job_manager.py").read_text(encoding="utf-8")
    assert "\nfrom binnacle.mcp.callctx import current_call\n" in entry


def test_server_keeps_the_full_runtime_tree():
    tree = ast.parse((SRC / "server.py").read_text(encoding="utf-8"))
    calls = [
        ast.unparse(node.value.func)
        for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    ]
    assert calls.count("import_runtime_modules") == 1, calls
    assert "import_manager_modules" not in ast.unparse(tree)


def test_import_manager_modules_loads_exactly_the_pinned_set():
    # A fresh interpreter: nothing outside the list (no excluded or other-OS
    # package, not even to list names) and every listed module imports.
    script = """
import json, sys
from binnacle.startup_imports import import_manager_modules
failed = import_manager_modules()
loaded = sorted(m for m in sys.modules if m.split(".")[0] == "binnacle")
print(json.dumps({"failed": list(failed), "loaded": loaded}))
"""
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    result = json.loads(done.stdout)
    assert result["failed"] == []
    assert result["loaded"] == list(manager_module_names())


def _raw(client, sock: Path, payload: dict) -> dict:
    if platform.system() == "Darwin":
        return client.request(sock, payload)
    return client._request(sock, payload)


def _attempt(call) -> dict:
    try:
        return call()
    except RuntimeError as exc:  # both clients raise RuntimeError subclasses
        return {"ok": False, "error": str(exc)}


def wide_exercise(client, sock: Path, work: Path) -> dict:
    """Every manager RPC path: start (fg, stdin, failing, bg), processes
    (Darwin), stop, a natural exit while serving, stop of an exited and an
    unknown job, and the error paths (missing workdir, op, version)."""

    def start(command, wait, call_id, stdin=None, workdir=work):
        return client.start(
            sock,
            command=command,
            workdir=workdir,
            stdin=stdin,
            wait_seconds=wait,
            call_id=call_id,
        )

    out = {"fg": start("echo e1d; echo e1d-err >&2", 10.0, "e1d-fg")}
    out["stdin"] = start("cat", 10.0, "e1d-stdin", stdin="e1d\n")
    out["exit3"] = start("exit 3", 10.0, "e1d-exit3")
    out["bg"] = start("sleep 30", 0.2, "e1d-bg")
    if platform.system() == "Darwin":
        out["processes"] = client.processes(sock, out["bg"]["job_id"])
    out["stop"] = client.stop(sock, out["bg"]["job_id"], call_id="e1d-stop")
    natural = start("sleep 0.2; echo e1d-late", 0.0, "e1d-natural")
    time.sleep(1.0)  # the job exits while the manager serves
    out["stop_exited"] = client.stop(sock, natural["job_id"], call_id="e1d-stop2")
    out["stop_unknown"] = _attempt(lambda: client.stop(sock, "0" * 12))
    out["bad_workdir"] = _attempt(
        lambda: start("true", 1.0, "e1d-bad", workdir=work / "missing")
    )
    out["bad_op"] = _attempt(lambda: _raw(client, sock, {"version": 1, "op": "e1d"}))
    out["bad_version"] = _attempt(
        lambda: _raw(client, sock, {"version": 99, "op": "ping"})
    )
    out["ping"] = client.ping(sock)
    return out


def test_serving_manager_loads_only_its_pinned_set(private_home):  # noqa: F811
    with running_manager(private_home) as (child, client, sock, pong, _):
        assert pong["pid"] == child.pid
        calls = wide_exercise(client, sock, private_home / "work")
        served, late = late_imports(private_home)
    assert [calls[k]["state"] for k in ("fg", "stdin", "exit3")] == ["exited"] * 3
    assert calls["bg"]["state"] == "running" and calls["stop"]["ok"] is True
    assert calls["stop_exited"]["ok"] is True
    for key in ("stop_unknown", "bad_workdir", "bad_op", "bad_version"):
        assert calls[key]["ok"] is False, (key, calls[key])
    assert calls["ping"]["owner_instance_id"] == pong["owner_instance_id"]
    log = (private_home / "manager.log").read_text(errors="replace")
    assert "event=startup_import_error" not in log, log[-4000:]
    # A module outside the list (a new closure module, or a lazy import the
    # list misses) fails here: either it is loaded at serve time or late.
    assert served == list(manager_module_names()), log[-4000:]
    assert late == [], log[-4000:]
