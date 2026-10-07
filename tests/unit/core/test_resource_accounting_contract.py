"""Resource ports preserve optional accounting and supplied-command execution."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
from functools import partial

import pytest

from binnacle import job_cgroup
from binnacle.platform.contracts.resource_contracts import (
    NoResourceAccounting,
    ResourceAccounting,
)


@pytest.fixture
def accounting(tmp_path, monkeypatch) -> ResourceAccounting:
    """Run every concrete operation against synthetic proc and cgroup trees."""
    proc = tmp_path / "proc" / "self"
    proc.mkdir(parents=True)
    (proc / "cgroup").write_text("0::/demo/binnacle-manager\n")
    (tmp_path / "cgroup" / "demo").mkdir(parents=True)
    for name in ("prepare", "create", "wrap_argv", "snapshot", "wait_empty", "cleanup"):
        kwargs = {"cgroup_fs": tmp_path / "cgroup"}
        if name == "prepare":
            kwargs["proc_root"] = tmp_path / "proc"
        monkeypatch.setattr(
            job_cgroup, name, partial(getattr(job_cgroup, name), **kwargs)
        )
    return job_cgroup.CgroupResourceAccounting()


@pytest.mark.parametrize("identity", [None, "", "/legacy/job-012345abcdef"])
def test_no_accounting_has_no_counters_and_refuses_legacy_cleanup(identity):
    accounting: ResourceAccounting = NoResourceAccounting()
    argv = ["arbitrary-interpreter", "two words", "$(literal)"]
    assert accounting.prepare() is None
    assert accounting.prepare(log_ready=True) is None
    assert accounting.create("012345abcdef") is None
    assert accounting.wrap_argv(argv, identity) is argv
    assert argv == ["arbitrary-interpreter", "two words", "$(literal)"]
    assert accounting.snapshot(identity) == {}
    assert accounting.wait_empty("/legacy/job-012345abcdef") is False
    assert accounting.cleanup(identity) is (identity is None)


@pytest.mark.parametrize("argv", [[], ["python", "-c", "print('two words')"]])
def test_no_identity_preserves_the_supplied_list(accounting, argv):
    before = argv.copy()
    for port in (accounting, NoResourceAccounting()):
        assert port.wrap_argv(argv, None) is argv
        assert argv == before


@pytest.mark.parametrize("controllers", [None, "", "io", "memory"])
def test_missing_controllers_allow_identity_and_optional_counters(
    accounting, tmp_path, caplog, controllers
):
    root = tmp_path / "cgroup" / "demo"
    if controllers is not None:
        (root / "cgroup.controllers").write_text(controllers)
        (root / "cgroup.subtree_control").write_text("")
    with caplog.at_level("INFO", logger="binnacle.jobs"):
        assert accounting.prepare(log_ready=True) == "/demo"
    if controllers is not None:
        assert "event=job_cgroup_ready root=/demo" in caplog.text
        expected = "+memory" if controllers == "memory" else ""
        assert (root / "cgroup.subtree_control").read_text() == expected
    identity = accounting.create("012345abcdef")
    assert identity == "/demo/job-012345abcdef"
    assert accounting.snapshot(identity) == {}
    assert accounting.cleanup(identity) is True
    assert accounting.create("../../escape") is None


def test_missing_delegation_does_not_prevent_plain_execution(accounting, tmp_path):
    (tmp_path / "proc" / "self" / "cgroup").unlink()
    assert accounting.prepare() is None
    identity = accounting.create("012345abcdef")
    assert identity is None
    argv = [sys.executable, "-c", "print('plain execution')"]
    result = subprocess.run(
        accounting.wrap_argv(argv, identity),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (
        0,
        "plain execution\n",
        "",
    )


def test_snapshot_shape_and_cleanup_outcomes(accounting, tmp_path):
    identity = "/demo"
    root = tmp_path / "cgroup" / "demo"
    assert accounting.snapshot(None) == {}
    assert accounting.snapshot("/absent") == {}
    assert accounting.snapshot(identity) == {}
    (root / "cpu.stat").write_text("usage_usec 123\n")
    (root / "cgroup.procs").write_text("1234\n")
    assert accounting.snapshot(identity) == {
        "cpu": {"usage_usec": 123},
        "processes": 1,
    }
    # Ordinary files stand in for a populated kernel scope that rejects rmdir.
    assert accounting.cleanup(identity) is False
    assert root.is_dir()
    (root / "cpu.stat").unlink()
    (root / "cgroup.procs").unlink()
    assert accounting.cleanup(identity) is True
    assert not root.exists()
    assert accounting.cleanup(identity) is True
    assert accounting.cleanup(None) is True


@pytest.mark.parametrize("events", [None, "frozen 0\n", "populated 0\n"])
def test_wait_empty_requires_an_observable_empty_scope(accounting, tmp_path, events):
    if events is not None:
        (tmp_path / "cgroup" / "demo" / "cgroup.events").write_text(events)
    assert accounting.wait_empty("/demo") is (events == "populated 0\n")


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("prepare", ()),
        ("create", ("012345abcdef",)),
        ("wrap_argv", (["printf", "probe"], "/demo")),
        ("snapshot", ("/demo",)),
        ("wait_empty", ("/demo",)),
        ("cleanup", ("/demo",)),
    ],
)
def test_optional_accounting_does_not_swallow_programming_errors(
    accounting, monkeypatch, method, args
):
    def broken(*args, **kwargs):
        raise RuntimeError("synthetic programming error")

    monkeypatch.setattr(job_cgroup, method, broken)
    with pytest.raises(RuntimeError, match="synthetic programming error"):
        getattr(accounting, method)(*args)


_PROBE = """
import json, os, signal, sys
print(json.dumps({
    'pid': os.getpid(), 'argv': sys.argv[1:], 'stdin': sys.stdin.read(),
    'env': os.environ['RESOURCE_PROBE'], 'cwd': os.getcwd(),
}), flush=True)
sys.stderr.write('command stderr\\n')
sys.stderr.flush()
if os.environ['RESOURCE_SIGNAL'] == 'yes':
    os.kill(os.getpid(), signal.SIGTERM)
