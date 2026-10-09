"""Private subprocess fixtures, also usable with an external archived source tree."""

import json
import os
import selectors
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

MANAGER = """
import json, sys
from pathlib import Path
from binnacle.features.commands import jobs, job_manager
from importlib.util import find_spec
if find_spec("binnacle.job_cgroup") is not None:
    from binnacle import job_cgroup
else:
    from binnacle.platform.linux import job_cgroup
source, spool, socket = map(Path, sys.argv[1:])
assert Path(jobs.__file__).resolve().is_relative_to(source.resolve())
jobs.JOBS_DIR = spool
job_cgroup.prepare = lambda **kwargs: None
job_cgroup.create = lambda job: None
job_manager._notify_systemd_ready = lambda: print(json.dumps({"source": jobs.__file__}), flush=True)
job_manager.JobManager(socket, owner_instance_id="reload-owner", boot_id="reload-boot").serve_forever()
"""

WORKER = """
import asyncio, json, sys
from pathlib import Path
from fastmcp import Client
from binnacle.features.commands import jobs
from binnacle.features.commands.commands_server import create_commands_server
source, spool, socket = map(Path, sys.argv[1:4])
assert Path(jobs.__file__).resolve().is_relative_to(source.resolve())
jobs.JOBS_DIR = spool
jobs.MANAGER_SOCKET = socket
jobs.OWNER_MODE = "manager"
jobs.WARMUP_S = 0.05
arguments = json.loads(sys.stdin.read())
async def main():
    async with Client(create_commands_server(), cache=False) as client:
        reply = await client.call_tool(sys.argv[4], arguments)
        print(json.dumps({"source": jobs.__file__, "payload": reply.structured_content}), flush=True)
asyncio.run(main())
"""


def source_env(source):
    env = {**os.environ, "PYTHONPATH": str(source)}
    env.pop("NOTIFY_SOCKET", None)
    return env


@contextmanager
def private_manager(root, source):
    """Own one temporary manager; wait on its actual readiness notification."""
    spool, socket = root / "jobs", root / "manager.sock"
    with (root / "manager.log").open("w") as log:
        proc = subprocess.Popen(
            [sys.executable, "-c", MANAGER, str(source), str(spool), str(socket)],
            env=source_env(source),
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=15), "manager did not report ready"
                ready = json.loads(proc.stdout.readline())
            assert Path(ready["source"]).resolve().is_relative_to(source.resolve())
            yield spool, socket, proc
        finally:
            # Stop only unfinished jobs in this fixture's spool before the owner.
            from binnacle.features.commands import job_client, job_store

            if proc.poll() is None:
                for job_id in job_store.list_job_ids(spool):
                    meta = job_store.read_meta(spool, job_id)
                    if meta and "exit_code" not in meta and "signal" not in meta:
                        job_client.stop(socket, job_id)
                proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()


def worker(source, spool, socket, tool, arguments):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            WORKER,
            str(source),
            str(spool),
            str(socket),
            tool,
        ],
        env=source_env(source),
        input=json.dumps(arguments),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    reply = json.loads(result.stdout.strip().splitlines()[-1])
    assert Path(reply["source"]).resolve().is_relative_to(source.resolve())
    return reply["payload"]


def reload_scenario(root, manager_source, worker_source):
    """New worker per call proves the durable boundary and both source paths."""
    with private_manager(root, manager_source) as (spool, socket, manager):
        live = worker(
            worker_source,
            spool,
            socket,
            "run_command",
            {
                "command": "printf ready; exec sleep 60",
                "workdir": "/tmp",
                "background": True,
                "stdin": "x" * 200_000,
            },
        )
        assert live["state"] == "running"
        job_id = live["job_id"]
        assert (spool / job_id / "stdin").stat().st_size == 200_000
        status = worker(
            worker_source,
            spool,
            socket,
            "job_status",
            {
                "job_id": job_id,
                "cursor": "start",
                "wait_seconds": 0,
            },
        )
        assert status["state"] == "running" and status["log_delta"] == "ready"
        assert status["next_cursor"] == f"v1:{job_id}:5"
        assert status["has_more"] is False
        assert manager.poll() is None
        stopped = worker(worker_source, spool, socket, "stop_job", {"job_id": job_id})
        repeated = worker(worker_source, spool, socket, "stop_job", {"job_id": job_id})
        assert (
            stopped
            == repeated
            == {
                "job_id": job_id,
                "state": "exited",
                "exit_code": None,
                "signal": 15,
            }
        )
        meta = json.loads((spool / job_id / "meta.json").read_text())
        assert meta["schema_version"] == 2
        assert meta["owner_instance_id"] == "reload-owner"
        assert meta["termination_reason"] == "stop_requested"
        return {"live": live, "status": status, "stop": stopped, "meta": meta}
