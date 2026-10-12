"""Darwin manager start/exit events cover available and missing output facts."""

from __future__ import annotations

import logging

from binnacle.platform.darwin import job_manager_telemetry as events


def test_manager_logging_installs_dated_unified_format(monkeypatch):
    seen = []
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: seen.append(kwargs))
    events.configure_job_manager_logging()
    assert seen[0]["datefmt"] == "%Y-%m-%dT%H:%M:%S"
    assert "%(msecs)03d" in seen[0]["format"]


def test_start_event_includes_lifecycle_identity_without_command_text(caplog):
    logger = logging.getLogger("binnacle.job_manager.test_telemetry")
    with caplog.at_level(logging.INFO):
        events.log_job_start(
            logger,
            "abcdef123456",
            {
                "pid": 12345,
                "workdir": "/tmp",
                "call_id": "call-123",
                "owner_instance_id": "long-owner-identifier",
                "command_hash": "deadbeefabcd",
                "command": "echo secret-not-logged",
            },
        )
    text = caplog.text
    assert "event=job_start" in text and "pid=12345" in text
    assert "call=call-123" in text and "command_hash=deadbeefabcd" in text
    assert "secret-not-logged" not in text


def test_exit_telemetry_missing_log_and_start_time_stays_structured(tmp_path, caplog):
    logger = logging.getLogger("binnacle.job_manager.test_telemetry")
    with caplog.at_level(logging.INFO):
        events.log_job_exit(
            logger,
            "abcdef123456",
            {
                "ended_at": 1001,
                "termination_reason": "signal",
                "exit_code": None,
                "signal": 9,
                "call_id": "call-123",
                "command_hash": "deadbeefabcd",
            },
            tmp_path / "missing",
        )
    message = caplog.text
    for fragment in (
        "event=job_exit",
        "signal=9",
        "runtime_s=-",
        "log_bytes=0",
        "reason=signal",
        "call=call-123",
        "owner_instance=-",
    ):
        assert fragment in message
