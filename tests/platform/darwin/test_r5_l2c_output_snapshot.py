"""r5 L2c: Darwin manager output and output_bytes describe ONE log snapshot.

A job writes in bursts ("m1\\n", a sleep, "m2\\n", ...) while run_command
(auto-background handoff) and job_status (tail and cursor modes) observe it
through a private, real com.binnacle.jobs. Every observation's text must be
the log exactly as long as its byte count says: the job log is append-only,
so the final log's prefix of that length is the oracle. The manager runs as
this module's own child in a private /tmp/r5-p5l2c-* runtime; only that exact
child is ever signalled (RULE-NO-PKILL).
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

from binnacle.config import RunCommandSettings
from binnacle.features.commands.command_contracts import (
    read_log_range_snapshot,
    read_log_snapshot,
    snapshot_size,
)
from binnacle.features.commands.tools import job_status as js
from binnacle.features.commands.tools import run_command as rc
from binnacle.mcp.callctx import current_client
from tests.platform.darwin.test_durable_manager_e2e import (
    _available_manager_backend,
    _ping_when_ready,
    _stop_manager,
)
from tests.platform.darwin.test_durable_tool_wiring import _manager

_DARWIN = pytest.mark.skipif(sys.platform != "darwin", reason="real manager")

RUNS = 50
BURSTS = 40
COMMAND = f"for i in $(seq 1 {BURSTS}); do echo m$i; sleep 0.02; done"
AUTO = RunCommandSettings(auto_background_patterns={"r5-l2c": (r"\bseq\b",)})


@pytest.fixture(scope="module")
def manager():
    """The real manager entry point with its own runtime, socket and jobs dir."""
    import subprocess

    with tempfile.TemporaryDirectory(prefix="r5-p5l2c-", dir="/tmp") as value:
        base = Path(value).resolve()
        (base / "rt").mkdir(mode=0o700)
        sock, jobs = base / "rt" / "jobs.sock", base / "jobs"
        toml = f'[jobs]\nsocket_path = "{sock}"\ndir = "{jobs}"\n'
        (base / "config.toml").write_text(toml)
        env = {"BINNACLE_CONFIG_FILE": str(base / "config.toml"), "HOME": str(base)}
        env["PATH"] = "/usr/bin:/bin"
        argv = [sys.executable, "-m", "binnacle.platform.darwin.job_manager_service"]
        with open(base / "manager.log", "wb") as log:
            child = subprocess.Popen(argv, env=env, cwd=base, stdout=log, stderr=log)
        try:
            (base / "mcp").mkdir()
            settings, root, backend = _available_manager_backend(
                base / "mcp", sock, jobs
            )
            _ping_when_ready(backend, child)
            backend.warmup_s = 0.4  # the auto-background handoff, sooner
            yield settings, root, backend
        finally:
            _stop_manager(child, sock)


def _final_log(backend, job_id):
    return (backend.jobs_dir / job_id / "out.log").read_bytes()


def _tail_of(snapshot: bytes, lines: int) -> str:
    """command_status._tail of the snapshot text."""
    return "\n".join(snapshot.decode().splitlines()[-lines:])


@_DARWIN
@pytest.mark.parametrize("run", range(RUNS))
def test_every_observation_is_one_snapshot(manager, run):
    settings, root, backend = manager
    token = current_client.set("r5-l2c-test")
    try:
        started = rc.run_command_impl(
            COMMAND,
            str(root),
            30,
            False,
            None,
            roots=settings.roots,
            settings=AUTO,
            backend=backend,
        ).structured_content
    finally:
        current_client.reset(token)
    job_id = started["job_id"]
    assert started["background_job"] is True  # the auto-background handoff
    observations = [("run_command", started)]
    cursor = "start"
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        tail = js.job_status_impl(job_id, 10_000, backend=backend)
        observations.append(("tail", tail.structured_content))
        status = js.job_status_impl(job_id, 10_000, cursor="start", backend=backend)
        observations.append(("cursor_start", status.structured_content))
        status = js.job_status_impl(job_id, 10_000, cursor=cursor, backend=backend)
        observations.append(("cursor_next", status.structured_content))
        cursor = status.structured_content["next_cursor"]
    final = js.job_status_impl(job_id, 10_000, wait_seconds=10, backend=backend)
    observations.append(("tail_waited", final.structured_content))
    assert final.structured_content["state"] == "exited"
    log = _final_log(backend, job_id)
    assert log.decode().split() == [f"m{i}" for i in range(1, BURSTS + 1)]

    skew = []
    for kind, payload in observations:
        if kind == "run_command":
            size, text = payload["output_bytes"], payload["output"]
            ok = size == len(text.encode()) and text == log[:size].decode()
            ok = ok and payload["truncated"] is False  # small: never clipped
        elif kind.startswith("tail"):
            size = payload["log_bytes"]
            ok = payload["log_tail"] == _tail_of(log[:size], 10_000)
        elif kind == "cursor_start":
            size, delta = payload["log_bytes"], payload["log_delta"]
            ok = (payload["delta_start"], payload["delta_end"]) == (0, size)
            ok = ok and delta == log[:size].decode() and payload["has_more"] is False
        else:
            start, end = payload["delta_start"], payload["delta_end"]
            delta = payload["log_delta"]
            ok = end == payload["log_bytes"] and delta == log[start:end].decode()
            ok = ok and len(delta.encode()) == end - start
        if not ok:
            skew.append((kind, {k: payload.get(k) for k in sorted(payload)}))
    assert not skew, f"{len(skew)}/{len(observations)} observations skewed: {skew}"


def _spool_job(backend, job_id, text):
    directory = backend.jobs_dir / job_id
    directory.mkdir()
    meta = {"command": "x", "workdir": "/tmp", "pid": 7, "started_at": time.time()}
    (directory / "meta.json").write_text(json.dumps(meta))
    (directory / "out.log").write_bytes(text)
    return directory / "out.log"


def test_log_reads_return_the_prefix_their_size_measured(tmp_path):
    """The pairing itself, on every OS: the size is a value, never a pin.

    r6 W2 X1e (SD-74): the tools pass a state's log_bytes to the read; the
    Darwin backend keeps no per-thread or per-instance size (SR6-N2).
    """
    _, _, backend = _manager(tmp_path)
    log = _spool_job(backend, "aaaaaaaaaaaa", b"m1\n")
    _spool_job(backend, "bbbbbbbbbbbb", b"b\n")
    size = snapshot_size(backend.job_state("aaaaaaaaaaaa"))
    assert size == 3
    with log.open("ab") as out:
        out.write(b"m2\n")  # a burst lands between the state and the read
    assert read_log_snapshot(backend, "aaaaaaaaaaaa", size) == b"m1\n"
    assert backend.read_log("aaaaaaaaaaaa") == b"m1\nm2\n"  # no size kept
    size = snapshot_size(backend.job_state("aaaaaaaaaaaa"))
    with log.open("ab") as out:
        out.write(b"m3\n")
    snapshot = read_log_range_snapshot(backend, "aaaaaaaaaaaa", 3, 100, size)
    assert snapshot == (b"m2\n", 6)
    backend.job_state("bbbbbbbbbbbb")  # another job's state never sizes this one
    assert backend.read_log_range("aaaaaaaaaaaa", 0, 100) == (b"m1\nm2\nm3\n", 9)
    size = snapshot_size(backend.job_state("aaaaaaaaaaaa"))
    log.write_bytes(b"")  # not append-only any more: never invent a prefix
    snapshot = read_log_range_snapshot(backend, "aaaaaaaaaaaa", 0, 100, size)
    assert snapshot == (b"", 0)
