"""Generate deterministic NOT_RUN samples for validator tests only.

These files do not represent real S0 setup, real model selection or a
ChatGPT experiment. The sample run_id makes the limitation explicit.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.job_awareness_feasibility.validation_lib import (
    BASE,
    sha256,
)

RUN = "JA-20261010-EXAMPLE_NOT_EXECUTED"
SRC = "1" * 40
DOC = "2" * 40
TIME = "2026-10-10T10:00:00+11:00"


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def model_value(model: str, effort: str, verified: bool = False) -> dict:
    return {
        "requested_model": model,
        "requested_effort": effort,
        "effective_model": model if verified else None,
        "effective_effort": effort if verified else None,
        "verification": "VERIFIED" if verified else "UNVERIFIED",
        "verification_evidence_ref": "S0/provenance.json" if verified else None,
        "fallback_used": False,
        "model_match_verified": verified,
        "effort_match_verified": verified,
    }


def build_s0(root: Path) -> tuple[dict, str]:
    """Create a complete structurally valid but entirely NOT_RUN sample."""
    plan = json.loads((BASE / "worker-manifest.json").read_text(encoding="utf-8"))
    lane_map = {x["id"]: x for x in plan["worker_lanes"]}
    payload = root / "fixtures" / "payloads" / "synthetic.txt"
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_text("SYNTHETIC ONLY; NO EXPERIMENT EXECUTED\n", encoding="utf-8")
    payload_sha = sha256(payload)

    fixture_ids = (
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
    )
    fixtures = {
        "schema": "job-awareness-fixtures-v1",
        "run_id": RUN,
        "source_sha": SRC,
        "seed": 101010,
        "carriers": ["CONTROL", "META", "TEXT", "STRUCT"],
        "fixtures": [
            {
                "id": fid,
                "owner": "A" if fid != "J-CROSS" else "B",
                "nonce_hash": payload_sha,
                "initial_state": "running",
                "stdout_sha256": payload_sha,
                "stdout_bytes": payload.stat().st_size,
                "page_boundaries": [0, payload.stat().st_size],
                "scenario_tags": [fid],
            }
            for fid in fixture_ids
        ],
        "trial_schedule": [
            {
                "pair_id": f"{carrier}-{i:02d}",
                "carrier": carrier,
                "fixture_id": "J-OK",
                "chat_label": ("A", "B", "C")[i % 3],
                "arm_order": ["CONTROL", "CANDIDATE"]
                if i % 2
                else ["CANDIDATE", "CONTROL"],
            }
            for carrier in ("META", "TEXT", "STRUCT")
            for i in range(1, 13)
        ],
        "limits": {
            "hint_max_bytes": 512,
            "latency_p95_ms": 5.0,
            "paired_trials_per_viable_carrier": 12,
        },
    }
    fixture_path = root / "fixtures" / "fixture-manifest.json"
    save_json(fixture_path, fixtures)
    fixture_sha = sha256(fixture_path)
    save_json(
        root / "S0" / "fixture-index.json",
        {
            "schema": "job-awareness-fixture-index-v1",
            "run_id": RUN,
            "items": [
                {
                    "path": "fixtures/payloads/synthetic.txt",
                    "sha256": payload_sha,
                    "size_bytes": payload.stat().st_size,
                    "synthetic_only": True,
                }
            ],
        },
    )
    save_json(
        root / "S0" / "provenance.json",
        {
            "schema": "job-awareness-s0-provenance-v1",
            "run_id": RUN,
            "source_sha": SRC,
            "docs_sha": DOC,
            "recorded_at": TIME,
            "tools": {
                tool: {
                    "name": tool,
                    "version": "SAMPLE-NOT-EXECUTED",
                    "verified": False,
                }
                for tool in ("codex-cli", "claude-cli", "chatgpt-desktop")
            },
            "runtime": {"example_only": True},
            "notes": ["Demonstration fixture, no real tools invoked"],
        },
    )
    save_json(
        root / "S0" / "resource-ledger.json",
        {
            "schema": "job-awareness-resources-v1",
            "run_id": RUN,
            "recorded_at": TIME,
            "resources": [],
        },
    )
    save_json(
        root / "S0" / "connection-evidence.json",
        {
            "schema": "job-awareness-connection-v1",
            "run_id": RUN,
            "at": TIME,
            "app_status": "BLOCKED",
            "protocol_version": None,
            "client_surface": None,
            "owned_test_app_ref": None,
            "approved_supported_interface": False,
            "nonce_tool_call_verified": False,
            "redacted_evidence_refs": [],
            "blocking_reason": "SAMPLE_NOT_EXECUTED",
        },
    )
    save_json(
        root / "S0" / "preflight.json",
        {
            "schema": "job-awareness-s0-preflight-v1",
            "run_id": RUN,
            "source_sha": SRC,
            "docs_sha": DOC,
            "fixture_sha256": fixture_sha,
            "started_at": TIME,
            "finished_at": TIME,
            "state": "PARTIAL",
            "executor": {
                "surface": "codex-cli",
                "version": "SAMPLE",
                "session_ref": "SIMULATED",
                "model": model_value("gpt-6-sol", "medium", verified=True),
            },
            "resource_baseline": {
                "production_pid_digest": "SIMULATED",
                "original_worktree_clean": False,
                "test_namespace": RUN,
                "staging_isolated": True,
            },
            "desktop_app_status": "BLOCKED",
            "outputs": [
                "run-manifest.json",
                "fixtures/fixture-manifest.json",
                "inputs/W1.input.json",
            ],
            "blocking_reasons": ["SAMPLE_NOT_EXECUTED"],
        },
    )
    (root / "S0" / "events.jsonl").write_text("", encoding="utf-8")
    (root / "S0" / "readiness.md").write_text(
        "# S0 NOT EXECUTED\n\nThis is a synthetic structure test, not evidence.\n",
        encoding="utf-8",
    )

    return lane_map, fixture_sha
