"""Darwin-only probes using test-owned children and cooperative escape teardown.

The socketpair fixture proves a live test-owned witness can disappear, not A3's
production transport authentication. Detached descendants exit through a test
release file or a hard self-timeout; they are never recovered by numeric signal.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from threading import Event, Thread

import pytest

from binnacle.platform.contracts.capability_contracts import (
    CapabilityState,
    CapabilityUnavailable,
)
from binnacle.platform.contracts.darwin_contracts import (
    ForegroundRequest,
    OwnerGeneration,
)
from binnacle.platform.contracts.process_contracts import (
    JobProcessIdentity,
    UnverifiedJobProcess,
)
from binnacle.platform.darwin.process_authority import _ForegroundOwner
from binnacle.platform.darwin.process_backend import (
    DarwinProcessBackend,
    _ForegroundRunner,
)
from binnacle.platform.darwin.witness_protocol import DarwinWitness

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="native Darwin child/grandchild and witness-loss probe",
)

GENERATION = OwnerGeneration("native-manager", "native-witness", "native-job")


def wait_file(path: Path, timeout: float = 3) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return
        time.sleep(0.01)
    pytest.fail(f"test-owned child did not publish {path.name}")


def terminate_owned(process):
    if process.poll() is None:
        process.terminate()
    process.wait(timeout=3)


class SocketChannel:
    """Known test-owned socketpair endpoint, no production auth claim."""

    def __init__(self, endpoint):
        self.endpoint = endpoint

    def request(self, payload, *, timeout_s):
        self.endpoint.settimeout(timeout_s)
        self.endpoint.sendall(json.dumps(payload).encode() + b"\n")
        data = bytearray()
        while b"\n" not in data:
            chunk = self.endpoint.recv(4096)
            if not chunk or len(data) + len(chunk) > 65536:
                raise ConnectionError("test witness closed")
            data.extend(chunk)
        return json.loads(data)

    def close(self):
        self.endpoint.close()


@pytest.fixture
def live_witness():
    local, remote = socket.socketpair()
    script = """
import json, socket, sys
endpoint = socket.socket(fileno=int(sys.argv[1]))
generation = json.loads(sys.argv[2])
with endpoint.makefile('rb') as stream:
    for line in stream:
        request = json.loads(line)
        response = dict(request, enrolled=request.get('generation') == generation)
        endpoint.sendall(json.dumps(response).encode() + b'\\n')
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(remote.fileno()),
            json.dumps(asdict(GENERATION)),
        ],
        pass_fds=(remote.fileno(),),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    remote.close()
    witness = DarwinWitness(SocketChannel(local), GENERATION)
    try:
        yield witness, process
    finally:
        witness.close()
        terminate_owned(process)


def test_native_witness_crash_revokes_observation(live_witness):
    witness, process = live_witness
    backend = DarwinProcessBackend(witness=witness)
    assert (
        backend.authority(GENERATION.job_id).capability.state is CapabilityState.LIMITED
    )
    terminate_owned(process)
    observation = backend.authority(GENERATION.job_id)
    assert observation.capability.state is CapabilityState.UNKNOWN
    assert not observation.can_signal and not observation.membership_closed


def test_native_group_child_receives_cleanup_without_claiming_tree_closure(tmp_path):
    ready, terminated = tmp_path / "child-ready", tmp_path / "child-term"
    code = f"""
import os, signal, time
if os.fork() == 0:
    def end(sig, frame):
        with open({str(terminated)!r}, 'w') as stream:
            stream.write(str(sig))
        os._exit(0)
    signal.signal(signal.SIGTERM, end)
    with open({str(ready)!r}, 'w') as stream:
        stream.write(str(os.getpgrp()))
    time.sleep(5)
    os._exit(0)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(5)
"""
    cancel = Event()

    def cancel_when_enrolled():
        wait_file(ready)
        cancel.set()

    thread = Thread(target=cancel_when_enrolled)
    thread.start()
    command = f"exec {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    try:
        with pytest.raises(CapabilityUnavailable, match="descendants_unverified=true"):
            _ForegroundRunner(3, 3).run_foreground(
                ForegroundRequest(command, tmp_path, None, 3, False, 3, 1000),
                cancel=cancel,
            )
    finally:
        thread.join(4)
    assert terminated.read_text() == str(signal.SIGTERM)
    assert int(ready.read_text()) != os.getpgrp()


def test_native_single_reaper_and_post_reap_cleanup_never_signal(monkeypatch):
    calls = []
    original = os.waitpid

    def wait(pid, flags):
        result = original(pid, flags)
        if result[0]:
            calls.append(result)
        return result

    monkeypatch.setattr(os, "waitpid", wait)
    owner = _ForegroundOwner(["/bin/bash", "-c", "exit 0"], env={}, file_actions=[])
    try:
        deadline = time.monotonic() + 3
        while owner.poll(owner.generation) is None:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        monkeypatch.setattr(
            os, "killpg", lambda *args: pytest.fail("post-reap group signal")
        )
        for _ in range(3):
            owner.cleanup(owner.generation)
            assert owner.poll(owner.generation) == 0
    finally:
        owner.cleanup(owner.generation)
    assert len(calls) == 1


