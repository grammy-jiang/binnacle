from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from tests.phase7_support import NOW, SHA_A, SHA_B, execution_ticket, resource_plan

from binnacle.domain.execution import (
    EXECUTOR_PROTOCOL_ID,
    EXECUTOR_PROTOCOL_VERSION,
    MAX_ARGUMENT_BYTES,
    MAX_ENVIRONMENT_ITEMS,
    MAX_ENVIRONMENT_VALUE_BYTES,
    MAX_INLINE_STDIN_BYTES,
    MAX_OUTPUT_CHUNK_BYTES,
    CancelDisposition,
    CancelRoutingDisposition,
    CancelRoutingResult,
    CommandAcceptanceState,
    CommandClosureState,
    CommandExecutionSnapshot,
    CreateReceiptDisposition,
    ExecutionError,
    ExecutionStartDisposition,
    ExecutionStartReceipt,
    ExecutionTicket,
    ExecutorCancelReceipt,
    ExecutorEvidenceEvent,
    ExecutorEvidenceState,
    ExecutorHello,
    ExecutorOutputChunk,
    ExecutorSnapshot,
    NoAcceptSealResult,
    OutputAvailability,
    OutputStream,
    ResourcePlan,
    canonical_timestamp,
    normalize_argv,
    normalize_environment,
    normalize_relative_cwd,
    require_executor_transition,
    ticket_correlation_sha256,
    validate_executable_path,
    validate_identifier,
    validate_sha256,
)


def _executor_snapshot(**changes: object) -> ExecutorSnapshot:
    values: dict[str, object] = {
        "operation_id": "op-fixture",
        "ticket_id": "ticket-fixture",
        "ticket_sha256": SHA_A,
        "execution_id": "execution-fixture",
        "state": ExecutorEvidenceState.ACCEPTED,
        "state_version": 1,
        "evidence_generation": 1,
        "effective_cancel_generation": 0,
        "acknowledged_cancel_generation": 0,
        "cancel_disposition": None,
        "launch_generation": 0,
        "launch_committed_at": None,
        "create_receipt_disposition": CreateReceiptDisposition.NOT_ATTEMPTED,
        "backend_reference": None,
        "backend_domain_identity_sha256": None,
        "accepted_at": NOW,
    }
    values.update(changes)
    return ExecutorSnapshot(**values)  # type: ignore[arg-type]


def _command_snapshot(**changes: object) -> CommandExecutionSnapshot:
    ticket = execution_ticket()
    values: dict[str, object] = {
        "operation_id": ticket.operation_id,
        "session_id": ticket.development_session_id,
        "workspace_id": ticket.workspace_id,
        "ticket_identity": ticket.routing_identity,
        "ticket_correlation_sha256": ticket_correlation_sha256(ticket),
        "record_version": 1,
        "acceptance_state": CommandAcceptanceState.UNRESOLVED,
        "execution_id": None,
        "executor_reference": None,
        "accepted_receipt_sha256": None,
        "no_accept_reference": None,
        "no_accept_receipt_sha256": None,
        "cancel_generation": 0,
        "acknowledged_cancel_generation": 0,
        "cancel_disposition": None,
        "supervisor_evidence_generation": 0,
        "supervisor_cancel_evidence_sha256": None,
        "last_executor_state": None,
        "terminal_evidence_sha256": None,
        "descendants_stopped": False,
        "output_finalized": False,
        "private_resources_cleaned": False,
        "cleanup_evidence_sha256": None,
        "closure_state": CommandClosureState.PENDING,
        "created_at": NOW,
        "updated_at": NOW,
        "last_reconciled_at": None,
    }
    values.update(changes)
    return CommandExecutionSnapshot(**values)  # type: ignore[arg-type]


