"""Execution harness for Chat scheduling v2 benchmark trials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.chat_scheduling_chat import (
    ChatArtifact,
    InstructionLease,
    ProjectClient,
    send_project_chat,
)
from scripts.chat_scheduling_manifest import ROOT as SCENARIO_ROOT
from scripts.chat_scheduling_manifest import load_scenario
from scripts.chat_scheduling_runtime import (
    FixtureLease,
    HarnessError,
    LocalMCP,
    ProductionSnapshot,
    TrialIdentity,
    new_state_dir,
    resolve_phase4_endpoint,
    shared_send_gate,
    validate_arm_endpoint,
    write_json,
)

PROJECT_ID = "g-p-6aaea9da2bc881918d6f9eb5177cf904"
PROJECT_NAME = "rp-test-sandbox"
ROOT = Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def arm_instructions(arm: str) -> str:
    if arm == "A":
        path = ROOT / "benchmarks/chat-mode-scheduling-v2/baseline-2026-09-23.json"
        return str(
            json.loads(path.read_text(encoding="utf-8"))["benchmark_project"][
                "live_instructions"
            ]
        )
    path = (
        ROOT
        / ".claude/skills/chatgpt-mcp-dev/references/project-instructions-chat-scheduling-v2.txt"
    )
    if not path.exists():
        raise HarnessError(f"instruction arm B is missing: {path}")
    return path.read_text(encoding="utf-8")


def _record_base(
    identity: TrialIdentity,
    state_dir: Path,
    *,
    kind: str,
    scenario_id: str | None = None,
    arm: str | None = None,
) -> dict[str, Any]:
    keys: tuple[str, ...] = ("schema_version", "kind", "run_id", "nonce", "scenario_id", "arm", "project_id", "project_name", "state_dir", "started_at", "finished_at", "status", "stage", "error", "cleanup", "instructions", "chat")  # fmt: skip
    values: tuple[Any, ...] = (1, kind, identity.run_id, identity.nonce, scenario_id, arm, PROJECT_ID, PROJECT_NAME, str(state_dir), _now(), None, "running", "created", None, {}, {}, {})  # fmt: skip
    return dict(zip(keys, values, strict=True))


def _safe_chat_cleanup(
    artifact: ChatArtifact | None,
) -> tuple[dict[str, Any], str | None]:
    if artifact is None:
        return {}, None
    try:
        return artifact.cleanup(), None
    except Exception as exc:  # noqa: BLE001 - cleanup error must be recorded, not mask restore
        return (
            {
                "chat_id": artifact.chat_id,
                "tracked": artifact.tracked,
                "conversation_saved": artifact.conversation_saved,
                "deleted": False,
            },
            f"{type(exc).__name__}: {exc}",
        )


def _begin_endpoint_capture(
    selected: dict[str, Any], state_dir: Path, identity: TrialIdentity, scenario_id: str
) -> dict[str, Any]:
    evidence = {
        "endpoint_id": selected["endpoint_id"],
        "logical_arm": selected["logical_arm"],
        "scenario_id": scenario_id,
        "trial_run_id": identity.run_id,
        "trial_nonce_sha256": hashlib.sha256(identity.nonce.encode()).hexdigest(),
        "evidence_integrity_error": False,
    }
    evidence.update(
        {
            key: selected.get(key)
            for key in (
                "base_topology_sha256",
                "lane_manifest_sha256",
                "runtime_registry_sha256",
                "admission_envelope_revision",
            )
        }
    )
    logs = {}
    for name in ("server", "manager", "tunnel"):
        path = Path(selected[f"{name}_log_path"]).expanduser()
        stat = path.stat()
        logs[name] = (path, stat.st_dev, stat.st_ino, stat.st_size)
        evidence[f"{name}_log_identity"] = [stat.st_dev, stat.st_ino]
        evidence[f"{name}_log_start_offset"] = stat.st_size
    write_json(state_dir / "endpoint-evidence.json", evidence)
    return {"logs": logs, "evidence": evidence}


def _finalize_endpoint_capture(
    capture: dict[str, Any], state_dir: Path
) -> dict[str, Any]:
    evidence, errors = capture["evidence"], []
    for name, values in capture["logs"].items():
        path, dev, ino, start = values
        try:
            with path.open("rb") as handle:
                stat = os.fstat(handle.fileno())
                if (stat.st_dev, stat.st_ino) != (dev, ino) or stat.st_size < start:
                    raise HarnessError("log identity/offset changed")
                handle.seek(start)
                data = handle.read(stat.st_size - start)
            (state_dir / f"endpoint-{name}.log").write_bytes(data)
            evidence[f"{name}_log_end_offset"] = stat.st_size
            evidence[f"{name}_log_sha256"] = hashlib.sha256(data).hexdigest()
        except (OSError, HarnessError) as exc:
            errors.append(f"{name}: {exc}")
    evidence["evidence_integrity_error"] = bool(errors)
    evidence["evidence_integrity_errors"] = errors
    write_json(state_dir / "endpoint-evidence.json", evidence)
    return evidence


def run_trial(
    scenario_id: str,
    arm: str,
    *,
    budget_s: int | None,
    endpoint_id: str,
    browser: str = "chrome",
    fail_after_instructions: bool = False,
    sources: dict[str, Any] | None = None,
) -> tuple[int, Path]:
    scenario = load_scenario(SCENARIO_ROOT / f"{scenario_id}.json")
    selected = resolve_phase4_endpoint(arm, budget_s, endpoint_id, sources=sources)
    identity = TrialIdentity.create(scenario_id)
    state_dir = new_state_dir(identity)
    record_path = state_dir / "trial.json"
    record = _record_base(
        identity, state_dir, kind="scenario", scenario_id=scenario_id, arm=arm
    )
    for key in ("budget_s", "connector_logical_name", "project_id", "project_name", "instruction_sha256", "base_topology_sha256", "lane_manifest_path", "lane_manifest_sha256", "runtime_registry_sha256", "admission_envelope_revision", "phase4_source_head"):  # fmt: skip
        record[key] = selected[key]
    record.update(
        phase=4,
        endpoint_id=endpoint_id,
        model_thinking_snapshot=selected["model_thinking"],
        source_head=selected["phase4_source_head"],
        manifest_sha256=hashlib.sha256(
            (SCENARIO_ROOT / f"{scenario_id}.json").read_bytes()
        ).hexdigest(),
        submission_status="not_submitted",
        provenance_classification=None,
        evidence_source="endpoint_logs",
        evidence_integrity_error=False,
    )
    record["trial_start_epoch_s"] = time.time()
    write_json(record_path, record)

    production_before = ProductionSnapshot.capture()
    record["production_before"] = production_before.__dict__
    project = ProjectClient(selected["project_name"], browser)
    actual_sha = hashlib.sha256(project.instructions().encode()).hexdigest()
    record["instructions"] = {
        "sha256": actual_sha,
        "expected_sha256": selected["instruction_sha256"],
        "verified": actual_sha == selected["instruction_sha256"],
        "mutated": False,
    }
    fixture = FixtureLease(
        scenario,
        identity,
        LocalMCP(
            f"http://{selected.get('host', '127.0.0.1')}:{selected['port']}/mcp",
            Path(selected["token_path"]).expanduser(),
        ),
        budget_s=selected["budget_s"],
    )
    artifact = ChatArtifact(selected["project_id"], state_dir, browser)
    url_file, timing_file = state_dir / "chat-url.txt", state_dir / "chat-timing.json"
    trial_error: Exception | None = None
    capture: dict[str, Any] | None = None
    fixture_entered = False

    try:
        if not record["instructions"]["verified"]:
            raise HarnessError("Project instruction hash differs from lane manifest")
        capture = _begin_endpoint_capture(selected, state_dir, identity, scenario_id)
        if fail_after_instructions:
            raise HarnessError("injected failure after instruction verification")
        fixture.__enter__()
        fixture_entered = True
        record["fixture"] = {
            "root": str(fixture.root),
            "jobs": fixture.jobs,
            "created": True,
        }
        record["prompt"] = fixture.rendered_prompt()
        record["stage"] = "chat_running"
        write_json(record_path, record)
        with shared_send_gate(trial=True, url_file=url_file, timing_file=timing_file):
            result = send_project_chat(
                selected["project_id"],
                record["prompt"],
                float(scenario.max_turn_runtime_s + 20),
                url_file,
                browser=browser,
                timing_file=timing_file,
            )
        record["submission_status"] = "completed"
        record["chat"]["send_result"] = result
        artifact.url = result["url"]
        artifact.discover(url_file)
        if artifact.chat_id is None:
            raise HarnessError("chat completed but no conversation id was discovered")
        artifact.track(f"Chat scheduling v2 {scenario_id} arm {arm} {identity.run_id}")
        record["chat"].update(chat_id=artifact.chat_id, tracked=True)
    except Exception as exc:  # noqa: BLE001 - trial boundary records normal failures
        trial_error = exc
        record["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        if fixture_entered:
            try:
                snapshot = state_dir / "fixture-final.json"
                fixture.snapshot(snapshot)
                record["fixture_final_path"] = str(snapshot)
            except Exception as exc:  # noqa: BLE001
                trial_error = trial_error or exc
                record.setdefault(
                    "fixture_snapshot_error", f"{type(exc).__name__}: {exc}"
                )
        artifact.discover(url_file)
        if artifact.chat_id is not None and not artifact.tracked:
            try:
                artifact.track(
                    f"Chat scheduling v2 {scenario_id} arm {arm} {identity.run_id}"
                )
            except Exception as exc:  # noqa: BLE001
                record["cleanup"]["chat_error"] = f"track failed: {exc}"
        chat_cleanup, cleanup_error = _safe_chat_cleanup(artifact)
        record["cleanup"]["chat"] = chat_cleanup
        if cleanup_error:
            record["cleanup"]["chat_error"] = cleanup_error
            trial_error = trial_error or HarnessError("chat cleanup was incomplete")
        record["cleanup"]["fixture"] = (
            fixture.cleanup()
            if fixture_entered
            else {"stopped_jobs": [], "errors": [], "root_removed": True}
        )
        if record["cleanup"]["fixture"]["errors"]:
            trial_error = trial_error or HarnessError("fixture cleanup was incomplete")
        try:
            production_after = ProductionSnapshot.capture()
            record["production_after"] = production_after.__dict__
            production_before.assert_unchanged(production_after)
            record["production_unchanged"] = True
        except Exception as exc:  # noqa: BLE001
            record["production_unchanged"] = False
            trial_error = trial_error or exc
        if capture is not None:
            evidence = _finalize_endpoint_capture(capture, state_dir)
            record["evidence_integrity_error"] = evidence["evidence_integrity_error"]
            if evidence["evidence_integrity_error"]:
                trial_error = trial_error or HarnessError(
                    "endpoint evidence integrity failure"
                )
        record["trial_end_epoch_s"] = time.time()
        if record["submission_status"] == "not_submitted":
            record["submission_status"] = (
                "failed_after_submission"
                if url_file.exists() or timing_file.exists()
                else "pre_submit_failure"
            )
        record["status"] = "failed" if trial_error else "completed"
        record["finished_at"], record["stage"] = _now(), "finished"
        if trial_error is not None and record.get("error") is None:
            record["error"] = {
                "type": type(trial_error).__name__,
                "message": str(trial_error),
            }
        write_json(record_path, record)
        try:
            from scripts.chat_scheduling_provenance import classify_state_dir

            record["provenance_classification"] = classify_state_dir(
                state_dir, scenario
            )
        except Exception as exc:  # noqa: BLE001 - integrity/provenance is required evidence
            trial_error = trial_error or exc
            record["evidence_integrity_error"] = True
            record["status"] = "failed"
            record["error"] = record.get("error") or {
                "type": type(exc).__name__,
                "message": str(exc),
            }
        write_json(record_path, record)

    return (1 if trial_error else 0), state_dir


def run_restore_probe(browser: str = "chrome") -> tuple[int, Path]:
    identity = TrialIdentity.create("restore-probe")
    state_dir = new_state_dir(identity)
    record_path = state_dir / "trial.json"
    record = _record_base(identity, state_dir, kind="restore_probe")
    project = ProjectClient(PROJECT_NAME, browser)
    before = project.instructions()
    sentinel = f"harness-restore-probe-{identity.nonce}"
    record["instructions"] = {
        "original": before,
        "desired": sentinel,
        "restored": False,
    }
    error: Exception | None = None
    try:
        with InstructionLease(project, sentinel):
            if project.instructions() != sentinel:
                raise HarnessError("restore probe did not apply sentinel")
            raise HarnessError("intentional restore-probe failure")
    except HarnessError as exc:
        # The intentional trial failure is expected; restoration is what we score.
        if str(exc) != "intentional restore-probe failure":
            error = exc
    except Exception as exc:  # noqa: BLE001 - restore probe scores any normal failure
        error = exc
    restored = project.instructions() == before
    record["instructions"]["restored"] = restored
    if not restored and error is None:
        error = HarnessError("restore probe left Project instructions changed")
    record["status"] = "failed" if error else "completed"
    record["error"] = (
        None
        if error is None
        else {
            "type": type(error).__name__,
            "message": str(error),
        }
    )
    record["finished_at"] = _now()
    record["stage"] = "finished"
    write_json(record_path, record)
    return (1 if error else 0), state_dir


def run_chat_smoke(browser: str = "chrome") -> tuple[int, Path]:
    """Exercise exact chat track/save/delete without any MCP benchmark calls."""
    identity = TrialIdentity.create("chat-smoke")
    state_dir = new_state_dir(identity)
    record_path = state_dir / "trial.json"
    record = _record_base(identity, state_dir, kind="chat_smoke")
    project = ProjectClient(PROJECT_NAME, browser)
    original = project.instructions()
    artifact = ChatArtifact(PROJECT_ID, state_dir, browser)
    url_file = state_dir / "chat-url.txt"
    timing_file = state_dir / "chat-timing.json"
    error: Exception | None = None
    try:
        with shared_send_gate(trial=False, url_file=url_file, timing_file=timing_file):
            result = send_project_chat(
                PROJECT_ID,
                f"Reply only harness-chat-smoke-{identity.nonce}",
                60,
                url_file,
                browser=browser,
                timing_file=timing_file,
            )
        artifact.url = result["url"]
        artifact.discover(url_file)
        if artifact.chat_id is None:
            raise HarnessError("chat smoke did not discover conversation id")
        artifact.track(f"Chat scheduling v2 harness chat smoke {identity.run_id}")
        expected = f"harness-chat-smoke-{identity.nonce}"
        if result.get("reply") != expected:
            raise HarnessError(
                f"chat smoke reply mismatch: {result.get('reply')!r} != {expected!r}"
            )
        record["chat"] = {
            "chat_id": artifact.chat_id,
            "reply": result.get("reply"),
            "tracked": True,
            "conversation_saved": False,
        }
    except Exception as exc:  # noqa: BLE001 - smoke trial records any normal failure
        error = exc
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        artifact.discover(url_file)
        cleanup, cleanup_error = _safe_chat_cleanup(artifact)
        record["cleanup"]["chat"] = cleanup
        if cleanup.get("conversation_saved"):
            record["chat"]["conversation_saved"] = True
        if cleanup.get("deleted"):
            record["chat"]["tracked"] = False
            record["chat"]["deleted"] = True
        if cleanup_error:
            record["cleanup"]["chat_error"] = cleanup_error
            if error is None:
                error = HarnessError(cleanup_error)
        if project.instructions() != original and error is None:
            error = HarnessError("chat smoke unexpectedly changed Project instructions")
        record["instructions"]["restored"] = project.instructions() == original
        record["status"] = "failed" if error else "completed"
        record["finished_at"] = _now()
        record["stage"] = "finished"
        write_json(record_path, record)
    return (1 if error else 0), state_dir


def main() -> None:
    parser = argparse.ArgumentParser(prog="chat-scheduling-harness")
    parser.add_argument(
        "--browser", choices=["chrome", "chromium", "auto"], default="chrome"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    trial = sub.add_parser("trial", help="run one manifest-defined benchmark trial")
    trial.add_argument("scenario")
    trial.add_argument("--arm", choices=["A", "B", "C", "H"], required=True)
    trial.add_argument("--budget-s", type=int)
    trial.add_argument("--endpoint", required=True)
    trial.add_argument(
        "--inject-failure-after-instructions",
        action="store_true",
        help="test-only: fail after applying instructions, before opening a chat",
    )

    sub.add_parser(
        "restore-probe",
        help="temporarily change benchmark Project instructions, inject failure, verify exact restore",
    )
    sub.add_parser(
        "chat-smoke",
        help="create, track, save, and delete one test chat without MCP benchmark calls",
    )

    args = parser.parse_args()
    if args.command == "trial":
        budget_s = validate_arm_endpoint(args.arm, args.budget_s, args.endpoint)
        code, state = run_trial(
            args.scenario,
            args.arm,
            budget_s=budget_s,
            endpoint_id=args.endpoint,
            browser=args.browser,
            fail_after_instructions=args.inject_failure_after_instructions,
        )
    elif args.command == "restore-probe":
        code, state = run_restore_probe(args.browser)
    else:
        code, state = run_chat_smoke(args.browser)

    print(json.dumps({"exit_code": code, "state_dir": str(state)}, indent=2))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
