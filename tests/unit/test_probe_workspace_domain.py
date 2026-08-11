"""Phase 5 path, content, reference, and ledger invariants."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from binnacle.adapters.probe_workspace import (
    ProbeEffectReferenceError,
    parse_probe_effect_reference,
)
from binnacle.domain.probe_workspace import (
    EMPTY_TERMINAL_HISTORY_SHA256,
    ProbeArtifact,
    ProbeArtifactState,
    ProbeOperationKind,
    ProbePathLedger,
    ProbePathSnapshot,
    ProbePreparedState,
    ProbeWorkspaceError,
    canonical_sha256,
    decode_probe_content,
    maximum_effect_sha256,
    normalize_probe_path,
    operation_fingerprint_sha256,
    prepared_input_sha256,
    prepared_state_sha256,
    target_identity_sha256,
    terminal_artifact_projection,
    terminal_history_sha256,
    validate_path_snapshot,
    validate_probe_identifier,
    validate_sha256,
)

NOW = datetime(2026, 8, 12, tzinfo=UTC)


def _artifact(
    generation: int,
    state: ProbeArtifactState,
    *,
    cleanup: str | None = None,
    removed: datetime | None = None,
) -> ProbeArtifact:
    return ProbeArtifact(
        artifact_id=f"artifact-{generation}",
        relative_path="probe.txt",
        path_generation=generation,
        owner_controller_id="controller-fixture",
        owner_controller_epoch=1,
        content_sha256="a" * 64,
        byte_count=4,
        state=state,
        create_operation_id=f"op-create-{generation}",
        active_cleanup_operation_id=cleanup,
        removed_by_cleanup_operation_id=cleanup if removed is not None else None,
        created_at=NOW,
        updated_at=NOW,
        removed_at=removed,
        file_identity_digest="b" * 64 if state is not ProbeArtifactState.ABANDONED else None,
    )


@pytest.mark.parametrize(
    "value",
    (
        "",
        ".",
        "..",
        ".staging",
        ".binnacle-private",
        "/absolute",
        "nested/name",
        r"nested\name",
        "C:drive",
        "line\nfeed",
        "e\u0301.txt",
        "x" * 256,
    ),
)
def test_probe_path_rejects_every_broad_or_noncanonical_shape(value: str) -> None:
    with pytest.raises(ProbeWorkspaceError):
        normalize_probe_path(value)


def test_probe_content_decoding_is_exact_and_bounded() -> None:
    assert decode_probe_content(text="snowman \u2603", encoded_base64=None) == (
        "snowman \u2603".encode()
    )
    assert (
        decode_probe_content(
            text=None,
            encoded_base64=base64.b64encode(b"binary\x00value").decode(),
        )
        == b"binary\x00value"
    )
    with pytest.raises(ProbeWorkspaceError, match="exactly one"):
        decode_probe_content(text="x", encoded_base64="eA==")
    with pytest.raises(ProbeWorkspaceError, match="exceeds"):
        decode_probe_content(text="x" * 65_537, encoded_base64=None)
    with pytest.raises(ProbeWorkspaceError, match="invalid"):
        decode_probe_content(text=None, encoded_base64="not base64!")
    with pytest.raises(ProbeWorkspaceError, match="outside"):
        decode_probe_content(text="x", encoded_base64=None, maximum_bytes=0)
    with pytest.raises(ProbeWorkspaceError, match="UTF-8"):
        decode_probe_content(text="\ud800", encoded_base64=None)


def test_probe_path_rejects_non_utf8_surrogate() -> None:
    with pytest.raises(ProbeWorkspaceError, match="UTF-8"):
        normalize_probe_path("\ud800")


def test_effect_reference_parser_is_closed_and_generation_bound() -> None:
    reference = parse_probe_effect_reference("probe-write:v1:artifact_fixture:7:" + "a" * 64)
    assert reference.operation is ProbeOperationKind.WRITE
    assert reference.path_generation == 7
    with pytest.raises(ProbeEffectReferenceError):
        parse_probe_effect_reference("probe-write:v1:artifact_fixture:0:" + "a" * 64)
    with pytest.raises(ProbeEffectReferenceError):
        parse_probe_effect_reference("probe-delete:v1:artifact_fixture:7:" + "a" * 64)


def test_probe_identifiers_digests_and_operation_fingerprints_are_closed() -> None:
    assert validate_probe_identifier("artifact.v1:fixture", name="artifact")
    assert validate_sha256("a" * 64, name="digest") == "a" * 64
    with pytest.raises(ProbeWorkspaceError, match="identifier"):
        validate_probe_identifier("contains space", name="artifact")
    with pytest.raises(ProbeWorkspaceError, match="lowercase"):
        validate_sha256("A" * 64, name="digest")

    prepared = prepared_input_sha256(
        operation=ProbeOperationKind.WRITE,
        relative_path="probe.txt",
        expected_content_sha256="a" * 64,
        byte_count=4,
        artifact_id=None,
    )
    target = target_identity_sha256("b" * 64, "probe.txt")
    maximum = maximum_effect_sha256(operation=ProbeOperationKind.WRITE, maximum_bytes=4)
    fingerprint = operation_fingerprint_sha256(
        operation=ProbeOperationKind.WRITE,
        prepared_operation_id="prepared-fixture",
        prepared_input_sha256=prepared,
        relative_path="probe.txt",
        expected_content_sha256="a" * 64,
        byte_count=4,
        artifact_id=None,
        target_identity_digest=target,
        maximum_effect_digest=maximum,
    )
    different_prepared_input = operation_fingerprint_sha256(
        operation=ProbeOperationKind.WRITE,
        prepared_operation_id="prepared-fixture",
        prepared_input_sha256="c" * 64,
        relative_path="probe.txt",
        expected_content_sha256="a" * 64,
        byte_count=4,
        artifact_id=None,
        target_identity_digest=target,
        maximum_effect_digest=maximum,
    )
    assert len({prepared, target, maximum, fingerprint}) == 4
    assert fingerprint == "200aecde07ece5d6dde912d9108fae80b7e1e340d0a661e2266ad8651376902d"
    assert different_prepared_input != fingerprint
    assert maximum_effect_sha256(operation=ProbeOperationKind.CLEANUP) != maximum
    with pytest.raises(ProbeWorkspaceError, match="maximum effect"):
        maximum_effect_sha256(operation=ProbeOperationKind.WRITE, maximum_bytes=65_537)


def test_terminal_history_and_active_snapshot_are_independently_validated() -> None:
    terminal = _artifact(1, ProbeArtifactState.REMOVED, removed=NOW)
    active = _artifact(2, ProbeArtifactState.CREATED)
    digest = terminal_history_sha256((terminal,))
    ledger = ProbePathLedger(
        relative_path="probe.txt",
        generation_high_water=2,
        terminal_history_count=1,
        terminal_history_sha256=digest,
        active_artifact_id=active.artifact_id,
        active_generation=2,
        active_create_operation_id=active.create_operation_id,
        ledger_version=5,
        updated_at=NOW,
    )
    snapshot = ProbePathSnapshot(ledger, (terminal,), active)
    validate_path_snapshot(snapshot)
    assert terminal_artifact_projection(terminal)["path_generation"] == 1
    with pytest.raises(ProbeWorkspaceError, match="non-terminal"):
        terminal_artifact_projection(active)

    corruptions = (
        replace(snapshot, ledger=replace(ledger, terminal_history_count=0)),
        replace(snapshot, ledger=replace(ledger, terminal_history_sha256="c" * 64)),
        replace(snapshot, ledger=replace(ledger, active_artifact_id="artifact-other")),
        replace(snapshot, ledger=replace(ledger, generation_high_water=3)),
        replace(snapshot, terminal_artifacts=(replace(terminal, path_generation=2),)),
        replace(snapshot, terminal_artifacts=(replace(terminal, active_cleanup_operation_id="x"),)),
        replace(snapshot, active_artifact=replace(active, state=ProbeArtifactState.REMOVED)),
    )
    for corrupt in corruptions:
        with pytest.raises(ProbeWorkspaceError):
            validate_path_snapshot(corrupt)

    deeper_corruptions = (
        replace(snapshot, ledger=replace(ledger, ledger_version=0)),
        replace(snapshot, ledger=replace(ledger, terminal_history_count=-1)),
        replace(
            snapshot, terminal_artifacts=(replace(terminal, state=ProbeArtifactState.CREATED),)
        ),
        replace(snapshot, active_artifact=replace(active, relative_path="other.txt")),
        replace(snapshot, active_artifact=replace(active, owner_controller_epoch=0)),
        replace(snapshot, active_artifact=replace(active, byte_count=-1)),
        replace(snapshot, active_artifact=replace(active, file_identity_digest=None)),
        replace(snapshot, active_artifact=replace(active, state=ProbeArtifactState.RESERVED)),
        replace(
            snapshot,
            terminal_artifacts=(replace(terminal, file_identity_digest=None),),
        ),
        replace(snapshot, active_artifact=replace(active, updated_at=NOW.replace(year=2025))),
        replace(snapshot, ledger=replace(ledger, active_generation=None)),
        replace(
            snapshot,
            ledger=replace(ledger, generation_high_water=3, active_generation=3),
            active_artifact=replace(active, path_generation=3),
        ),
    )
    for corrupt in deeper_corruptions:
        with pytest.raises(ProbeWorkspaceError):
            validate_path_snapshot(corrupt)


def test_stable_empty_snapshot_and_prepared_state_digest_are_canonical() -> None:
    ledger = ProbePathLedger(
        relative_path="probe.txt",
        generation_high_water=0,
        terminal_history_count=0,
        terminal_history_sha256=EMPTY_TERMINAL_HISTORY_SHA256,
        active_artifact_id=None,
        active_generation=None,
        active_create_operation_id=None,
        ledger_version=1,
        updated_at=NOW,
    )
    validate_path_snapshot(ProbePathSnapshot(ledger, (), None))
    with pytest.raises(ProbeWorkspaceError, match="incomplete active"):
        validate_path_snapshot(
            ProbePathSnapshot(replace(ledger, active_artifact_id="artifact-1"), (), None)
        )
    with pytest.raises(ProbeWorkspaceError, match="high-water"):
        validate_path_snapshot(
            ProbePathSnapshot(replace(ledger, generation_high_water=1), (), None)
        )

    state = ProbePreparedState(
        operation=ProbeOperationKind.WRITE,
        relative_path="probe.txt",
        content_sha256="a" * 64,
        byte_count=4,
        artifact_id=None,
        owner_controller_id="controller-fixture",
        owner_controller_epoch=1,
        root_identity_sha256="b" * 64,
        ledger_version=1,
        generation_high_water=0,
        terminal_history_count=0,
        terminal_history_sha256=EMPTY_TERMINAL_HISTORY_SHA256,
        active_artifact_id=None,
        active_generation=None,
        active_create_operation_id=None,
        write_reservation_transition="absent_generation_N_then_exact_self_reserved_generation_N_plus_1",
        cleanup_target_transition=None,
        cleanup_claim_transition=None,
        expected_file_identity_digest=None,
    )
    assert prepared_state_sha256(state) == canonical_sha256(
        {
            "active_artifact_id": None,
            "active_create_operation_id": None,
            "active_generation": None,
            "artifact_id": None,
            "byte_count": 4,
            "cleanup_claim_transition": None,
            "cleanup_target_transition": None,
            "content_sha256": "a" * 64,
            "expected_file_identity_digest": None,
            "generation_high_water": 0,
            "ledger_version": 1,
            "operation": "write",
            "owner_controller_epoch": 1,
            "owner_controller_id": "controller-fixture",
            "relative_path": "probe.txt",
            "root_identity_sha256": "b" * 64,
            "terminal_history_count": 0,
            "terminal_history_sha256": EMPTY_TERMINAL_HISTORY_SHA256,
            "write_reservation_transition": (
                "absent_generation_N_then_exact_self_reserved_generation_N_plus_1"
            ),
        }
    )
