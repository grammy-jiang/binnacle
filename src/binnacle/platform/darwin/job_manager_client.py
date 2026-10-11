"""Darwin ``job_client`` over A3 authenticated IPC: unchanged RPC v1 objects.

Messages and signatures equal ``binnacle.features.commands.job_client``; only
the A3 connect handshake is retried and a dispatched request is never replayed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.contracts.capability_contracts import (
    BudgetExceeded,
    NativeCapabilityError,
)
from binnacle.platform.darwin.job_manager_service import (
    MANAGER_LABEL,
    PROTOCOL_VERSION,
)


class DarwinJobManagerError(RuntimeError):
    """The manager could not accept or complete an ownership operation."""


class DarwinJobClient:
    """``job_client`` over A3: one channel per call; only connect is retried."""

    def __init__(
        self, *, label: str = MANAGER_LABEL, error_type: type[Exception] | None = None
    ) -> None:
        self.label, self.error_type = label, error_type

    def _error(self, message: str) -> Exception:
        return (self.error_type or DarwinJobManagerError)(message)

    def request(
        self, socket_path: Path, payload: dict[str, Any], *, timeout_s: float = 5.0
    ) -> dict[str, Any]:
        from binnacle.platform.darwin.generation_runtime import (
            discover_service_lease as discover,
        )
        from binnacle.platform.darwin.ipc_transport import connect_authenticated

        failure: Exception | None = None
        for _attempt in range(2):  # a rotated generation re-reads credentials
            try:
                root, name = socket_path.parent, socket_path.name
                lease = discover(root=root, label=self.label, name=name)
                channel = connect_authenticated(socket_path, lease=lease, timeout_s=5)
                break
            except (NativeCapabilityError, OSError) as exc:
                failure = exc
        else:
            code = getattr(failure, "code", type(failure).__name__)
            message = f"{pc.JOB_MANAGER_UNAVAILABLE} at {socket_path}: {code}"
            raise self._error(message) from failure
        try:  # a dispatched request is never replayed
            response = channel.request(payload, timeout_s=min(60.0, timeout_s))
        except BudgetExceeded as exc:  # job_client: the socket timeout text
            message = f"{pc.JOB_MANAGER_UNAVAILABLE} at {socket_path}: timed out"
            raise self._error(message) from exc
        except NativeCapabilityError as exc:
            message = "job manager closed the connection without a response"
            raise self._error(message) from exc
        finally:
            channel.close()
        if response.get("ok") is not True:
            error = response.get("error") or "job manager request failed"
            raise self._error(str(error))
        return dict(response)

    def ping(self, socket_path: Path) -> dict[str, Any]:
        return self.request(socket_path, {"version": PROTOCOL_VERSION, "op": "ping"})

    def start(
        self,
        socket_path: Path,
        *,
        command: str,
        workdir: Path,
        stdin: str | None,
        wait_seconds: float,
        call_id: str,
    ) -> dict[str, Any]:
        payload = {"version": PROTOCOL_VERSION, "op": "start", "command": command}
        payload.update(workdir=str(workdir), stdin=stdin, wait_seconds=wait_seconds)
        payload["call_id"] = call_id
        timeout = max(5.0, wait_seconds + 5.0)
        return self.request(socket_path, payload, timeout_s=timeout)

    def stop(
        self, socket_path: Path, job_id: str, *, call_id: str = "-"
    ) -> dict[str, Any]:
        payload = {"version": PROTOCOL_VERSION, "op": "stop", "job_id": job_id}
        payload["call_id"] = call_id
        return self.request(socket_path, payload, timeout_s=10.0)
