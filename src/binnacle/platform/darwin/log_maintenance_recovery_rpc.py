"""Dormant Issue #30 read-only recovery RPC over existing Darwin A3 authentication.

There is intentionally no executable entrypoint, startup hook, provisioning,
CLI, restart or archive action. The *only* operation is a bounded observation
of one trusted, preselected private transaction root. Native A3 authenticates
the peer and generation; neither RPC arguments nor reply flags grant authority
to mutate a Mac service or raw log.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.darwin.log_maintenance_observer import (
    inspect_unowned_transaction,
)
from binnacle.platform.darwin.log_maintenance_recovery_policy import (
    RecoveryAssessment,
    RecoveryRisk,
    RecoveryStatus,
    assess_recovery,
)
from binnacle.platform.darwin.log_maintenance_transaction import (
    _PHASES,
    MaintenanceJournalRefused,
)

_VERSION = 1
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_LABEL = "com.binnacle.log-maintenance-observer"
_ENDPOINT = "observe.sock"
_RUNTIME_NAME = "log-maintenance-observer-ipc"
_REQUEST_KEYS = frozenset({"version", "op", "nonce"})
_REPLY_KEYS = frozenset(
    {
        "version",
        "ok",
        "op",
        "nonce",
        "phase",
        "revision",
        "status",
        "risks",
        "manual_review_required",
        "production_authorized",
        "autonomous_restart_allowed",
    }
)
_RISK_NAMES: frozenset[str] = frozenset(
    {
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
    }
)


class RecoveryRPCRefused(RuntimeError):
    """Untrusted or unavailable read-only observation; no actions permitted."""


def _bound_root(root: Path) -> str:
    if (
        not root.is_absolute()
        or not root.name.startswith("txn-")
        or _NONCE.fullmatch(root.name[4:]) is None
        or root.resolve() != root
    ):
        raise RecoveryRPCRefused("recovery transaction root not pinned")
    return root.name[4:]


def _request_nonce(nonce: object) -> str:
    if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
        raise RecoveryRPCRefused("recovery RPC transaction nonce invalid")
    return nonce


def _wire(assessment: RecoveryAssessment, revision: int) -> dict[str, object]:
    if (
        assessment.transaction_nonce is None
        or assessment.phase is None
        or assessment.production_authorized
        or assessment.autonomous_restart_allowed
        or not assessment.manual_review_required
    ):
        raise RecoveryRPCRefused("recovery RPC cannot transmit an authority")
    return {
        "version": _VERSION,
        "ok": True,
        "op": "inspect",
        "nonce": assessment.transaction_nonce,
        "phase": assessment.phase,
        "revision": revision,
        "status": assessment.status,
        "risks": list(assessment.risks),
        "manual_review_required": True,
        "production_authorized": False,
        "autonomous_restart_allowed": False,
    }


@dataclass(frozen=True)
class RecoveryObservationHandler:
    """Server-side read-only dispatch pinned to ONE trusted transaction root.

    Constructed by a future independent out-of-band actor, never from a
    client-controlled path. Underlying A3 must authenticate the caller before
    dispatch; this handler itself is pure request validation and observation.
    """

    root: Path

    def __post_init__(self) -> None:
        _bound_root(self.root)

    def __call__(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if (
            not isinstance(payload, dict)
            or set(payload) != _REQUEST_KEYS
            or type(payload.get("version")) is not int
            or payload["version"] != _VERSION
            or payload.get("op") != "inspect"
            or _request_nonce(payload.get("nonce")) != _bound_root(self.root)
        ):
            raise RecoveryRPCRefused("recovery RPC operation not allowlisted")
        try:
            snapshot = inspect_unowned_transaction(self.root)
            assessment = assess_recovery(snapshot)
            return _wire(assessment, snapshot.revision)
        except (MaintenanceJournalRefused, OSError, ValueError):
            # No path, pid, archived log, state details or secret is disclosed
            # on failure. UNKNOWN can never be interpreted as "complete".
            return {"version": _VERSION, "ok": False, "code": "journal_unavailable"}


def _expected_from_phase(phase: str) -> tuple[RecoveryStatus, tuple[RecoveryRisk, ...]]:
    """Re-derive *read-only* policy instead of trusting server-supplied flags."""
    if phase == "complete":
        return "completion_record_manual_review", ("observation_not_authenticated",)
    if phase == "intent":
        return "pre_stop_manual_review", ("observation_not_authenticated",)
    incomplete: tuple[RecoveryRisk, ...] = (
        "journal_incomplete",
        "controller_terminated_before_completion",
    )
    if _PHASES.index(phase) < _PHASES.index("guardian_armed"):
        return "pre_stop_manual_review", (*incomplete, "observation_not_authenticated")
    return (
        "possible_outage_manual_review",
        (*incomplete, "producer_may_be_offline", "observation_not_authenticated"),
    )


def _parse_reply(value: Mapping[str, object], nonce: str) -> RecoveryAssessment:
    """Refuse invented success, noncanonical values, missing/manual flags."""
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise RecoveryRPCRefused("recovery RPC observation unavailable")
    if (
        set(value) != _REPLY_KEYS
        or type(value.get("version")) is not int
        or value["version"] != _VERSION
        or value["op"] != "inspect"
        or value["nonce"] != nonce
        or value["manual_review_required"] is not True
        or value["production_authorized"] is not False
        or value["autonomous_restart_allowed"] is not False
    ):
        raise RecoveryRPCRefused("recovery RPC response not authority-safe")
    phase = value["phase"]
    revision = value["revision"]
    risks = value["risks"]
    if (
        not isinstance(phase, str)
        or phase not in _PHASES
        or type(revision) is not int
        or revision != _PHASES.index(phase)
        or not isinstance(risks, list)
        or not all(isinstance(r, str) and r in _RISK_NAMES for r in risks)
    ):
        raise RecoveryRPCRefused("recovery RPC response evidence malformed")
    expected_status, expected_risks = _expected_from_phase(phase)
    if value["status"] != expected_status or risks != list(expected_risks):
        raise RecoveryRPCRefused("recovery RPC response risk classification changed")
    return RecoveryAssessment(
        nonce,
        phase,
        expected_status,
        expected_risks,
    )


def observe_recovery_over_a3(
    socket_path: Path,
    *,
    lease: ServiceLease,
    transaction_nonce: str,
    timeout_s: float = 5.0,
) -> RecoveryAssessment:
    """A3 peer/generation-authenticated read only; no replay after dispatch.

    No retry after unknown I/O outcome, even though the handler is currently
    observational. This avoids accidentally turning future RPC additions
    into replayable service mutations.
    """
    nonce = _request_nonce(transaction_nonce)
    if (
        type(timeout_s) not in (int, float)
        or not math.isfinite(timeout_s)
        or not 0 < timeout_s <= 10
    ):
        raise RecoveryRPCRefused("recovery RPC timeout invalid")
    _validate_endpoint(socket_path, lease)
    # Use the existing native Darwin A3 challenge-response, HMAC transcript,
    # peer PID/UID and generation fencing; no second authentication protocol.
    from binnacle.platform.darwin.ipc_transport import connect_authenticated

    channel = connect_authenticated(socket_path, lease=lease, timeout_s=timeout_s)
    try:
        reply = channel.request(
            {"version": _VERSION, "op": "inspect", "nonce": nonce},
            timeout_s=timeout_s,
        )
        return _parse_reply(reply, nonce)
    finally:
        channel.close()


def _validate_endpoint(socket_path: Path, lease: ServiceLease) -> None:
    if (
        not socket_path.is_absolute()
        or socket_path.name != _ENDPOINT
        or socket_path.parent.name != _RUNTIME_NAME
        or lease.label != _LABEL
        or lease.uid != os.getuid()
    ):
        raise RecoveryRPCRefused("recovery observer endpoint not allowlisted")


def serve_readonly_recovery_over_a3(
    socket_path: Path,
    *,
    lease: ServiceLease,
    transaction_root: Path,
    stop: Event,
) -> None:
    """Explicit-only isolated A3 socket service; no autorun or daemon install.

    Requires a separate pre-existing private A3 runtime root and a
    preapproved transaction root. This cannot bootstrap itself or another
    service and has no links to the installed Jobs/MCP sockets.
    """
    if os.getuid() == 0 or os.geteuid() != os.getuid():
        raise RecoveryRPCRefused("observer service must be unprivileged")
    _validate_endpoint(socket_path, lease)
    if transaction_root == socket_path.parent:
        raise RecoveryRPCRefused("observer socket cannot share journal state root")
    handler = RecoveryObservationHandler(transaction_root)
    from binnacle.platform.darwin.ipc_transport import serve_authenticated

    serve_authenticated(socket_path, lease=lease, handler=handler, stop=stop)
