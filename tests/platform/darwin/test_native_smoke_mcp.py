"""E0 native authenticated MCP endpoint smoke (interface 1.1.0).

Test-owned, transient, loopback-only. It starts a real FastMCP HTTP endpoint on an
ephemeral 127.0.0.1 port with a random token, drives it with a real MCP client and
proves positive teardown. Nothing here installs a service, touches launchd, TCC or
any path outside a ``tmp_path`` the test owns.

Gating: skipped (with an owned reason) off macOS and until the B0 Darwin
composition exists (``binnacle.platform.composition.host_os_family("Darwin")``
stops raising ``UnsupportedHostOS``). FULL_PARITY_NO_GO: the eight registered
names never imply eight enabled tools; tools whose capability is not accepted
are reported as unsupported, not asserted as working.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import socket
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="E0 native smoke: macOS-only (Linux collection must skip cleanly)",
)

INTERFACE = "binnacle-darwin-r3-interface-1.1.0"
FULL_PARITY = "FULL_PARITY_NO_GO"
REGISTERED_TOOLS = (
    "read_file",
    "list_files",
    "search_text",
    "edit_file",
    "write_file",
    "run_command",
    "job_status",
    "stop_job",
)
# Frozen 1.1.0: stop_job is disabled by policy on Darwin.
POLICY_DISABLED = frozenset({"stop_job"})


def _b0_composition_gate() -> str | None:
    """Return an owned skip reason until the B0 Darwin composition exists."""
    composition = pytest.importorskip(
        "binnacle.platform.composition",
        reason="E0: binnacle.platform.composition missing at this commit",
    )
    try:
        composition.host_os_family("Darwin")
    except composition.UnsupportedHostOS:
        return (
            "E0: B0 Darwin composition not present yet "
            "(host_os_family('Darwin') still raises UnsupportedHostOS); "
            "this smoke runs on the B0 commit"
        )
    return None


@dataclass
class Endpoint:
    url: str
    host: str
    port: int
    token: str
    root: Path
    thread: threading.Thread
    server: Any
    errors: list[BaseException] = field(default_factory=list)


def _real_darwin_wiring(settings: Any) -> dict[str, Any]:
    """Mirror binnacle.server.create_server's Darwin wiring with test-owned inputs."""
    from binnacle.features.commands.command_backend import create_command_backend
    from binnacle.features.files.paths import FileToolAccess
    from binnacle.platform.composition import create_file_access, create_search_access
    from binnacle.platform.contracts.capability_contracts import (
        Capability,
        CapabilityState,
    )

    files = create_file_access()
    search = (
        create_search_access(files=files, rg_bin=settings.rg_bin)
        if files is not None
        else None
    )
    access = FileToolAccess(
        roots=settings.roots,
        files=files,
        search=search,
        generation="unavailable",
        capability=Capability(
            CapabilityState.UNAVAILABLE, "review_pending", "darwin_public_tools"
        ),
    )
    return {"file_access": access, "backend": create_command_backend()}


def _port_closed(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) != 0


