"""Synthetic, consumer-scoped hint policy checks."""

import unittest
from itertools import permutations
from unittest.mock import Mock, patch

from binnacle.features.commands.job_awareness.hint_policy import select_candidates
from binnacle.features.commands.job_awareness.hint_render import render_hint
from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    BoundaryError,
    ByteRange,
    ConsumerReceipt,
    ErrorCode,
    Failure,
    HintCarrier,
    JobRef,
    Observation,
    ObservationState,
    OutputSnapshot,
    ReceiptState,
    Scope,
    SourceKind,
    Success,
    TerminalKind,
    TerminalOutcome,
)
from tests.contracts.job_awareness.fakes import FakeHandleAuthority, FakeReceiptQuery


def fixture(number: int) -> Observation:
    job = JobRef("ja1_" + "a" * 32, f"{number:012x}", "g1_" + "b" * 32)
    terminal = TerminalOutcome(TerminalKind.EXIT_CODE, 0)
    snapshot = OutputSnapshot(
        job,
        "c" * 64,
        3,
        terminal,
        100,
        10000,
        SourceKind.CONTROLLER_SEALED_SYNTHETIC,
        "d" * 32,
    )
    return Observation(job, ObservationState.TERMINAL, terminal, snapshot)


def receipt(observation: Observation, state: ReceiptState) -> ConsumerReceipt:
    assert observation.snapshot is not None
    return ConsumerReceipt(
        state, observation.job, observation.snapshot.sha256, (), False, 0, 1
    )


class HintPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = tuple(fixture(i) for i in range(1, 9))
        self.auth = FakeHandleAuthority()
        self.grant = self.auth.issue(tuple(item.job for item in self.items))
        self.query = FakeReceiptQuery(self.auth)

    def add(self, item: Observation, state: ReceiptState, grant=None) -> None:
        assert item.snapshot is not None
        self.query.register(grant or self.grant, item.snapshot, receipt(item, state))

    def test_query_controls_candidates(self) -> None:
        for item, state in zip(
            self.items,
            (
                ReceiptState.COMPLETE,
                ReceiptState.PARTIAL,
                ReceiptState.UNCONFIRMED,
                ReceiptState.OUTPUT_EXPIRED,
                ReceiptState.PARTIAL,
                ReceiptState.UNCONFIRMED,
                ReceiptState.UNCONFIRMED,
                ReceiptState.UNCONFIRMED,
            ),
            strict=True,
        ):
            self.add(item, state)
        selected = select_candidates(self.grant, self.items, self.auth, self.query)
        self.assertEqual(
            [item.job for item in selected], [self.items[2].job, self.items[5].job]
        )
        self.assertEqual(
            [item.category.value for item in selected], ["TERMINAL_UNCONFIRMED"] * 2
        )

    def test_null_and_foreign_grant_do_not_disclose(self) -> None:
        self.add(self.items[0], ReceiptState.UNCONFIRMED)
        self.assertEqual(
            select_candidates(None, self.items[:1], self.auth, self.query), ()
        )
        foreign = FakeHandleAuthority().issue((self.items[0].job,))
        self.assertEqual(
            select_candidates(foreign, self.items[:1], self.auth, self.query), ()
        )

    def test_complete_partial_expired_and_zero_jobs(self) -> None:
        self.add(self.items[0], ReceiptState.COMPLETE)
        self.add(self.items[1], ReceiptState.PARTIAL)
        self.add(self.items[2], ReceiptState.OUTPUT_EXPIRED)
        selected = select_candidates(self.grant, self.items[:3], self.auth, self.query)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].category.value, "TERMINAL_PARTIAL")
        self.assertEqual(select_candidates(self.grant, (), self.auth, self.query), ())

    def test_large_count_rejected_without_port_work(self) -> None:
        self.assertEqual(
            select_candidates(
                self.grant, self.items + self.items[:1], self.auth, self.query
            ),
            (),
        )
        self.assertEqual(self.auth.check_calls, 0)

    def test_duplicate_and_mismatched_observations_do_not_query(self) -> None:
        self.assertEqual(
            select_candidates(
                self.grant, (self.items[0], self.items[0]), self.auth, self.query
            ),
            (),
        )
        wrong = fixture(99)
        object.__setattr__(wrong.snapshot, "job", self.items[0].job)
        self.assertEqual(
            select_candidates(self.grant, (wrong,), self.auth, self.query), ()
        )
        self.assertEqual(self.auth.check_calls, 0)

    def test_query_error_and_invalid_success_suppress_everything(self) -> None:
        self.add(self.items[0], ReceiptState.UNCONFIRMED)
        self.assertEqual(
            select_candidates(self.grant, self.items[:2], self.auth, self.query), ()
        )

        class InvalidQuery:
            def query(self, grant, snapshot):
                return Success({"state": "UNCONFIRMED", "job": snapshot.job})

        self.assertEqual(
            select_candidates(self.grant, self.items[:1], self.auth, InvalidQuery()), ()
        )

    def test_foreign_receipt_and_unsupported_state_suppress(self) -> None:
        foreign = self.auth.issue((self.items[0].job,))
        self.add(self.items[0], ReceiptState.UNCONFIRMED, foreign)
        self.assertEqual(
            select_candidates(self.grant, self.items[:1], self.auth, self.query), ()
        )

        class WrongReceipt:
            def query(self, grant, snapshot):
                return Success(receipt(self_item, ReceiptState.UNCONFIRMED))

        self_item = self.items[1]
        self.assertEqual(
            select_candidates(self.grant, self.items[:1], self.auth, WrongReceipt()), ()
        )

        class UnsupportedReceipt:
            def query(self, grant, snapshot):
                value = receipt(self_item, ReceiptState.UNCONFIRMED)
                object.__setattr__(value, "job", snapshot.job)
                object.__setattr__(value, "state", "future-status")
                return Success(value)

        self.assertEqual(
            select_candidates(
                self.grant, self.items[:1], self.auth, UnsupportedReceipt()
            ),
            (),
        )

    def test_query_exception_suppresses(self) -> None:
        class BrokenQuery:
            def query(self, grant, snapshot):
                raise TimeoutError("private path /secret")

        self.assertEqual(
            select_candidates(self.grant, self.items[:1], self.auth, BrokenQuery()), ()
        )

    def test_corrupt_observations_suppress_batch_before_ports(self) -> None:
        self.add(self.items[0], ReceiptState.UNCONFIRMED)
        faults: tuple[tuple[str, str, object], ...] = (
            ("observation", "job", []),
            ("observation", "snapshot", "/private/path"),
            ("observation", "state", "TERMINAL"),
            ("observation", "state", []),
            ("observation", "terminal", []),
            ("job", "job_id", []),
            ("job", "incarnation", "/private/path"),
            ("snapshot", "job", []),
            ("snapshot", "seal_id", "/private/path"),
            ("snapshot", "seal_id", []),
            ("snapshot", "sha256", []),
            ("snapshot", "byte_length", True),
            ("snapshot", "terminal", []),
            ("snapshot", "source_kind", "CONTROLLER_SEALED_SYNTHETIC"),
            ("terminal", "kind", []),
            ("terminal", "value", -1),
        )
        for target, field, value in faults:
            for corrupt_first in (False, True):
                with self.subTest(target=target, field=field, first=corrupt_first):
                    item = fixture(2)
                    record = item if target == "observation" else getattr(item, target)
                    object.__setattr__(record, field, value)
                    items = (
                        (item, self.items[0])
                        if corrupt_first
                        else (self.items[0], item)
                    )
                    authority = Mock(wraps=self.auth)
                    query = Mock(wraps=self.query)
                    selected = select_candidates(self.grant, items, authority, query)
                    self.assertEqual(selected, ())
                    self.assertIsNone(render_hint(selected, HintCarrier.TEXT))
                    authority.check.assert_not_called()
                    query.query.assert_not_called()

    def test_missing_record_fields_suppress(self) -> None:
        for target, field in (("observation", "job"), ("snapshot", "seal_id")):
            with self.subTest(target=target):
                item = fixture(1)
                record = item if target == "observation" else item.snapshot
                object.__delattr__(record, field)
                query = Mock()
                self.assertEqual(
                    select_candidates(self.grant, (item,), self.auth, query), ()
                )
                query.query.assert_not_called()

    def test_corrupt_receipt_discards_previously_ranked_candidate(self) -> None:
        faults: tuple[tuple[str, object], ...] = (
            ("job", []),
            ("state", []),
            ("snapshot_sha256", []),
            ("ranges", []),
            ("empty_confirmed", "private"),
            ("commit_version", -1),
            ("authority_revision", False),
        )
        for field, value in faults:
            with self.subTest(field=field):
                bad = receipt(self.items[1], ReceiptState.UNCONFIRMED)
                object.__setattr__(bad, field, value)
                query = Mock()
                query.query.side_effect = [
                    Success(receipt(self.items[0], ReceiptState.UNCONFIRMED)),
                    Success(bad),
                ]
                selected = select_candidates(
                    self.grant, self.items[:2], self.auth, query
                )
                self.assertEqual(selected, ())
                self.assertIsNone(render_hint(selected, HintCarrier.META))

    def test_corrupt_nested_receipt_and_missing_success_value_suppress(self) -> None:
        bad_range = ByteRange(0, 1)
        object.__setattr__(bad_range, "stop", [])
        bad = receipt(self.items[0], ReceiptState.UNCONFIRMED)
        object.__setattr__(bad, "ranges", (bad_range,))
        missing = Success(bad)
        object.__delattr__(missing, "value")
        for result in (Success(bad), missing):
            with self.subTest(result_type=type(result)):
                query = Mock()
                query.query.return_value = result
                self.assertEqual(
                    select_candidates(self.grant, self.items[:1], self.auth, query), ()
                )

    def test_deny_complete_and_foreign_results_emit_nothing(self) -> None:
        item = self.items[0]
        for state in (ReceiptState.COMPLETE, ReceiptState.OUTPUT_EXPIRED):
            query = Mock()
            query.query.return_value = Success(receipt(item, state))
            selected = select_candidates(self.grant, (item,), self.auth, query)
            self.assertEqual(selected, ())
            self.assertIsNone(render_hint(selected, HintCarrier.TEXT))
        for grant in (self.grant, FakeHandleAuthority().issue((item.job,))):
            self.auth.revoke(self.grant)
            query = Mock()
            selected = select_candidates(grant, (item,), self.auth, query)
            self.assertEqual(selected, ())
            self.assertIsNone(render_hint(selected, HintCarrier.TEXT))
            query.query.assert_not_called()

    def test_authority_precedes_each_receipt_read_and_ranking_is_stable(self) -> None:
        for item in self.items[:4]:
            self.add(
                item,
                ReceiptState.PARTIAL
                if item == self.items[0]
                else ReceiptState.UNCONFIRMED,
            )
        calls: list[tuple[str, JobRef]] = []

        def check(grant, job, scopes):
            self.assertIs(grant, self.grant)
            self.assertEqual(scopes, frozenset({Scope.OBSERVE}))
            calls.append(("check", job))
            return self.auth.check(grant, job, scopes)

        def query(grant, snapshot):
            self.assertIs(grant, self.grant)
            self.assertEqual(calls[-1], ("check", snapshot.job))
            calls.append(("query", snapshot.job))
            return self.query.query(grant, snapshot)

        for items in permutations(self.items[:4]):
            calls.clear()
            authority = Mock(check=check)
            receipts = Mock(query=query)
            selected = select_candidates(self.grant, items, authority, receipts)
            self.assertEqual(
                tuple(item.job for item in selected),
                tuple(item.job for item in self.items[1:3]),
            )
            self.assertEqual(len(calls), 8)

    def test_candidate_validation_failure_after_port_returns_suppresses(self) -> None:
        def query(grant, snapshot):
            result = receipt(self.items[0], ReceiptState.UNCONFIRMED)
            object.__setattr__(snapshot, "seal_id", "/private/path")
            return Success(result)

        selected = select_candidates(
            self.grant, self.items[:1], self.auth, Mock(query=query)
        )
        self.assertEqual(selected, ())
        self.assertIsNone(render_hint(selected, HintCarrier.TEXT))

    def test_unexpected_validation_errors_are_not_hidden(self) -> None:
        for error in (RuntimeError, TypeError):
            with (
                self.subTest(error=error),
                patch(
                    "binnacle.features.commands.job_awareness.hint_policy.replace",
                    side_effect=error("programming error"),
                ),
                self.assertRaises(error),
            ):
                select_candidates(self.grant, self.items[:1], self.auth, self.query)

    def test_denied_busy_and_running_suppress(self) -> None:
        self.add(self.items[0], ReceiptState.UNCONFIRMED)
        self.auth.revoke(self.grant)
        self.assertEqual(
            select_candidates(self.grant, self.items[:1], self.auth, self.query), ()
        )
        running = Observation(self.items[0].job, ObservationState.RUNNING, None, None)
        self.assertEqual(
            select_candidates(self.grant, (running,), self.auth, self.query), ()
        )

        class BusyAuthority:
            def check(self, grant, job, required_scopes):
                self.required_scopes = required_scopes
                return AuthorityDecision.DENIED

        busy = BusyAuthority()
        self.assertEqual(
            select_candidates(self.grant, self.items[:1], busy, self.query), ()
        )
        self.assertEqual(busy.required_scopes, frozenset({Scope.OBSERVE}))

        class BusyQuery:
            def query(self, grant, snapshot):
                return Failure(BoundaryError(ErrorCode.BUSY))

        active = FakeHandleAuthority()
        active_grant = active.issue((self.items[0].job,))
        self.assertEqual(
            select_candidates(active_grant, self.items[:1], active, BusyQuery()), ()
        )


if __name__ == "__main__":
    unittest.main()
