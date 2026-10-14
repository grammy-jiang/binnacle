"""Disposable Issue #30 controller adapter; NOT a native installed actuator.

All process and file operations here belong to pytest's temp fixture only.
This connects the reusable controller to real source/archive/J7/watchdog,
durable journal and fake Jobs Manager start/ping interfaces.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from binnacle.companions.darwin_log_archive_finalize import (
    ArchiveFinalizeRefused,
)
from binnacle.companions.darwin_log_transaction_controller import (
    GuardianReceipt,
    ProducerPin,
    QuiescenceReceipt,
    StepReceipt,
)
from binnacle.companions.service_watchdog_maintenance import (
    WatchdogMaintenanceFence,
)
from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain
from binnacle.platform.darwin.job_manager_maintenance_fence import ManagerStartFence
from binnacle.platform.darwin.job_manager_service import PROTOCOL_VERSION
from tests.issue30_full_transaction_fixture import (
    FixtureProducer,
    _durable_disarm,
    _open_guardian,
)
from tests.issue30_rehearsal_support import (
    _release_jobs,
    _request_jobs,
)
from tests.platform.darwin.test_job_manager_maintenance_fence import _manager

RAW = "mcp.stderr.log.0"
PRODUCER = "system/com.binnacle.mcp"


class FixtureHold:
    producer = PRODUCER

    def __init__(self, root: Path, owner: FixtureProducer, pin: ProducerPin) -> None:
        self.root = root
        self.owner = owner
        self.pin = pin
        self.held = False
        self.verified = 0

    def __enter__(self) -> FixtureHold:  # noqa: PYI034 - Python 3.10
        if (
            self.held
            or self.owner.original is None
            or self.owner.original.poll() is None
        ):
            raise ArchiveFinalizeRefused("fixture writer not stopped")
        self.held = True
        return self

    def verify(self, name: str, info: os.stat_result) -> None:
        if (
            name != RAW
            or not self.held
            or self.owner.original is None
            or self.owner.original.poll() is None
            or (info.st_dev, info.st_ino) != (self.pin.device, self.pin.inode)
        ):
            raise ArchiveFinalizeRefused("fixture writer generation not proven")
        self.verified += 1

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.held = False


class TestControllerExecutor:
    """The only effects are on disposable writer and synthetic barriers."""

    def __init__(
        self,
        root: Path,
        *,
        failure: str | None = None,
        job_running: bool = False,
    ) -> None:
        self.root = root
        self.writer = FixtureProducer(root)
        self.writer.start_original()
        self.gate = ToolAdmissionDrain()
        self.manager, self.job_owner, _root = _manager(root)
        fence = ManagerStartFence(
            root / "manager-pause",
            owner_instance_id=self.manager.owner_instance_id,
            pid=os.getpid(),
        )
        self.manager.maintenance_fence = fence.refusal
        self.manager.maintenance_probe = lambda reply: fence.synchronized_ping(
            self.manager, reply
        )
        self.failure = failure
        self.job_running = job_running
        self.events: list[str] = []
        self.guardian: subprocess.Popen[str] | None = None
        self.holds: list[FixtureHold] = []
        self.jobs_paused = False
        self.restored = False

    def _step(self, name: str, nonce: str) -> StepReceipt:
        self.events.append(name)
        if name == self.failure:
            raise RuntimeError("fixture rejected step " + name)
        digest = hashlib.sha256(f"{nonce}:{name}".encode()).hexdigest()
        return StepReceipt(nonce=nonce, digest=digest)

    def pin(self) -> ProducerPin:
        original = self.writer.original
        assert original is not None
        path = self.root / "private-logs" / RAW
        info = path.stat()
        return ProducerPin(PRODUCER, original.pid, "c" * 32, info.st_dev, info.st_ino)

    def witness_watchdog(self, nonce: str) -> int:
        self._step("watchdog", nonce)
        WatchdogMaintenanceFence(self.root / "watchdog").poll()
        return os.getpid()

    def fence_mcp(self, nonce: str) -> QuiescenceReceipt:
        self._step("mcp", nonce)
        self.gate.fence(nonce=nonce, generation=self.gate.generation)
        snapshot = self.gate.wait_drained(nonce=nonce, timeout=0.025)
        return QuiescenceReceipt(
            nonce,
            hashlib.sha256(snapshot.generation.encode()).hexdigest(),
            in_flight=snapshot.in_flight,
            unknown=0,
        )

    def fence_jobs(self, nonce: str) -> QuiescenceReceipt:
        self._step("jobs", nonce)
        _request_jobs(self.manager, self.root, nonce)
        self.jobs_paused = True
        ping = self.manager.dispatch({"version": PROTOCOL_VERSION, "op": "ping"})
        if (
            ping.get("maintenance_admission") != {"state": "paused", "nonce": nonce}
            or ping.get("ok") is not True
        ):
            raise RuntimeError("fake manager failed transaction coherent ping")
        return QuiescenceReceipt(
            nonce,
            hashlib.sha256(str(ping["owner_instance_id"]).encode()).hexdigest(),
            in_flight=ping["running_jobs"],
            unknown=ping["unknown_jobs"],
        )

    def release_jobs(self, nonce: str) -> None:
        self.events.append("jobs_release")
        if self.jobs_paused:
            _release_jobs(self.manager, self.root, nonce)
            self.jobs_paused = False

    def arm_guardian(self, nonce: str, producer: ProducerPin) -> GuardianReceipt:
        self._step("guardian", nonce)
        self.guardian = _open_guardian(self.root)
        return GuardianReceipt(
            nonce,
            hashlib.sha256(str(self.guardian.pid).encode()).hexdigest(),
            pid=self.guardian.pid,
        )

    def stop_writer(self, producer: ProducerPin) -> StepReceipt:
        self._step("stop", self.root.name[-32:])
        self.writer.stop_original()
        return self._step("stopped", self.root.name[-32:])

    def prove_writers_closed(self, producer: ProducerPin) -> QuiescenceReceipt:
        nonce = self.root.name[-32:]
        evidence = self._step("fd", nonce)
        if self.writer.original is None or self.writer.original.poll() is None:
            raise RuntimeError("old fake writer still has writable FD")
        return QuiescenceReceipt(evidence.nonce, evidence.digest)

    def writer_hold(self, producer: ProducerPin) -> FixtureHold:
        holder = FixtureHold(self.root, self.writer, producer)
        self.holds.append(holder)
        return holder

    def restore_writer(self, producer: ProducerPin) -> StepReceipt:
        nonce = self.root.name[-32:]
        self._step("restore", nonce)
        if self.writer.active is None:
            self.writer.start_active()
        assert self.writer.active is not None
        assert self.writer.active.poll() is None
        self.restored = True
        return self._step("restored", nonce)

    def verify_mcp_resumed(self, nonce: str) -> StepReceipt:
        self._step("mcp_resumed", nonce)
        if self.writer.active is None or self.writer.active.poll() is not None:
            raise RuntimeError("no newly restored test writer generation")
        old = self.gate
        if old.snapshot().pause_nonce != nonce:
            raise RuntimeError("old MCP gate was not fenced")
        # The same generation may NEVER be unfenced. A fresh instance has a
        # distinct incarnation and newly admitting request gate.
        self.gate = ToolAdmissionDrain()
        if (
            self.gate.generation == old.generation
            or self.gate.snapshot().pause_nonce is not None
        ):
            raise RuntimeError("fresh MCP generation not safely admitting")
        return StepReceipt(
            nonce, hashlib.sha256(self.gate.generation.encode()).hexdigest()
        )

    def disarm_guardian(self, nonce: str) -> None:
        self.events.append("guardian_disarm")
        if self.guardian is not None:
            _durable_disarm(self.root)

    def close(self) -> None:
        self.writer.close()
        (self.root / "guardian-worker.stop").touch(exist_ok=True)
        if self.guardian is not None:
            self.guardian.wait(timeout=6)
            for stream in (self.guardian.stdout, self.guardian.stderr):
                if stream is not None:
                    stream.close()
