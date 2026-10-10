"""Contract-validation tests: synthetic inputs, never real MCP/ChatGPT calls."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "docs" / "job-awareness-feasibility"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests.job_awareness_feasibility.sample_builder import build_sample, save_json
from tests.job_awareness_feasibility.semantic_evidence import (
    verify_case_inputs,
    verify_csv_evidence_semantics,
    verify_paired_performance_metrics,
    verify_raw_trace_contract,
    verify_w5_trial_schedule,
)
from tests.job_awareness_feasibility.validate_contracts import (
    final_check,
    plan_check,
    run_check,
    worker_check,
)
from tests.job_awareness_feasibility.validation_lib import (
    ContractError,
    load_json,
    model_check,
    read_csv,
    safe_relative,
    schema_validate,
    sha256,
)


class ContractValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ja-validation-sample-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        build_sample(self.root)

    def modify(self, relative, fn):
        path = self.root / relative
        value = load_json(path)
        fn(value)
        save_json(path, value)

    def test_static_plan_is_valid(self):
        self.assertEqual(len(plan_check()["worker_lanes"]), 5)

    def test_positive_synthetic_run_and_all_worker_structures(self):
        run, inputs, fixture = run_check(self.root)
        self.assertEqual(run["status"], "FROZEN")
        self.assertEqual(len(inputs), 5)
        self.assertEqual(len(fixture["fixtures"]), 10)
        for wid in ("W1", "W2", "W3", "W4", "W5"):
            self.assertEqual(worker_check(self.root, wid)["state"], "NOT_RUN")
        self.assertEqual(final_check(self.root)["decision"], "INCONCLUSIVE")

    def test_invalid_fixture_hash_is_detected(self):
        self.modify("fixtures/fixture-manifest.json", lambda x: x.update(seed=77))
        with self.assertRaisesRegex(ContractError, "fixture hash"):
            run_check(self.root)

    def test_missing_s0_packet_is_detected(self):
        (self.root / "inputs" / "W3.input.json").unlink()
        with self.assertRaises(ContractError):
            run_check(self.root)

    def test_mismatched_model_handoff_is_detected(self):
        self.modify(
            "inputs/W1.input.json",
            lambda x: x["model_request"].update(model="DEFAULT_WRONG_MODEL"),
        )
        # Fails the cryptographic packet seal before model fields can be trusted.
        with self.assertRaisesRegex(ContractError, "input_hash"):
            run_check(self.root)

    def test_declared_model_is_checked_even_if_packet_seal_is_recomputed(self):
        path = self.root / "inputs" / "W2.input.json"
        self.modify(
            "inputs/W2.input.json",
            lambda x: x["model_request"].update(effort="low"),
        )
        self.modify(
            "run-manifest.json",
            lambda x: x["worker_inputs"]["W2"].update(sha256=sha256(path)),
        )
        with self.assertRaisesRegex(ContractError, "model_request"):
            run_check(self.root)

    def test_worker_requires_model_selection_receipt(self):
        (self.root / "W2/model-selection.json").unlink()
        with self.assertRaises(ContractError):
            worker_check(self.root, "W2")

    def test_model_selection_receipt_cannot_conflict_with_final_results(self):
        self.modify(
            "W3/model-selection.json",
            lambda x: x["executor"].update(requested_effort="medium"),
        )
        with self.assertRaises(ContractError):
            worker_check(self.root, "W3")

    def test_missing_s0_event_output_fails_preflight(self):
        (self.root / "S0/events.jsonl").unlink()
        with self.assertRaises(ContractError):
            run_check(self.root)

    def test_executed_case_without_exact_raw_trace_is_rejected(self):
        case = {"id": "M-META", "status": "PASS", "evidence_refs": []}
        with self.assertRaisesRegex(ContractError, "mandatory raw trace"):
            verify_raw_trace_contract("W1", case, self.root / "W1", set(), {})

    def test_undeclared_worker_case_input_is_rejected(self):
        packet = load_json(self.root / "inputs/W1.input.json")
        with self.assertRaisesRegex(ContractError, "undeclared case input"):
            verify_case_inputs(
                {"id": "M-META", "input_refs": ["../../secret_file"]}, packet, "W1"
            )

    def test_server_served_without_client_receipt_cannot_be_acknowledged(self):
        rows = [
            {
                "case_id": "R-ACK",
                "acknowledged": "true",
                "client_received": "",
                "has_more": "false",
            }
        ]
        result = load_json(self.root / "W3/results.json")
        with self.assertRaisesRegex(ContractError, "unconfirmed client receipt"):
            verify_csv_evidence_semantics("W3", rows, result)

    def test_w1_cannot_claim_that_meta_was_model_visible(self):
        rows = [{"model_visibility": "MODEL_VISIBLE"}]
        result = load_json(self.root / "W1/results.json")
        with self.assertRaisesRegex(ContractError, "may not claim model visibility"):
            verify_csv_evidence_semantics("W1", rows, result)

    def test_w5_cannot_claim_model_action_without_client_receipt(self):
        rows = [
            {
                "server_sent": "true",
                "client_received": "",
                "model_used": "true",
                "fully_drained": "false",
                "correct_fetch": "false",
                "meaningful_followup": "false",
            }
        ]
        result = load_json(self.root / "W5/results.json")
        with self.assertRaisesRegex(
            ContractError, "no confirmed client-visible evidence"
        ):
            verify_csv_evidence_semantics("W5", rows, result)

    def _performance_rows(self):
        rows = []
        for i, delta in enumerate((-2.0, 1.0, 4.0), 1):
            for arm, ms in (("CONTROL", 10.0), ("CANDIDATE", 10.0 + delta)):
                rows.append(
                    {
                        "case_id": "P-LATENCY",
                        "pair_id": f"pair{i}",
                        "carrier": "TEXT",
                        "cohort_jobs": "1",
                        "round_index": str(i),
                        "arm": arm,
                        "processing_ms": str(ms),
                    }
                )
        return rows

    def test_signed_paired_latency_percentiles_recalculate_correctly(self):
        rows = self._performance_rows()
        metrics = {
            "measurements": [
                {
                    "carrier": "TEXT",
                    "cohort_jobs": 1,
                    "sample_count": 3,
                    "p50_ms": 1.0,
                    "p95_ms": 4.0,
                    "p99_ms": 4.0,
                }
            ]
        }
        verify_paired_performance_metrics(rows, metrics)
        metrics["measurements"][0]["p95_ms"] = 9.0
        with self.assertRaisesRegex(ContractError, "signed nearest-rank"):
            verify_paired_performance_metrics(rows, metrics)

    def test_missing_paired_control_is_rejected(self):
        rows = [
            x
            for x in self._performance_rows()
            if not (x["pair_id"] == "pair2" and x["arm"] == "CONTROL")
        ]
        metrics = {"measurements": []}
        with self.assertRaisesRegex(ContractError, "missing control/candidate"):
            verify_paired_performance_metrics(rows, metrics)

    def test_negative_latency_values_are_valid_metrics(self):
        data = load_json(self.root / "W4/metrics.json")
        data["measurements"] = [
            {
                "cohort_jobs": 1,
                "carrier": "TEXT",
                "sample_count": 2,
                "p50_ms": -2.1,
                "p95_ms": -0.5,
                "p99_ms": -0.5,
                "max_reminder_bytes": 20,
                "token_method": "MEASURED",
                "token_count": 2,
                "host_load_details": "synthetic",
                "inconclusive_reason": None,
            }
        ]
        schema_validate(data, "metrics.schema.json")

    def _w5_pair_rows(self):
        fixture = load_json(self.root / "fixtures/fixture-manifest.json")
        pkt = load_json(self.root / "inputs/W5.input.json")
        rows = []
        for item in fixture["trial_schedule"]:
            if item["carrier"] != "TEXT":
                continue
            for pos, arm in enumerate(item["arm_order"], 1):
                rows.append(
                    {
                        "trial_id": item["pair_id"] + ("-" + arm),
                        "pair_id": item["pair_id"],
                        "carrier": item["carrier"],
                        "arm": arm,
                        "arm_order": str(pos),
                        "chat_label": item["chat_label"],
                        "subject_model": "GPT-6",
                        "subject_effort": "Medium",
                        "model_verified": "true",
                    }
                )
        return fixture, pkt, rows

    def test_w5_frozen_arm_order_must_match(self):
        fixture, pkt, rows = self._w5_pair_rows()
        verify_w5_trial_schedule(rows, fixture, pkt)
        rows[0]["arm_order"] = "2" if rows[0]["arm_order"] == "1" else "1"
        with self.assertRaisesRegex(ContractError, "pre-registered order"):
            verify_w5_trial_schedule(rows, fixture, pkt)

    def test_w5_model_effort_drift_is_rejected(self):
        fixture, pkt, rows = self._w5_pair_rows()
        rows[0]["subject_effort"] = "High"
        with self.assertRaisesRegex(ContractError, "model/effort drift"):
            verify_w5_trial_schedule(rows, fixture, pkt)

    def test_worker_missing_case_is_detected(self):
        self.modify(
            "W1/results.json",
            lambda x: x["scenarios"].pop(),
        )
        with self.assertRaisesRegex(ContractError, "exactly the planned"):
            worker_check(self.root, "W1")

    def test_worker_forged_pass_with_unverified_model_is_rejected(self):
        self.modify("W4/results.json", lambda x: x.update(state="PASS"))
        with self.assertRaisesRegex(ContractError, "verified effective model"):
            worker_check(self.root, "W4")

    def test_referenced_evidence_mutation_is_detected(self):
        path = self.root / "W2/findings.md"
        original = path.read_bytes()
        path.write_bytes(b"X" + original[1:])
        with self.assertRaisesRegex(ContractError, "sha256"):
            worker_check(self.root, "W2")

    def test_missing_indexed_artifact_is_detected(self):
        (self.root / "W3/receipt-verdict.json").unlink()
        with self.assertRaises(ContractError):
            worker_check(self.root, "W3")

    def test_malformed_csv_header_is_detected(self):
        file = self.root / "W4/latency-samples.csv"
        file.write_text("wrong,header\n", encoding="utf-8")
        # Update the index so this test reaches the strict header validation.
        self.modify(
            "W4/evidence-index.json",
            lambda x: next(
                a.update(sha256=sha256(file), size_bytes=file.stat().st_size)
                for a in x["artifacts"]
                if a["path"] == "latency-samples.csv"
            ),
        )
        with self.assertRaisesRegex(ContractError, "CSV header"):
            worker_check(self.root, "W4")

    def test_invalid_raw_csv_boolean_is_detected(self):
        p = self.root / "W1/carrier-matrix.csv"
        with p.open("a", encoding="utf-8") as out:
            out.write("M-META,META,modern,yes,true,true,NOT_TESTED,wire/M-META.json\n")
        with self.assertRaisesRegex(ContractError, "boolean must be true/false"):
            read_csv(p, "W1")

    def test_duplicate_json_keys_are_rejected(self):
        p = self.root / "W1/results.json"
        p.write_text('{"state":"PASS","state":"NOT_RUN"}', encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "duplicate JSON key"):
            load_json(p)

    def test_path_escape_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "unsafe artifact reference"):
            safe_relative(self.root, "../outside.md", must_exist=False)

    def test_symlink_escape_is_rejected(self):
        p = self.root / "W1/link"
        p.symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(ContractError):
            safe_relative(self.root / "W1", "link/findings.md", must_exist=False)

    def test_model_pass_requires_selector_proof_and_no_fallback(self):
        valid = {
            "requested_model": "opus",
            "requested_effort": "high",
            "effective_model": "opus",
            "effective_effort": "high",
            "verification": "VERIFIED",
            "verification_evidence_ref": "selection.json",
            "fallback_used": False,
            "model_match_verified": True,
            "effort_match_verified": True,
        }
        model_check(valid, {"model": "opus", "effort": "high"}, require_verified=True)
        valid["fallback_used"] = True
        with self.assertRaisesRegex(ContractError, "fallback"):
            model_check(
                valid, {"model": "opus", "effort": "high"}, require_verified=True
            )

    def test_schema_catches_unreported_model_verification(self):
        d = load_json(self.root / "W5/surface-capability.json")
        del d["subject"]["model_match_verified"]
        with self.assertRaises(ContractError):
            schema_validate(d, "desktop-surface.schema.json")

    def test_unsupported_chat_ui_cannot_claim_go(self):
        self.modify(
            "decision.json", lambda x: x.update(decision="GO_TO_IMPLEMENTATION_PLAN")
        )
        with self.assertRaisesRegex(ContractError, "G0-G7 PASS"):
            final_check(self.root)

    def test_w5_unverified_chat_cannot_be_called_pass(self):
        self.modify("W5/results.json", lambda x: x.update(state="PASS"))
        with self.assertRaisesRegex(ContractError, "verified effective model"):
            worker_check(self.root, "W5")


if __name__ == "__main__":
    unittest.main()
