"""R4 J5 end-to-end durable jobs: real J1 owner + J2 manager in a test subprocess.

State is a private tmp root and 127.0.0.1 port. MCP cases use test-only AVAILABLE
rows (committed rows stay UNAVAILABLE until J-CR); launchd uses r4test.j5 labels.
"""

from __future__ import annotations

import asyncio
import json
import os
import plistlib
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from mcp.types import Implementation

from binnacle.features.commands import job_client, job_store
from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.darwin import job_manager_service as svc
from binnacle.platform.darwin.generation_runtime import (
    discover_service_lease,
    open_service_lease,
)
from binnacle.platform.darwin.job_manager_client import DarwinJobClient
from binnacle.platform.darwin.job_manager_entry import serve_job_manager
from binnacle.platform.darwin.job_process_owner import DarwinJobProcessOwner

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin kqueue/A3 IPC")
LABEL = svc.MANAGER_LABEL
REPO = Path(__file__).resolve().parents[3]
Err = job_client.JobManagerError
GRACE = 0.5


def _manager_main(root: Path, jobs: Path) -> int:
    """Child entry: the real owner and manager, SIGTERM drains and closes."""
    boot = "r4-j5-boot-" + root.parent.name  # one host boot across incarnations
    grace = {"stop_sigterm_grace_s": GRACE, "stop_sigkill_grace_s": GRACE}
    owner = DarwinJobProcessOwner(boot_id=boot, start_reaper=False, **grace)
    manager = svc.DarwinJobManager(
        owner=owner, jobs_dir=jobs, boot_id=boot, wait_max_s=50, keep_newest=50,
        grace=(GRACE, GRACE),
    )  # fmt: skip
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    lease = open_service_lease(root=root, label=LABEL, generation=secrets.token_hex(16))
    serve_job_manager(manager, socket_path=root / "jobs.sock", lease=lease, stop=stop)
    return 0


def meta_of(jobs: Path, job_id: str) -> dict[str, Any]:
    return dict(json.loads((jobs / job_id / "meta.json").read_text()))


def client(label: str = LABEL) -> DarwinJobClient:
    return DarwinJobClient(label=label, error_type=Err)


def ping(sock: Path, label: str = LABEL) -> dict[str, Any] | None:
    with suppress(Err):
        return client(label).ping(sock)
    return None


def tamper(sock: Path) -> bytes:
    auth = sock.with_name("jobs.sock.auth")
    original = auth.read_bytes()
    auth.write_text(json.dumps({**json.loads(original), "key": "0" * 64}))
    return original


def group_gone(pgid: int) -> bool:
    with suppress(ProcessLookupError):
        os.killpg(pgid, 0)
        return False
    return True