def test_ticket_round_trips_with_exact_digest() -> None:
    ticket = execution_ticket()

    assert type(ticket).from_wire(ticket.to_wire()) == ticket
    assert ticket.computed_sha256() == ticket.ticket_sha256
    assert ticket.routing_identity.nonce_sha256 != ticket.single_use_nonce


def test_ticket_rejects_mutated_digest_bound_data() -> None:
    ticket = execution_ticket()

    with pytest.raises(ExecutionError, match="digest mismatch"):
        replace(ticket, listener_exposure="loopback")


def test_environment_is_sorted_and_closed() -> None:
    assert normalize_environment({"PATH": "/usr/bin", "LANG": "C"}) == (
        ("LANG", "C"),
        ("PATH", "/usr/bin"),
    )
    with pytest.raises(ExecutionError, match="not permitted"):
        normalize_environment({"LD_PRELOAD": "fixture"})
    with pytest.raises(ExecutionError, match="not permitted"):
        normalize_environment({"AWS_SECRET_ACCESS_KEY": "fixture"})
    with pytest.raises(ExecutionError, match="not permitted"):
        normalize_environment({"DOCKER_HOST": "unix:///fixture"})
    with pytest.raises(ExecutionError, match="not permitted"):
        normalize_environment({"HTTP_PROXY": "http://fixture"})
    with pytest.raises(ExecutionError, match="allowlist-shaped"):
        normalize_environment({"lower": "bad"})


def test_executor_transition_graph_rejects_backward_edge() -> None:
    require_executor_transition(
        ExecutorEvidenceState.ACCEPTED,
        ExecutorEvidenceState.LAUNCH_PREPARING,
    )
    with pytest.raises(ExecutionError, match="illegal executor evidence transition"):
        require_executor_transition(
            ExecutorEvidenceState.RUNNING,
            ExecutorEvidenceState.ACCEPTED,
        )


def test_start_result_is_discriminated() -> None:
    with pytest.raises(ExecutionError, match="contradictory shape"):
        ExecutionStartReceipt(
            disposition=ExecutionStartDisposition.NO_ACCEPT_PROVEN,
            execution_id="exec-fixture",
            evidence_generation=1,
            accepted_at=None,
            executor_reference=None,
            no_accept_reference="seal-fixture",
            receipt_sha256=SHA_A,
        )


def test_executor_hello_rejects_incompatible_or_untrusted_identity() -> None:
    hello = ExecutorHello(
        protocol_id=EXECUTOR_PROTOCOL_ID,
        protocol_version=EXECUTOR_PROTOCOL_VERSION,
        build_sha256=SHA_A,
        profile_sha256=SHA_B,
        supervisor_instance_id="supervisor-fixture",
        supervisor_generation=1,
        backend_ready=False,
        readiness="recovering",
    )
    assert not hello.backend_ready

    for changes, message in (
        ({"protocol_version": "2"}, "protocol identity"),
        ({"build_sha256": "bad"}, "SHA-256"),
        ({"supervisor_instance_id": " bad"}, "invalid"),
        ({"supervisor_generation": 0}, "readiness"),
        ({"readiness": "invented"}, "readiness"),
    ):
        with pytest.raises(ExecutionError, match=message):
            replace(hello, **changes)


def test_resource_plan_wire_shape_and_ceilings_are_closed() -> None:
    plan = resource_plan()
    assert ResourcePlan.from_wire(plan.to_wire()) == plan

    with pytest.raises(ExecutionError, match="fields are not exact"):
        ResourcePlan.from_wire({**plan.to_wire(), "extra": 1})
    with pytest.raises(ExecutionError, match="must be an integer"):
        ResourcePlan.from_wire({**plan.to_wire(), "pids": True})
    with pytest.raises(ExecutionError, match="positive"):
        replace(plan, pids=0)
    with pytest.raises(ExecutionError, match="ceiling"):
        replace(plan, wall_time_seconds=86_401)


