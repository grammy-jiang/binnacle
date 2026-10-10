"""Emit synthetic W1-W5 NOT_RUN packets/results plus a supervisor sample."""

from __future__ import annotations

import csv
from pathlib import Path

from tests.job_awareness_feasibility.sample_s0 import (
    DOC,
    RUN,
    SRC,
    TIME,
    build_s0,
    model_value,
    save_json,
)
from tests.job_awareness_feasibility.validation_lib import (
    COMMON,
    CSV_COLUMNS,
    EXTRA,
    HYPOTHESES,
    LANES,
    sha256,
)


def build_sample(root: Path) -> None:
    """Produce a full structurally valid but completely unexecuted sample run."""
    lane_map, fixture_sha = build_s0(root)
    inputs = {}
    for wid in LANES:
        lane = lane_map[wid]
        if wid == "W5":
            model_request = {
                "model": lane["operator_model_request"],
                "effort": lane["operator_effort_request"],
            }
            subject_request = {
                "surface": "ChatGPT Chat",
                "model": lane["subject_model_request"],
                "effort": lane["subject_effort_request"],
            }
        else:
            model_request = {"model": lane["model"], "effort": lane["reasoning_effort"]}
            subject_request = None
        outputs = []
        for filename in COMMON + EXTRA[wid]:
            ext = Path(filename).suffix.removeprefix(".")
            outputs.append(
                {
                    "ref": filename,
                    "format": ext,
                    "purpose": "SAMPLE_ONLY; not executed",
                }
            )
        pkt = {
            "schema": "job-awareness-worker-input-v1",
            "run_id": RUN,
            "worker": wid,
            "source_sha": SRC,
            "docs_sha": DOC,
            "fixture_sha256": fixture_sha,
            "fixture_path": "fixtures/fixture-manifest.json",
            "issued_at": TIME,
            "model_request": model_request,
            "subject_request": subject_request,
            "worktree_path": f"~/Projects/EXAMPLE_{wid}_NOT_CREATED",
            "results_path": f"~/Projects/EXAMPLE_RESULTS_NOT_CREATED/{wid}",
            "scenarios": lane["scenarios"],
            "inputs": [
                {
                    "ref": "fixtures/fixture-manifest.json",
                    "format": "json",
                    "sha256": fixture_sha,
                    "purpose": "synthetic fixture contract",
                }
            ],
            "outputs": outputs,
            "limits": {
                "max_runtime_s": 60,
                "max_spend_usd": 0,
                "memory_safety_margin_mb": 1024,
            },
            "permissions": {
                "gui": wid == "W5",
                "production_writes": False,
                "other_worker_writes": False,
            },
        }
        packet_path = root / "inputs" / f"{wid}.input.json"
        save_json(packet_path, pkt)
        inputs[wid] = {
            "path": f"inputs/{wid}.input.json",
            "sha256": sha256(packet_path),
        }

        result_root = root / wid
        result_root.mkdir(parents=True, exist_ok=True)
        save_json(
            result_root / "model-selection.json",
            {
                "schema": "job-awareness-model-selection-v1",
                "run_id": RUN,
                "worker": wid,
                "recorded_at": TIME,
                "executor": model_value(
                    model_request["model"], model_request["effort"]
                ),
                "subject": (
                    model_value(subject_request["model"], subject_request["effort"])
                    if subject_request is not None
                    else None
                ),
                "selection_command": "NOT_EXECUTED_SAMPLE",
                "observed_selector_evidence_refs": [],
                "notes": ["NO_ACTUAL_MODEL_SELECTION_OR_SESSION"],
            },
        )
        (result_root / "findings.md").write_text(
            f"# {wid} NOT RUN\n\nThis is a synthetic contract validation sample.\n",
            encoding="utf-8",
        )
        (result_root / "events.jsonl").write_text("", encoding="utf-8")
        with (result_root / EXTRA[wid][0]).open(
            "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.writer(file)
            writer.writerow(CSV_COLUMNS[wid])
        if wid == "W2":
            (result_root / "identity-provenance.md").write_text(
                "# No identity probe was performed\n", encoding="utf-8"
            )
        if wid == "W3":
            save_json(
                result_root / "receipt-verdict.json",
                {
                    "schema": "job-awareness-receipt-verdict-v1",
                    "run_id": RUN,
                    "worker": "W3",
                    "cases": ["R-ACK"],
                    "variants": [
                        {
                            "name": name,
                            "verdict": "UNRESOLVED",
                            "necessary_assumptions": [],
                            "counterexample_refs": [],
                        }
                        for name in (
                            "SERVER_FETCH",
                            "NEXT_TRUSTED_CALL",
                            "EXPLICIT_RECEIPT",
                        )
                    ],
                    "recommended_transition": None,
                    "outstanding_uncertainties": ["NOT_RUN"],
                },
            )
        if wid == "W4":
            save_json(
                result_root / "metrics.json",
                {
                    "schema": "job-awareness-performance-metrics-v1",
                    "run_id": RUN,
                    "worker": "W4",
                    "cohorts": [0, 1, 10, 100],
                    "carriers": ["CONTROL", "META", "TEXT", "STRUCT"],
                    "measurements": [],
                    "source_samples": "latency-samples.csv",
                },
            )
        if wid == "W5":
            save_json(
                result_root / "surface-capability.json",
                {
                    "schema": "job-awareness-desktop-surface-v1",
                    "run_id": RUN,
                    "worker": "W5",
                    "observed_at": TIME,
                    "launcher": "SAMPLE_UNVERIFIED",
                    "surface": "CHAT_MODE_NOT_VERIFIED",
                    "operator": model_value("gpt-6-astra", "high"),
                    "subject": model_value("GPT-6", "Medium"),
                    "chat_model_locked": False,
                    "chat_mcp_tool_invoked": False,
                    "nonce_verified": False,
                    "evidence_refs": [],
                    "limitation": "NOT_RUN",
                },
            )
        artifacts = []
        for path in sorted(result_root.iterdir()):
            if path.is_file():
                artifacts.append(
                    {
                        "path": path.name,
                        "sha256": sha256(path),
                        "size_bytes": path.stat().st_size,
                        "media_type": "text/plain"
                        if path.suffix in (".md", ".csv", ".jsonl")
                        else "application/json",
                        "provenance": "SYNTHETIC_SCHEMA_SAMPLE_ONLY",
                        "layer": "fixture_generated",
                        "redacted": True,
                        "privacy_checked": True,
                        "event_ids": [],
                    }
                )
        save_json(
            result_root / "evidence-index.json",
            {
                "schema": "job-awareness-evidence-index-v1",
                "run_id": RUN,
                "worker": wid,
                "source_sha": SRC,
                "fixture_sha256": fixture_sha,
                "artifacts": artifacts,
            },
        )
        save_json(
            result_root / "results.json",
            {
                "schema": "job-awareness-worker-result-v1",
                "run_id": RUN,
                "worker": wid,
                "source_sha": SRC,
                "docs_sha": DOC,
                "fixture_sha256": fixture_sha,
                "input_sha256": inputs[wid]["sha256"],
                "started_at": TIME,
                "finished_at": TIME,
                "state": "NOT_RUN",
                "executor": {
                    "surface": lane["executor"],
                    "version": "SAMPLE",
                    "session_ref": "NOT_RUN",
                    "model": model_value(
                        model_request["model"], model_request["effort"]
                    ),
                },
                "subject": (
                    {
                        "surface": "ChatGPT Chat",
                        "model": model_value(
                            subject_request["model"], subject_request["effort"]
                        ),
                    }
                    if subject_request is not None
                    else None
                ),
                "hypotheses": dict.fromkeys(HYPOTHESES[wid], "UNRESOLVED"),
                "scenarios": [
                    {
                        "id": cid,
                        "status": "NOT_RUN",
                        "expected": "A real experiment provides evidence",
                        "observed": "THIS IS AN UNEXECUTED SCHEMA SAMPLE",
                        "input_refs": ["fixtures/fixture-manifest.json"],
                        "evidence_refs": [],
                        "event_ids": [],
                        "proof_layers": [],
                        "duration_ms": None,
                        "blocking_reason": "SAMPLE_NOT_EXECUTED",
                    }
                    for cid in lane["scenarios"]
                ],
                "metrics": {},
                "limitations": ["SAMPLE_NOT_EXECUTED"],
                "artifact_index": "evidence-index.json",
            },
        )

    save_json(
        root / "run-manifest.json",
        {
            "schema": "job-awareness-run-v1",
            "run_id": RUN,
            "source_sha": SRC,
            "docs_sha": DOC,
            "fixture_sha256": fixture_sha,
            "fixture_path": "fixtures/fixture-manifest.json",
            "frozen_at": TIME,
            "status": "FROZEN",
            "s0_preflight_path": "S0/preflight.json",
            "worker_inputs": inputs,
            "desktop_app_status": "BLOCKED",
            "notes": ["SYNTHETIC VALIDATOR SAMPLE, NO EXPERIMENT EXECUTED"],
        },
    )
    workers = {}
    gate_reasons = {}
    for wid in LANES:
        lane = lane_map[wid]
        if wid == "W5":
            model, effort = (
                lane["operator_model_request"],
                lane["operator_effort_request"],
            )
        else:
            model, effort = lane["model"], lane["reasoning_effort"]
        workers[wid] = {
            "input_sha256": inputs[wid]["sha256"],
            "requested_model": model,
            "requested_effort": effort,
            "process_ref": None,
            "session_ref": None,
            "worktree": f"~/Projects/EXAMPLE_{wid}_NOT_CREATED",
            "dispatch_state": "NOT_STARTED",
            "reason": "SAMPLE_ONLY",
        }
    save_json(
        root / "supervisor" / "dispatch-ledger.json",
        {
            "schema": "job-awareness-dispatch-ledger-v1",
            "run_id": RUN,
            "source_sha": SRC,
            "docs_sha": DOC,
            "at": TIME,
            "workers": workers,
        },
    )
    summaries = {
        wid: {
            "state": "NOT_RUN",
            "structural_validation": "PASS",
            "model_verification": "UNVERIFIED",
            "result_ref": f"{wid}/results.json",
        }
        for wid in LANES
    }
    save_json(
        root / "supervisor" / "collection-report.json",
        {
            "schema": "job-awareness-collection-report-v1",
            "run_id": RUN,
            "source_sha": SRC,
            "docs_sha": DOC,
            "fixture_sha256": fixture_sha,
            "at": TIME,
            "files_checked": 0,
            "schema_errors": [],
            "hash_errors": [],
            "missing_evidence": ["ALL_REAL_EVIDENCE_NOT_RUN"],
            "worker_summaries": summaries,
        },
    )
    (root / "supervisor" / "reconciliation.md").write_text(
        "# NONE: no experiments were run\n", encoding="utf-8"
    )
    gate_reasons = {
        f"G{i}": {
            "status": "NOT_RUN",
            "reason": "SAMPLE_NOT_EXECUTED",
            "evidence_refs": [],
        }
        for i in range(8)
    }
    save_json(
        root / "decision.json",
        {
            "schema": "job-awareness-manager-decision-v1",
            "run_id": RUN,
            "source_sha": SRC,
            "docs_sha": DOC,
            "fixture_sha256": fixture_sha,
            "generated_at": TIME,
            "workers": {
                wid: {
                    "status": "NOT_RUN",
                    "result_ref": f"{wid}/results.json",
                    "model_verified": False,
                }
                for wid in LANES
            },
            "gates": gate_reasons,
            "decision": "INCONCLUSIVE",
            "reason": "THIS IS A STRUCTURAL SAMPLE, NOT A REAL DECISION",
            "limitations": ["NO_REAL_EXPERIMENTS"],
            "production_authorized": False,
            "report_ref": "MANAGER-SUMMARY.md",
        },
    )
    (root / "MANAGER-SUMMARY.md").write_text(
        "# Sample only\n\nNo workers or experiments were launched.\n", encoding="utf-8"
    )
