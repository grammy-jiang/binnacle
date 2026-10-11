"""E0 native authenticated MCP smoke (interface 1.1.0), PRODUCTION scope only.

A test-owned, loopback-only FastMCP endpoint (random token, private spool, root under
``/tmp``) driven by a real MCP client, with positive teardown. Only the committed
``DARWIN_RELEASE_SCOPE`` is used (no ``release_scope`` argument): seven tools LIMITED,
``stop_job`` UNAVAILABLE. FULL_PARITY_NO_GO. ``E0_EVIDENCE_DIR`` records observations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

FULL_PARITY = "FULL_PARITY_NO_GO"
TOOLS = "read_file list_files search_text edit_file write_file run_command job_status stop_job"
REGISTERED_TOOLS = tuple(TOOLS.split())
LIMITED_TOOLS = tuple(t for t in REGISTERED_TOOLS if t != "stop_job")
PER_FILE_LIMIT = 16 * 1024 * 1024  # big.txt = Pi LINUX-AGG-CAP one_long_line bytes
STOP_JOB_TEXT = (
    "stop_job is unavailable on macOS. "
    "run_command is available in foreground mode only (no background jobs)."
)


@pytest.fixture
def native_host() -> None:
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
    errors: list[BaseException] = field(default_factory=list)


def _port_closed(host: str, port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host, port)) != 0


def _start_endpoint(root: Path, token: str) -> Endpoint:
    import uvicorn

    from binnacle.application import compose_native_tools, create_application
    from binnacle.config import Settings

    settings = Settings()
    settings.roots.default_root = root
    settings.roots.extra_roots = ()
    file_access, backend = compose_native_tools(settings=settings)
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
    spool = root.parent / "spool"
    spool.mkdir(mode=0o700, exist_ok=True)
    url = f"http://{host}:{port}/mcp"
    return Endpoint(url, host, port, token, root, spool, thread, server, errors)


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
    if out := os.environ.get("E0_EVIDENCE_DIR"):
        text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
        (Path(out) / f"{name}.json").write_text(text)


@pytest.fixture
def work_dir(native_host: None) -> Iterator[Path]:
    # run_command only accepts workdirs under /tmp or ~/Projects.
    base = Path(tempfile.mkdtemp(prefix="r3-E0-", dir="/tmp")).resolve()
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def endpoint(work_dir: Path) -> Iterator[Endpoint]:
    root = work_dir / "root"
    root.mkdir()
    (root / "hello.txt").write_text("hello e0\n", encoding="utf-8")
    ep = _start_endpoint(root, secrets.token_urlsafe(32))
    try:
        yield ep
    finally:
        proof = _stop_endpoint(ep)
        assert not proof["thread_alive"], "incomplete cleanup: server thread alive"
        assert proof["port_closed"], "incomplete cleanup: port still open"
        assert not proof["errors"], proof["errors"]
        assert not proof["spool_entries"], "incomplete cleanup: spool not empty"
        _record("cleanup-production", proof)


def _client(url: str, token: str | None):
    from fastmcp import Client

    return Client(url, auth=token)


async def _call(client, name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        res = await client.call_tool(name, args, raise_on_error=False)
    except Exception as exc:  # noqa: BLE001
        return {"error": True, "text": f"{type(exc).__name__}: {exc}", "data": None}
    text = " ".join(getattr(c, "text", "") for c in res.content)
    return {"error": bool(res.is_error), "text": text, "data": res.structured_content}


def _calls(endpoint: Endpoint, steps: list[tuple[str, str, dict[str, Any]]]):
    async def go():
        out: dict[str, dict[str, Any]] = {}
        async with _client(endpoint.url, endpoint.token) as c:
            for label, tool, args in steps:
                out[label] = await _call(c, tool, args)
        return out

    return asyncio.run(go())


def _schema_digests(tools) -> dict[str, str]:
    return {
        t.name: hashlib.sha256(
            json.dumps(t.input_schema, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for t in tools
    }


def _gone(pid: int, *, group: bool = False, timeout: float = 10.0) -> bool:
    """Poll until a pid (or its process group) no longer exists."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            (os.killpg if group else os.kill)(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def test_release_table_is_the_committed_production_scope() -> None:
    from binnacle.platform.contracts.capability_contracts import CapabilityState
    from binnacle.platform.contracts.darwin_release_scope import DARWIN_RELEASE_SCOPE

    rows = DARWIN_RELEASE_SCOPE
    states = {t: rows[t].capability.state for t in REGISTERED_TOOLS}
    assert all(states[t] is CapabilityState.LIMITED for t in LIMITED_TOOLS), states
    assert states["stop_job"] is CapabilityState.UNAVAILABLE
    assert DARWIN_RELEASE_SCOPE["stop_job"].enabling_gate == "never"


