"""Tests for deterministic structured diagnostic logging."""

import json
import logging

import structlog

from binnacle.config import LoggingSettings
from binnacle.logging import configure_logging


def test_json_logging_emits_parseable_record(capsys: object) -> None:
    runtime = configure_logging(LoggingSettings(format="json"))
    try:
        structlog.get_logger("unit").info("hello", answer=42)
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        record = json.loads(captured.err)
        assert record["event"] == "hello"
        assert record["level"] == "info"
        assert record["logger"] == "unit"
        assert record["timestamp"]
        assert record["answer"] == 42
    finally:
        runtime.close()


def test_reconfigure_logging_closes_previous_runtime() -> None:
    first = configure_logging(LoggingSettings())
    first_handler = first.handler

    second = configure_logging(LoggingSettings(format="json"))
    try:
        assert first_handler not in logging.getLogger().handlers
        assert second.handler in logging.getLogger().handlers
    finally:
        second.close()


def test_logging_runtime_close_is_idempotent() -> None:
    runtime = configure_logging(LoggingSettings())

    runtime.close()
    runtime.close()

    assert runtime.handler not in logging.getLogger().handlers
