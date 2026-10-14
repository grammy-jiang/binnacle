"""Out-of-band Issue #30 transaction coordinator, without a native actuator.

This is deliberately NOT an MCP command, launchd service, scheduler, CLI
or production opt-in. The controller orders independently verified witnesses,
holds the existing J7 locks, uses the actual durable journal and BZ2 finalizer,
and ensures bounded restoration before releasing Watchdog/Jobs fences.

The provided executor is untrusted until a separately privileged native
helper authenticates the controller, exact installed root:wheel service,
guardian generation and old-inode FD census. There is NO default executor;
a test-owned executor is permitted only with explicit injection. Calling this
controller never by itself authorizes production bootout or raw-log deletion.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from binnacle.companions.darwin_log_archive_finalize import (
    FinalizedArchive,
    FinalizeMilestones,
    WriterHold,
    finalize_archive,
)
from binnacle.companions.darwin_log_j7_interlocks import J7Interlocks
from binnacle.companions.service_watchdog_maintenance import (
    confirmed_ack,
    release_pause,
    request_pause,
)

_NONCE = re.compile(r"^[0-9a-f]{32}$")
_LABELS = frozenset(
    {
        "system/com.binnacle.mcp",
        "system/com.binnacle.jobs",
        "system/com.binnacle.tunnel",
        "system/com.binnacle.service-watchdog",
        "system/com.binnacle.resource-monitor",
    }
)


class ControllerRefused(RuntimeError):
    """No successful authorization or quiescence can be inferred."""


@dataclass(frozen=True)
class ProducerPin:
    label: str
    pid: int
    generation: str
    device: int
    inode: int

    def __post_init__(self) -> None:
        if (
            self.label not in _LABELS
            or type(self.pid) is not int
            or self.pid <= 0
            or not isinstance(self.generation, str)
            or _NONCE.fullmatch(self.generation) is None
            or type(self.device) is not int
            or self.device <= 0
            or type(self.inode) is not int
            or self.inode <= 0
        ):
            raise ControllerRefused("untrusted pinned producer generation")


@dataclass(frozen=True)
class StepReceipt:
    """External proof is an opaque SHA256; this wrapper never authenticates it."""

    nonce: str
    digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.nonce, str)
            or _NONCE.fullmatch(self.nonce) is None
            or not isinstance(self.digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.digest) is None
        ):
            raise ControllerRefused("malformed independent transaction receipt")


@dataclass(frozen=True)
class QuiescenceReceipt(StepReceipt):
    in_flight: int = 0
    unknown: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            type(self.in_flight) is not int
            or type(self.unknown) is not int
            or self.in_flight != 0
            or self.unknown != 0
        ):
            raise ControllerRefused("active or unknown operations bar maintenance")


@dataclass(frozen=True)
class GuardianReceipt(StepReceipt):
    pid: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if type(self.pid) is not int or self.pid <= 0:
            raise ControllerRefused("guardian readiness incarnation unprovable")


class _JournalSnapshot(Protocol):
    nonce: str
    target: str
    revision: int
    phase: str


class _Journal(Protocol):
    def __enter__(self) -> _Journal: ...  # noqa: PYI034 - Python 3.10
    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def begin(
        self,
        *,
        nonce: str,
        controller_generation: str,
        target: str,
        producer_pid: int,
        producer_generation: str,
        source_dev: int,
        source_ino: int,
    ) -> _JournalSnapshot: ...

    def advance(
        self,
        *,
        nonce: str,
        expected_revision: int,
        phase: str,
        receipt_digest: str,
    ) -> _JournalSnapshot: ...


class TransactionExecutor(Protocol):
    """All external effects are an explicit, separately authenticated adapter.

    There is NO installed/default implementation. These methods are NOT
    authentication by virtue of satisfying this Python protocol.
    """

    def pin(self) -> ProducerPin: ...
    def witness_watchdog(self, nonce: str) -> int: ...
    def fence_mcp(self, nonce: str) -> QuiescenceReceipt: ...
    def fence_jobs(self, nonce: str) -> QuiescenceReceipt: ...
    def release_jobs(self, nonce: str) -> None: ...
    def arm_guardian(self, nonce: str, producer: ProducerPin) -> GuardianReceipt: ...
    def stop_writer(self, producer: ProducerPin) -> StepReceipt: ...
    def prove_writers_closed(self, producer: ProducerPin) -> QuiescenceReceipt: ...
    def writer_hold(self, producer: ProducerPin) -> WriterHold: ...
    def restore_writer(self, producer: ProducerPin) -> StepReceipt: ...
    def verify_mcp_resumed(self, nonce: str) -> StepReceipt: ...
    def disarm_guardian(self, nonce: str) -> None: ...


@dataclass(frozen=True)
class TransactionResult:
    nonce: str
    archive: FinalizedArchive
    phase: str
    production_authorized: bool = False

    def __post_init__(self) -> None:
        if self.production_authorized or self.phase != "complete":
            raise ValueError("transaction result never grants production authority")


def _require(receipt: StepReceipt, nonce: str) -> str:
    if not isinstance(receipt, StepReceipt) or receipt.nonce != nonce:
        raise ControllerRefused("unowned or unverifiable phase acknowledgement")
    return receipt.digest


def _require_quiet(receipt: QuiescenceReceipt, nonce: str) -> str:
    # The neutral StepReceipt cannot prove a drained MCP request set or
    # zero active/UNKNOWN Jobs. A claim of quiescence must be typed and
    # validated even when an injected executor violates its Protocol.
    if not isinstance(receipt, QuiescenceReceipt):
        raise ControllerRefused("unverified MCP/Jobs quiet-window receipt")
    return _require(receipt, nonce)


def run_maintenance_transaction(
    *,
    j7_root: Path,
    watchdog_root: Path,
    journal: _Journal,
    archive_root: Path,
    raw_name: str,
    executor: TransactionExecutor,
    nonce: str,
    controller_generation: str,
    watchdog_timeout_s: float = 60.0,
    min_free_bytes: int = 100 * 1024**3,
) -> TransactionResult:
    """One bounded ordered transaction, restoring service before releasing locks.

    The external executor must be an *out-of-band* controller, not a callable
    reachable through the MCP process it may stop. The finalizer still owns
    all raw-source/Archive inode and disk-safety checks. This function can
    only sequence a separately authenticated executor; it is NOT an
    authorization boundary by itself.
    """
    if (
        not isinstance(nonce, str)
        or _NONCE.fullmatch(nonce) is None
        or not isinstance(controller_generation, str)
        or _NONCE.fullmatch(controller_generation) is None
        or nonce == controller_generation
        or type(min_free_bytes) is not int
        or min_free_bytes < 0
        or not isinstance(watchdog_timeout_s, (int, float))
        or isinstance(watchdog_timeout_s, bool)
        or not 1 <= watchdog_timeout_s <= 120
        or not j7_root.is_absolute()
        or not watchdog_root.is_absolute()
        or not archive_root.is_absolute()
    ):
        raise ControllerRefused("untrusted transaction invocation")

    pinned = executor.pin()
    if not isinstance(pinned, ProducerPin):
        raise ControllerRefused("producer identity not pinned")
    from binnacle.companions.darwin_log_archive_finalize import _PRODUCERS

    if _PRODUCERS.get(raw_name.rsplit(".", 1)[0]) != pinned.label:
        raise ControllerRefused("source not owned by specified writer")

    with journal:
        current = journal.begin(
            nonce=nonce,
            controller_generation=controller_generation,
            target=pinned.label,
            producer_pid=pinned.pid,
            producer_generation=pinned.generation,
            source_dev=pinned.device,
            source_ino=pinned.inode,
        )

        def advance(phase: str, digest: str) -> None:
            nonlocal current
            if (
                current.nonce != nonce
                or current.target != pinned.label
                or current.phase == "complete"
            ):
                raise ControllerRefused("journal owner changed during transaction")
            current = journal.advance(
                nonce=nonce,
                expected_revision=current.revision,
                phase=phase,
                receipt_digest=digest,
            )
            if current.phase != phase:
                raise ControllerRefused("journal failed to publish durable milestone")

        watch_requested = jobs_requested = guardian_armed = writer_stopped = False
        restored = False
        restore_attempted = False
        stop_confirmed = False
        outcome: FinalizedArchive | None = None

        def restore_and_verify() -> str:
            nonlocal restored, restore_attempted
            # A native bootstrap can succeed and lose its reply. The first
            # attempt's outcome is then UNKNOWN: retrying bootstraps may
            # duplicate live writers, so only the independent guardian may
            # reconcile a failed/ambiguous attempt.
            restore_attempted = True
            writer_receipt = _require(executor.restore_writer(pinned), nonce)
            # A restarted writer is not a healthy MCP generation until its
            # actual request admission reopens and authenticates freshly.
            # The previous gate remains fenced forever.
            admitted_receipt = _require(executor.verify_mcp_resumed(nonce), nonce)
            restored = True
            return hashlib.sha256(
                (nonce + "|" + writer_receipt + "|" + admitted_receipt).encode()
            ).hexdigest()

        # A crash after stopping this producer cannot be repaired by a Python
        # finally: an independently owned READY guardian must already exist.
        # All fixture-SIGKILL tests additionally prove this out-of-process.
        with J7Interlocks(j7_root) as interlock:
            try:
                interlock.verify()
                advance(
                    "j7_locked",
                    hashlib.sha256(
                        (nonce + "|" + "j7" + "|" + str(os.getpid())).encode()
                    ).hexdigest(),
                )

                request_pause(
                    watchdog_root,
                    nonce=nonce,
                    until=time.time() + float(watchdog_timeout_s),
                )
                watch_requested = True
                wd_pid = executor.witness_watchdog(nonce)
                if (
                    type(wd_pid) is not int
                    or wd_pid <= 0
                    or not confirmed_ack(
                        watchdog_root, nonce=nonce, watchdog_pid=wd_pid
                    )
                ):
                    raise ControllerRefused("watchdog incarnation ACK unprovable")
                advance(
                    "watchdog_acked",
                    hashlib.sha256(
                        (nonce + "|" + "watchdog" + "|" + str(wd_pid)).encode()
                    ).hexdigest(),
                )
                interlock.verify()

                advance("mcp_drained", _require_quiet(executor.fence_mcp(nonce), nonce))
                jobs_requested = True
                advance(
                    "jobs_drained", _require_quiet(executor.fence_jobs(nonce), nonce)
                )
                interlock.verify()

                guardian = executor.arm_guardian(nonce, pinned)
                if not isinstance(guardian, GuardianReceipt):
                    raise ControllerRefused("independent guardian not ready")
                guardian_armed = True
                advance("guardian_armed", _require(guardian, nonce))
                interlock.verify()

                # Guard all remaining work by the real, exact owner.
                writer_stopped = True  # an unknown stop outcome demands guardian
                stopped_receipt = _require(executor.stop_writer(pinned), nonce)
                stop_confirmed = True
                advance("producer_stopped", stopped_receipt)
                advance(
                    "writer_fds_closed",
                    _require(executor.prove_writers_closed(pinned), nonce),
                )

                hold = executor.writer_hold(pinned)

                def canonical_verified(record: FinalizedArchive) -> None:
                    advance("canonical_verified", record.sha256)

                def raw_pruned(record: FinalizedArchive) -> None:
                    advance("raw_pruned", record.sha256)

                outcome = finalize_archive(
                    archive_root,
                    raw_name,
                    hold=hold,
                    min_free_bytes=min_free_bytes,
                    milestones=FinalizeMilestones(
                        canonical_verified=canonical_verified,
                        raw_pruned=raw_pruned,
                    ),
                )
                interlock.verify()
                # Both the new writer AND newly admitting MCP incarnation
                # must be proven before the transaction can become complete.
                restored_receipt = restore_and_verify()
                advance("producer_restored", restored_receipt)
                executor.disarm_guardian(nonce)
                guardian_armed = False
            finally:
                if (
                    writer_stopped
                    and stop_confirmed
                    and not restored
                    and not restore_attempted
                ):
                    # Only a confirmed stop with NO preceding restore attempt
                    # permits the single in-process recovery attempt. An
                    # unknown restore outcome is delegated to the independent
                    # guardian; never blindly launch the writer twice.
                    try:
                        restore_and_verify()
                    except Exception:  # noqa: BLE001 - guardian keeps UNKNOWN state
                        restored = False
                if jobs_requested and (restored or not writer_stopped):
                    executor.release_jobs(nonce)
                    jobs_requested = False
                if watch_requested and (restored or not writer_stopped):
                    release_pause(watchdog_root, nonce=nonce)
                    watch_requested = False
                if guardian_armed and restored:
                    executor.disarm_guardian(nonce)
                    guardian_armed = False

        if not restored or jobs_requested or watch_requested or guardian_armed:
            raise ControllerRefused("service restoration or barrier release incomplete")
        if outcome is None:
            raise ControllerRefused("archive finalization incomplete")
        advance(
            "complete",
            hashlib.sha256(
                (nonce + "|" + "complete" + "|" + outcome.sha256).encode()
            ).hexdigest(),
        )
        return TransactionResult(nonce, outcome, current.phase)
