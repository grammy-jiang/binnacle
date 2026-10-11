"""E0 native authenticated MCP endpoint smoke (interface 1.1.0).

Test-owned, transient, loopback-only. It starts a real FastMCP HTTP endpoint on an
ephemeral 127.0.0.1 port with a random token, drives it with a real MCP client and
proves positive teardown. Nothing here installs a service, touches launchd, TCC or
any path outside a ``tmp_path`` the test owns.

Two scopes are exercised through the production composition
(``compose_native_tools``): the committed release table (every tool typed
UNAVAILABLE) and a test-only candidate scope passed through the keyword-only
``release_scope`` argument. Off a native host every test skips through the
``native_host`` fixture (a capability probe, not a module-level skip).
FULL_PARITY_NO_GO: eight registered names never imply eight enabled tools.

Set ``E0_EVIDENCE_DIR`` to have each test append its observations as JSON.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
import secrets
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

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
CANDIDATE_TOOLS = tuple(t for t in REGISTERED_TOOLS if t != "stop_job")


@pytest.fixture
def native_host() -> None:
    """Skip unless the native file mechanism composes on this host."""
    pytest.importorskip("uvicorn", reason="E0: uvicorn not installed")
    pytest.importorskip("fastmcp", reason="E0: fastmcp not installed")
    from binnacle.platform import composition

    try:
        native_files = composition.create_file_access()
    except composition.UnsupportedHostOS:
        pytest.skip("E0: no native adapter composition for this host")
    if native_files is None:
        pytest.skip("E0: no native file mechanism on this host (Linux adapters own it)")
    native_files.close()


@dataclass
class Endpoint:
    url: str
    host: str
    port: int
    token: str
    root: Path
    spool: Path
    thread: threading.Thread
    server: Any
    scope: str
    errors: list[BaseException] = field(default_factory=list)


def _candidate_scope() -> dict[str, Any]:
    """Test-only scope: all tools but stop_job LIMITED; never a runtime flag."""
    from binnacle.platform.contracts.capability_contracts import (
        Capability,
        CapabilityState,
    )
    from binnacle.platform.contracts.darwin_release_scope import DARWIN_RELEASE_SCOPE

    scope = dict(DARWIN_RELEASE_SCOPE)
    for tool in CANDIDATE_TOOLS:
        scope[tool] = dataclasses.replace(
            scope[tool],
            capability=Capability(CapabilityState.LIMITED, "test_only", tool),
        )
    return scope


def _port_closed(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) != 0


def _start_endpoint(
    root: Path, token: str, *, candidate: bool = False, spool: Path | None = None
) -> Endpoint:
    import uvicorn

    from binnacle.application import compose_native_tools, create_application
    from binnacle.config import Settings

    settings = Settings()
    settings.roots.default_root = root
    settings.roots.extra_roots = ()
    kwargs: dict[str, Any] = {"release_scope": _candidate_scope()} if candidate else {}
    file_access, backend = compose_native_tools(settings=settings, **kwargs)
    app = create_application(
        settings=settings, token=token, backend=backend, file_access=file_access
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
    spool = spool or root.parent / "spool"
    spool.mkdir(mode=0o700, exist_ok=True)
    return Endpoint(
        f"http://{host}:{port}/mcp",
        host,
        port,
        token,
        root,
        spool,
        thread,
        server,
        "candidate" if candidate else "production",
        errors,
    )


def _stop_endpoint(ep: Endpoint) -> dict[str, Any]:
    ep.server.should_exit = True
    ep.thread.join(timeout=20)
    return {
        "thread_alive": ep.thread.is_alive(),
        "port_closed": _port_closed(ep.host, ep.port),
        "errors": [repr(e) for e in ep.errors],
        "spool_entries": sorted(p.name for p in ep.spool.iterdir()),
    }


def _record(name: str, payload: dict[str, Any]) -> None:
    out = os.environ.get("E0_EVIDENCE_DIR")
    if not out:
        return
    path = Path(out) / f"{name}.json"
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")


@pytest.fixture(params=["production", "candidate"])
def endpoint(request, tmp_path: Path, native_host: None) -> Iterator[Endpoint]:
    root = tmp_path / "root"
    root.mkdir()
    (root / "hello.txt").write_text("hello e0\n", encoding="utf-8")
    ep = _start_endpoint(
        root, secrets.token_urlsafe(32), candidate=request.param == "candidate"
    )
    try:
        yield ep
    finally:
        proof = _stop_endpoint(ep)
        assert not proof["thread_alive"], "incomplete cleanup: server thread alive"
        assert proof["port_closed"], "incomplete cleanup: port still open"
        assert not proof["errors"], proof["errors"]
        assert not proof["spool_entries"], "incomplete cleanup: spool not empty"
        _record(f"cleanup-{ep.scope}", proof)


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
    text = " ".join(getattr(c, "text", "") for c in res.content)
    return {"status": "denied" if res.is_error else "ok", "detail": text[:300]}


def _schema_digests(tools) -> dict[str, str]:
    return {
        t.name: hashlib.sha256(
            json.dumps(t.input_schema, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for t in tools
    }


def test_handshake_and_eight_tool_schemas(endpoint: Endpoint) -> None:
    async def go():
        async with _client(endpoint.url, endpoint.token) as c:
            return await c.list_tools()

    tools = _run(go())
    names = {t.name for t in tools}
    # Registered names are asserted; enablement is NOT inferred from them.
    assert names == set(REGISTERED_TOOLS), sorted(names)
    for tool in tools:
        assert tool.input_schema.get("type") == "object", tool.name
        assert tool.description, tool.name
    digests = _schema_digests(tools)
    _record(f"schema-{endpoint.scope}", {"digests": digests})


def test_production_scope_types_every_tool_unavailable(endpoint: Endpoint) -> None:
    if endpoint.scope != "production":
        pytest.skip("E0: production-scope assertion")
    hello = str(endpoint.root / "hello.txt")
    calls = {
        "list_files": {"path": str(endpoint.root)},
        "read_file": {"path": hello},
        "search_text": {"pattern": "hello", "path": str(endpoint.root)},
        "edit_file": {"path": hello, "old_string": "hello", "new_string": "bye"},
        "write_file": {"path": str(endpoint.root / "new.txt"), "content": "x"},
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
    _record(
        "calls-production",
        {"interface": INTERFACE, "full_parity": FULL_PARITY, "outcomes": outcomes},
    )
    for name, outcome in outcomes.items():
        assert outcome["status"] == "denied", (name, outcome)
        assert "UNAVAILABLE" in outcome["detail"].upper() or (
            "unavailable" in outcome["detail"]
        ), (name, outcome)
    assert (endpoint.root / "hello.txt").read_text() == "hello e0\n"
    assert not (endpoint.root / "new.txt").exists()


def test_candidate_scope_supported_calls_and_denials(endpoint: Endpoint) -> None:
    if endpoint.scope != "candidate":
        pytest.skip("E0: candidate-scope assertion")
    root = endpoint.root
    outside = root.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n")
    (root / "link").symlink_to(outside / "secret.txt")
    (root / "linkdir").symlink_to(outside, target_is_directory=True)
    denied_file = root / "eperm.txt"
    denied_file.write_text("nope\n")
    denied_file.chmod(0)
    big = root / "big.bin"
    big.write_bytes(b"A" * (21 * 1024 * 1024))
    (root / "docs").mkdir()
    (root / "docs" / "note.txt").write_text("hello docs\n")
    hello = str(root / "hello.txt")

    async def go():
        out: dict[str, dict[str, Any]] = {}
        async with _client(endpoint.url, endpoint.token) as c:
            steps = {
                "read_file": ("read_file", {"path": hello}),
                "list_files": ("list_files", {"path": str(root)}),
                "search_text": (
                    "search_text",
                    {"pattern": "hello", "path": str(root / "docs")},
                ),
                # Observation only: a 21 MiB single-line file in scope.
                "search_text_with_oversized_file": (
                    "search_text",
                    {"pattern": "hello", "path": str(root)},
                ),
                "write_file": (
                    "write_file",
                    {"path": str(root / "w.txt"), "content": "written\n"},
                ),
                "edit_file": (
                    "edit_file",
                    {
                        "path": str(root / "w.txt"),
                        "old_string": "written",
                        "new_string": "edited",
                    },
                ),
                "read_after_edit": ("read_file", {"path": str(root / "w.txt")}),
                "job_status": ("job_status", {}),
                "run_command": (
                    "run_command",
                    {"command": "true", "workdir": str(root)},
                ),
                "deny_root_escape_read": (
                    "read_file",
                    {"path": str(outside / "secret.txt")},
                ),
                "deny_root_escape_dotdot": (
                    "read_file",
                    {"path": str(root / ".." / "outside" / "secret.txt")},
                ),
                "deny_symlink_file": ("read_file", {"path": str(root / "link")}),
                "deny_symlink_dir_list": (
                    "list_files",
                    {"path": str(root / "linkdir")},
                ),
                "deny_symlink_write": (
                    "write_file",
                    {"path": str(root / "linkdir" / "x.txt"), "content": "x"},
                ),
                "deny_eperm_read": ("read_file", {"path": str(denied_file)}),
                "deny_oversized_read": ("read_file", {"path": str(big)}),
                "unsupported_stop_job": ("stop_job", {"job_id": "e0-nonexistent"}),
            }
            for label, (tool, args) in steps.items():
                out[label] = await _call_outcome(c, tool, args)
        return out

    try:
        outcomes = _run(go())
    finally:
        denied_file.chmod(0o600)
    _record(
        "calls-candidate",
        {"interface": INTERFACE, "full_parity": FULL_PARITY, "outcomes": outcomes},
    )
    for label in ("read_file", "list_files", "search_text", "write_file", "edit_file"):
        assert outcomes[label]["status"] == "ok", (label, outcomes[label])
    assert (
        "hello e0" in outcomes["read_file"]["detail"]
        or outcomes["read_file"]["status"] == "ok"
    )
    assert (root / "w.txt").read_text() == "edited\n"
    assert not (outside / "x.txt").exists()
    for label, outcome in outcomes.items():
        if label.startswith("deny_") or label == "unsupported_stop_job":
            assert outcome["status"] == "denied", (label, outcome)
    assert "secret" not in outcomes["deny_root_escape_read"]["detail"]
    assert (outside / "secret.txt").read_text() == "secret\n"
    # job_status / run_command stay observed data, never asserted as working:
    # commands remain inert in a candidate scope until A2 opens its entrypoint.
    ok = [n for n, o in outcomes.items() if o["status"] == "ok"]
    assert "stop_job" not in ok and "unsupported_stop_job" not in ok


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


def test_stale_service_rejected_after_teardown_and_restart(
    tmp_path: Path, native_host: None
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = _start_endpoint(root, secrets.token_urlsafe(32))
    proof = _stop_endpoint(first)
    assert not proof["thread_alive"] and proof["port_closed"]

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
        proof = _stop_endpoint(second)
    assert not proof["thread_alive"] and proof["port_closed"]
    _record("stale-service", {"first": first.port, "second": second.port, "ok": True})


def test_cleanup_is_positive_and_complete(tmp_path: Path, native_host: None) -> None:
    root = tmp_path / "root"
    root.mkdir()
    before = {t.ident for t in threading.enumerate()}
    ep = _start_endpoint(root, secrets.token_urlsafe(32))
    proof = _stop_endpoint(ep)
    assert not proof["thread_alive"]
    assert proof["port_closed"]
    leftover = [
        t for t in threading.enumerate() if t.ident not in before and t.is_alive()
    ]
    assert not leftover, f"incomplete cleanup: {leftover}"
    assert not proof["errors"], proof["errors"]
