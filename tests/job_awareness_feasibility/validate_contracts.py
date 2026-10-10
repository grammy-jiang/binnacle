"""Offline Job Awareness evidence validation; never launches experiments.

Usage:
  uv run python docs/job-awareness-feasibility/validate_contracts.py --plan
  uv run python docs/job-awareness-feasibility/validate_contracts.py --run RUN_ROOT
  uv run python docs/job-awareness-feasibility/validate_contracts.py --worker RUN_ROOT W1
  uv run python docs/job-awareness-feasibility/validate_contracts.py --final RUN_ROOT
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from tests.job_awareness_feasibility.plan_validation import plan_check
from tests.job_awareness_feasibility.semantic_evidence import (
    verify_case_inputs,
    verify_csv_evidence_semantics,
    verify_event_evidence_provenance,
    verify_paired_performance_metrics,
    verify_raw_trace_contract,
    verify_w5_trial_schedule,
)
from tests.job_awareness_feasibility.validation_lib import (
    COMMON,
    EXTRA,
    HYPOTHESES,
    LANES,
    ContractError,
    assert_equal,
    fail,
    load_json,
    model_check,
    read_csv,
    read_events,
    safe_relative,
    schema_validate,
    sha256,
)


def run_check(root: Path) -> tuple[dict, dict[str, dict], dict]:
    plan = plan_check()
    run = load_json(root / "run-manifest.json")
    schema_validate(run, "run-manifest.schema.json")
    fixture_path = safe_relative(root, run["fixture_path"])
    fixture = load_json(fixture_path)
    schema_validate(fixture, "fixture-manifest.schema.json")
    assert_equal("fixture hash", sha256(fixture_path), run["fixture_sha256"])
    for k in ("run_id", "source_sha"):
        assert_equal("fixtures." + k, fixture[k], run[k])
    must_have = {
        "J-OK",
        "J-FAIL",
        "J-QUIET",
        "J-UTF8",
        "J-BIG",
        "J-UNKNOWN",
        "J-LOSS",
        "J-EXPIRED",
        "J-CROSS",
        "J-RESTART",
    }
    ids = [j["id"] for j in fixture["fixtures"]]
    if len(set(ids)) != len(ids) or not must_have.issubset(ids):
        fail("fixture IDs missing or duplicated")
    if set(fixture["carriers"]) != {"CONTROL", "META", "TEXT", "STRUCT"}:
        fail("carrier matrix is not frozen")
    for pair in fixture["trial_schedule"]:
        if len(set(pair["arm_order"])) != 2 or set(pair["arm_order"]) != {
            "CONTROL",
            "CANDIDATE",
        }:
            fail("trial order must contain CONTROL and CANDIDATE exactly once")
        if pair["fixture_id"] not in ids:
            fail("trial refers to missing fixture")
    assert_equal("hint byte cap", fixture["limits"]["hint_max_bytes"], 512)
    counts = Counter(x["carrier"] for x in fixture["trial_schedule"])
    for carrier in ("META", "TEXT", "STRUCT"):
        if counts[carrier] < 12:
            fail(f"trial schedule has too few pre-registered pairs for {carrier}")
    preflight = load_json(safe_relative(root, run["s0_preflight_path"]))
    schema_validate(preflight, "s0-preflight.schema.json")
    for key in ("run_id", "source_sha", "docs_sha", "fixture_sha256"):
        assert_equal("S0." + key, preflight[key], run[key])
    model_check(
        preflight["executor"]["model"],
        {"model": plan["s0"]["model"], "effort": plan["s0"]["reasoning_effort"]},
        require_verified=preflight["state"] in ("PREPARED", "PARTIAL"),
    )
    assert_equal(
        "S0 status", preflight["desktop_app_status"], run["desktop_app_status"]
    )
    for file, schema in (
        ("S0/provenance.json", "provenance.schema.json"),
        ("S0/resource-ledger.json", "resource-ledger.schema.json"),
        ("S0/connection-evidence.json", "connection-evidence.schema.json"),
        ("S0/fixture-index.json", "fixture-index.schema.json"),
    ):
        val = load_json(safe_relative(root, file))
        schema_validate(val, schema)
        assert_equal(file + ".run_id", val["run_id"], run["run_id"])
        if file.endswith("fixture-index.json"):
            for item in val["items"]:
                path = safe_relative(root, item["path"])
                assert_equal(
                    item["path"] + ".size", path.stat().st_size, item["size_bytes"]
                )
                assert_equal(item["path"] + ".sha256", sha256(path), item["sha256"])
    safe_relative(root, "S0/readiness.md")
    safe_relative(root, "S0/events.jsonl")
    inputs = {}
    for lane in plan["worker_lanes"]:
        wid = lane["id"]
        entry = run["worker_inputs"][wid]
        path = safe_relative(root, entry["path"])
        assert_equal(wid + ".input_hash", sha256(path), entry["sha256"])
        pkt = load_json(path)
        schema_validate(pkt, "worker-input.schema.json")
        for k in ("run_id", "source_sha", "docs_sha", "fixture_sha256"):
            assert_equal(wid + "." + k, pkt[k], run[k])
        assert_equal(wid + ".worker", pkt["worker"], wid)
        assert_equal(wid + ".scenarios", pkt["scenarios"], lane["scenarios"])
        if wid == "W5":
            request = {
                "model": lane["operator_model_request"],
                "effort": lane["operator_effort_request"],
            }
            subject = {
                "surface": "ChatGPT Chat",
                "model": lane["subject_model_request"],
                "effort": lane["subject_effort_request"],
            }
            assert_equal("W5 subject", pkt["subject_request"], subject)
        else:
            request = {"model": lane["model"], "effort": lane["reasoning_effort"]}
            assert_equal(wid + ".subject_request", pkt["subject_request"], None)
        assert_equal(wid + ".model_request", pkt["model_request"], request)
        if pkt["permissions"]["gui"] != (wid == "W5"):
            fail(wid + ": GUI ownership permission mismatch")
        outputs = [x["ref"] for x in pkt["outputs"]]
        if set(outputs) != set(COMMON + EXTRA[wid]) or len(outputs) != len(
            set(outputs)
        ):
            fail(wid + ": worker input must declare exactly the frozen output formats")
        for item in pkt["inputs"]:
            if item["format"] == "app":
                if item["sha256"] is not None:
                    fail(wid + ": app reference must not embed/hash secret token")
            elif item["sha256"] is not None:
                input_file = safe_relative(root, item["ref"])
                assert_equal(
                    wid + "." + item["ref"] + ".hash",
                    sha256(input_file),
                    item["sha256"],
                )
        inputs[wid] = pkt
    return run, inputs, fixture


def worker_check(
    root: Path,
    wid: str,
    run: dict | None = None,
    inputs: dict[str, dict] | None = None,
    fixture: dict | None = None,
) -> dict:
    if wid not in LANES:
        fail(f"unknown worker: {wid}")
    if run is None or inputs is None or fixture is None:
        run, inputs, fixture = run_check(root)
    base = safe_relative(root, wid, must_exist=False)
    pkt = inputs[wid]
    result = load_json(safe_relative(base, "results.json"))
    schema_validate(result, "worker-result.schema.json")
    for k in ("run_id", "source_sha", "docs_sha", "fixture_sha256"):
        assert_equal(wid + ".result." + k, result[k], run[k])
    assert_equal(wid + ".result.worker", result["worker"], wid)
    assert_equal(
        wid + ".result.input_sha256",
        result["input_sha256"],
        run["worker_inputs"][wid]["sha256"],
    )
    expected = pkt["scenarios"]
    got = [x["id"] for x in result["scenarios"]]
    if len(set(got)) != len(got) or set(got) != set(expected):
        fail(wid + ": results must include exactly the planned case IDs")
    if set(result["hypotheses"]) != set(HYPOTHESES[wid]):
        fail(wid + ": missing/extra hypothesis verdict")
    selection = load_json(safe_relative(base, "model-selection.json"))
    schema_validate(selection, "model-selection.schema.json")
    assert_equal(wid + ".selection.run_id", selection["run_id"], run["run_id"])
    assert_equal(wid + ".selection.worker", selection["worker"], wid)
    assert_equal(
        wid + ".selection.executor", selection["executor"], result["executor"]["model"]
    )
    m = result["executor"]["model"]
    model_check(m, pkt["model_request"], require_verified=result["state"] == "PASS")
    if wid == "W5":
        if selection["subject"] is None or result["subject"] is None:
            fail("W5 requires model-selection receipt for operator and subject")
        assert_equal(
            "W5 subject receipt", selection["subject"], result["subject"]["model"]
        )
        model_check(
            selection["subject"],
            pkt["subject_request"],
            require_verified=result["state"] == "PASS",
        )
    elif selection["subject"] is not None:
        fail(wid + ": a CLI worker cannot claim a ChatGPT subject")
    if wid == "W5":
        if result["subject"] is None:
            fail("W5 must include distinct ChatGPT subject fields even if blocked")
        model_check(
            result["subject"]["model"],
            pkt["subject_request"],
            require_verified=result["state"] == "PASS",
        )
    elif result["subject"] is not None:
        fail(wid + ": non-Desktop worker cannot invent ChatGPT subject observations")
    index = load_json(safe_relative(base, "evidence-index.json"))
    schema_validate(index, "evidence-index.schema.json")
    for k in ("run_id", "source_sha", "fixture_sha256"):
        assert_equal(wid + ".index." + k, index[k], result[k])
    assert_equal(wid + ".index.worker", index["worker"], wid)
    names = set()
    indexed_by_path = {}
    for item in index["artifacts"]:
        path = safe_relative(base, item["path"])
        if item["path"] in names:
            fail(wid + ": duplicate evidence-index path")
        names.add(item["path"])
        indexed_by_path[item["path"]] = item
        assert_equal(item["path"] + ".size", path.stat().st_size, item["size_bytes"])
        assert_equal(item["path"] + ".sha256", sha256(path), item["sha256"])
        if not item["privacy_checked"]:
            fail(wid + ": indexed artifact was not privacy-checked")
    if not {"findings.md", "events.jsonl", "model-selection.json"}.issubset(names):
        fail(wid + ": evidence index missing common mandatory files")
    for ref in selection["observed_selector_evidence_refs"]:
        if ref not in names:
            fail(wid + ": model selection has unindexed selector evidence")
    if result["state"] == "PASS" and not selection["observed_selector_evidence_refs"]:
        fail(wid + ": PASS requires independent selector evidence")
    for selected in (selection["executor"], selection["subject"]):
        if selected and selected["verification"] == "VERIFIED":
            ref = selected["verification_evidence_ref"]
            if (
                ref not in names
                or ref not in selection["observed_selector_evidence_refs"]
            ):
                fail(
                    wid
                    + ": verified model selection has no matching indexed selector proof"
                )
    event_map = read_events(
        safe_relative(base, "events.jsonl"), wid, run["run_id"], set(expected)
    )
    for case in result["scenarios"]:
        verify_case_inputs(case, pkt, wid)
        if case["status"] in ("PASS", "FAIL"):
            if not case["event_ids"] or not case["evidence_refs"]:
                fail(
                    wid
                    + "/"
                    + case["id"]
                    + ": executed case needs event IDs and raw evidence"
                )
        else:
            if case["status"] in ("BLOCKED", "NOT_RUN") and not case["blocking_reason"]:
                fail(wid + "/" + case["id"] + ": blocked/not run requires reason")
        for ref in case["evidence_refs"]:
            if ref not in names:
                fail(wid + "/" + case["id"] + ": unindexed evidence " + ref)
        for eid in case["event_ids"]:
            if eid not in event_map or event_map[eid]["scenario_id"] != case["id"]:
                fail(wid + "/" + case["id"] + ": missing or wrong event " + eid)
        declared_layers = {event_map[eid]["layer"] for eid in case["event_ids"]}
        if not set(case["proof_layers"]).issubset(declared_layers):
            fail(
                wid + "/" + case["id"] + ": claimed proof layers lack event references"
            )
        verify_raw_trace_contract(wid, case, base, names, event_map)
    for item in event_map.values():
        if (
            item["raw_artifact_ref"] is not None
            and item["raw_artifact_ref"] not in names
        ):
            fail(wid + ": event raw artifact is not indexed")
    verify_event_evidence_provenance(wid, event_map, indexed_by_path)
    if result["state"] == "PASS" and any(
        x["status"] != "PASS" for x in result["scenarios"]
    ):
        fail(wid + ": worker PASS cannot contain unfinished/failing test scenarios")
    records = read_csv(safe_relative(base, EXTRA[wid][0]), wid)
    if result["state"] == "PASS" and not records:
        fail(wid + ": PASS requires raw evidence rows")
    verify_csv_evidence_semantics(wid, records, result)
    for row in records:
        if row["trace_ref"] and row["trace_ref"] not in names:
            fail(wid + ": unindexed CSV trace_ref " + row["trace_ref"])
    if (
        wid == "W2"
        and "I-TURN" in {x["id"] for x in result["scenarios"] if x["status"] == "PASS"}
        and sum(x["case_id"] == "I-TURN" for x in records) < 90
    ):
        fail("W2 I-TURN requires >=90 attributed mock calls")
    if wid == "W3":
        receipt = load_json(safe_relative(base, "receipt-verdict.json"))
        schema_validate(receipt, "receipt-verdict.schema.json")
        if {x["name"] for x in receipt["variants"]} != {
            "SERVER_FETCH",
            "NEXT_TRUSTED_CALL",
            "EXPLICIT_RECEIPT",
        }:
            fail("W3 receipt verdict must compare all three options")
    if wid == "W4":
        metrics = load_json(safe_relative(base, "metrics.json"))
        schema_validate(metrics, "metrics.schema.json")
        if set(metrics["cohorts"]) != {0, 1, 10, 100}:
            fail("W4 performance output must cover all four cohort sizes")
        cases = {x["id"]: x["status"] for x in result["scenarios"]}
        if cases["P-BASE"] == "PASS" and {
            int(x["cohort_jobs"]) for x in records if x["case_id"] == "P-BASE"
        } != {0, 1, 10, 100}:
            fail("W4 passing baseline omitted cohort")
        if (
            cases["P-LATENCY"] == "PASS"
            and len(
                {int(x["round_index"]) for x in records if x["case_id"] == "P-LATENCY"}
            )
            < 3
        ):
            fail("W4 passing latency lacks 3 randomized rounds")
        if cases["P-LATENCY"] == "PASS":
            verify_paired_performance_metrics(records, metrics)
    if wid == "W5":
        surface = load_json(safe_relative(base, "surface-capability.json"))
        schema_validate(surface, "desktop-surface.schema.json")
        model_check(
            surface["operator"],
            pkt["model_request"],
            require_verified=result["state"] == "PASS",
        )
        model_check(
            surface["subject"],
            pkt["subject_request"],
            require_verified=result["state"] == "PASS",
        )
        assert_equal(
            "W5 operator UI selector", surface["operator"], selection["executor"]
        )
        assert_equal("W5 subject UI selector", surface["subject"], selection["subject"])
        w5_cases = {x["id"]: x["status"] for x in result["scenarios"]}
        if w5_cases["U-CANARY"] == "PASS" and (
            surface["surface"] != "VERIFIED_CHAT_MODE"
            or not surface["chat_mcp_tool_invoked"]
        ):
            fail("W5 U-CANARY PASS requires real Chat mode MCP proof")
        if w5_cases["U-PAIR"] == "PASS":
            subject_result = result["subject"]
            if subject_result is None:
                fail("W5 paired-trial subject result is missing")
            model_check(
                result["executor"]["model"], pkt["model_request"], require_verified=True
            )
            model_check(
                subject_result["model"],
                pkt["subject_request"],
                require_verified=True,
            )
            if (
                surface["surface"] != "VERIFIED_CHAT_MODE"
                or not surface["chat_model_locked"]
            ):
                fail("W5 U-PAIR PASS requires pinned genuine Chat mode")
        if result["state"] == "PASS":
            if (
                surface["surface"] != "VERIFIED_CHAT_MODE"
                or not surface["chat_mcp_tool_invoked"]
            ):
                fail("W5 PASS requires actual Chat mode with verified test MCP call")
            if not surface["chat_model_locked"]:
                fail("W5 PASS requires pinned ChatGPT model and effort")
        if w5_cases["U-PAIR"] == "PASS":
            verify_w5_trial_schedule(records, fixture, pkt)
    return result


def final_check(root: Path) -> dict:
    run, inputs, fixture = run_check(root)
    reports = {wid: worker_check(root, wid, run, inputs, fixture) for wid in LANES}
    for file, schema in (
        ("supervisor/dispatch-ledger.json", "dispatch-ledger.schema.json"),
        ("supervisor/collection-report.json", "collection-report.schema.json"),
    ):
        val = load_json(safe_relative(root, file))
        schema_validate(val, schema)
        assert_equal(file + ".run_id", val["run_id"], run["run_id"])
    decision = load_json(safe_relative(root, "decision.json"))
    schema_validate(decision, "manager-decision.schema.json")
    for key in ("run_id", "source_sha", "docs_sha", "fixture_sha256"):
        assert_equal("manager." + key, decision[key], run[key])
    safe_relative(root, "MANAGER-SUMMARY.md")
    safe_relative(root, "supervisor/reconciliation.md")
    for wid, result in reports.items():
        assert_equal(
            "manager." + wid + ".status",
            decision["workers"][wid]["status"],
            result["state"],
        )
        expected_verified = result["executor"]["model"][
            "verification"
        ] == "VERIFIED" and (
            wid != "W5"
            or (
                result["subject"] is not None
                and result["subject"]["model"]["verification"] == "VERIFIED"
            )
        )
        assert_equal(
            "manager." + wid + ".model_verified",
            decision["workers"][wid]["model_verified"],
            expected_verified,
        )
    if decision["decision"] == "GO_TO_IMPLEMENTATION_PLAN":
        if any(x["status"] != "PASS" for x in decision["gates"].values()):
            fail("GO requires G0-G7 PASS")
        if any(x["state"] != "PASS" for x in reports.values()):
            fail("GO requires W1-W5 PASS")
    return decision


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--plan",
        action="store_true",
        help="Validate static plan/schema/prompts without a run",
    )
    mode.add_argument(
        "--run", type=Path, metavar="RUN_ROOT", help="Validate frozen S0 inputs"
    )
    mode.add_argument(
        "--worker",
        nargs=2,
        metavar=("RUN_ROOT", "Wn"),
        help="Validate S0 and an individual worker",
    )
    mode.add_argument(
        "--final",
        type=Path,
        metavar="RUN_ROOT",
        help="Validate final integrated evidence",
    )
    args = cli.parse_args()
    try:
        if args.plan:
            plan = plan_check()
            print("PASS:static-plan", len(plan["worker_lanes"]), "independent lanes")
        elif args.run:
            run, inputs, fixture = run_check(args.run)
            print(
                "PASS:S0-structure",
                run["run_id"],
                run["status"],
                "inputs",
                len(inputs),
                "fixtures",
                len(fixture["fixtures"]),
            )
        elif args.worker:
            root, wid = args.worker
            result = worker_check(Path(root), wid)
            print(
                "PASS:worker-structure",
                wid,
                result["state"],
                len(result["scenarios"]),
                "cases",
            )
        else:
            result = final_check(args.final)
            print("PASS:final-structure", result["run_id"], result["decision"])
    except (ContractError, KeyError, TypeError, ValueError, OSError) as exc:
        print("FAIL:CONTRACT", exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
