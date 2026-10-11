"""R4 J5 end-to-end durable jobs: real J1 owner + J2 manager in a test subprocess.

Everything runs against a private runtime dir, token (A3 generation), jobs dir and
the test label ``com.binnacle.r4test.e2e``; the production daemons are never touched.
Tests that need J4's tool wiring or J3's launchd plist are written now and skip
per test with a reason naming the lane.
"""

from __future__ import annotations

import json
import os
import plistlib
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

from binnacle.features.commands import job_client, job_store
from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.darwin import job_manager_service as svc
from binnacle.platform.darwin.generation_runtime import (
    discover_service_lease,
    open_service_lease,
)
from binnacle.platform.darwin.job_process_owner import DarwinJobProcessOwner

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin kqueue/A3 IPC")
LABEL = "com.binnacle.r4test.e2e"
REPO = Path(__file__).resolve().parents[3]
Err = job_client.JobManagerError
GRACE = 0.5


def need(lane: str, reason: str) -> None:
    """In-body per-test gate for behaviour another R4 lane has yet to deliver."""
    j4_wired = "darwin_background_jobs_unavailable" not in (
        REPO / "src/binnacle/features/commands/tools/run_command.py"
    ).read_text(encoding="utf-8")
    j3_plist = Path(os.environ.get("BINNACLE_J5_J3_PLIST", "/nonexistent"))
    ready = {"J4": j4_wired, "J3": j3_plist.is_file()}[lane]
    if not ready:
        pytest.skip(f"needs {lane}: {reason}")


def _manager_main(root: Path, jobs: Path) -> int:
    """Child entry: the real owner and manager, SIGTERM drains and closes."""
    boot = "r4-j5-boot-" + root.parent.name  # one host boot across incarnations
    # The manager's reap_forever drives reap_exits; the owner's own reaper thread
    # would consume the exits first and the manager would never persist them.
    owner = DarwinJobProcessOwner(
        boot_id=boot,
        stop_sigterm_grace_s=GRACE,
        stop_sigkill_grace_s=GRACE,
        start_reaper=False,
    )
    manager = svc.DarwinJobManager(
        owner=owner,
        jobs_dir=jobs,
        boot_id=boot,
        wait_max_s=50,
        keep_newest=50,
        grace=(GRACE, GRACE),
    )
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    lease = open_service_lease(root=root, label=LABEL, generation=secrets.token_hex(16))
    svc.serve_job_manager(
        manager, socket_path=root / "jobs.sock", lease=lease, stop=stop
    )
    return 0


def meta_of(jobs: Path, job_id: str) -> dict[str, Any]:
    return dict(json.loads((jobs / job_id / "meta.json").read_text()))


def client() -> svc.DarwinJobClient:
    return svc.DarwinJobClient(label=LABEL, error_type=Err)


