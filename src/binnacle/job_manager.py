"""Stable local owner for ``run_command`` processes.

The FastMCP service may reload or restart independently. This manager is a sibling
systemd user service and owns the ``Popen`` wait/reaper lifecycle for commands.
"""

from __future__ import annotations

import json
import logging
import os
import socketserver
import subprocess
import uuid
from pathlib import Path
from typing import Any, cast

from binnacle import jobs
from binnacle.callctx import current_call
from binnacle.config import get_settings
from binnacle.job_client import PROTOCOL_VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("binnacle.job_manager")


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        manager = cast(JobManager, self.server.manager)  # type: ignore[attr-defined]
        try:
            raw = self.rfile.readline()
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise TypeError("request must be a JSON object")
            response = manager.dispatch(request)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            response = {"ok": False, "error": f"invalid job-manager request: {exc}"}
        self.wfile.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")


class JobManager:
    def __init__(
        self,
        socket_path: Path,
        *,
        owner_instance_id: str | None = None,
        boot_id: str | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.owner_instance_id = owner_instance_id or uuid.uuid4().hex
        self.boot_id = boot_id or _boot_id()
        self.server: _ThreadingUnixServer | None = None

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("version") != PROTOCOL_VERSION:
            return {"ok": False, "error": "unsupported job-manager protocol version"}
        op = request.get("op")
        if op == "ping":
            return {
                "ok": True,
                "version": PROTOCOL_VERSION,
                "owner_instance_id": self.owner_instance_id,
                "boot_id": self.boot_id,
            }
        if op == "start":
            return self._start(request)
        if op == "stop":
            return self._stop(request)
        return {"ok": False, "error": f"unknown job-manager operation {op!r}"}

    def _start(self, request: dict[str, Any]) -> dict[str, Any]:
        command = request["command"]
        workdir = Path(request["workdir"])
        stdin = request.get("stdin")
        wait_seconds = float(request.get("wait_seconds", 0.0))
        call_id = str(request.get("call_id") or "-")
        if not isinstance(command, str) or not isinstance(stdin, (str, type(None))):
            raise TypeError("command/stdin have invalid types")
        if wait_seconds < 0 or wait_seconds > get_settings().run_command.wait_max_s:
            raise ValueError("wait_seconds outside manager bounds")

        token = current_call.set(call_id)
        try:
            job_id, proc = jobs.start_job(
                command,
                workdir,
                stdin,
                owner_instance_id=self.owner_instance_id,
                boot_id=self.boot_id,
            )
        except OSError as exc:
            return {"ok": False, "error": f"could not start job: {exc}"}
        finally:
            current_call.reset(token)

        try:
            proc.wait(timeout=wait_seconds)
            jobs.record_exit(job_id, proc)
        except subprocess.TimeoutExpired:
            jobs.reap_in_background(job_id, proc)
        state = jobs.job_state(job_id)
        return {
            "ok": True,
            "job_id": job_id,
            "state": state["state"] if state else "unknown",
        }

    def _stop(self, request: dict[str, Any]) -> dict[str, Any]:
        job_id = request["job_id"]
        if not isinstance(job_id, str):
            raise TypeError("job_id must be a string")
        jobs.mark_stop_requested(job_id)
        state = jobs.stop_job_embedded(job_id)
        if state is None:
            return {"ok": False, "error": f"no job with id {job_id!r}"}
        return {"ok": True, "job_id": job_id, "state": state["state"]}

    def prepare(self) -> int:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        recovered = jobs.recover_previous_owner(self.owner_instance_id, self.boot_id)
        return recovered

    def serve_forever(self) -> None:
        recovered = self.prepare()
        server = _ThreadingUnixServer(str(self.socket_path), _Handler)
        server.manager = self  # type: ignore[attr-defined]
        self.server = server
        os.chmod(self.socket_path, 0o600)
        log.info(
            "event=job_manager_start pid=%d owner=%s boot=%s recovered=%d socket=%s",
            os.getpid(),
            self.owner_instance_id[:12],
            self.boot_id,
            recovered,
            self.socket_path,
        )
        try:
            server.serve_forever(poll_interval=0.1)
        finally:
            server.server_close()
            self.server = None
            self.socket_path.unlink(missing_ok=True)

    def shutdown(self) -> None:
        if self.server is not None:
            self.server.shutdown()


def main() -> None:
    settings = get_settings()
    JobManager(settings.jobs.socket_path).serve_forever()


if __name__ == "__main__":
    main()