def test_handshake_and_eight_tool_schemas(endpoint: Endpoint) -> None:
    client_instructions: list[str | None] = []

    async def go():
        async with _client(endpoint.url, endpoint.token) as c:
            client_instructions.append(c.instructions)
            return await c.list_tools()

    tools = asyncio.run(go())
    assert {t.name for t in tools} == set(REGISTERED_TOOLS)
    for tool in tools:
        assert tool.input_schema.get("type") == "object" and tool.description
    _record("schema-production", {"digests": _schema_digests(tools)})
    low = json.dumps([[t.description for t in tools], client_instructions[0]]).lower()
    banned = r"\b(r1|cr1|gate|review|pending)\b|raspberry|vcgencmd|pinctrl|i2cdetect"
    assert not re.search(banned + "|libcamera|sig(term|kill)|become jobs", low)
    d = {t.name: t.description.lower() for t in tools}
    assert "unavailable on macos" in d["stop_job"] and "in memory" in d["job_status"]
    assert "macos workstation" in low


def test_stop_job_is_unavailable_never_enabled(endpoint: Endpoint) -> None:
    out = _calls(endpoint, [("stop_job", "stop_job", {"job_id": "e0-nonexistent"})])
    _record("calls-stop-job", {"full_parity": FULL_PARITY, **out})
    assert out["stop_job"]["error"]
    assert out["stop_job"]["text"] == STOP_JOB_TEXT


def _mk_outside(root: Path) -> Path:
    outside = root.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("hello secret\n")
    (root / "link").symlink_to(outside / "secret.txt")
    (root / "linkdir").symlink_to(outside, target_is_directory=True)
    return outside


def test_file_tools_happy_paths_and_denials(endpoint: Endpoint) -> None:
    root = endpoint.root
    outside = _mk_outside(root)
    w, sec = str(root / "w.txt"), str(outside / "secret.txt")
    edit = {"path": w, "old_string": "written", "new_string": "edited"}
    out = _calls(
        endpoint,
        [
            ("read", "read_file", {"path": str(root / "hello.txt")}),
            ("write", "write_file", {"path": w, "content": "written\n"}),
            ("edit", "edit_file", edit),
            ("read_after_edit", "read_file", {"path": w}),
            ("deny_root_escape", "read_file", {"path": sec}),
            ("deny_symlink_file", "read_file", {"path": str(root / "link")}),
            (
                "deny_symlink_write",
                "write_file",
                {"path": str(root / "linkdir" / "x.txt"), "content": "x"},
            ),
            (
                "deny_write_escape",
                "write_file",
                {"path": str(outside / "y"), "content": "y"},
            ),
        ],
    )
    _record("calls-file-tools", {"full_parity": FULL_PARITY, **out})
    for label in ("read", "write", "edit", "read_after_edit"):
        assert not out[label]["error"], (label, out[label])
    assert "hello e0" in json.dumps(out["read"]["data"]) + out["read"]["text"]
    assert (root / "w.txt").read_text() == "edited\n"
    assert all(o["error"] for k, o in out.items() if k.startswith("deny_")), out
    assert "secret" not in out["deny_root_escape"]["text"]
    assert (outside / "secret.txt").read_text() == "hello secret\n"
    assert not (outside / "x.txt").exists() and not (outside / "y").exists()


def test_list_files_symlink_policy(endpoint: Endpoint) -> None:
    root, r = endpoint.root, str(endpoint.root)
    outside = root.parent / "out"
    outside.mkdir()
    (outside / "s.txt").write_text("s")
    (root / "d").mkdir()
    (root / "d" / "in.txt").write_text("x")
    for name, target in (
        ("flink", "hello.txt"),
        ("dlink", "d"),
        ("outlink", "../out/s.txt"),
        ("dangle", "nope"),
    ):
        (root / name).symlink_to(target)
    out = _calls(
        endpoint,
        [
            ("list", "list_files", {"path": r}),
            ("glob_star", "list_files", {"path": r, "glob": "*"}),
            ("glob_2star", "list_files", {"path": r, "glob": "**/*"}),
        ],
    )
    _record("calls-list-symlinks", {"full_parity": FULL_PARITY, **out})
    typed = {
        Path(e["path"]).relative_to(root).as_posix(): (e["type"], e.get("bytes"))
        for e in out["list"]["data"]["entries"]
    }
    # In-root links are typed by target; outside and dangling links are omitted.
    assert typed == {
        "d": ("dir", None),
        "dlink": ("dir", None),
        "hello.txt": ("file", 9),
        "flink": ("file", 9),
    }, typed
    for label in ("glob_star", "glob_2star"):
        names = {Path(e["path"]).name for e in out[label]["data"]["entries"]}
        assert out[label]["data"]["mode"] == "glob" and names == {"hello.txt", "in.txt"}