def until(predicate: Any, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        time.sleep(0.05)
    return bool(predicate())


class Stack:
    def __init__(self, base: Path) -> None:
        self.root, self.jobs = base / "rt", base / "jobs"
        self.work = base / "work"
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.work.mkdir(exist_ok=True)
        self.sock = self.root / "jobs.sock"
        self.proc: subprocess.Popen[bytes] | None = None
        self.idents: dict[int, str] = {}  # pgid -> (start time, command) at spawn

    def spawn_manager(self, root: Path | None = None) -> subprocess.Popen[bytes]:
        argv = [sys.executable, __file__, str(root or self.root), str(self.jobs)]
        return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def start(self) -> None:
        self.proc = self.spawn_manager()
        assert until(lambda: ping(self.sock) is not None, 20), "manager not ready"

    def run(self, command: str, wait: float = 0.2) -> Any:
        kw: dict[str, Any] = {"workdir": self.work, "stdin": None, "call_id": "e2e"}
        return client().start(self.sock, command=command, wait_seconds=wait, **kw)

    def end(self, sig: int) -> int:
        assert self.proc is not None
        self.proc.send_signal(sig)  # the exact Popen child this stack spawned
        code = self.proc.wait(20)
        self.proc = None
        return code


@pytest.fixture
def stack() -> Iterator[Stack]:
    with tempfile.TemporaryDirectory(prefix="r4-j5-", dir="/tmp") as value:
        env = Stack(Path(value).resolve())
        try:
            yield env
        finally:
            if env.proc is not None and env.proc.poll() is None:
                env.proc.kill()
                env.proc.communicate(timeout=5)
            for pgid, seen in env.idents.items():  # only a still-matching group
                if ident(pgid) == seen:
                    with suppress(ProcessLookupError):
                        os.killpg(pgid, signal.SIGKILL)


def ident(pid: int) -> str:
    argv = ["/bin/ps", "-o", "lstart=,command=", "-p", str(pid)]
    return subprocess.run(
        argv, capture_output=True, text=True, check=False
    ).stdout.strip()


def track(stack: Stack, job_id: str) -> int:
    pgid = int(meta_of(stack.jobs, job_id)["pgid"])
    stack.idents[pgid] = ident(pgid)
    return pgid


@NATIVE
def test_wait_expiry_continues_as_durable_job(stack: Stack) -> None:
    stack.start()
    marker = stack.work / "done"
    job = stack.run(f"sleep 1; echo tail; touch {marker}", wait=0.2)
    track(stack, job["job_id"])
    assert job["state"] == "running"  # wait expiry never kills (Linux parity)
    assert not marker.exists()
    assert until(marker.exists, 10)
    assert until(lambda: meta_of(stack.jobs, job["job_id"]).get("exit_code") == 0)
    meta = meta_of(stack.jobs, job["job_id"])
    assert (meta["owner"], meta["termination_reason"]) == ("manager", "normal_exit")
    assert (stack.jobs / job["job_id"] / "out.log").read_text() == "tail\n"


@NATIVE
def test_stop_sends_term_then_kill_after_grace(stack: Stack) -> None:
    stack.start()
    polite = stack.run("sleep 60", wait=0.2)
    stubborn = stack.run("trap '' TERM; sleep 60", wait=0.3)
    pgids = [track(stack, j["job_id"]) for j in (polite, stubborn)]
    for job in (polite, stubborn):
        reply = client().stop(stack.sock, job["job_id"], call_id="e2e-stop")
        assert reply == {"ok": True, "job_id": job["job_id"], "state": "exited"}
    first, second = (meta_of(stack.jobs, j["job_id"]) for j in (polite, stubborn))
    assert (first["signal"], first["termination_reason"]) == (15, "stop_requested")
    assert (second["signal"], second["stop_requested"]) == (9, True)  # TERM ignored
    assert all(group_gone(pgid) for pgid in pgids)


@NATIVE
def test_manager_sigkill_marks_unknown_and_never_adopts(stack: Stack) -> None:
    stack.start()
    job = stack.run("sleep 60", wait=0.1)
    pgid = track(stack, job["job_id"])
    stack.end(signal.SIGKILL)
    assert not group_gone(pgid)  # the orphaned leader survives its manager
    stack.start()  # a new incarnation recovers the spool, owning nothing
    meta = meta_of(stack.jobs, job["job_id"])
    assert (meta["authority"], meta["exit_code"]) == ("UNKNOWN", None)
    assert meta["signal"] is None
    assert meta["termination_reason"] == "owner_restart"
    with pytest.raises(Err, match=pc.OWNER_LOST_STOP_REFUSED):
        client().stop(stack.sock, job["job_id"])
    assert not group_gone(pgid)  # never signalled: no adoption


@NATIVE
def test_graceful_manager_stop_leaves_no_orphans(stack: Stack) -> None:
    # The measured R4 orphan case: before, a restart left the child running
    # (reparented to PID 1). A manager stop now reaps every owned group.
    stack.start()
    marker = stack.work / "inflight"
    job = stack.run(f"(sleep 60 &) ; sleep 60; touch {marker}", wait=0.2)
    pgid = track(stack, job["job_id"])
    assert stack.end(signal.SIGTERM) == 0
    assert group_gone(pgid)
    meta = meta_of(stack.jobs, job["job_id"])
    assert (meta["signal"], meta["termination_reason"]) == (15, "owner_restart")
    assert "authority" not in meta and not marker.exists()


@NATIVE
def test_peer_and_generation_refusals_never_dispatch(stack: Stack) -> None:
    stack.start()
    original = tamper(stack.sock)
    with pytest.raises(Err, match=pc.JOB_MANAGER_UNAVAILABLE):
        stack.run(f"touch {stack.work / 'x'}")
    stack.sock.with_name("jobs.sock.auth").write_bytes(original)
    other = LABEL + ".other"
    with pytest.raises(Err, match=pc.JOB_MANAGER_UNAVAILABLE):
        client(other).ping(stack.sock)  # label mismatch is refused before any bytes
    with pytest.raises(NativeCapabilityError, match="generation_mismatch"):
        discover_service_lease(root=stack.root, label=other, name="jobs.sock")
    assert job_store.list_job_ids(stack.jobs) == []
    assert not (stack.work / "x").exists()


@NATIVE
def test_second_writer_on_same_jobs_dir_is_refused(stack: Stack) -> None:
    stack.start()
    job = stack.run("sleep 30", wait=0.1)
    track(stack, job["job_id"])
    before = meta_of(stack.jobs, job["job_id"])
    other_root = stack.root.parent / "rt2"
    other_root.mkdir(mode=0o700)
    rival = stack.spawn_manager(other_root)
    _, err = rival.communicate(timeout=20)
    assert rival.returncode != 0 and b"already owns" in err
    assert meta_of(stack.jobs, job["job_id"]) == before  # rival ran no recovery
    assert not (other_root / "jobs.sock").exists()
    assert client().ping(stack.sock)["pid"] == stack.proc.pid  # type: ignore[union-attr]


@NATIVE
def test_stale_or_ambiguous_process_reference_stays_unowned() -> None:
    victim = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
    owner = DarwinJobProcessOwner(boot_id=uuid.uuid4().hex)
    try:
        for ref in ("deadbeef0000", str(victim.pid), ""):
            seen = owner.authority(ref)
            assert (seen.authority, seen.alive) == ("UNKNOWN", None)
            assert seen.reason_code == "darwin_job_not_owned"
            with pytest.raises(pc.UnverifiedJobProcess):
                owner.signal_owned_group(ref, "kill")
        assert victim.poll() is None  # a live pid grants nothing
    finally:
        owner.close()
        victim.kill()
        victim.wait(5)


def _mcp_main(port: int, work: Path, jobs: Path, sock: Path, token: str) -> int:
    from dataclasses import replace

    from binnacle.application import compose_native_tools, create_application
    from binnacle.config import RootsSettings, Settings
    from binnacle.platform.contracts import capability_contracts as cc
    from binnacle.platform.contracts import darwin_release_scope as drs

    scope: dict[str, Any] | None = dict(drs.release_scope_for_owner("manager"))
    for tool in drs.COMMAND_TOOLS:
        row = cc.Capability(cc.CapabilityState.AVAILABLE, "test", tool)
        scope[tool] = replace(scope[tool], capability=row)  # type: ignore[index]
    if os.environ.get("BINNACLE_J5_PRODUCTION_ROWS") == "1":
        scope = None  # switch: the committed production table, no override
    settings = Settings(roots=RootsSettings(default_root=work))
    settings.jobs.dir, settings.jobs.socket_path = jobs, sock
    settings.run_command.auto_background_patterns = {"r4-j5": ("^sleep ",)}
    settings.run_command.auto_background_evidence_dir = work.parent / "evidence"
    access, backend = compose_native_tools(
        settings=settings, release_scope=scope, owner="manager"
    )
    app = create_application(
        file_access=access, settings=settings, token=token, backend=backend
    )
    app.run(transport="http", host="127.0.0.1", port=port, show_banner=False)
    return 0


class McpStack:
    def __init__(self, stack: Stack) -> None:
        with socket.socket() as probe:  # a free 127.0.0.1 port, never a fixed one
            probe.bind(("127.0.0.1", 0))
            self.port = int(probe.getsockname()[1])
        self.stack, self.token = stack, secrets.token_hex(16)
        self.proc: subprocess.Popen[bytes] | None = None
        self.env = {**os.environ, "HOME": str(stack.root.parent)}

    def start(self) -> None:
        argv = [sys.executable, __file__, "mcp", str(self.port), str(self.stack.work)]
        argv += [str(self.stack.jobs), str(self.stack.sock), self.token]
        out = subprocess.DEVNULL
        self.proc = subprocess.Popen(
            argv, env=self.env, stdout=out, stderr=out, start_new_session=True
        )
        assert until(self._up, 60), "MCP server did not listen"

    def _up(self) -> bool:
        with suppress(OSError), socket.create_connection(("127.0.0.1", self.port), 1):
            return True
        return False

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()  # exact Popen pid recorded at spawn
            self.proc.wait(20)
            self.proc = None

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "run_command":
            args = {"workdir": str(self.stack.work), **args}
        url = f"http://127.0.0.1:{self.port}/mcp"

        async def once() -> Any:
            async with Client(
                url,
                auth=self.token,
                client_info=Implementation(name="r4-j5", version="0"),
            ) as client:
                return await client.call_tool(tool, args, raise_on_error=False)

        out = asyncio.run(once())
        text = " ".join(getattr(c, "text", "") for c in out.content)
        return {**(out.structured_content or {}), "isError": out.is_error, "text": text}


@pytest.fixture
def mcp(stack: Stack) -> Iterator[McpStack]:
    stack.start()
    server = McpStack(stack)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@NATIVE
def test_mcp_wait_expiry_background_and_auto_background(mcp: McpStack) -> None:
    marker = mcp.stack.work / "marker"
    reply = mcp.call(
        "run_command", {"command": f"sleep 2; touch {marker}", "wait_seconds": 1}
    )
    assert reply["state"] == "running" and reply["job_id"]  # wait expiry never kills
    assert until(marker.exists, 10)
    status = mcp.call("job_status", {"job_id": reply["job_id"], "wait_seconds": 5})
    assert (status["state"], status["exit_code"]) == ("exited", 0)
    slow = mcp.call("run_command", {"command": "sleep 3", "background": True})
    assert slow["state"] == "running" and slow["background_job"] is True
    fast = mcp.call("run_command", {"command": "echo hi", "background": True})
    assert fast["state"] == "exited" and fast["output"].strip() == "hi"
    auto = mcp.call("run_command", {"command": "sleep 3; echo auto"})
    assert auto["state"] == "running" and auto["background_job"] is True
    # an explicit background=false opts out of the pattern (Linux parity)
    quick = mcp.call("run_command", {"command": "echo y", "background": False})
    assert quick["state"] == "exited" and quick["background_job"] is False


@NATIVE
def test_mcp_cursor_across_mcp_restart(mcp: McpStack) -> None:
    args = {"command": "echo a; sleep 2; echo b", "background": True}
    job = mcp.call("run_command", args)
    first = mcp.call("job_status", {"job_id": job["job_id"], "cursor": "start"})
    mcp.stop()
    mcp.start()  # an MCP restart does not own the job
    args = {"job_id": job["job_id"], "cursor": first["next_cursor"], "wait_seconds": 5}
    rest = mcp.call("job_status", args)
    assert first["log_delta"] == "a\n" and first["state"] == "running"
    assert rest["state"] == "exited" and rest["log_delta"] == "b\n"
    assert rest["delta_start"] == first["delta_end"]  # the cursor carried over


@NATIVE
def test_mcp_stop_job_term_then_kill(mcp: McpStack) -> None:
    args = {"command": "trap '' TERM; sleep 60", "background": True}
    job_id = mcp.call("run_command", args)["job_id"]
    assert mcp.call("stop_job", {"job_id": job_id})["state"] == "exited"
    assert mcp.call("job_status", {"job_id": job_id})["signal"] == 9


@NATIVE
def test_mcp_unreachable_manager_fails_closed_then_unknown_never_adopted(
    mcp: McpStack,
) -> None:
    original = tamper(mcp.stack.sock)  # peer refusal, then a dead manager
    refused = mcp.call("run_command", {"command": "touch x", "background": True})
    mcp.stack.sock.with_name("jobs.sock.auth").write_bytes(original)
    assert refused["isError"] and not (mcp.stack.work / "x").exists()
    job = mcp.call("run_command", {"command": "sleep 30", "background": True})
    pgid = track(mcp.stack, job["job_id"])
    mcp.stack.end(signal.SIGKILL)
    ident_args = {"job_id": job["job_id"]}
    for tool, args in (
        ("run_command", {"command": "touch x"}),
        ("stop_job", ident_args),
    ):
        reply = mcp.call(tool, args)  # per-call error, never a fallback
        assert reply["isError"] and pc.JOB_MANAGER_UNAVAILABLE in reply["text"], tool
    status = mcp.call("job_status", {"job_id": job["job_id"]})  # read-only spool
    assert status["state"] == "running" and not status["isError"]
    mcp.stack.start()  # a new incarnation never adopts the orphaned leader
    status = mcp.call("job_status", {"job_id": job["job_id"]})
    assert status["state"] == "unknown" and status.get("exit_code") is None
    assert mcp.call("stop_job", ident_args)["isError"] and not group_gone(pgid)
    assert not (mcp.stack.work / "x").exists()


def launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    argv = ["/bin/launchctl", *args]
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def label_pid(target: str) -> int | None:
    found = re.search(
        r"^\s+pid = (\d+)$", launchctl("print", target).stdout, re.MULTILINE
    )
    return int(found[1]) if found else None


def render_test_plist(base: Path, label: str, config: Path) -> Path:
    assert label.startswith("com.binnacle.r4test.j5."), "never a production label"
    env = {"HOME": str(base), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO / "src")}
    env["BINNACLE_CONFIG_FILE"] = str(config)
    module = "binnacle.platform.darwin.job_manager_service"  # the production entry
    plist = {
        "Label": label,
        "ProgramArguments": [sys.executable, "-m", module],
        "EnvironmentVariables": env,
        "LimitLoadToSessionType": "Background",
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardErrorPath": str(base / "launchd.err.log"),
    }
    path = base / f"{label}.plist"
    path.write_bytes(plistlib.dumps(plist))
    return path


