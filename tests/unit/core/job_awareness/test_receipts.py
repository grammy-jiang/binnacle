"""Pure receipt truth over canonical pages, not output delivery."""

import importlib
import unittest

from binnacle.features.commands.job_awareness.models import (
    ByteRange,
    JobRef,
    OutputSnapshot,
    ReceiptState,
    SourceKind,
    TerminalKind,
    TerminalOutcome,
)


def snapshot(length=32769):
    return OutputSnapshot(
        JobRef("ja1_" + "1" * 32, "2" * 12, "g1_" + "3" * 32),
        "a" * 64,
        length,
        TerminalOutcome(TerminalKind.EXIT_CODE, 1),
        1,
        10000,
        SourceKind.CONTROLLER_SEALED_SYNTHETIC,
        "4" * 32,
    )


class ReceiptPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec(
                "binnacle.features.commands.job_awareness.receipts"
            ),
            "receipt policy missing",
        )
        self.policy = importlib.import_module(
            "binnacle.features.commands.job_awareness.receipts"
        )

    def test_canonical_page_union(self):
        s = snapshot()
        receipt = self.policy.project_receipt(s, (32768, 0, 0), 1, 1, 2)
        self.assertEqual(receipt.state, ReceiptState.PARTIAL)
        self.assertEqual(receipt.ranges, (ByteRange(0, 16384), ByteRange(32768, 32769)))
        self.assertEqual(
            self.policy.project_receipt(s, (32768, 16384, 0), 2, 1, 2).state,
            ReceiptState.COMPLETE,
        )
        for bad in [(1,), (-1,), (32769,), (True,)]:
            with self.assertRaises(ValueError):
                self.policy.project_receipt(s, bad, 1, 1, 2)

    def test_empty_and_failed_terminal(self):
        s = snapshot(0)
        self.assertEqual(
            self.policy.project_receipt(s, (), 0, 1, 2).state, ReceiptState.UNCONFIRMED
        )
        result = self.policy.project_receipt(s, (0,), 1, 1, 2)
        self.assertEqual(result.state, ReceiptState.COMPLETE)
        self.assertTrue(result.empty_confirmed)
        self.assertEqual(
            self.policy.project_receipt(s, (0,), 1, 1, 10000).state,
            ReceiptState.OUTPUT_EXPIRED,
        )