def group_gone(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    return False


def until(predicate: Any, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


class Stack:
    """One manager subprocess over a private runtime root and jobs dir."""

    def __init__(self, base: Path) -> None:
        self.root, self.jobs = base / "rt", base / "jobs"
        self.work = base / "work"
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.work.mkdir(exist_ok=True)
        self.sock = self.root / "jobs.sock"
        self.proc: subprocess.Popen[bytes] | None = None

    def spawn_manager(self, root: Path | None = None) -> subprocess.Popen[bytes]:
        argv = [sys.executable, __file__, str(root or self.root), str(self.jobs)]
        return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def start(self) -> None:
        self.proc = self.spawn_manager()
        assert until(lambda: self._ping() is not None, 20), "manager did not publish"

    def _ping(self) -> dict[str, Any] | None:
        with suppress(Err):
            return client().ping(self.sock)
        return None

    def run(self, command: str, wait: float = 0.2) -> Any:
        kw: dict[str, Any] = {"workdir": self.work, "stdin": None, "call_id": "e2e"}
        return client().start(self.sock, command=command, wait_seconds=wait, **kw)

    def stop_manager(self) -> int:
        assert self.proc is not None
        self.proc.send_signal(signal.SIGTERM)
        code = self.proc.wait(20)
        self.proc = None
        return code

    def kill_manager(self) -> None:
        assert self.proc is not None
        self.proc.kill()
        self.proc.communicate(timeout=5)
        self.proc = None


@pytest.fixture
def stack() -> Iterator[Stack]:
    with tempfile.TemporaryDirectory(prefix="r4-j5-", dir="/tmp") as value:
        env = Stack(Path(value).resolve())
        pgids: list[int] = []
        env.pgids = pgids  # type: ignore[attr-defined]
        try:
            yield env
        finally:
            if env.proc is not None and env.proc.poll() is None:
                env.proc.kill()
                env.proc.communicate(timeout=5)
            for pgid in pgids:
                with suppress(ProcessLookupError):
                    os.killpg(pgid, signal.SIGKILL)


def track(stack: Stack, job_id: str) -> int:
    pgid = int(meta_of(stack.jobs, job_id)["pgid"])
    stack.pgids.append(pgid)  # type: ignore[attr-defined]
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
    stack.kill_manager()
    assert not group_gone(pgid)  # the orphaned leader survives its manager
    stack.start()  # a new incarnation recovers the spool, owning nothing
    meta = meta_of(stack.jobs, job["job_id"])
    assert (meta["authority"], meta["exit_code"], meta["signal"]) == (
        "UNKNOWN",
        None,
        None,
    )
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
    assert stack.stop_manager() == 0
    assert group_gone(pgid)
    meta = meta_of(stack.jobs, job["job_id"])
    assert (meta["signal"], meta["termination_reason"]) == (15, "owner_restart")
    assert "authority" not in meta and not marker.exists()


@NATIVE
def test_log_cursor_survives_a_client_restart(stack: Stack) -> None:
    # An MCP restart is only a new client; the manager keeps the spool and job.
    stack.start()
    job = stack.run("echo one; sleep 1; echo two", wait=0.0)
    track(stack, job["job_id"])
    assert until(
        lambda: (stack.jobs / job["job_id"] / "out.log").read_text() == "one\n"
    )
    first, cursor = job_store.read_log_range(stack.jobs, job["job_id"], 0, 4096)
    assert (first, cursor) == (b"one\n", 4)
    assert client().ping(stack.sock)["pid"] == stack.proc.pid  # type: ignore[union-attr]
    assert until(lambda: meta_of(stack.jobs, job["job_id"]).get("exit_code") == 0)
    rest, end = job_store.read_log_range(stack.jobs, job["job_id"], cursor, 4096)
    assert (rest, end) == (b"two\n", 8)


@NATIVE
def test_peer_and_generation_refusals_never_dispatch(stack: Stack) -> None:
    stack.start()
    auth = stack.sock.with_name("jobs.sock.auth")
    original = auth.read_bytes()
    auth.write_text(json.dumps({**json.loads(original), "key": "0" * 64}))
    with pytest.raises(Err, match=pc.JOB_MANAGER_UNAVAILABLE):
        stack.run(f"touch {stack.work / 'x'}")
    auth.write_bytes(original)
    other = svc.DarwinJobClient(label=LABEL + ".other", error_type=Err)
    with pytest.raises(Err, match=pc.JOB_MANAGER_UNAVAILABLE):
        other.ping(stack.sock)  # label mismatch is refused before any bytes
    with pytest.raises(NativeCapabilityError, match="generation_mismatch"):
        discover_service_lease(root=stack.root, label=LABEL + ".other")
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
        assert (
            victim.poll() is None
        )  # a live pid on disk or in the table grants nothing
    finally:
        owner.close()
        victim.kill()
        victim.wait(5)


# --- needs J4's tool wiring (job_status/stop_job/run_command over MCP) --------


class McpStack:
    """`binnacle serve` on a private 127.0.0.1 port over the manager's runtime dir."""

    def __init__(self, stack: Stack, port: int) -> None:
        self.stack, self.port = stack, port
        self.token = "Bearer " + secrets.token_hex(16)  # file is the header value
        self.proc: subprocess.Popen[bytes] | None = None
        home = stack.root.parent / "home"
        (home / ".config/binnacle").mkdir(parents=True)
        (home / ".config/binnacle/token").write_text(self.token)
        cfg = home / ".config/binnacle/config.toml"
        cfg.write_text(
            f'[roots]\ndefault_root = "{stack.work}"\n'
            f'[auth]\ntoken_file = "{home}/.config/binnacle/token"\n'
            f'[serve]\nhost = "127.0.0.1"\nport = {port}\n[jobs]\ndir = "{stack.jobs}"\n'
        )
        self.env = {"PATH": os.environ["PATH"], "HOME": str(home)}
        self.env["BINNACLE_CONFIG_FILE"] = str(cfg)
        self.env["BINNACLE_RUNTIME_DIR"] = str(stack.root)

    def start(self) -> None:
        argv = [sys.executable, "-m", "binnacle", "serve", "--host", "127.0.0.1"]
        argv += ["--port", str(self.port)]
        self.proc = subprocess.Popen(
            argv, env=self.env, cwd=str(self.stack.work), start_new_session=True
        )
        assert until(self._listening, 30), "MCP server did not listen"

    def _listening(self) -> bool:
        with suppress(OSError):
            socket.create_connection(("127.0.0.1", self.port), 0.2).close()
            return True
        return False

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            self.proc.wait(20)
            self.proc = None

    def _post(self, head: dict[str, str], body: dict[str, Any]) -> tuple[Any, str]:
        url = f"http://127.0.0.1:{self.port}/mcp"
        request = urllib.request.Request(url, json.dumps(body).encode(), head)
        with urllib.request.urlopen(request, timeout=120) as reply:
            return reply.headers, reply.read().decode()

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        head = {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }
        head["Accept"] = "application/json, text/event-stream"
        client_info = {"name": "r4-j5", "version": "0"}
        init = {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": client_info,
        }
        seen, _ = self._post(head, rpc(1, "initialize", init))
        head["mcp-session-id"] = seen.get("mcp-session-id") or ""
        self._post(head, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _, text = self._post(
            head, rpc(2, "tools/call", {"name": tool, "arguments": args})
        )
        data = [line[5:] for line in text.splitlines() if line.startswith("data:")]
        return dict(json.loads(data[-1] if data else text)["result"])


def rpc(ident: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "method": method, "params": params}


J4_REASONS = {
    "test_mcp_wait_expiry_continues": "run_command wait expiry must yield a durable job_id",
    "test_mcp_background_and_auto_background": "background=true must reach the manager",
    "test_mcp_cursor_across_mcp_restart": "job_status cursor over the manager spool",
    "test_mcp_stop_job_term_then_kill": "stop_job must delegate to the manager",
    "test_mcp_manager_kill_is_unknown": "job_status must render authority=UNKNOWN as unknown",
    "test_mcp_peer_refusal_fails_closed": "run_command must fail closed on manager refusal",
}


@pytest.fixture
def mcp(stack: Stack, request: pytest.FixtureRequest) -> Iterator[McpStack]:
    need("J4", J4_REASONS[request.node.name])
    stack.start()
    server = McpStack(stack, 18000 + os.getpid() % 1000)
    server.start()
    try:
        yield server
    finally:
        server.stop()


def sc(result: dict[str, Any]) -> dict[str, Any]:
    return dict(result.get("structuredContent") or {})


def test_mcp_wait_expiry_continues(mcp: McpStack) -> None:
    marker = mcp.stack.work / "marker"
    reply = sc(
        mcp.call(
            "run_command", {"command": f"sleep 2; touch {marker}", "wait_seconds": 1}
        )
    )
    assert reply["state"] == "running" and reply["job_id"]
    assert until(marker.exists, 10)
    status = sc(mcp.call("job_status", {"job_id": reply["job_id"], "wait_seconds": 5}))
    assert (status["state"], status["exit_code"]) == ("exited", 0)


def test_mcp_background_and_auto_background(mcp: McpStack) -> None:
    slow = sc(mcp.call("run_command", {"command": "sleep 3", "background": True}))
    assert slow["state"] == "running" and slow["background_job"] is True
    fast = sc(mcp.call("run_command", {"command": "echo hi", "background": True}))
    assert fast["state"] == "exited" and fast["output"].strip() == "hi"
    # auto_background_patterns (J4 settings key, as in the R4 evidence config) is
    # exercised by the Pi-parity auto_bg rerun against the same candidate.


def test_mcp_cursor_across_mcp_restart(mcp: McpStack) -> None:
    job = sc(
        mcp.call(
            "run_command", {"command": "echo a; sleep 2; echo b", "background": True}
        )
    )
    first = sc(mcp.call("job_status", {"job_id": job["job_id"], "cursor": "start"}))
    mcp.stop()
    mcp.start()  # an MCP restart does not own the job
    args = {"job_id": job["job_id"], "cursor": first["next_cursor"], "wait_seconds": 5}
    rest = sc(mcp.call("job_status", args))
    assert rest["state"] == "exited" and "b" in rest["output"]


def test_mcp_stop_job_term_then_kill(mcp: McpStack) -> None:
    command = "trap '' TERM; sleep 60"
    job = sc(mcp.call("run_command", {"command": command, "background": True}))
    assert sc(mcp.call("stop_job", {"job_id": job["job_id"]}))["state"] == "exited"
    assert sc(mcp.call("job_status", {"job_id": job["job_id"]}))["signal"] == 9


def test_mcp_manager_kill_is_unknown(mcp: McpStack) -> None:
    job = sc(mcp.call("run_command", {"command": "sleep 60", "background": True}))
    pgid = track(mcp.stack, job["job_id"])
    mcp.stack.kill_manager()
    mcp.stack.start()
    status = sc(mcp.call("job_status", {"job_id": job["job_id"]}))
    assert status["state"] == "unknown" and status.get("exit_code") is None
    assert mcp.call("stop_job", {"job_id": job["job_id"]}).get("isError")
    assert not group_gone(pgid)  # no adoption


def test_mcp_peer_refusal_fails_closed(mcp: McpStack) -> None:
    auth = mcp.stack.sock.with_name("jobs.sock.auth")
    original = auth.read_bytes()
    auth.write_text(json.dumps({**json.loads(original), "key": "0" * 64}))
    refused = mcp.call("run_command", {"command": "touch x", "background": True})
    auth.write_bytes(original)
    assert refused.get("isError") and not (mcp.stack.work / "x").exists()


# --- needs J3's launchd plist for the jobs manager ---------------------------


def test_launchd_user_label_runs_the_jobs_manager_on_a_test_port() -> None:
    need(
        "J3", "BINNACLE_J5_J3_PLIST must name the rendered com.binnacle.r4test.* plist"
    )
    plist = Path(os.environ["BINNACLE_J5_J3_PLIST"])
    label = plistlib.loads(plist.read_bytes())["Label"]
    assert label.startswith("com.binnacle.r4test."), "never the production label"
    domain, target = f"gui/{os.getuid()}", f"gui/{os.getuid()}/{label}"
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    try:
        probe = ["launchctl", "print", target]
        ok = lambda: (
            subprocess.run(probe, capture_output=True, check=False).returncode == 0
        )
        assert until(ok, 10)
    finally:
        subprocess.run(["launchctl", "bootout", domain, str(plist)], check=False)


if __name__ == "__main__":
    raise SystemExit(_manager_main(Path(sys.argv[1]), Path(sys.argv[2])))