def _start_endpoint(root: Path, token: str) -> Endpoint:
    gate = _b0_composition_gate()
    if gate:
        pytest.skip(gate)
    uvicorn = pytest.importorskip("uvicorn", reason="E0: uvicorn not installed")
    pytest.importorskip("fastmcp", reason="E0: fastmcp not installed")
    from binnacle.application import create_application
    from binnacle.config import Settings

    settings = Settings()
    settings.roots.default_root = root
    settings.roots.extra_roots = ()
    app = create_application(
        settings=settings, token=token, **_real_darwin_wiring(settings)
    ).http_app()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            asyncio.run(server.serve())
        except BaseException as exc:  # noqa: BLE001 - surfaced by the fixture
            errors.append(exc)

    thread = threading.Thread(target=run, name="e0-native-smoke", daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not (
        server.started and server.servers and server.servers[0].sockets
    ):
        if errors:
            raise errors[0]
        time.sleep(0.05)
    assert server.started, "test-owned endpoint did not start"
    host, port = server.servers[0].sockets[0].getsockname()[:2]
    return Endpoint(
        f"http://{host}:{port}/mcp", host, port, token, root, thread, server, errors
    )


def _stop_endpoint(ep: Endpoint) -> None:
    ep.server.should_exit = True
    ep.thread.join(timeout=20)


@pytest.fixture
def endpoint(tmp_path: Path) -> Iterator[Endpoint]:
    root = tmp_path / "root"
    root.mkdir()
    (root / "hello.txt").write_text("hello e0\n", encoding="utf-8")
    ep = _start_endpoint(root, secrets.token_urlsafe(32))
    try:
        yield ep
    finally:
        _stop_endpoint(ep)
        assert not ep.thread.is_alive(), "incomplete cleanup: server thread alive"
        assert _port_closed(ep.host, ep.port), "incomplete cleanup: port still open"
        assert not ep.errors, ep.errors


def _client(url: str, token: str | None):
    from fastmcp import Client

    return Client(url, auth=token)


def _run(coro):
    return asyncio.run(coro)


async def _call_outcome(client, name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        res = await client.call_tool(name, args, raise_on_error=False)
    except Exception as exc:  # noqa: BLE001 - denial is data here
        return {"status": "denied", "detail": f"{type(exc).__name__}: {exc}"}
    return {
        "status": "denied" if res.is_error else "ok",
        "detail": str(res.content)[:300],
    }


def test_handshake_and_eight_tool_schemas(endpoint: Endpoint) -> None:
    async def go():
        async with _client(endpoint.url, endpoint.token) as c:
            return await c.list_tools()

    tools = {t.name: t for t in _run(go())}
    # Registered names are asserted; enablement is NOT inferred from them.
    assert set(tools) == set(REGISTERED_TOOLS), sorted(tools)
    for name, tool in tools.items():
        assert tool.input_schema.get("type") == "object", name
        assert tool.description, name


def test_supported_and_unsupported_tool_calls_are_reported(
    endpoint: Endpoint, capsys: pytest.CaptureFixture[str]
) -> None:
    hello = str(endpoint.root / "hello.txt")
    calls = {
        "list_files": {"path": str(endpoint.root)},
        "read_file": {"path": hello},
        "search_text": {"pattern": "hello", "path": str(endpoint.root)},
        "job_status": {},
        "stop_job": {"job_id": "e0-nonexistent"},
        "run_command": {"command": "true"},
    }

    async def go():
        out = {}
        async with _client(endpoint.url, endpoint.token) as c:
            for name, args in calls.items():
                out[name] = await _call_outcome(c, name, args)
        return out

    outcomes = _run(go())
    report = {
        "interface": INTERFACE,
        "full_parity": FULL_PARITY,
        "outcomes": outcomes,
        "unsupported": sorted(n for n, o in outcomes.items() if o["status"] != "ok"),
    }
    print("E0-SMOKE-REPORT " + json.dumps(report, sort_keys=True))
    # Every unsupported tool must return the typed UNAVAILABLE marker, not a
    # generic crash (foreground run_command stays disabled; stop_job UNAVAILABLE).
    for name in POLICY_DISABLED | {"run_command", "job_status"}:
        assert outcomes[name]["status"] == "denied", outcomes[name]
    for name, outcome in outcomes.items():
        if outcome["status"] == "denied":
            assert "native_capability_unavailable" in outcome["detail"], (
                name,
                outcome,
            )
            assert "darwin_commands_unavailable" not in outcome["detail"], name
    # No fabricated parity: the report must not claim eight working tools.
    assert len([o for o in outcomes.values() if o["status"] == "ok"]) < len(
        REGISTERED_TOOLS
    )


def test_invalid_token_denied(endpoint: Endpoint) -> None:
    async def go():
        async with _client(endpoint.url, "not-" + endpoint.token) as c:
            await c.list_tools()

    with pytest.raises(Exception):  # noqa: B017 - any auth failure shape
        _run(go())


def test_missing_token_denied(endpoint: Endpoint) -> None:
    async def go():
        async with _client(endpoint.url, None) as c:
            await c.list_tools()

    with pytest.raises(Exception):  # noqa: B017
        _run(go())


def test_wrong_peer_cannot_reach_listener(endpoint: Endpoint) -> None:
    """No unauthorized listener: bound to loopback only, not a LAN address."""
    assert endpoint.host == "127.0.0.1"
    lan = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packets sent; selects local route
            lan = s.getsockname()[0]
    except OSError:
        pass
    if not lan or lan.startswith("127."):
        pytest.skip("E0: no non-loopback local address to act as a wrong peer")
    assert _port_closed(lan, endpoint.port), f"listener reachable on {lan}"


def test_stale_service_rejected_after_teardown_and_restart(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = _start_endpoint(root, secrets.token_urlsafe(32))
    _stop_endpoint(first)
    assert not first.thread.is_alive()
    assert _port_closed(first.host, first.port)

    async def stale():
        async with _client(first.url, first.token) as c:
            await c.list_tools()

    with pytest.raises(Exception):  # noqa: B017
        _run(stale())
    # A fresh generation must reject the previous generation's token.
    second = _start_endpoint(root, secrets.token_urlsafe(32))
    try:

        async def old_token():
            async with _client(second.url, first.token) as c:
                await c.list_tools()

        with pytest.raises(Exception):  # noqa: B017
            _run(old_token())
    finally:
        _stop_endpoint(second)
    assert not second.thread.is_alive()
    assert _port_closed(second.host, second.port)


def test_cleanup_is_positive_and_complete(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    before = {t.ident for t in threading.enumerate()}
    ep = _start_endpoint(root, secrets.token_urlsafe(32))
    _stop_endpoint(ep)
    assert not ep.thread.is_alive()
    assert _port_closed(ep.host, ep.port)
    leftover = [
        t for t in threading.enumerate() if t.ident not in before and t.is_alive()
    ]
    assert not leftover, f"incomplete cleanup: {leftover}"
    assert not ep.errors, ep.errors