sys.exit(23)
"""


def _run_probe(argv, workdir, stdin, env):
    with subprocess.Popen(
        argv,
        cwd=workdir,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(stdin, timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=5)
            raise
        payload = json.loads(stdout)
        assert payload.pop("pid") == proc.pid
        return payload, proc.returncode, stderr, proc.pid


@pytest.mark.parametrize("attach", ["none", "attached", "failed"])
@pytest.mark.parametrize("terminate", [False, True])
def test_argv_exec_matches_direct_and_legacy_execution(
    accounting, tmp_path, attach, terminate
):
    identity = None if attach == "none" else "/demo/quoted ' $ scope"
    procs = tmp_path / "cgroup" / "demo" / "quoted ' $ scope" / "cgroup.procs"
    if identity:
        procs.parent.mkdir()
        if attach == "failed":
            procs.mkdir()  # Writes fail even when the test runs as root.
        else:
            procs.write_text("")
    executable = tmp_path / "python with ' spaces"
    executable.symlink_to(sys.executable)
    arguments = [
        "",
        "two words",
        "'\"",
        "$literal",
        "$(literal)",
        "`literal`",
        "a;b",
        "*",
        "line\nbreak",
        "back\\slash",
        "--option",
        "π",
    ]
    base = [str(executable), "-c", _PROBE, *arguments]
    before = base.copy()
    wrapped = accounting.wrap_argv(base, identity)
    assert base == before
    legacy = job_cgroup.launch_argv(
        "exec " + shlex.join(base), identity, cgroup_fs=tmp_path / "cgroup"
    )
    stdin = "input ' $ \\ data\n" * 10000
    env = {
        **os.environ,
        "RESOURCE_PROBE": "literal ' $ \\ value",
        "RESOURCE_SIGNAL": "yes" if terminate else "no",
    }
    expected = {
        "argv": arguments,
        "stdin": stdin,
        "env": env["RESOURCE_PROBE"],
        "cwd": str(tmp_path),
    }
    results = []
    for argv in (base, legacy, wrapped):
        payload, code, stderr, pid = _run_probe(argv, tmp_path, stdin, env)
        assert payload == expected
        assert code == (-signal.SIGTERM if terminate else 23)
        if argv is not base and attach == "attached":
            assert procs.read_text() == f"{pid}\n"
        results.append(stderr)
    assert results[0] == "command stderr\n"
    assert results[1] == results[2]
    if attach != "failed":
        assert results[0] == results[2]
    else:
        assert "cgroup.procs" in results[2]
        assert results[2].endswith("command stderr\n")
    assert base == before
