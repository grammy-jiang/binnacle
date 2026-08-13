"""Read-only integrity verification for isolated privileged-broker evidence."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final

PRIVILEGED_BROKER_REVISION: Final = "0001_privileged_evidence"
EXPECTED_PRIVILEGED_TABLES: Final = frozenset(
    {
        "alembic_version",
        "privileged_meta",
        "privileged_operation_bindings",
        "privileged_no_accept_tombstones",
        "privileged_subeffects",
        "privileged_package_plans",
        "privileged_runtime_slots",
        "privileged_restart_checkpoints",
        "privileged_selector_generations",
        "privileged_evidence_events",
    }
)


class PrivilegedBrokerIntegrityError(RuntimeError):
    """Privileged evidence is incompatible, contradictory, or not replay-safe."""


@dataclass(frozen=True, slots=True)
class PrivilegedBrokerIntegrityReport:
    revision: str
    readiness: str
    schema_generation: int
    evidence_generation: int
    unresolved_bindings: int
    accepted_bindings: int
    outstanding_accepted_bindings: int
    sealed_bindings: int
    active_subeffects: int
    uncertain_subeffects: int
    package_plans: int
    runtime_slots: int
    restart_checkpoints: int
    selector_generations: int

    @property
    def retains_authority(self) -> bool:
        return bool(
            self.unresolved_bindings
            or self.outstanding_accepted_bindings
            or self.active_subeffects
            or self.uncertain_subeffects
            or self.package_plans
            or self.runtime_slots
            or self.restart_checkpoints
            or self.selector_generations
        )


def verify_privileged_broker_connection(
    connection: sqlite3.Connection,
    *,
    expected_revision: str = PRIVILEGED_BROKER_REVISION,
) -> PrivilegedBrokerIntegrityReport:
    try:
        return _verify(connection, expected_revision=expected_revision)
    except PrivilegedBrokerIntegrityError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, sqlite3.Error) as exc:
        raise PrivilegedBrokerIntegrityError(
            "privileged-broker evidence contains an invalid value"
        ) from exc


def _verify(
    connection: sqlite3.Connection,
    *,
    expected_revision: str,
) -> PrivilegedBrokerIntegrityReport:
    connection.row_factory = sqlite3.Row
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise PrivilegedBrokerIntegrityError("privileged-broker SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise PrivilegedBrokerIntegrityError("privileged-broker foreign-key integrity failed")
    tables = frozenset(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    if tables != EXPECTED_PRIVILEGED_TABLES:
        raise PrivilegedBrokerIntegrityError("privileged-broker table set is incompatible")
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    meta = connection.execute("SELECT * FROM privileged_meta WHERE id=1").fetchone()
    if revision is None or revision[0] != expected_revision or meta is None:
        raise PrivilegedBrokerIntegrityError("privileged-broker identity is incompatible")
    schema_generation = _integer(meta["schema_generation"])
    high_water = _integer(meta["evidence_generation_high_water"])
    readiness = str(meta["readiness"])
    if (
        schema_generation != 1
        or high_water < 0
        or readiness
        not in {
            "uninitialized",
            "disabled",
            "recovering",
            "ready",
            "restricted_recovery",
            "integrity_failed",
        }
    ):
        raise PrivilegedBrokerIntegrityError("privileged-broker metadata is contradictory")

    events = tuple(
        connection.execute("SELECT * FROM privileged_evidence_events ORDER BY evidence_generation")
    )
    if len(events) != high_water or any(
        _integer(row["evidence_generation"]) != expected
        for expected, row in enumerate(events, start=1)
    ):
        raise PrivilegedBrokerIntegrityError("privileged evidence generation has a gap")

    bindings = tuple(
        connection.execute("SELECT * FROM privileged_operation_bindings ORDER BY operation_id")
    )
    for row in bindings:
        _verify_binding(connection, row, high_water)
    _verify_subeffects(connection, high_water)
    package_plans = _verify_package_plans(connection)
    runtime_slots = _verify_runtime_slots(connection)
    restart_checkpoints = _verify_restart_checkpoints(connection, high_water)
    selector_generations = _verify_selector_generations(connection)
    pending_lkg_promotions = frozenset(
        str(row[0])
        for row in connection.execute(
            "SELECT operation_id FROM privileged_restart_checkpoints "
            "WHERE state='terminal' AND outcome='candidate_ready' "
            "AND lkg_promotion_evidence_sha256 IS NULL"
        )
    )
    orphan_events = int(
        connection.execute(
            "SELECT COUNT(*) FROM privileged_evidence_events event "
            "LEFT JOIN privileged_operation_bindings binding "
            "ON binding.operation_id=event.operation_id "
            "WHERE binding.operation_id IS NULL"
        ).fetchone()[0]
    )
    if orphan_events:
        raise PrivilegedBrokerIntegrityError("privileged event has no retained binding")

    active_states = "('intent_recorded','started','reconciling','restricted_recovery')"
    active_subeffects = int(
        connection.execute(
            f"SELECT COUNT(*) FROM privileged_subeffects WHERE state IN {active_states}"
        ).fetchone()[0]
    )
    uncertain_subeffects = int(
        connection.execute(
            "SELECT COUNT(*) FROM privileged_subeffects WHERE state='uncertain'"
        ).fetchone()[0]
    )
    return PrivilegedBrokerIntegrityReport(
        revision=str(revision[0]),
        readiness=readiness,
        schema_generation=schema_generation,
        evidence_generation=high_water,
        unresolved_bindings=sum(row["acceptance_state"] == "unresolved" for row in bindings),
        accepted_bindings=sum(row["acceptance_state"] == "accepted" for row in bindings),
        outstanding_accepted_bindings=sum(
            row["acceptance_state"] == "accepted"
            and (
                row["execution_state"] != "terminal"
                or str(row["operation_id"]) in pending_lkg_promotions
            )
            for row in bindings
        ),
        sealed_bindings=sum(row["acceptance_state"] == "sealed_no_accept" for row in bindings),
        active_subeffects=active_subeffects,
        uncertain_subeffects=uncertain_subeffects,
        package_plans=package_plans,
        runtime_slots=runtime_slots,
        restart_checkpoints=restart_checkpoints,
        selector_generations=selector_generations,
    )


def _verify_binding(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    high_water: int,
) -> None:
    state = str(row["acceptance_state"])
    generation = _integer(row["evidence_generation"])
    tombstones = tuple(
        connection.execute(
            "SELECT * FROM privileged_no_accept_tombstones WHERE operation_id=?",
            (row["operation_id"],),
        )
    )
    if state not in {"unresolved", "accepted", "sealed_no_accept"}:
        raise PrivilegedBrokerIntegrityError("privileged acceptance state is invalid")
    if generation > high_water:
        raise PrivilegedBrokerIntegrityError("privileged acceptance exceeds evidence high-water")
    if state == "sealed_no_accept":
        if len(tombstones) != 1:
            raise PrivilegedBrokerIntegrityError("privileged no-accept binding lacks tombstone")
        tombstone = tombstones[0]
        if (
            tombstone["ticket_id"] != row["ticket_id"]
            or tombstone["ticket_sha256"] != row["ticket_sha256"]
            or _integer(tombstone["evidence_generation"]) != generation
            or tombstone["evidence_sha256"] != row["acceptance_evidence_sha256"]
        ):
            raise PrivilegedBrokerIntegrityError("privileged no-accept evidence conflicts")
    elif tombstones:
        raise PrivilegedBrokerIntegrityError("privileged tombstone has no sealed binding")
    if state != "unresolved":
        event = connection.execute(
            "SELECT operation_id,event_type,event_sha256 FROM privileged_evidence_events "
            "WHERE evidence_generation=?",
            (generation,),
        ).fetchone()
        expected_type = "ticket.accepted" if state == "accepted" else "ticket.sealed_no_accept"
        if (
            event is None
            or event["operation_id"] != row["operation_id"]
            or event["event_type"] != expected_type
            or event["event_sha256"] != row["acceptance_evidence_sha256"]
        ):
            raise PrivilegedBrokerIntegrityError(
                "privileged acceptance lacks its exact evidence event"
            )
    execution_state = str(row["execution_state"])
    active_slot = row["active_slot"]
    effect_knowledge = str(row["effect_knowledge"])
    result_evidence = row["result_evidence_sha256"]
    if state == "unresolved" and (
        execution_state != "not_accepted"
        or active_slot is not None
        or effect_knowledge != "none"
        or result_evidence is not None
    ):
        raise PrivilegedBrokerIntegrityError("unresolved privileged binding carries effect truth")
    if state == "sealed_no_accept" and (
        execution_state != "terminal"
        or active_slot is not None
        or effect_knowledge != "known_no_subeffect"
        or result_evidence != row["acceptance_evidence_sha256"]
    ):
        raise PrivilegedBrokerIntegrityError("sealed privileged binding effect truth conflicts")
    if state == "accepted":
        allowed = {
            "accepted_pre_effect": {"none"},
            "executing": {"known_effect"},
            "reconciling": {"known_effect"},
            "terminal": {"known_no_subeffect", "known_effect"},
            "uncertain": {"uncertain"},
            "restricted_recovery": {"uncertain"},
        }
        if effect_knowledge not in allowed.get(execution_state, set()):
            raise PrivilegedBrokerIntegrityError("accepted privileged outcome is contradictory")
        evidence_required = execution_state in {
            "terminal",
            "uncertain",
            "restricted_recovery",
        }
        if evidence_required != (result_evidence is not None):
            raise PrivilegedBrokerIntegrityError("privileged outcome evidence shape is invalid")
        expected_active = execution_state != "terminal"
        if expected_active != (active_slot == 1):
            raise PrivilegedBrokerIntegrityError("privileged active-slot evidence conflicts")


def _verify_subeffects(connection: sqlite3.Connection, high_water: int) -> None:
    del high_water
    rows = tuple(
        connection.execute(
            """
            SELECT subeffect.*, binding.acceptance_state, binding.action
            FROM privileged_subeffects subeffect
            LEFT JOIN privileged_operation_bindings binding
              ON binding.operation_id=subeffect.operation_id
            ORDER BY subeffect.operation_id, subeffect.subeffect_generation
            """
        )
    )
    expected_by_operation: dict[str, int] = {}
    for row in rows:
        operation_id = str(row["operation_id"])
        expected = expected_by_operation.get(operation_id, 1)
        if _integer(row["subeffect_generation"]) != expected:
            raise PrivilegedBrokerIntegrityError("privileged subeffect generation has a gap")
        expected_by_operation[operation_id] = expected + 1
        if row["acceptance_state"] != "accepted":
            raise PrivilegedBrokerIntegrityError("privileged subeffect lacks accepted binding")
        action = str(row["action"])
        kind = str(row["kind"])
        allowed_kinds = {
            "package_install": {"package_transaction"},
            "service_restart": {"service_stop", "service_start"},
            "controlled_restart": {
                "service_stop",
                "service_start",
                "selector_activate",
                "selector_restore",
                "runtime_verify",
            },
        }
        if kind not in allowed_kinds.get(action, set()):
            raise PrivilegedBrokerIntegrityError(
                "privileged subeffect kind conflicts with its accepted action"
            )


def _verify_package_plans(connection: sqlite3.Connection) -> int:
    rows = tuple(
        connection.execute(
            """
            SELECT package_plan.*, binding.action, binding.acceptance_state
            FROM privileged_package_plans package_plan
            LEFT JOIN privileged_operation_bindings binding
              ON binding.operation_id=package_plan.operation_id
            ORDER BY package_plan.operation_id
            """
        )
    )
    for row in rows:
        if row["acceptance_state"] != "accepted" or row["action"] != "package_install":
            raise PrivilegedBrokerIntegrityError(
                "privileged package plan lacks an accepted package binding"
            )
    return len(rows)


def _verify_runtime_slots(connection: sqlite3.Connection) -> int:
    rows = tuple(
        connection.execute("SELECT * FROM privileged_runtime_slots ORDER BY slot_generation")
    )
    if any(
        _integer(row["slot_generation"]) != expected for expected, row in enumerate(rows, start=1)
    ):
        raise PrivilegedBrokerIntegrityError("privileged runtime slot generation has a gap")
    if sum(row["state"] == "active" for row in rows) > 1:
        raise PrivilegedBrokerIntegrityError("multiple privileged runtime slots are active")
    if sum(row["state"] == "lkg" for row in rows) > 1:
        raise PrivilegedBrokerIntegrityError("multiple privileged runtime slots are LKG")
    if any(
        (row["role"], row["state"])
        not in {
            ("candidate", "staging"),
            ("candidate", "complete"),
            ("candidate", "active"),
            ("candidate", "restricted"),
            ("lkg", "lkg"),
            ("lkg", "restricted"),
            ("prior", "prior"),
            ("prior", "restricted"),
        }
        for row in rows
    ):
        raise PrivilegedBrokerIntegrityError("privileged runtime slot role and state differ")
    return len(rows)


def _verify_restart_checkpoints(connection: sqlite3.Connection, high_water: int) -> int:
    rows = tuple(
        connection.execute(
            """
            SELECT checkpoint.*, binding.action, binding.acceptance_state,
                   binding.execution_state, binding.result_evidence_sha256 AS binding_result,
                   candidate.role AS candidate_role,
                   candidate.state AS candidate_state,
                   lkg.role AS lkg_role,
                   lkg.state AS lkg_state
            FROM privileged_restart_checkpoints checkpoint
            LEFT JOIN privileged_operation_bindings binding
              ON binding.operation_id=checkpoint.operation_id
            LEFT JOIN privileged_runtime_slots candidate
              ON candidate.slot_id=checkpoint.candidate_slot_id
            LEFT JOIN privileged_runtime_slots lkg
              ON lkg.slot_id=checkpoint.lkg_slot_id
            ORDER BY checkpoint.operation_id
            """
        )
    )
    complete_states = {"complete", "active", "lkg", "prior"}
    for row in rows:
        state = str(row["state"])
        outcome = str(row["outcome"])
        if (
            row["acceptance_state"] != "accepted"
            or row["action"] != "controlled_restart"
            or row["candidate_slot_id"] == row["lkg_slot_id"]
            or row["candidate_state"] not in complete_states
            or row["lkg_state"] not in {"lkg", "prior"}
            or not 1 <= _integer(row["evidence_generation"]) <= high_water
        ):
            raise PrivilegedBrokerIntegrityError(
                "privileged restart checkpoint lacks accepted complete slot evidence"
            )
        terminal = state == "terminal"
        restricted = state == "restricted_recovery"
        expected_outcomes = (
            {"candidate_ready", "rollback_ready", "no_subeffect", "failed"}
            if terminal
            else ({"restricted_recovery"} if restricted else {"pending"})
        )
        if outcome not in expected_outcomes:
            raise PrivilegedBrokerIntegrityError(
                "privileged restart checkpoint outcome is contradictory"
            )
        promotion_values = (
            row["lkg_promotion_audit_sha256"],
            row["lkg_promotion_evidence_sha256"],
            row["lkg_promoted_at"],
        )
        promoted = all(value is not None for value in promotion_values)
        if any(value is not None for value in promotion_values) != promoted:
            raise PrivilegedBrokerIntegrityError(
                "privileged restart LKG promotion evidence is incomplete"
            )
        if promoted:
            if (
                outcome != "candidate_ready"
                or row["candidate_role"] not in {"lkg", "prior"}
                or row["candidate_state"] not in {"lkg", "prior"}
                or row["candidate_role"] != row["candidate_state"]
                or row["lkg_role"] != "prior"
                or row["lkg_state"] != "prior"
                or row["closed_at"] is None
                or row["lkg_promoted_at"] < row["closed_at"]
            ):
                raise PrivilegedBrokerIntegrityError(
                    "privileged restart LKG promotion lifecycle is contradictory"
                )
            event = connection.execute(
                "SELECT operation_id,event_type,event_sha256 "
                "FROM privileged_evidence_events WHERE evidence_generation=?",
                (_integer(row["evidence_generation"]),),
            ).fetchone()
            if (
                event is None
                or event["operation_id"] != row["operation_id"]
                or event["event_type"] != "restart.lkg_promoted"
                or event["event_sha256"] != row["lkg_promotion_evidence_sha256"]
            ):
                raise PrivilegedBrokerIntegrityError(
                    "privileged restart LKG promotion lacks its exact evidence event"
                )
        elif outcome == "candidate_ready" and (
            row["candidate_role"] != "candidate"
            or row["candidate_state"] not in {"complete", "active"}
            or row["lkg_role"] != "lkg"
            or row["lkg_state"] != "lkg"
        ):
            raise PrivilegedBrokerIntegrityError(
                "candidate-ready checkpoint lacks a pending LKG promotion"
            )
        expected_binding_state = (
            "terminal" if terminal else ("restricted_recovery" if restricted else None)
        )
        if expected_binding_state is not None and (
            row["execution_state"] != expected_binding_state
            or row["binding_result"] != row["result_evidence_sha256"]
        ):
            raise PrivilegedBrokerIntegrityError(
                "privileged restart checkpoint and binding closure differ"
            )
    return len(rows)


def _verify_selector_generations(connection: sqlite3.Connection) -> int:
    rows = tuple(
        connection.execute(
            """
            SELECT selector.*, binding.action, binding.acceptance_state,
                   old_slot.state AS old_slot_state, new_slot.state AS new_slot_state
            FROM privileged_selector_generations selector
            LEFT JOIN privileged_operation_bindings binding
              ON binding.operation_id=selector.operation_id
            LEFT JOIN privileged_runtime_slots old_slot
              ON old_slot.slot_id=selector.old_slot_id
            LEFT JOIN privileged_runtime_slots new_slot
              ON new_slot.slot_id=selector.new_slot_id
            ORDER BY selector.selector_generation
            """
        )
    )
    complete_states = {"complete", "active", "lkg", "prior"}
    for expected, row in enumerate(rows, start=1):
        initial = bool(row["initial_bootstrap"])
        if _integer(row["selector_generation"]) != expected:
            raise PrivilegedBrokerIntegrityError("privileged selector generation has a gap")
        if (
            initial != (expected == 1)
            or initial != (row["operation_id"] is None)
            or (initial and row["old_slot_id"] is not None)
        ):
            raise PrivilegedBrokerIntegrityError(
                "privileged selector bootstrap identity is contradictory"
            )
        if not initial and (
            row["acceptance_state"] != "accepted" or row["action"] != "controlled_restart"
        ):
            raise PrivilegedBrokerIntegrityError(
                "privileged selector lacks an accepted restart binding"
            )
        if row["new_slot_state"] not in complete_states or (
            row["old_slot_id"] is not None and row["old_slot_state"] not in complete_states
        ):
            raise PrivilegedBrokerIntegrityError(
                "privileged selector references an incomplete runtime slot"
            )
    return len(rows)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PrivilegedBrokerIntegrityError("privileged evidence integer is invalid")
    return value


__all__ = [
    "EXPECTED_PRIVILEGED_TABLES",
    "PRIVILEGED_BROKER_REVISION",
    "PrivilegedBrokerIntegrityError",
    "PrivilegedBrokerIntegrityReport",
    "verify_privileged_broker_connection",
]
