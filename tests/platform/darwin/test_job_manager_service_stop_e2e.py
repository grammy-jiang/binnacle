"""Exact-owner stop persistence after manager exit (split for module size)."""

from __future__ import annotations

import os
import sys

import pytest

from tests.platform.darwin.test_job_manager_service import (
    client,
    group_gone,
    meta_of,
    run,
    serving,
)
from tests.platform.darwin.test_job_manager_service import (
    runtime as runtime,  # noqa: PLC0414 - shared service test fixture
)

NATIVE = pytest.mark.skipif(
    sys.platform != "darwin" or not hasattr(os, "waitid"),
    reason="Darwin A3 IPC; SD-97 requires waitid",
)


@NATIVE
def test_manager_stop_kills_and_records_owned_groups_no_orphans(runtime, tmp_path):
    # R4-REQ-J1J2-no-orphans; an MCP server restart is only a new client.
    with serving(runtime) as (sock, manager, errors):
        job = run(sock, "sleep 60 & wait", tmp_path)
        pgid = meta_of(manager.jobs_dir, job["job_id"])["pgid"]
        assert client().ping(sock)["owner_instance_id"] == manager.owner_instance_id
        assert manager.state(job["job_id"]) == "running"
    meta = meta_of(manager.jobs_dir, job["job_id"])
    # Linux job_owner._record_interruption: no exit status, reason owner_restart.
    got = (meta["exit_code"], meta["signal"], meta["termination_reason"])
    assert got == (None, None, "owner_restart")
    assert "authority" not in meta and not errors
    assert group_gone(pgid)  # no untracked survivor in the owned group
