"""Benchmark-only historical H10 adapter and isolated-launcher primitives."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from binnacle.blocking_wall_guard import (
    BlockingDecision,
    BlockingLease,
    BlockingRelease,
)

HISTORICAL_BUDGET_S = 10
HISTORICAL_POLICY = "historical_one_shot"
HISTORICAL_EXHAUSTED_POLICY = "historical_one_shot_exhausted"
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MCP_INIT = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "phase4-endpoint-launcher", "version": "1"},
        },
    }
).encode()


class HistoricalOneShotTracker:
    """Allow one positive wait of at most ten seconds per client/base turn."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: set[tuple[str | None, str]] = set()
        self._active: dict[tuple[str | None, str], int] = {}

    def acquire(
        self,
        *,
        client: str | None,
        turn: str | None,
        requested_wait_s: int,
        bounded_wait_s: int,
        budget_s: int | None,
    ) -> BlockingLease:
        """Return a lease compatible with the job_status tracker contract."""
        del budget_s
        if turn is None:
            return self._untracked_lease(requested_wait_s, bounded_wait_s)

        key = (client, turn)
        with self._lock:
            active_before = self._active.get(key, 0)
            if key in self._seen:
                decision = BlockingDecision(
                    policy=HISTORICAL_EXHAUSTED_POLICY,
                    requested_wait_s=requested_wait_s,
                    bounded_wait_s=bounded_wait_s,
                    effective_wait_s=0,
                    budget_s=HISTORICAL_BUDGET_S,
                    spent_before_s=float(HISTORICAL_BUDGET_S),
                    remaining_before_s=0.0,
                    active_before=active_before,
                    blocking_budget_exhausted=True,
                )
                return BlockingLease(decision, self._exhausted_release(active_before))

            self._seen.add(key)
            effective_wait_s = max(0, min(bounded_wait_s, HISTORICAL_BUDGET_S))
            decision = BlockingDecision(
                policy=HISTORICAL_POLICY,
                requested_wait_s=requested_wait_s,
                bounded_wait_s=bounded_wait_s,
                effective_wait_s=effective_wait_s,
                budget_s=HISTORICAL_BUDGET_S,
                spent_before_s=0.0,
                remaining_before_s=float(HISTORICAL_BUDGET_S),
                active_before=active_before,
                blocking_budget_exhausted=False,
            )
            if effective_wait_s <= 0:
                return BlockingLease(decision, self._exhausted_release(active_before))
            started = self._clock()
            self._active[key] = active_before + 1
            return BlockingLease(
                decision,
                lambda: self._release_first(key, started, effective_wait_s),
            )

    def _release_first(
        self,
        key: tuple[str | None, str],
        started: float,
        effective_wait_s: int,
    ) -> BlockingRelease:
        with self._lock:
            active = self._active.get(key, 0)
            if active < 1:
                raise RuntimeError("historical one-shot active state is inconsistent")
            active -= 1
            if active:
                self._active[key] = active
            else:
                self._active.pop(key, None)
            elapsed = max(0.0, min(self._clock() - started, float(effective_wait_s)))
            return BlockingRelease(
                spent_after_s=float(HISTORICAL_BUDGET_S),
                remaining_after_s=0.0,
                active_after=active,
                window_closed=active == 0,
                window_wall_s=elapsed if active == 0 else None,
            )

    @staticmethod
    def _exhausted_release(active_after: int) -> Callable[[], BlockingRelease]:
        def release() -> BlockingRelease:
            return BlockingRelease(
                spent_after_s=float(HISTORICAL_BUDGET_S),
                remaining_after_s=0.0,
                active_after=active_after,
                window_closed=False,
                window_wall_s=None,
            )

        return release

    @staticmethod
    def _untracked_lease(requested_wait_s: int, bounded_wait_s: int) -> BlockingLease:
        decision = BlockingDecision(
            policy="no_turn",
            requested_wait_s=requested_wait_s,
            bounded_wait_s=bounded_wait_s,
            effective_wait_s=bounded_wait_s,
            budget_s=None,
            spent_before_s=None,
            remaining_before_s=None,
            active_before=0,
            blocking_budget_exhausted=False,
        )
        return BlockingLease(
            decision,
            lambda: BlockingRelease(None, None, 0, False, None),
        )


def install_historical_tracker() -> HistoricalOneShotTracker:
    """Install the H-only tracker before importing the benchmark MCP app."""
    from binnacle.tools import job_status as job_status_module

    tracker = HistoricalOneShotTracker()
    job_status_module.blocking_wall_tracker = cast(Any, tracker)
    return tracker


def serve(host: str, port: int) -> None:
    """Run the benchmark MCP server with the historical tracker installed."""
    install_historical_tracker()
    import uvicorn

    uvicorn.run(
        "binnacle.server:app",
        host=host,
        port=port,
        reload=False,
        loop="uvloop",
        http="httptools",
    )


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write private runtime JSON with mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        path.chmod(0o600)
    finally:
        temp.unlink(missing_ok=True)


