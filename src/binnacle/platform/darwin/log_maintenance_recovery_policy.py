"""Pure, advisory-only Issue #30 crash recovery classification.

There are intentionally NO operations that boot a producer, pause a
watchdog, acquire a live J7 lease, inspect process FDs or delete logs.
The policy analyzes an already verified on-disk JournalSnapshot and
optionally supplied observations. Raw observations are NOT authentication
evidence: a future controller must verify its own source/peer/generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from binnacle.platform.darwin.log_maintenance_transaction import JournalSnapshot

_GEN = re.compile(r"^[0-9a-f]{32}$")

RecoveryStatus = Literal[
    "unverifiable",
    "pre_stop_manual_review",
    "possible_outage_manual_review",
    "completion_record_manual_review",
]

RecoveryRisk = Literal[
    "journal_missing_or_untrusted",
    "journal_incomplete",
    "controller_terminated_before_completion",
    "producer_may_be_offline",
    "producer_absent_observed",
    "producer_identity_unverifiable",
    "producer_incarnation_changed",
    "producer_generation_changed",
    "source_inode_unverifiable",
    "source_inode_changed",
    "observation_not_authenticated",
    "watchdog_pause_unverified",
    "guardian_readiness_unverified",
    "mcp_activity_unverified",
    "mcp_calls_active",
    "jobs_activity_unverified",
    "jobs_running",
    "jobs_unknown",
    "source_writers_unverified",
    "source_writable_fds_open",
]


@dataclass(frozen=True)
class RecoveryReadings:
    """Optional facts supplied by future independently authenticated probes.

    This object cannot attest that its caller is trustworthy. It only
    influences conservative manual-review risks, never action authority.
    """

    authenticated: bool = False
    target: str | None = None
    producer_alive: bool | None = None
    producer_pid: int | None = None
    producer_generation: str | None = None
    source_dev: int | None = None
    source_ino: int | None = None
    watchdog_paused: bool | None = None
    guardian_ready: bool | None = None
    mcp_inflight: int | None = None
    jobs_running: int | None = None
    jobs_unknown: int | None = None
    source_writable_fds: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "mcp_inflight",
            "jobs_running",
            "jobs_unknown",
            "source_writable_fds",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be nonnegative integer or unknown")

        for name in ("producer_pid", "source_dev", "source_ino"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be positive integer or unknown")
        if self.producer_generation is not None and (
            not isinstance(self.producer_generation, str)
            or _GEN.fullmatch(self.producer_generation) is None
        ):
            raise ValueError("producer generation not a valid witness")
        for name in (
            "authenticated",
            "producer_alive",
            "watchdog_paused",
            "guardian_ready",
        ):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ValueError(f"{name} must be boolean or unknown")


@dataclass(frozen=True)
class RecoveryAssessment:
    """Safe diagnostic: there is no success value that permits live actions."""

    transaction_nonce: str | None
    phase: str | None
    status: RecoveryStatus
    risks: tuple[RecoveryRisk, ...]
    manual_review_required: bool = True
    production_authorized: bool = False
    autonomous_restart_allowed: bool = False

    def __post_init__(self) -> None:
        if (
            not self.manual_review_required
            or self.production_authorized
            or self.autonomous_restart_allowed
        ):
            raise ValueError("recovery assessment cannot authorize a live action")


def assess_recovery(
    snapshot: JournalSnapshot | None,
    readings: RecoveryReadings | None = None,
) -> RecoveryAssessment:
    """Classify a verified journal conservatively, never initiate recovery.

    A snapshot that is absent, incomplete, or inconsistent with runtime
    readings is a reason to stop and investigate. Even readings that look
    perfect do not provide a service ACL, transport authentication,
    privileged FD census, or authority to restore/prune a production log.
    """
    if snapshot is None:
        return RecoveryAssessment(
            None, None, "unverifiable", ("journal_missing_or_untrusted",)
        )
    if snapshot.production_authorized:
        # JournalSnapshot itself rejects this construction. Retain an
        # explicit boundary if another implementation supplies a subtype.
        raise ValueError("untrusted journal unexpectedly grants authority")

    risks: list[RecoveryRisk] = []
    status: RecoveryStatus
    if snapshot.phase == "complete":
        status = "completion_record_manual_review"
    elif snapshot.producer_may_be_stopped:
        status = "possible_outage_manual_review"
        risks.extend(
            (
                "journal_incomplete",
                "controller_terminated_before_completion",
                "producer_may_be_offline",
            )
        )
    else:
        status = "pre_stop_manual_review"
        if snapshot.needs_external_recovery:
            risks.extend(
                ("journal_incomplete", "controller_terminated_before_completion")
            )

    if readings is None or not readings.authenticated:
        risks.append("observation_not_authenticated")
        return RecoveryAssessment(
            snapshot.nonce, snapshot.phase, status, tuple(dict.fromkeys(risks))
        )

    if (
        readings.target != snapshot.target
        or readings.producer_alive is None
        or readings.producer_pid is None
    ):
        risks.append("producer_identity_unverifiable")
    else:
        if not readings.producer_alive:
            risks.append("producer_absent_observed")
        elif readings.producer_pid != snapshot.producer_pid:
            risks.append("producer_incarnation_changed")
        if readings.producer_generation is None:
            risks.append("producer_identity_unverifiable")
        elif readings.producer_generation != snapshot.producer_generation:
            risks.append("producer_generation_changed")

    if readings.source_dev is None or readings.source_ino is None:
        risks.append("source_inode_unverifiable")
    elif (
        readings.source_dev != snapshot.source_dev
        or readings.source_ino != snapshot.source_ino
    ):
        risks.append("source_inode_changed")

    if readings.watchdog_paused is not True:
        risks.append("watchdog_pause_unverified")
    if readings.guardian_ready is not True:
        risks.append("guardian_readiness_unverified")

    if readings.mcp_inflight is None:
        risks.append("mcp_activity_unverified")
    elif readings.mcp_inflight:
        risks.append("mcp_calls_active")

    if readings.jobs_running is None or readings.jobs_unknown is None:
        risks.append("jobs_activity_unverified")
    if readings.jobs_running is not None and readings.jobs_running > 0:
        risks.append("jobs_running")
    if readings.jobs_unknown is not None and readings.jobs_unknown > 0:
        risks.append("jobs_unknown")

    if readings.source_writable_fds is None:
        risks.append("source_writers_unverified")
    elif readings.source_writable_fds:
        risks.append("source_writable_fds_open")

    return RecoveryAssessment(
        snapshot.nonce, snapshot.phase, status, tuple(dict.fromkeys(risks))
    )
