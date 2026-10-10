"""Semantic checks linking cases to frozen IO, raw traces and proof layers.

These catch internal contradictions. They cannot independently authenticate a
ChatGPT screenshot or convert a server-sent packet into client receipt.
"""

from __future__ import annotations

from collections import defaultdict
from math import ceil, isclose
from pathlib import Path

from tests.job_awareness_feasibility.validation_lib import (
    BASE,
    fail,
    load_json,
    safe_relative,
    schema_validate,
)


def verify_raw_trace_contract(
    worker: str,
    case: dict,
    base: Path,
    indexed: set[str],
    event_map: dict,
) -> None:
    if case["status"] not in ("PASS", "FAIL"):
        return
    io = load_json(BASE / "step-io.json")
    planned = next(item for item in io["workers"][worker] if item["id"] == case["id"])
    raw_prefixes = {
        "W1": "wire/",
        "W2": "identity/",
        "W3": "receipt/",
        "W4": "perf/",
        "W5": "ui/",
    }
    expected = [
        row["ref"].removeprefix(worker + "/")
        for row in planned["outputs"]
        if row["ref"].startswith(worker + "/" + raw_prefixes[worker])
        and row["format"] == "json"
    ]
    if not expected:
        fail(worker + "/" + case["id"] + ": no planned raw trace")
    # Unsupported structured carriers still need a schema-valid diagnostic.
    if case["id"] == "M-STRUCT" and "wire/M-STRUCT.json" not in indexed:
        expected = ["unsupported/M-STRUCT.json"]
    for filename in expected:
        if filename not in indexed or filename not in case["evidence_refs"]:
            fail(
                worker
                + "/"
                + case["id"]
                + ": mandatory raw trace not indexed: "
                + filename
            )
        trace = load_json(safe_relative(base, filename))
        schema_validate(trace, "trace.schema.json")
        if trace["worker"] != worker or trace["scenario_id"] != case["id"]:
            fail(worker + "/" + case["id"] + ": raw trace has wrong owner/case")
        for eid in trace["event_ids"]:
            if eid not in event_map or event_map[eid]["scenario_id"] != case["id"]:
                fail(worker + "/" + case["id"] + ": raw trace references wrong event")


def verify_event_evidence_provenance(
    worker: str,
    events: dict,
    indexed_by_path: dict,
) -> None:
    for item in events.values():
        layer = item["layer"]
        ref = item["raw_artifact_ref"]
        if layer in ("client_received", "model_used", "workflow_continued") and not ref:
            fail(worker + ": model/client proof event requires source artifact")
        if not ref:
            continue
        artifact = indexed_by_path.get(ref)
        if artifact is None:
            fail(worker + ": event raw evidence missing from index")
        if layer != artifact["layer"] and layer in (
            "client_received",
            "model_used",
            "workflow_continued",
        ):
            fail(worker + ": proof claims stronger observation than indexed evidence")


def verify_csv_evidence_semantics(
    worker: str, records: list[dict], result: dict
) -> None:
    cases = {x["id"]: x["status"] for x in result["scenarios"]}
    if worker == "W1" and any(
        x["model_visibility"] == "MODEL_VISIBLE" for x in records
    ):
        fail("W1 may not claim model visibility (only W5 can observe it)")
    if (
        worker == "W2"
        and cases.get("I-LEAK") == "PASS"
        and any(x["leak"] == "true" and x["case_id"] == "I-LEAK" for x in records)
    ):
        fail("W2 reports PASS despite actual cross-chat leak")
    if worker == "W3":
        for row in records:
            if row["acknowledged"] == "true" and row["client_received"] != "true":
                fail("W3 falsely acknowledges unconfirmed client receipt")
            if row["acknowledged"] == "true" and row["has_more"] == "true":
                fail("W3 acknowledged an incompletely drained result")
    if worker == "W4":
        for row in records:
            if (
                row["reminder_bytes"]
                and int(row["reminder_bytes"]) > 512
                and cases.get(row["case_id"]) == "PASS"
            ):
                fail("W4 cannot PASS a case with reminder over 512 bytes")
    if worker == "W5":
        for row in records:
            if row["client_received"] == "true" and row["server_sent"] != "true":
                fail("W5 client receipt cannot precede an emitted reply")
            if row["model_used"] == "true" and row["client_received"] != "true":
                fail("W5 model action has no confirmed client-visible evidence")
            if row["fully_drained"] == "true" and row["correct_fetch"] != "true":
                fail("W5 cannot finish drain without correct job-specific read")
            if row["meaningful_followup"] == "true" and row["correct_fetch"] != "true":
                fail("W5 follow-up is not proven after correct job result")