def test_native_fork_cannot_inherit_owner_even_with_recycled_pid_simulation():
    # Isolate fork from pytest/plugin threads. The native fork is real; recycling
    # the parent's number is simulated, not forced by exhausting the host PID set.
    script = """
import os, time
from binnacle.platform.contracts.capability_contracts import AuthorityUnknown
from binnacle.platform.darwin.process_authority import _ForegroundOwner
owner = _ForegroundOwner(['/bin/sleep', '0.2'], env={}, file_actions=[])
original_pid = os.getpid()
read_fd, write_fd = os.pipe()
probe = os.fork()
if probe == 0:
    os.close(read_fd)
    os.getpid = lambda: original_pid
    try:
        owner.cleanup(owner.generation)
    except AuthorityUnknown:
        os.write(write_fd, b'unknown')
        os._exit(0)
    os._exit(1)
os.close(write_fd)
try:
    assert os.read(read_fd, 20) == b'unknown'
    assert os.waitpid(probe, 0)[1] == 0
    deadline = time.monotonic() + 2
    while owner.poll(owner.generation) is None:
        assert time.monotonic() < deadline
        time.sleep(0.01)
finally:
    os.close(read_fd)
    owner.cleanup(owner.generation)
print('fork owner rejected')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "fork owner rejected"


def test_native_manager_and_witness_loss_leaves_detached_orphan_unknown(
    tmp_path, live_witness, monkeypatch
):
    witness, witness_process = live_witness
    ready, release, done = (
        tmp_path / name for name in ("orphan-ready", "release", "orphan-done")
    )
    leader_done = tmp_path / "leader-done"
    heartbeat = tmp_path / "heartbeat"
    code = f"""
import json, os, time
intermediate = os.fork()
if intermediate == 0:
    os.setsid()
    if os.fork() != 0:
        os._exit(0)
    with open({str(ready)!r}, 'w') as stream:
        json.dump({{'pid': os.getpid(), 'pgid': os.getpgrp()}}, stream)
    deadline = time.monotonic() + 4
    while not os.path.exists({str(release)!r}) and time.monotonic() < deadline:
        with open({str(heartbeat)!r}, 'a') as stream:
            stream.write('alive\\n')
        time.sleep(0.02)
    with open({str(done)!r}, 'w') as stream:
        stream.write('self-exit')
    os._exit(0)
os.waitpid(intermediate, 0)
time.sleep(0.7)
with open({str(leader_done)!r}, 'w') as stream:
    stream.write('leader-exit')
"""
    manager_code = """
import sys
from pathlib import Path
from threading import Event
from binnacle.platform.contracts.darwin_contracts import ForegroundRequest
from binnacle.platform.darwin.process_backend import _ForegroundRunner
_ForegroundRunner(3, 3).run_foreground(
    ForegroundRequest(sys.argv[1], Path(sys.argv[2]), None, 3, False, 3, 1000), cancel=Event())
"""
    command = f"exec {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    manager = subprocess.Popen(
        [sys.executable, "-c", manager_code, command, str(tmp_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    try:
        wait_file(ready)
        wait_file(heartbeat)
        assert witness.observe(GENERATION.job_id).generation == GENERATION
        terminate_owned(manager)
        terminate_owned(witness_process)
        before = heartbeat.stat().st_size
        time.sleep(0.08)
        assert (
            heartbeat.stat().st_size > before
        )  # orphan still running after both handles die
        historic = json.loads(ready.read_text())

        def no_adoption(*args):
            pytest.fail("replacement manager signaled a historic process")

        monkeypatch.setattr(os, "killpg", no_adoption)
        replacement = DarwinProcessBackend()
        assert replacement.identity_from_record(historic) is None
        observation = replacement.authority(GENERATION.job_id)
        assert observation.capability.state is CapabilityState.UNKNOWN
        assert not observation.membership_closed and not observation.can_signal
        assert (
            DarwinProcessBackend(witness=witness)
            .authority(GENERATION.job_id)
            .capability.state
            is CapabilityState.UNKNOWN
        )
        with pytest.raises(UnverifiedJobProcess):
            replacement.open_job_signals(JobProcessIdentity(historic))
        with pytest.raises(CapabilityUnavailable):
            replacement.signal_job(historic["pgid"], {historic["pid"]}, "kill")
    finally:
        release.touch()
        terminate_owned(manager)
        wait_file(done, 5)
        wait_file(leader_done, 5)
    assert done.read_text() == "self-exit"