def test_ticket_wire_parser_rejects_noncanonical_shapes() -> None:
    ticket = execution_ticket()
    wire = ticket.to_wire()

    invalid_values: tuple[tuple[str, object, str], ...] = (
        ("argv", "python", "argv wire"),
        ("environment", [["LANG"]], "environment wire"),
        ("resource_plan", "limits", "resource plan wire"),
        ("inline_stdin_base64", 5, "stdin wire"),
        ("inline_stdin_base64", "not-base64!", "wire encoding"),
        ("issued_at", "not-a-time", "wire encoding"),
        ("controller_epoch", True, "must be an integer"),
        ("stdin_reference_sha256", 5, "text or null"),
    )
    for name, value, message in invalid_values:
        mutated = dict(wire)
        mutated[name] = value
        with pytest.raises(ExecutionError, match=message):
            ExecutionTicket.from_wire(mutated)

    with pytest.raises(ExecutionError, match="fields are not exact"):
        ExecutionTicket.from_wire({**wire, "extra": "field"})


def test_ticket_post_init_rejects_invalid_deadlines_inputs_and_digests() -> None:
    ticket = execution_ticket()

    invalid: tuple[tuple[dict[str, object], str], ...] = (
        ({"controller_epoch": 0}, "positive"),
        ({"monotonic_deadline_ns": -1}, "cannot be negative"),
        ({"issued_at": datetime.now()}, "timezone-aware"),
        ({"expires_at": ticket.issued_at}, "expiry"),
        ({"executable_path": "python"}, "canonical absolute"),
        ({"argv": ("different",)}, "argv"),
        ({"environment": (("LANG", "different"),)}, "environment"),
        ({"cwd_relative": "subdir"}, "cwd"),
        ({"resource_plan_sha256": SHA_B}, "resource plan"),
        ({"inline_stdin": None}, "absent stdin"),
        ({"inline_stdin": b"different"}, "stdin"),
        ({"inline_stdin": b"x" * (MAX_INLINE_STDIN_BYTES + 1)}, "reviewed limit"),
        ({"stdin_reference_sha256": SHA_A}, "mutually exclusive"),
    )
    for changes, message in invalid:
        with pytest.raises(ExecutionError, match=message):
            replace(ticket, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ((), "item count"),
        (("x" * (MAX_ARGUMENT_BYTES + 1),), "reviewed limit"),
        (("line\nfeed",), "invalid value"),
        (("e\u0301",), "NFC-normalized"),
        ((1,), "invalid value"),
    ],
)
def test_argv_normalization_rejects_unbounded_or_ambiguous_values(
    value: tuple[object, ...], message: str
) -> None:
    with pytest.raises(ExecutionError, match=message):
        normalize_argv(value)


@pytest.mark.parametrize(
    "value",
    ["", "/absolute", "back\\slash", "parent/../escape", "double//separator", "line\nfeed"],
)
def test_cwd_normalization_rejects_noncanonical_paths(value: str) -> None:
    with pytest.raises(ExecutionError, match="command cwd"):
        normalize_relative_cwd(value)


def test_low_level_identity_and_timestamp_validators_are_strict() -> None:
    assert normalize_relative_cwd(".") == "."
    assert normalize_relative_cwd("sub/dir") == "sub/dir"
    validate_executable_path("/usr/bin/python3")
    validate_identifier("valid:id", name="fixture")
    validate_sha256(SHA_A, name="fixture")
    assert canonical_timestamp(NOW).endswith("+00:00")

    for action, message in (
        (lambda: validate_executable_path("/usr/../bin/python"), "canonical absolute"),
        (lambda: validate_identifier("", name="fixture"), "invalid"),
        (lambda: validate_sha256("A" * 64, name="fixture"), "lowercase"),
        (lambda: canonical_timestamp(datetime.now()), "timezone-aware"),
    ):
        with pytest.raises(ExecutionError, match=message):
            action()