def test_list_files_and_search_text_on_fixture(endpoint: Endpoint) -> None:
    root, r = endpoint.root, str(endpoint.root)
    _mk_outside(root)
    (root / "docs").mkdir()
    (root / "docs" / "note.md").write_text("hello docs\n")
    (root / "docs" / "a.py").write_text("print('hello')\n")
    (root / "big.txt").write_bytes(b"hello" + b"A" * (PER_FILE_LIMIT + 1024))
    hello = {"pattern": "hello", "path": r}
    out = _calls(
        endpoint,
        [
            ("list_all", "list_files", {"path": r}),
            ("list_glob_md", "list_files", {"path": r, "glob": "*.md"}),
            ("deny_list_link", "list_files", {"path": str(root / "linkdir")}),
            ("deny_search_link", "search_text", {**hello, "path": f"{r}/linkdir"}),
            ("search_glob_py", "search_text", {**hello, "glob": "*.py"}),
            ("search_all", "search_text", hello),
        ],
    )
    _record("calls-list-search", {"full_parity": FULL_PARITY, **out})

    def rel(label: str, key: str) -> set[str]:
        entries = out[label]["data"]["entries"]
        return {Path(e[key]).relative_to(root).as_posix() for e in entries}

    for label in ("list_all", "list_glob_md", "search_glob_py", "search_all"):
        assert not out[label]["error"], (label, out[label])
    assert rel("list_all", "path") >= {"docs", "hello.txt", "big.txt"}
    assert rel("list_glob_md", "path") == {"docs/note.md"}
    assert rel("search_glob_py", "file") == {"docs/a.py"}
    d, names = out["search_all"]["data"], {"hello.txt", "docs/note.md", "docs/a.py"}
    assert rel("search_all", "file") == {*names, "big.txt"}
    assert d["truncated"] is False and "note" not in d
    assert out["search_all"]["text"] == f"Found 4 matches for 'hello' under {r}."
    for label, o in out.items():
        if label.startswith("deny_"):
            assert o["error"] and "secret" not in o["text"], (label, o)


def test_run_command_sd18(endpoint: Endpoint) -> None:
    root, wd, py = endpoint.root, str(endpoint.root), sys.executable
    leader, child, bg, esc = (root / n for n in ("leader", "child", "bg", "esc"))
    spawn = (
        "import subprocess as s;p=s.Popen(['sleep','602'],start_new_session=True,"
        "stdin=s.DEVNULL,stdout=s.DEVNULL,stderr=s.DEVNULL);"
        f"open('{esc}','w').write(str(p.pid))"
    )
    timeout_cmd = f"echo $$ > {leader}; sleep 600 & echo $! > {child}; wait"
    cmds: dict[str, dict[str, Any]] = {
        "echo": {"command": "echo hi"},
        "exit3": {"command": "exit 3"},
        "stdin": {"command": "cat", "stdin": "fromstdin"},
        "workdir": {"command": "pwd"},
        "truncation": {"command": "head -c 3000000 /dev/zero | tr '\\0' x"},
        "timeout": {"command": timeout_cmd, "wait_seconds": 2},
        "background_true": {"command": "echo bg", "background": True},
        "sleep_amp": {"command": f"sleep 600 & echo $! > {bg}"},
        "escapee": {"command": f'{py} -c "{spawn}"'},
    }
    out = _calls(
        endpoint, [(k, "run_command", {"workdir": wd, **v}) for k, v in cmds.items()]
    )
    esc_pid = int(esc.read_text()) if esc.exists() else None
    evidence: dict[str, Any] = {"full_parity": FULL_PARITY, "calls": out}
    try:
        assert out["echo"]["data"]["output"] == "hi\n"
        assert "descendants_unverified=true" in out["echo"]["text"]
        assert out["exit3"]["data"]["exit_code"] == 3
        assert out["stdin"]["data"]["output"] == "fromstdin"
        assert out["workdir"]["data"]["output"].strip() == wd
        trunc = out["truncation"]["data"]
        assert trunc["truncated"] is True and trunc["output_bytes"] == 3_000_000
        assert len(trunc["output"]) < trunc["output_bytes"]
        assert out["timeout"]["error"]
        assert "darwin_background_jobs_unavailable" in out["timeout"]["text"]
        lead, kid = int(leader.read_text()), int(child.read_text())
        assert _gone(lead) and _gone(kid) and _gone(lead, group=True), (lead, kid)
        evidence["timeout_pids"] = {"leader": lead, "child": kid}
        assert out["background_true"]["error"]
        assert "darwin_background_jobs_unavailable" in out["background_true"]["text"]
        # 'sleep 600 &' is cleaned when the command ends.
        assert not out["sleep_amp"]["error"] and _gone(int(bg.read_text()))
        # setsid escapee: honestly reported, not claimed cleaned.
        assert esc_pid is not None and not out["escapee"]["error"], out["escapee"]
        assert "descendants_unverified=true" in out["escapee"]["text"]
        assert not _gone(esc_pid, timeout=0), "escapee should outlive the command"
        evidence["escapee_pid"] = esc_pid
    finally:
        # Kill ONLY the exact recorded escapee, after confirming what it is.
        if esc_pid is not None and not _gone(esc_pid, timeout=0):
            ps = ["ps", "-p", str(esc_pid), "-o", "command="]
            cmd = subprocess.run(
                ps, capture_output=True, text=True, check=False
            ).stdout.strip()
            evidence["escapee_command"] = cmd
            if cmd == "sleep 602":
                os.kill(esc_pid, signal.SIGKILL)
        evidence["escapee_dead"] = esc_pid is None or _gone(esc_pid)
        _record("sd18-run-command", evidence)
    assert evidence["escapee_dead"]


