"""Lifecycle telemetry that is orthogonal to the core job contract tests."""

import sys
import time

import pytest

from binnacle.features.commands import jobs as jobstore
from tests.integration.job_test_support import run, stop

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="no Darwin counterpart: durable jobs / Linux job engine are UNAVAILABLE on Darwin by release scope (CR0-04)",
)


pytestmark = [LINUX_ONLY, pytest.mark.usefixtures("_short_job_warmup")]


READY_TIMEOUT_S = 10.0


def _wait_for_marker(marker, timeout_s=READY_TIMEOUT_S):
    """Wait (bounded) until the child has written its readiness marker."""
    deadline = time.monotonic() + timeout_s
    while not marker.exists():
        assert time.monotonic() < deadline, f"child never became ready: {marker}"
        time.sleep(0.01)


def test_stop_escalation_is_visible_in_telemetry(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(jobstore, "STOP_SIGTERM_GRACE_S", 0.25)
    # The child writes the marker only AFTER it ignores SIGTERM, so stop() can
    # never land in the startup window where SIGTERM still kills it (gate flake:
    # signal 15 instead of the SIGKILL escalation).
    marker = tmp_path / "sigterm-ignored"
    p = run(
        "exec python3 -c 'import pathlib, signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        'pathlib.Path(sys.argv[1]).write_text("ready"); time.sleep(30)\' '
        f"{marker}",
        background=True,
    )
    _wait_for_marker(marker)
    with caplog.at_level("WARNING", logger="binnacle.jobs"):
        r = stop(p["job_id"])
    assert r["state"] == "exited" and r["signal"] == 9
    assert any(
        f"event=job_stop_escalate job_id={p['job_id']}" in record.getMessage()
        and "signal=SIGKILL" in record.getMessage()
        for record in caplog.records
    )