def test_environment_rejects_unbounded_and_noncanonical_values() -> None:
    with pytest.raises(ExecutionError, match="item count"):
        normalize_environment({f"NAME_{index}": "x" for index in range(MAX_ENVIRONMENT_ITEMS + 1)})
    with pytest.raises(ExecutionError, match="value is invalid"):
        normalize_environment({"LANG": "line\nfeed"})
    with pytest.raises(ExecutionError, match="NFC-normalized"):
        normalize_environment({"LANG": "e\u0301"})
    with pytest.raises(ExecutionError, match="reviewed limit"):
        normalize_environment({"LANG": "x" * (MAX_ENVIRONMENT_VALUE_BYTES + 1)})


def test_command_snapshot_acceptance_and_closure_shapes_are_exact() -> None:
    accepted = _command_snapshot(
        acceptance_state=CommandAcceptanceState.ACCEPTED_EXECUTION,
        execution_id="execution-fixture",
        executor_reference="executor-fixture",
        accepted_receipt_sha256=SHA_A,
    )
    assert accepted.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION

    complete = replace(
        accepted,
        cancel_generation=1,
        acknowledged_cancel_generation=1,
        terminal_evidence_sha256=SHA_A,
        descendants_stopped=True,
        output_finalized=True,
        private_resources_cleaned=True,
        cleanup_evidence_sha256=SHA_B,
        closure_state=CommandClosureState.COMPLETE,
    )
    assert complete.closure_state is CommandClosureState.COMPLETE

    sealed = _command_snapshot(
        acceptance_state=CommandAcceptanceState.NO_ACCEPT_PROVEN,
        no_accept_reference="seal-fixture",
        no_accept_receipt_sha256=SHA_A,
    )
    assert sealed.no_accept_reference == "seal-fixture"

    for changes, message in (
        ({"record_version": 0}, "generations"),
        ({"acceptance_state": CommandAcceptanceState.ACCEPTED_EXECUTION}, "accepted evidence"),
        (
            {
                "acceptance_state": CommandAcceptanceState.NO_ACCEPT_PROVEN,
                "no_accept_reference": "seal-fixture",
            },
            "no-accept evidence shape",
        ),
        ({"closure_state": CommandClosureState.COMPLETE}, "closure lacks"),
        ({"created_at": datetime.now()}, "timezone-aware"),
        (
            {
                "acceptance_state": CommandAcceptanceState.ACCEPTED_EXECUTION,
                "execution_id": "execution-fixture",
                "executor_reference": "executor-fixture",
                "accepted_receipt_sha256": SHA_A,
                "no_accept_reference": "seal-fixture",
            },
            "contradictory no-accept",
        ),
        (
            {
                "acceptance_state": CommandAcceptanceState.NO_ACCEPT_PROVEN,
                "no_accept_reference": "seal-fixture",
                "no_accept_receipt_sha256": SHA_A,
                "execution_id": "execution-fixture",
            },
            "carries execution evidence",
        ),
    ):
        with pytest.raises(ExecutionError, match=message):
            _command_snapshot(**changes)