def test_job_status_completed_and_unknown(endpoint: Endpoint) -> None:
    run = {"command": "echo js", "workdir": str(endpoint.root)}
    job_id = _calls(endpoint, [("r", "run_command", run)])["r"]["data"]["job_id"]
    out = _calls(
        endpoint,
        [
            ("by_id", "job_status", {"job_id": job_id}),
            ("deny_unknown", "job_status", {"job_id": "e0-unknown-id"}),
        ],
    )
    _record("calls-job-status", {"full_parity": FULL_PARITY, **out})
    assert not out["by_id"]["error"], out["by_id"]
    assert out["by_id"]["data"]["job_id"] == job_id
    assert out["by_id"]["data"]["state"] == "exited"
    assert out["deny_unknown"]["error"] and "No job" in out["deny_unknown"]["text"]


def _assert_denied(url: str, token: str | None) -> None:
    async def go():
        async with _client(url, token) as c:
            await c.list_tools()

    with pytest.raises(Exception):  # noqa: B017 - any auth failure shape
        asyncio.run(go())


@pytest.mark.parametrize("variant", ["invalid", "missing"])
def test_bad_token_denied(endpoint: Endpoint, variant: str) -> None:
    _assert_denied(endpoint.url, "x" + endpoint.token if variant == "invalid" else None)


def test_wrong_peer_cannot_reach_listener(endpoint: Endpoint) -> None:
    assert endpoint.host == "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # no packets sent; selects the local route
            lan = s.getsockname()[0]
        except OSError:
            lan = "127.0.0.1"
    if lan.startswith("127."):
        pytest.skip("E0: no non-loopback local address to act as a wrong peer")
    assert _port_closed(lan, endpoint.port), f"listener reachable on {lan}"


def test_stale_service_rejected_after_teardown_and_restart(work_dir: Path) -> None:
    root = work_dir / "root"
    root.mkdir()

    first = _start_endpoint(root, secrets.token_urlsafe(32))
    proof = _stop_endpoint(first)
    assert not proof["thread_alive"] and proof["port_closed"]
    _assert_denied(first.url, first.token)
    # A fresh generation rejects the previous token.
    second = _start_endpoint(root, secrets.token_urlsafe(32))
    try:
        _assert_denied(second.url, first.token)
    finally:
        proof = _stop_endpoint(second)
    assert not proof["thread_alive"] and proof["port_closed"] and not proof["errors"]
    leftover = [t for t in threading.enumerate() if t.name == "e0-native-smoke"]
    assert not leftover, f"incomplete cleanup: {leftover}"
    _record("cleanup-positive", proof)
    _record("stale-service", {"first": first.port, "second": second.port, "ok": True})
