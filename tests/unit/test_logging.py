"""Tests for deterministic structured diagnostic logging."""

import json
import logging

import pytest
import structlog

from binnacle.config import LoggingSettings
from binnacle.logging import configure_logging


def test_json_logging_emits_parseable_record(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = configure_logging(LoggingSettings(format="json"))
    try:
        structlog.get_logger("unit").info("hello", answer=42)
        captured = capsys.readouterr()
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


def test_replaced_root_handlers_are_closed() -> None:
    class TrackingHandler(logging.Handler):
        closed_by_test = False

        def emit(self, record: logging.LogRecord) -> None:
            del record

        def close(self) -> None:
            self.closed_by_test = True
            super().close()

    previous = TrackingHandler()
    logging.getLogger().addHandler(previous)

    runtime = configure_logging(LoggingSettings())
    try:
        assert previous.closed_by_test is True
    finally:
        runtime.close()