def test_executor_snapshot_enforces_launch_terminal_and_cleanup_shapes() -> None:
    committed = _executor_snapshot(
        state=ExecutorEvidenceState.LAUNCH_COMMITTED,
        state_version=2,
        launch_generation=1,
        launch_committed_at=NOW,
        create_receipt_disposition=CreateReceiptDisposition.COMMITTED_PENDING,
    )
    assert committed.launch_generation == 1

    closed = _executor_snapshot(
        state=ExecutorEvidenceState.CLOSED,
        state_version=4,
        exit_code=0,
        terminal_reason="completed",
        terminal_evidence_sha256=SHA_A,
        descendants_stopped=True,
        output_finalized=True,
        cleanup_complete=True,
        cleanup_evidence_sha256=SHA_B,
    )
    assert closed.cleanup_complete

    created = _executor_snapshot(
        state=ExecutorEvidenceState.RUNNING,
        state_version=3,
        launch_generation=1,
        launch_committed_at=NOW,
        create_receipt_disposition=CreateReceiptDisposition.DOMAIN_CREATED,
        backend_reference="backend-fixture",
        backend_domain_identity_sha256=SHA_A,
    )
    assert created.backend_reference == "backend-fixture"

    for changes, message in (
        ({"state_version": 0}, "generations"),
        ({"effective_cancel_generation": 0, "acknowledged_cancel_generation": 1}, "exceeds"),
        ({"accepted_at": datetime.now()}, "timezone-aware"),
        ({"launch_generation": 1}, "generation/time"),
        ({"launch_committed_at": NOW}, "generation/time"),
        (
            {
                "launch_generation": 1,
                "launch_committed_at": NOW,
                "create_receipt_disposition": CreateReceiptDisposition.DOMAIN_CREATED,
            },
            "lacks exact backend",
        ),
        ({"state": ExecutorEvidenceState.EXITED}, "terminal evidence shape"),
        ({"state": ExecutorEvidenceState.EXITED, "exit_code": 0}, "lacks evidence"),
        (
            {
                "state": ExecutorEvidenceState.CLOSED,
                "exit_code": 0,
                "terminal_evidence_sha256": SHA_A,
            },
            "complete closure",
        ),
        ({"cleanup_complete": True}, "cleanup completion"),
        ({"backend_reference": " bad"}, "invalid"),
        ({"backend_domain_identity_sha256": "bad"}, "lowercase SHA-256"),
    ):
        with pytest.raises(ExecutionError, match=message):
            _executor_snapshot(**changes)


def test_evidence_and_receipt_discriminators_reject_contradictions() -> None:
    event = ExecutorEvidenceEvent(
        event_id="event-fixture",
        operation_id="op-fixture",
        expected_state=ExecutorEvidenceState.ACCEPTED,
        expected_state_version=1,
        target_state=ExecutorEvidenceState.LAUNCH_PREPARING,
        reason_code="launch_preparing",
        recorded_at=NOW,
    )
    assert len(event.event_sha256) == 64

    accepted_routing = CancelRoutingResult(
        CancelRoutingDisposition.ACCEPTED_EXECUTION,
        1,
        1,
        _executor_snapshot(),
    )
    assert accepted_routing.snapshot is not None
    sealed_routing = CancelRoutingResult(
        CancelRoutingDisposition.NO_ACCEPT_PROVEN,
        1,
        1,
        None,
        "seal-fixture",
    )
    assert sealed_routing.no_accept_reference == "seal-fixture"
    pending_routing = CancelRoutingResult(
        CancelRoutingDisposition.PENDING_PREACCEPT,
        1,
        1,
        None,
    )
    assert pending_routing.snapshot is None

    accepted_seal = NoAcceptSealResult(
        ExecutionStartDisposition.ACCEPTED_EXECUTION,
        0,
        1,
        _executor_snapshot(),
        None,
        "executor-fixture",
        SHA_A,
    )
    assert accepted_seal.executor_reference == "executor-fixture"
    no_accept_seal = NoAcceptSealResult(
        ExecutionStartDisposition.NO_ACCEPT_PROVEN,
        0,
        1,
        None,
        "seal-fixture",
        None,
        SHA_A,
    )
    assert no_accept_seal.seal_reference == "seal-fixture"
    cancel_receipt = ExecutorCancelReceipt(
        1,
        CancelDisposition.ATTACHED_PRELAUNCH,
        1,
        "execution-fixture",
        SHA_A,
    )
    assert cancel_receipt.execution_id == "execution-fixture"

    with pytest.raises(ExecutionError, match="version/time"):
        replace(event, expected_state_version=0)
    with pytest.raises(ExecutionError, match="illegal executor evidence transition"):
        replace(event, target_state=ExecutorEvidenceState.CLOSED)
    with pytest.raises(ExecutionError, match="invalid"):
        replace(event, backend_reference=" bad")

    for factory, message in (
        (
            lambda: CancelRoutingResult(
                CancelRoutingDisposition.PENDING_PREACCEPT,
                1,
                1,
                _executor_snapshot(),
            ),
            "pending cancel routing",
        ),
        (
            lambda: CancelRoutingResult(
                CancelRoutingDisposition.NO_ACCEPT_PROVEN,
                1,
                1,
                None,
            ),
            "lacks exact seal",
        ),
        (
            lambda: NoAcceptSealResult(
                ExecutionStartDisposition.ACCEPTED_EXECUTION,
                0,
                1,
                None,
                None,
                None,
                SHA_A,
            ),
            "lacks exact execution",
        ),
        (
            lambda: ExecutorCancelReceipt(0, CancelDisposition.UNCERTAIN, 1, None, SHA_A),
            "must be positive",
        ),
    ):
        with pytest.raises(ExecutionError, match=message):
            factory()


