"""Explicit hard acceptance gate, separate from upstream feature smoke tests.

Run with BINNACLE_LSP_RELEASE_GATE=1 and other patched-upstream variables.
This currently FAILS against pinned b5325f1 because shared multilspy JSON-RPC
retains abandoned requests after timeout and after provider termination.
Do not xfail or silently skip when the release gate is requested.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from tests.integration.test_lsp_multilspy_patched_upstream import _new_native_server

pytest_plugins = ("tests.integration.test_lsp_multilspy_patched_upstream",)


@pytest.mark.asyncio
async def test_timeout_must_not_leave_pending_requests_after_stop(
    patched_upstream, disposable_workspace
):
    if os.environ.get("BINNACLE_LSP_RELEASE_GATE") != "1":
        pytest.skip("opt in to the hard request-cleanup release gate")

    server = _new_native_server(disposable_workspace, patched_upstream)
    async with server.start_server():
        handler = server.server
        assert not handler._response_handlers
        original_send = handler._send_payload

        async def simulate_unresponsive_peer(_payload):
            return None

        handler._send_payload = simulate_unresponsive_peer
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    handler.send_request("textDocument/definition", {}), timeout=0.05
                )
        finally:
            handler._send_payload = original_send

    assert server.server.process is None
    assert not handler._response_handlers, (
        "BLOCKER: multilspy retains cancelled JSON-RPC requests after provider stop"
    )
