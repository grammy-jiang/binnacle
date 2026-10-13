"""r5 L2b (SD-61 branch a1): Darwin processes[] items pass the strict client.

job_status for a running Darwin-manager job goes through the strict in-memory
FastMCP client, which validates structured output against the pinned Linux
outputSchema. The items are the real ``group_listing`` of a process group this
test spawned (state ``?`` for SRUN, no ``cpu_s``) and must validate; a
``cpu_s`` of null must not, because the schema stays ``number``. Only the
group this test started is signalled (RULE-NO-PKILL).
"""

import asyncio
import json
import platform
import subprocess

import pytest
from fastmcp import Client

from binnacle.platform.darwin import job_manager_procinfo as procinfo
from tests.platform.darwin.test_durable_tool_wiring import (
    _app,
    _manager,
    _run,
    _SpoolClient,
)
from tests.platform.darwin.test_r5_l2b_processes import linux_builder_keys

_DARWIN = pytest.mark.skipif(
    platform.system() != "Darwin", reason="native Darwin KERN_PROC_PGRP listing"
)


class _ListingClient(_SpoolClient):
    """The spool stand-in plus the manager's JCRP-F6 processes reply."""

    def __init__(self, jobs_dir, items):
        super().__init__(jobs_dir)
        self.items = items

    def processes(self, socket_path, job_id, *, max_cmd_chars):
        reply = {"ok": True, "job_id": job_id, "processes": self.items}
        return json.loads(json.dumps(reply, sort_keys=True))  # the A3 wire form


def _strict_job_status(tmp_path, items):
    settings, root, backend = _manager(tmp_path)
    backend.client = _ListingClient(settings.jobs.dir, items)
    job_id = _run(settings, root, backend, "RUNNING", 0).structured_content["job_id"]

    async def call():
        async with Client(_app(settings, backend)) as client:
            return await client.call_tool("job_status", {"job_id": job_id})

    return asyncio.run(call())


@pytest.fixture
def listed():
    """The real group_listing of a sleeping group this test owns."""
    child = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
    try:
        items = procinfo.group_listing(child.pid, 200)
        assert [item["pid"] for item in items] == [child.pid]
        yield items
    finally:
        child.kill()  # the exact Popen child, never a pattern
        child.wait(timeout=10)


@_DARWIN
def test_running_job_status_without_cpu_s_passes_the_strict_client(tmp_path, listed):
    assert set(listed[0]) == {"pid", "state", "etime_s", "cmd"}
    assert listed[0]["state"] == "?"  # SRUN: R or S is not knowable here
    result = _strict_job_status(tmp_path, listed)  # raises on a schema error
    assert result.structured_content["state"] == "running"
    assert result.structured_content["processes"] == listed


@_DARWIN
def test_null_cpu_s_is_rejected_by_the_pinned_schema(tmp_path, listed):
    with pytest.raises(RuntimeError, match=r"(?s)Invalid structured content.*cpu_s"):
        _strict_job_status(tmp_path, [{**listed[0], "cpu_s": None}])


@_DARWIN
def test_job_status_bytes_list_item_keys_in_the_linux_order(
    tmp_path, listed, monkeypatch
):
    """STEER-03: after the sort_keys IPC hop the MCP bytes follow Linux."""
    linux = linux_builder_keys(tmp_path, monkeypatch)
    result = _strict_job_status(tmp_path, listed)
    wire = json.dumps(result.structured_content)  # the structured result bytes
    (item,) = json.loads(wire)["processes"]
    assert list(item) == [key for key in linux if key in listed[0]]
    keys = [f'"{key}":' for key in item]
    start = wire.index('"processes":')
    assert sorted(keys, key=lambda k: wire.index(k, start)) == keys