def test_output_chunks_have_bounded_exact_cursors() -> None:
    chunk = ExecutorOutputChunk(
        operation_id="op-fixture",
        execution_id="execution-fixture",
        stream=OutputStream.STDOUT,
        offset=0,
        next_offset=3,
        data=b"out",
        eof=False,
        availability=OutputAvailability.AVAILABLE,
        stream_sha256=None,
    )
    assert chunk.next_offset == 3

    with pytest.raises(ExecutionError, match="cursor"):
        replace(chunk, next_offset=2)
    with pytest.raises(ExecutionError, match="reviewed limit"):
        replace(
            chunk, data=b"x" * (MAX_OUTPUT_CHUNK_BYTES + 1), next_offset=MAX_OUTPUT_CHUNK_BYTES + 1
        )
    with pytest.raises(ExecutionError, match="expired output"):
        replace(chunk, availability=OutputAvailability.EXPIRED)
    with pytest.raises(ExecutionError, match="lowercase SHA-256"):
        replace(chunk, stream_sha256="bad")


def test_start_receipt_acceptance_and_routing_deadlines_are_exact() -> None:
    accepted = ExecutionStartReceipt(
        disposition=ExecutionStartDisposition.ACCEPTED_EXECUTION,
        execution_id="execution-fixture",
        evidence_generation=1,
        accepted_at=NOW,
        executor_reference="executor-fixture",
        no_accept_reference=None,
        receipt_sha256=SHA_A,
    )
    assert accepted.accepted_at == NOW
    sealed = ExecutionStartReceipt(
        disposition=ExecutionStartDisposition.NO_ACCEPT_PROVEN,
        execution_id=None,
        evidence_generation=1,
        accepted_at=None,
        executor_reference=None,
        no_accept_reference="seal-fixture",
        receipt_sha256=SHA_A,
    )
    assert sealed.no_accept_reference == "seal-fixture"

    with pytest.raises(ExecutionError, match="must be positive"):
        replace(accepted, evidence_generation=0)
    with pytest.raises(ExecutionError, match="carries no-accept"):
        replace(accepted, no_accept_reference="seal-fixture")
    with pytest.raises(ExecutionError, match="lacks execution evidence"):
        replace(accepted, executor_reference=None)
    with pytest.raises(ExecutionError, match="contradictory shape"):
        replace(sealed, no_accept_reference=None)

    routing = execution_ticket().routing_identity
    with pytest.raises(ExecutionError, match="routing deadline"):
        replace(routing, monotonic_deadline_ns=-1)
    with pytest.raises(ExecutionError, match="routing deadline"):
        replace(routing, expires_at=datetime.now())


def test_cwd_length_limit_is_bounded() -> None:
    with pytest.raises(ExecutionError, match="exceeds the reviewed limit"):
        normalize_relative_cwd("x" * 4_097)
