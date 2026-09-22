"""Lifecycle telemetry that is orthogonal to the core job contract tests."""

from binnacle import jobs as jobstore
from tests.integration.job_test_support import run, stop


def test_stop_escalation_is_visible_in_telemetry(monkeypatch, caplog):
    monkeypatch.setattr(jobstore, "STOP_SIGTERM_GRACE_S", 0.25)
    p = run(
        "exec python3 -c 'import signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'",
        background=True,
    )
    with caplog.at_level("WARNING", logger="binnacle.jobs"):
        r = stop(p["job_id"])
    assert r["state"] == "exited" and r["signal"] == 9
    assert any(
        f"event=job_stop_escalate job_id={p['job_id']}" in record.getMessage()
        and "signal=SIGKILL" in record.getMessage()
        for record in caplog.records
    )
