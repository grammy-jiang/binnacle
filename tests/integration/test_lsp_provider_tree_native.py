"""P2.4 native-only process ownership tests with real disposable child PIDs.

No live Binnacle server, no user project and no Pyright executable required.
These tests attest only observed process-tree cleanup, never OS sandboxing.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from anyio import fail_after

from binnacle.features.development_intelligence.lsp_process_tree import (
    NativeProviderTree,
    ProcessIdentity,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX session process tree")


@pytest.fixture
def spawn_script(tmp_path: Path) -> Path:
    script = tmp_path / "provider_with_child.py"
    script.write_text(
        "import json, os, signal, subprocess, sys, time\nfrom pathlib import Path\nroot = Path(sys.argv[1])\nmode = sys.argv[2]\nchild_code = \"import os,sys,time\\nfrom pathlib import Path\\nsignal_file=Path(sys.argv[1])\\nwhile not signal_file.exists():\\n    time.sleep(.02)\\nos.setsid()\\nsignal_file.with_suffix('.done').touch()\\nwhile True:\\n    time.sleep(1)\\n\"\nchild = subprocess.Popen([sys.executable, '-u', '-c', child_code, str(root / 'escape.signal')], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=mode == 'escaped')\n(root / 'ready.json').write_text(json.dumps({'pid':child.pid, 'mode':mode}))\nwhile not (root / 'finish').exists():\n    time.sleep(0.02)\n",
        encoding="utf-8",
    )
    return script


async def spawn_with_ready(script: Path, tmp_path: Path, mode: str):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        str(script),
        str(tmp_path),
        mode,
        start_new_session=True,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:

        async def ready():
            while not (tmp_path / "ready.json").exists():
                if process.returncode is not None:
                    raise RuntimeError("fixture child exited before readiness")
                await asyncio.sleep(0.01)
            return json.loads((tmp_path / "ready.json").read_text())

        return process, await asyncio.wait_for(ready(), timeout=5)
    except BaseException:
        process.kill()
        await process.wait()
        raise


def runnable(pid: int) -> bool:
    import psutil

    try:
        task = psutil.Process(pid)
        return task.is_running() and task.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["group", "escaped"])
async def test_observed_descendant_cleanup_with_os_process_identity(
    spawn_script: Path, tmp_path: Path, mode: str
):
    owner = NativeProviderTree(grace_seconds=0.1, kill_seconds=0.6)
    process, child = await spawn_with_ready(spawn_script, tmp_path, mode)
    try:
        owner.capture(process.pid)
        with fail_after(4):
            # There is an actual live descendant when we sample, not a PID
            # claimed in arbitrary output or a synthetic process mock.
            owner.observe()
            assert child["pid"] in owner.members
            assert runnable(child["pid"])
            outcome = await owner.cleanup()
        assert outcome.root_pid == process.pid
        assert outcome.observed_descendants >= 1
        if mode == "escaped":
            assert outcome.escaped_descendants == 1
            assert outcome.status == "cleanup_unverified"
            assert outcome.reason == "escaped_descendant_observed"
        else:
            assert outcome.escaped_descendants == 0
            assert outcome.status == "observed_clean"
        assert outcome.remaining == ()
        assert not runnable(child["pid"])
        await asyncio.wait_for(process.wait(), timeout=4)
        assert not runnable(process.pid)
    finally:
        (tmp_path / "finish").touch()
        if process.returncode is None:
            process.kill()
            await process.wait()
        # Child is an isolated test-spawned PID; cannot kill arbitrary ones.
        # The tested owner should always have taken care of its descendant.
        assert not runnable(child["pid"]), "test fixture process leaked"


@pytest.mark.asyncio
async def test_reaps_group_descendant_after_original_provider_exits(
    spawn_script: Path, tmp_path: Path
):
    tree = NativeProviderTree(grace_seconds=0.1, kill_seconds=0.5)
    proc, child = await spawn_with_ready(spawn_script, tmp_path, "group")
    try:
        tree.capture(proc.pid)
        (tmp_path / "finish").touch()
        await asyncio.wait_for(proc.wait(), 3)
        assert runnable(child["pid"])
        # No child enumeration from parent is possible after parent exit.
        tree.observe()
        assert child["pid"] in tree.members
        outcome = await tree.cleanup()
        assert outcome.status == "observed_clean"
        assert not runnable(child["pid"])
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        assert not runnable(child["pid"])


@pytest.mark.asyncio
async def test_absent_observation_returns_unverified_without_signalling():
    owner = NativeProviderTree()
    evidence = await owner.cleanup()
    assert evidence.status == "cleanup_unverified"
    assert evidence.reason == "root_not_observed"
    assert evidence.root_pid is None
    with pytest.raises(RuntimeError, match="already_used"):
        owner.capture(os.getpid())
    with pytest.raises(RuntimeError, match="already_called"):
        await owner.cleanup()


def test_rejects_unowned_pid_or_process_group_and_invalid_deadlines():
    owner = NativeProviderTree()
    for pid in (0, -1, True, "12"):
        with pytest.raises(ValueError, match="invalid_owned_lsp_pid"):
            owner.capture(pid)
    # Never assume the test runner's existing process group is privately owned.
    if os.getpgid(os.getpid()) != os.getpid():
        with pytest.raises(RuntimeError, match="independent_session"):
            owner.capture(os.getpid())
    for bad in (0, -1, 6):
        with pytest.raises(ValueError, match="deadline"):
            NativeProviderTree(grace_seconds=bad)


def test_pid_identity_reuse_cannot_receive_signals(monkeypatch):
    import psutil

    # Simulated reused PID has a different birth time. The owner must never
    # signal a process based on a former owner object's numeric PID alone.
    pid = os.getpid()
    actual = NativeProviderTree._identity(pid)
    assert actual is not None
    calls: list[int] = []
    monkeypatch.setattr(
        psutil.Process, "send_signal", lambda self, _sig: calls.append(self.pid)
    )
    NativeProviderTree._signal(
        ProcessIdentity(pid, actual.created - 10, actual.pgid), 15
    )
    assert calls == []


@pytest.mark.asyncio
async def test_descendant_escaping_after_first_observation_is_never_clean(
    spawn_script: Path, tmp_path: Path
):
    """An already recorded child may create a new session later."""
    tree = NativeProviderTree(grace_seconds=0.1, kill_seconds=0.7)
    parent, child = await spawn_with_ready(spawn_script, tmp_path, "group")
    try:
        tree.capture(parent.pid)
        tree.observe()
        assert child["pid"] in tree.members
        assert child["pid"] not in tree.escaped
        (tmp_path / "escape.signal").touch()

        async def wait_for_escape():
            while not (tmp_path / "escape.done").is_file():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_escape(), timeout=5)
        assert runnable(child["pid"])
        tree.observe()
        assert child["pid"] in tree.escaped
        outcome = await tree.cleanup()
        assert outcome.status == "cleanup_unverified"
        assert outcome.reason == "escaped_descendant_observed"
        assert outcome.escaped_descendants == 1
        assert not runnable(child["pid"])
    finally:
        (tmp_path / "finish").touch()
        if parent.returncode is None:
            parent.kill()
        await parent.wait()
        assert not runnable(child["pid"])
