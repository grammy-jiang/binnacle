"""ONE complete Issue #30 maintenance transaction on owned synthetic services.

This is NOT a production controller. No installed launchd label, Mac socket,
real Binnacle Job or real log is touched. The synthetic writer is a separate
owned subprocess; a separate fixture guardian handles SIGKILL in fault tests.
The actual canonical .bz2 data-plane and merged J7/Watchdog/MCP/Jobs gates
are exercised together instead of only asserting separate unit mocks.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from binnacle.companions.darwin_log_archive_finalize import (
    FinalizedArchive,
    FinalizeMilestones,
    finalize_archive,
)
from binnacle.companions.darwin_log_j7_interlocks import J7Interlocks
from binnacle.companions.service_watchdog_maintenance import (
    WatchdogMaintenanceFence,
    confirmed_ack,
    release_pause,
    request_pause,
)
from binnacle.companions.service_watchdog_safety import active_jobs
from binnacle.mcp.tool_admission_drain import ToolAdmissionDrain
from binnacle.platform.darwin.job_manager_maintenance_fence import ManagerStartFence
from binnacle.platform.darwin.job_manager_service import PROTOCOL_VERSION
from binnacle.platform.darwin.log_maintenance_transaction import (
    JournalSnapshot,
    MaintenanceTransactionJournal,
)
from tests.issue30_rehearsal_support import (
    FixtureJobsManager,
    RehearsalRefused,
    _release_jobs,
    _request_jobs,
    _safe_fixture,
)

_SUFFIX = re.compile(r"^issue30-fixture-e2e-[0-9a-f]{32}$")
_RAW = "mcp.stderr.log.0"
_ACTIVE = "mcp.stderr.log"
_PRODUCER = "system/com.binnacle.mcp"


class FixtureProducer:
    """The test owns every writer PID, pipe and exact file it may touch."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.original: subprocess.Popen[str] | None = None
        self.active: subprocess.Popen[str] | None = None

    def _start(self, mode: str) -> subprocess.Popen[str]:
        filename = _RAW if mode == "raw" else _ACTIVE
        destination = self.root / "private-logs" / filename
        if not destination.exists():
            fd = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            os.close(fd)
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.issue30_e2e_writer_fixture",
                str(self.root),
                mode,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            close_fds=True,
        )
        assert proc.stdout is not None
        ready = proc.stdout.readline().strip()
        if ready != f"READY {proc.pid} {mode}" or proc.poll() is not None:
            proc.terminate()
            proc.communicate(timeout=3)
            raise RehearsalRefused("fixture writer could not start")
        return proc

    def start_original(self) -> None:
        if self.original is not None:
            raise RehearsalRefused("fixture producer already started")
        self.original = self._start("raw")

    def start_active(self) -> None:
        if self.active is not None:
            raise RehearsalRefused("fixture active writer generation already exists")
        self.active = self._start("active")
        record = self.root / "active-writer.json"
        fd = os.open(
            record, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        try:
            os.write(
                fd,
                json.dumps(
                    {"pid": self.active.pid, "nonce": self.root.name[-32:]}
                ).encode(),
            )
            os.fsync(fd)
        finally:
            os.close(fd)

    def stop_original(self) -> None:
        if self.original is None:
            raise RehearsalRefused("fixture producer has no original generation")
        self._stop(self.original)

    @staticmethod
    def _stop(proc: subprocess.Popen[str]) -> None:
        if proc.poll() is None:
            assert proc.stdin is not None
            proc.stdin.write("STOP\n")
            proc.stdin.flush()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired as exc:
                proc.terminate()  # only our fixture-owned subprocess
                proc.wait(timeout=3)
                raise RehearsalRefused("fixture writer did not release FD") from exc
        if proc.returncode != 0:
            raise RehearsalRefused("fixture writer returned an unknown status")
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def close(self) -> None:
        for proc in (self.original, self.active):
            if proc is not None and proc.poll() is None:
                self._stop(proc)


class StoppedFixtureHold:
    """Exact synthetic stop authority for the real archive finalizer."""

    producer = _PRODUCER

    def __init__(self, writer: FixtureProducer, root: Path, j7: J7Interlocks):
        self.writer, self.root, self.j7 = writer, root, j7
        self.held = False
        self.verified = 0

    def __enter__(self) -> StoppedFixtureHold:  # noqa: PYI034 - Py3.10
        if self.held or self.writer.original is None:
            raise RehearsalRefused("fixture writer hold not uniquely owned")
        if self.writer.original.poll() is None:
            raise RehearsalRefused("fixture producer still writing")
        self.j7.verify()
        self.held = True
        return self

    def verify(self, source: str, info: os.stat_result) -> None:
        self.j7.verify()
        if (
            source != _RAW
            or not self.held
            or self.writer.original is None
            or self.writer.original.poll() is None
            or self.writer.active is not None
        ):
            raise RehearsalRefused("fixture writer restart fence unprovable")
        current = (self.root / "private-logs" / _RAW).stat()
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise RehearsalRefused("fixture old log generation changed")
        self.verified += 1

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.held = False


@dataclass(frozen=True)
class FixtureCompleted:
    archive: FinalizedArchive
    journal: JournalSnapshot
    restored_pid: int
    guardian_outcome: str
    production_authorized: bool = False

    def __post_init__(self) -> None:
        if self.production_authorized or self.journal.production_authorized:
            raise ValueError("fixture cannot authorize real log pruning")


def setup_fixture(root: Path) -> None:
    """Create ONLY a root already reserved by a test under its temporary dir."""
    if (
        not root.is_absolute()
        or _SUFFIX.fullmatch(root.name) is None
        or root.exists()
        or os.getuid() == 0
    ):
        raise RehearsalRefused("unsafe e2e fixture root")
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    for name in ("j7-state", "watchdog", "manager-pause", "private-logs"):
        (root / name).mkdir(mode=0o700)
        (root / name).chmod(0o700)
    (root / "j7-state" / "j7").mkdir(mode=0o700)
    (root / "j7-state" / "j7").chmod(0o700)
    nonce = root.name.removeprefix("issue30-fixture-e2e-")
    (root / ("txn-" + nonce)).mkdir(mode=0o700)


def _open_guardian(root: Path) -> subprocess.Popen[str]:
    guardian = subprocess.Popen(
        [sys.executable, "-m", "tests.issue30_e2e_guardian_fixture", str(root)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        close_fds=True,
    )
    assert guardian.stdout is not None
    if guardian.stdout.readline().strip() != f"READY {guardian.pid}":
        guardian.terminate()
        guardian.communicate(timeout=3)
        raise RehearsalRefused("independent fixture guardian not ready")
    return guardian


def _guardian_outcome(root: Path, *, timeout: float = 5) -> str:
    deadline = time.monotonic() + timeout
    path = root / "guardian-outcome.json"
    while time.monotonic() < deadline:
        if path.exists():
            record = json.loads(path.read_bytes())
            return str(record["state"])
        time.sleep(0.03)
    raise RehearsalRefused("fixture guardian did not report restored state")


def _durable_disarm(root: Path) -> None:
    """A live test writer was restored; never spawn a second test writer."""
    fd = os.open(
        root / "guardian-disarm",
        os.O_WRONLY | os.O_EXCL | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.write(fd, b"synthetic writer confirmed running after refusal\n")
        os.fsync(fd)
    finally:
        os.close(fd)


def run_complete_fixture_transaction(
    root: Path,
    *,
    manager: FixtureJobsManager,
    mcp: ToolAdmissionDrain,
    writer: FixtureProducer,
    inject_failure: str | None = None,
    after_stop: Callable[[], None] | None = None,
    after_canonical_verified: Callable[[], None] | None = None,
    after_raw_unlink: Callable[[], None] | None = None,
    after_producer_restored: Callable[[], None] | None = None,
) -> FixtureCompleted:
    """Run real data-plane BZ2 publish/prune in the exact fixture gate order.

    A live guardian is armed before stopping the writer. Failures before/after
    unlink restore the *separate test writer* in finally and retain accurate
    incomplete journal evidence. Independent SIGKILL recovery is qualified in
    a separate subprocess test, not by relying on Python finally.
    """
    _safe_fixture(root, manager)
    nonce = root.name.removeprefix("issue30-fixture-e2e-")
    if _SUFFIX.fullmatch(root.name) is None or mcp.snapshot().pause_nonce is not None:
        raise RehearsalRefused("e2e fixture is not a fresh transaction")
    raw = root / "private-logs" / _RAW
    if writer.original is None or writer.original.poll() is not None:
        raise RehearsalRefused("fixture writer is not live")
    source = raw.stat()
    journal_root = root / ("txn-" + nonce)
    txn_generation = "b" * 32
    guardian: subprocess.Popen[str] | None = None
    finalized: FinalizedArchive | None = None
    snapshot: JournalSnapshot | None = None
    watchdog_armed = jobs_armed = producer_stopped = False

    def fail(point: str) -> None:
        if inject_failure == point:
            raise RehearsalRefused(f"synthetic failure at {point}")

    with MaintenanceTransactionJournal(journal_root) as txn:
        snapshot = txn.begin(
            nonce=nonce,
            controller_generation=txn_generation,
            target=_PRODUCER,
            producer_pid=writer.original.pid,
            producer_generation="c" * 32,
            source_dev=source.st_dev,
            source_ino=source.st_ino,
        )

        def advance(phase: str, proof: str) -> JournalSnapshot:
            nonlocal snapshot
            assert snapshot is not None
            digest = hashlib.sha256(
                (nonce + "|" + phase + "|" + proof).encode()
            ).hexdigest()
            snapshot = txn.advance(
                nonce=nonce,
                expected_revision=snapshot.revision,
                phase=phase,
                receipt_digest=digest,
            )
            return snapshot

        with J7Interlocks(root / "j7-state") as j7:
            fence = ManagerStartFence(
                root / "manager-pause",
                owner_instance_id=manager.owner_instance_id,
                pid=os.getpid(),
            )
            manager.maintenance_fence = fence.refusal
            manager.maintenance_probe = lambda reply: fence.synchronized_ping(
                manager, reply
            )
            try:
                j7.verify()
                advance("j7_locked", "fixture J7 locks verified")
                fail("j7_locked")
                request_pause(root / "watchdog", nonce=nonce, until=time.time() + 90)
                watchdog_armed = True
                WatchdogMaintenanceFence(root / "watchdog").poll()
                if not confirmed_ack(
                    root / "watchdog", nonce=nonce, watchdog_pid=os.getpid()
                ):
                    raise RehearsalRefused("fixture Watchdog pause missing")
                advance("watchdog_acked", "fixture watchdog incarnation confirmed")
                fail("watchdog_acked")

                mcp.fence(nonce=nonce, generation=mcp.generation)
                drain = mcp.wait_drained(nonce=nonce, timeout=0.05)
                if not drain.drained:
                    raise RehearsalRefused("fixture MCP not fully drained")
                advance("mcp_drained", mcp.generation)
                fail("mcp_drained")

                _request_jobs(manager, root, nonce)
                jobs_armed = True
                ping = manager.dispatch({"version": PROTOCOL_VERSION, "op": "ping"})
                if (
                    ping.get("ok") is not True
                    or ping.get("owner_instance_id") != manager.owner_instance_id
                    or ping.get("pid") != os.getpid()
                    or ping.get("maintenance_admission")
                    != {"state": "paused", "nonce": nonce}
                    or ping.get("running_jobs") != 0
                    or ping.get("unknown_jobs") != 0
                    or active_jobs(manager.jobs_dir) != 0
                ):
                    raise RehearsalRefused("fixture Jobs admission not drained")
                advance("jobs_drained", str(ping["owner_instance_id"]))
                fail("jobs_drained")

                guardian = _open_guardian(root)
                if guardian.poll() is not None:
                    raise RehearsalRefused("guardian exited before bootout")
                advance("guardian_armed", str(guardian.pid))
                fail("guardian_armed")

                producer_stopped = True
                writer.stop_original()
                if after_stop is not None:
                    after_stop()  # test-only subprocess crash injection
                if writer.original.poll() is None:
                    raise RehearsalRefused("fixture writer stop unverified")
                advance("producer_stopped", str(writer.original.pid))
                fail("producer_stopped")

                hold = StoppedFixtureHold(writer, root, j7)
                with hold:
                    hold.verify(_RAW, source)
                advance("writer_fds_closed", str(hold.verified))
                fail("writer_fds_closed")

                def canonical(info: FinalizedArchive) -> None:
                    advance("canonical_verified", info.sha256)
                    if after_canonical_verified is not None:
                        after_canonical_verified()
                    fail("canonical_verified")

                def pruned(info: FinalizedArchive) -> None:
                    # The archive core calls this only after unlink+fsync.
                    # Kill here to prove the journal conservatively stays
                    # at canonical_verified if this receipt was lost.
                    if after_raw_unlink is not None:
                        after_raw_unlink()
                    advance("raw_pruned", info.sha256)
                    fail("raw_pruned")

                finalized = finalize_archive(
                    root / "private-logs",
                    _RAW,
                    hold=hold,
                    min_free_bytes=0,
                    milestones=FinalizeMilestones(canonical, pruned),
                )
                fail("before_restore")
                writer.start_active()
                if writer.active is None or writer.active.poll() is not None:
                    raise RehearsalRefused("fixture new generation not ready")
                advance("producer_restored", str(writer.active.pid))
                if after_producer_restored is not None:
                    after_producer_restored()
                fail("producer_restored")
            finally:
                if producer_stopped:
                    if writer.active is None:
                        writer.start_active()
                    if writer.active is not None and writer.active.poll() is None:
                        _durable_disarm(root)
                elif (
                    guardian is not None
                    and writer.original is not None
                    and writer.original.poll() is None
                ):
                    # Controller declined maintenance after guardian ACK
                    # but BEFORE stopping its old fixture writer. Mark
                    # the still-live original to prevent a duplicate
                    # guardian restart if teardown later closes its pipe.
                    _durable_disarm(root)
                if jobs_armed:
                    _release_jobs(manager, root, nonce)
                if watchdog_armed:
                    release_pause(root / "watchdog", nonce=nonce)
        # Both J7 locks were released after producer restoration. A
        # successful transaction is now durably marked complete.
        if finalized is None or writer.active is None:
            raise RehearsalRefused("fixture finalization is not complete")
        advance("complete", "synthetic restart and all barriers released")

    if snapshot is None or finalized is None or writer.active is None:
        raise RehearsalRefused("fixture completion incomplete")
    outcome = _guardian_outcome(root)
    if guardian is not None:
        guardian.wait(timeout=4)
        for stream in (guardian.stdout, guardian.stderr):
            if stream is not None:
                stream.close()
    return FixtureCompleted(
        finalized,
        snapshot,
        writer.active.pid,
        outcome,
    )
