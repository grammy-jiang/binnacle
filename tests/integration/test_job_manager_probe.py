"""An owner-identity probe is not an invalid Manager request.

The Rust MCP admits an external Manager v2 by connecting to the v1 control
socket and the v2 start socket, reading SO_PEERCRED and closing both without
sending anything. Such a connection is logged at debug level, not as an
invalid or refused request; a malformed request still warns.
"""

from __future__ import annotations

import logging
import socket
import time
from pathlib import Path

from binnacle.features.commands import job_client
from tests.integration.test_job_manager_v2 import running_owner  # noqa: F401

LOGGERS = ("binnacle.job_manager", "binnacle.job_manager_v2")


def _probe(path: Path) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(str(path))


def _wait_for(caplog, event: str) -> bool:
    for _ in range(400):
        if any(event in record.getMessage() for record in caplog.records):
            return True
        time.sleep(0.005)
    return False


def test_closed_probe_connections_are_debug_not_warnings(
    running_owner,  # noqa: F811
    caplog,
):
    _, _, _, run, _ = running_owner
    caplog.set_level(logging.DEBUG, logger=LOGGERS[0])
    caplog.set_level(logging.DEBUG, logger=LOGGERS[1])
    _probe(run / "legacy-v1.sock")
    _probe(run / "start-v2.sock")
    assert _wait_for(caplog, "event=job_manager_probe_closed")
    assert _wait_for(caplog, "event=job_manager_v2_probe_closed")
    assert job_client.ping(run / "legacy-v1.sock")["version"] == 1
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING and record.name in LOGGERS
    ]
    assert warnings == []


def test_malformed_requests_still_warn(running_owner, caplog):  # noqa: F811
    _, _, _, run, _ = running_owner
    caplog.set_level(logging.WARNING, logger=LOGGERS[0])
    caplog.set_level(logging.WARNING, logger=LOGGERS[1])
    for name in ("legacy-v1.sock", "start-v2.sock"):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(6)
            conn.connect(str(run / name))
            conn.sendall(b"\n")
            assert conn.recv(4096)
    assert _wait_for(caplog, "event=job_manager_request_invalid")
    assert _wait_for(caplog, "event=job_manager_v2_refused")
