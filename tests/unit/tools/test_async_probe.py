"""Temporary async-orchestration probe tool behavior."""

from __future__ import annotations

import asyncio
import time

from binnacle.tools import async_probe


class FakeContext:
    def __init__(self, initialize: bool, request_settings):
        self.initialize = initialize
        self.request_settings = request_settings

    def client_supports_extension(self, extension_id: str) -> bool:
        assert extension_id == async_probe.TASKS_EXTENSION
        return self.initialize

    def client_extension_settings(self, identifier: str):
        assert identifier == async_probe.TASKS_EXTENSION
        return self.request_settings


def test_capabilities_payload_distinguishes_initialize_and_request_support():
    assert async_probe.capabilities_payload(FakeContext(False, None)) == {
        "tasks_initialize_capability": False,
        "tasks_request_capability": False,
        "tasks_request_settings": None,
        "protocol_version": None,
        "client_name": None,
    }
    assert async_probe.capabilities_payload(FakeContext(True, {})) == {
        "tasks_initialize_capability": True,
        "tasks_request_capability": True,
        "tasks_request_settings": {},
        "protocol_version": None,
        "client_name": None,
    }


def test_wait_is_actually_async_and_bounded_by_requested_delay():
    started = time.monotonic()
    result = asyncio.run(async_probe.wait_impl("unit", "short", 0.1))
    elapsed = time.monotonic() - started
    assert elapsed >= 0.09
    assert result.structured_content["probe_id"] == "unit"
    assert result.structured_content["label"] == "short"


def test_seed_is_unpredictable_and_echo_preserves_exact_value():
    first = asyncio.run(async_probe.seed_impl("unit")).structured_content
    second = asyncio.run(async_probe.seed_impl("unit")).structured_content
    assert first["token"] != second["token"]
    echoed = async_probe.echo_impl("unit", first["token"]).structured_content
    assert echoed["probe_id"] == first["probe_id"]
    assert echoed["token"] == first["token"]


def test_seed_delay_creates_a_controlled_dependency_window():
    started = time.monotonic()
    result = asyncio.run(async_probe.seed_impl("unit", 0.1)).structured_content
    assert time.monotonic() - started >= 0.09
    assert result["delay_s"] == 0.1