def verify_case_inputs(case: dict, packet: dict, worker: str) -> None:
    provided = {x["ref"] for x in packet["inputs"]}
    for ref in case["input_refs"]:
        normalized = ref.split("#", 1)[0]
        if normalized not in provided and not normalized.startswith("source://"):
            fail(worker + "/" + case["id"] + ": undeclared case input: " + ref)


def verify_paired_performance_metrics(records: list[dict], metrics: dict) -> None:
    """Recalculate W4 incremental percentiles from actual matched raw samples."""
    groups: dict[tuple, dict] = defaultdict(dict)
    for row in records:
        if row["case_id"] != "P-LATENCY":
            continue
        if not row["pair_id"] or not row["processing_ms"]:
            fail("W4 P-LATENCY requires pair_id and measured processing_ms")
        key = (
            row["carrier"],
            int(row["cohort_jobs"]),
            int(row["round_index"]),
            row["pair_id"],
        )
        arm = row["arm"]
        if arm not in ("CONTROL", "CANDIDATE") or arm in groups[key]:
            fail(f"W4 duplicated/invalid paired arm: {key}")
        groups[key][arm] = float(row["processing_ms"])
    if not groups:
        fail("W4 P-LATENCY passed with no raw paired timing samples")
    deltas = defaultdict(list)
    for key, arms in groups.items():
        if set(arms) != {"CONTROL", "CANDIDATE"}:
            fail(f"W4 missing control/candidate arm for {key}")
        deltas[key[:2]].append(arms["CANDIDATE"] - arms["CONTROL"])
    metrics_map = {}
    for entry in metrics["measurements"]:
        metric_key = (entry["carrier"], entry["cohort_jobs"])
        if metric_key in metrics_map:
            fail(f"W4 duplicate metrics group: {metric_key}")
        metrics_map[metric_key] = entry
    for delta_key, group in deltas.items():
        if delta_key not in metrics_map:
            fail(f"W4 raw pair group absent from metrics.json: {delta_key}")
        values = sorted(group)
        entry = metrics_map[delta_key]
        if entry["sample_count"] != len(values):
            fail(f"W4 sample_count mismatch for {delta_key}")
        for label, percent in (("p50_ms", 50), ("p95_ms", 95), ("p99_ms", 99)):
            expected = values[max(0, ceil(percent / 100 * len(values)) - 1)]
            found = entry[label]
            if found is None or not isclose(found, expected, abs_tol=0.001, rel_tol=0):
                fail(
                    f"W4 {label} differs from signed nearest-rank raw sample deltas for {delta_key}"
                )


def verify_w5_trial_schedule(records: list[dict], fixture: dict, packet: dict) -> None:
    """Verify frozen S0 pair/arm order; this does not grade model behavior."""
    by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    seen_trial_ids: set[str] = set()
    for row in records:
        key = (row["carrier"], row["pair_id"])
        by_pair[key].append(row)
        if row["trial_id"] in seen_trial_ids:
            fail("W5 duplicate trial_id")
        seen_trial_ids.add(row["trial_id"])
        if (
            row["subject_model"] != packet["subject_request"]["model"]
            or row["subject_effort"] != packet["subject_request"]["effort"]
        ):
            fail("W5 paired-trial subject model/effort drift")
        if row["model_verified"] != "true":
            fail("W5 paired-trial subject model not verified")
    schedule = {(x["carrier"], x["pair_id"]): x for x in fixture["trial_schedule"]}
    if not by_pair:
        fail("W5 U-PAIR PASS without actual paired experiments")
    for key, arms in by_pair.items():
        if (
            key not in schedule
            or len(arms) != 2
            or {x["arm"] for x in arms} != {"CONTROL", "CANDIDATE"}
        ):
            fail(f"W5 invalid or unregistered pair: {key}")
        definition = schedule[key]
        for arm in arms:
            position = definition["arm_order"].index(arm["arm"]) + 1
            if (
                arm["arm_order"] != str(position)
                or arm["chat_label"] != definition["chat_label"]
            ):
                fail(f"W5 pair deviates from pre-registered order/chat: {key}")
    carriers = {x[0] for x in by_pair}
    if any(sum(x[0] == carrier for x in by_pair) < 12 for carrier in carriers):
        fail("W5 viable carrier must have at least 12 registered complete pairs")