def spawn(
    command: list[str], log_path: Path, env: dict[str, str], repo_root: Path
) -> subprocess.Popen[bytes]:
    """Spawn one isolated benchmark child with merged private logging."""
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        return subprocess.Popen(
            command,
            cwd=repo_root,
            env=env,
            stdout=fd,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        os.close(fd)


def start_ticks(pid: int) -> str | None:
    """Return Linux process start ticks for stale-PID protection."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return raw[raw.rfind(")") + 2 :].split()[19]
    except (OSError, IndexError):
        return None


def identity(pid: int) -> dict[str, Any]:
    ticks = start_ticks(pid)
    if ticks is None:
        raise RuntimeError(f"process {pid} exited before identity capture")
    return {"pid": pid, "start_time_ticks": ticks}


def _proc_words(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def _proc_env(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    result: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            result[key.decode(errors="replace")] = value.decode(errors="replace")
    return result


def process_matches(role: str, entry: dict[str, Any], repo_root: Path) -> bool:
    """Verify start identity, command, worktree and config before PID reuse."""
    identity_data = entry.get("process_start_identity", {}).get(role)
    pid = entry.get(f"{role}_pid")
    if not isinstance(identity_data, dict) or not isinstance(pid, int):
        return False
    if identity_data.get("pid") != pid or start_ticks(pid) != identity_data.get(
        "start_time_ticks"
    ):
        return False
    try:
        if Path(f"/proc/{pid}/cwd").resolve() != repo_root.resolve():
            return False
    except OSError:
        return False
    words = _proc_words(pid)
    joined = " ".join(words)
    if role == "manager":
        command_ok = "binnacle-jobs" in joined
    elif role == "server":
        port_ok = str(entry["port"]) in words
        marker = (
            "chat_scheduling_historical_guard.py"
            if entry["endpoint_id"] == "H"
            else "binnacle"
        )
        command_ok = (
            marker in joined
            and port_ok
            and (entry["endpoint_id"] == "H" or "serve" in words)
        )
    else:
        command_ok = "tunnel-client" in joined and entry["tunnel_profile"] in words
    return command_ok and (
        role == "tunnel"
        or _proc_env(pid).get("BINNACLE_CONFIG_FILE") == entry["config_path"]
    )


def port_in_use(host: str, port: int) -> bool:
    """Test whether a reserved address cannot be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def mcp_healthy(host: str, port: int, token_path: Path, timeout: float = 0.5) -> bool:
    """Probe authenticated MCP initialize without exposing the token."""
    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/mcp",
            data=_MCP_INIT,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": token_path.read_text(encoding="utf-8").strip(),
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def manager_healthy(socket_path: Path) -> bool:
    from binnacle.job_client import JobManagerError, ping

    try:
        ping(socket_path)
        return True
    except JobManagerError:
        return False


def wait_ready(
    predicate: Callable[..., bool],
    proc: subprocess.Popen[bytes],
    label: str,
    *args: object,
    timeout: float = 10.0,
) -> None:
    """Bound readiness and fail if the child exits first."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{label} exited during readiness")
        if predicate(*args):
            return
        time.sleep(0.1)
    raise RuntimeError(f"{label} did not become ready within {timeout:g}s")


def terminate(pid: int, timeout: float = 5.0) -> None:
    """Terminate only a previously verified benchmark process group."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if start_ticks(pid) is None:
            return
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def load_env(path: Path) -> dict[str, str]:
    """Load a simple deployment env file without logging secret values."""
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        if "=" not in line:
            raise RuntimeError(f"invalid environment line in {path}")
        key, value = line.split("=", 1)
        if not _ENV_KEY.fullmatch(key):
            raise RuntimeError(f"invalid environment key in {path}")
        parts = shlex.split(value, comments=False, posix=True)
        if len(parts) > 1:
            raise RuntimeError(f"invalid environment value for {key} in {path}")
        result[key] = parts[0] if parts else ""
    return result


def _main_probe_ok(value: Any) -> bool:
    if isinstance(value, dict):
        return (
            value.get("name") == "main" and value.get("probe_status") == "ok"
        ) or any(_main_probe_ok(item) for item in value.values())
    return isinstance(value, list) and any(_main_probe_ok(item) for item in value)


def tunnel_healthy(url_path: Path, old_mtime: int | None) -> bool:
    """Require a rewritten health URL, readyz and a healthy main MCP probe."""
    try:
        stat = url_path.stat()
        if old_mtime is not None and stat.st_mtime_ns == old_mtime:
            return False
        base = url_path.read_text(encoding="utf-8").strip().rstrip("/")
        with urllib.request.urlopen(f"{base}/readyz", timeout=1) as response:  # nosec B310
            if response.status != 200:
                return False
        with urllib.request.urlopen(f"{base}/api/status", timeout=1) as response:  # nosec B310
            return _main_probe_ok(json.load(response))
    except (OSError, ValueError, urllib.error.URLError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve(args.host, args.port)
        return 0
    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