@NATIVE
def test_launchd_kickstart_restart_leaves_no_orphans_and_marks_owner_restart(
    stack: Stack,
) -> None:
    base, sock = stack.root.parent, stack.sock
    config = base / "config.toml"
    config.write_text(f'[jobs]\nsocket_path = "{sock}"\ndir = "{stack.jobs}"\n')
    label = f"com.binnacle.r4test.j5.jobs.{uuid.uuid4().hex[:8]}"
    plist = render_test_plist(base, label, config)
    domain, target = f"user/{os.getuid()}", f"user/{os.getuid()}/{label}"
    try:
        assert launchctl("bootstrap", domain, str(plist)).returncode == 0
        assert until(lambda: ping(sock) is not None, 60), "manager not ready"
        first = label_pid(target)  # recorded to prove a new incarnation
        job = client().start(
            sock, command="(sleep 120 &); sleep 120", wait_seconds=0.2,
            workdir=stack.work, stdin=None, call_id="e2e-launchd",
        )  # fmt: skip
        pgid = track(stack, job["job_id"])
        result = launchctl("kickstart", "-k", target)  # SIGTERM -> owned groups reaped
        assert result.returncode == 0, result.stderr
        assert until(lambda: group_gone(pgid), 30), "group member survived restart"
        assert until(lambda: ping(sock) is not None, 60), "no restart"
        assert label_pid(target) not in (None, first)
        meta = meta_of(stack.jobs, job["job_id"])
        assert meta["termination_reason"] == "owner_restart"
        assert (ping(sock) or {})["running_jobs"] == 0  # the new incarnation owns none
    finally:
        launchctl("bootout", target)
        assert until(lambda: launchctl("print", target).returncode != 0, 30)
        plist.unlink(missing_ok=True)
    assert launchctl("print", target).returncode != 0  # label absent after teardown


if __name__ == "__main__":
    if sys.argv[1] == "mcp":
        port, work, jobs, sock, token = sys.argv[2:7]
        raise SystemExit(
            _mcp_main(int(port), Path(work), Path(jobs), Path(sock), token)
        )
    raise SystemExit(_manager_main(Path(sys.argv[1]), Path(sys.argv[2])))
