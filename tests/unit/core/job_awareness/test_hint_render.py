"""Bounded hint text tests."""

import unittest
from typing import cast
from unittest.mock import patch

from binnacle.features.commands.job_awareness.hint_render import (
    _within_utf8_budget,
    render_hint,
)
from binnacle.features.commands.job_awareness.models import (
    CandidateCategory,
    HintCarrier,
    JobRef,
    ReminderCandidate,
)


def candidate(number: int, category=CandidateCategory.TERMINAL_UNCONFIRMED):
    return ReminderCandidate(
        JobRef("ja1_" + "a" * 32, f"{number:012x}", "g1_" + "b" * 32),
        category,
        "c" * 32,
        None if category is CandidateCategory.RUNNING else "d" * 64,
    )


class HintRenderTests(unittest.TestCase):
    def test_utf8_byte_cap(self) -> None:
        self.assertTrue(_within_utf8_budget("é" * 256))
        self.assertFalse(_within_utf8_budget("é" * 255 + "界"))
        self.assertTrue(_within_utf8_budget("😀" * 128))
        self.assertFalse(_within_utf8_budget("e\u0301" * 171))
        self.assertFalse(_within_utf8_budget("\ud800"))
        hint = render_hint((candidate(1), candidate(2)), HintCarrier.META)
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint.utf8_bytes, len(hint.text.encode("utf-8")))
        self.assertLessEqual(hint.utf8_bytes, 512)
        self.assertIn(candidate(1).job.canonical_key, hint.text)
        self.assertEqual(render_hint((candidate(1),) * 3, HintCarrier.META), None)

    def test_no_private_data(self) -> None:
        hint = render_hint((candidate(1),), HintCarrier.TEXT)
        assert hint is not None
        for secret in ("/private/path", "SIGNED_PROOF", "raw log", "d" * 64):
            self.assertNotIn(secret, hint.text)
        self.assertEqual(
            render_hint((cast(ReminderCandidate, object()),), HintCarrier.TEXT), None
        )
        self.assertEqual(render_hint((), HintCarrier.TEXT), None)

    def test_unsupported_category_and_carrier(self) -> None:
        self.assertEqual(
            render_hint((candidate(1, CandidateCategory.RUNNING),), HintCarrier.META),
            None,
        )
        self.assertEqual(render_hint((candidate(1),), cast(HintCarrier, "META")), None)

    def test_unicode_job_id_rejected_at_frozen_type_boundary(self) -> None:
        with self.assertRaises(ValueError):
            JobRef("ja1_" + "a" * 32, "界" * 12, "g1_" + "b" * 32)

    def test_corrupted_candidate_identifier_is_not_reflected(self) -> None:
        item = candidate(1)
        object.__setattr__(item.job, "job_id", "../private")
        self.assertIsNone(render_hint((item,), HintCarrier.TEXT))

    def test_duplicate_and_wrong_job_type_suppress(self) -> None:
        item = candidate(1)
        self.assertIsNone(render_hint((item, item), HintCarrier.TEXT))
        object.__setattr__(item, "job", "../private")
        self.assertIsNone(render_hint((item,), HintCarrier.TEXT))

    def test_corrupt_candidate_suppresses_entire_hint(self) -> None:
        faults: tuple[tuple[str, object], ...] = (
            ("category", []),
            ("category", "TERMINAL_UNCONFIRMED"),
            ("observation_epoch", "/private/path"),
            ("observation_epoch", []),
            ("snapshot_sha256", "/private/path"),
            ("snapshot_sha256", None),
            ("job", []),
        )
        for field, value in faults:
            for carrier in HintCarrier:
                with self.subTest(field=field, carrier=carrier):
                    item = candidate(2)
                    object.__setattr__(item, field, value)
                    self.assertIsNone(render_hint((candidate(1), item), carrier))

    def test_missing_candidate_fields_suppress(self) -> None:
        for field in ("job", "category", "observation_epoch", "snapshot_sha256"):
            with self.subTest(field=field):
                item = candidate(1)
                object.__delattr__(item, field)
                self.assertIsNone(render_hint((item,), HintCarrier.TEXT))

    def test_corrupt_job_fields_suppress_before_hashing(self) -> None:
        for field in ("run_namespace", "job_id", "incarnation"):
            with self.subTest(field=field):
                item = candidate(1)
                object.__setattr__(item.job, field, [])
                self.assertIsNone(render_hint((item,), HintCarrier.TEXT))

    def test_unexpected_validation_errors_are_not_hidden(self) -> None:
        for error in (RuntimeError, TypeError):
            with (
                self.subTest(error=error),
                patch(
                    "binnacle.features.commands.job_awareness.hint_render.replace",
                    side_effect=error("programming error"),
                ),
                self.assertRaises(error),
            ):
                render_hint((candidate(1),), HintCarrier.TEXT)

    def test_budget_rejection_suppresses_whole_hint(self) -> None:
        with patch(
            "binnacle.features.commands.job_awareness.hint_render._within_utf8_budget",
            return_value=False,
        ):
            self.assertIsNone(render_hint((candidate(1),), HintCarrier.TEXT))


if __name__ == "__main__":
    unittest.main()
