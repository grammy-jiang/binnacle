"""Safe execution harness for Chat scheduling v2 benchmark trials.

Step 0.3 owns lifecycle safety only. Scoring/analyzing the resulting trial
records is implemented separately in Step 0.4.
"""

from __future__ import annotations

import argparse
import json
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
    write_json,
)

PROJECT_ID = "g-p-6aaea9da2bc881918d6f9eb5177cf904"
PROJECT_NAME = "rp-test-sandbox"
ROOT = Path(__file__).resolve().parents[1]
BASELINE_SNAPSHOT = (
    ROOT / "benchmarks" / "chat-mode-scheduling-v2" / "baseline-2026-09-23.json"
)
B_INSTRUCTIONS = (
    ROOT
    / ".claude"
    / "skills"
    / "chatgpt-mcp-dev"
    / "references"
    / "project-instructions-chat-scheduling-v2.txt"
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def arm_instructions(arm: str) -> str:
    if arm == "A":
        snapshot = json.loads(BASELINE_SNAPSHOT.read_text(encoding="utf-8"))
        return str(snapshot["benchmark_project"]["live_instructions"])
    if not B_INSTRUCTIONS.exists():
        raise HarnessError(f"instruction arm B is missing: {B_INSTRUCTIONS}")
    return B_INSTRUCTIONS.read_text(encoding="utf-8")


def _record_base(
    identity: TrialIdentity,
    state_dir: Path,
    *,
    kind: str,
    scenario_id: str | None = None,
    arm: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": kind,
        "run_id": identity.run_id,
        "nonce": identity.nonce,
        "scenario_id": scenario_id,
        "arm": arm,
        "project_id": PROJECT_ID,
        "project_name": PROJECT_NAME,
        "state_dir": str(state_dir),
        "started_at": _now(),
        "finished_at": None,
        "status": "running",
        "stage": "created",
        "error": None,
        "cleanup": {},
        "instructions": {},
        "chat": {},
    }


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


def run_trial(
    scenario_id: str,
    arm: str,
    *,
    browser: str = "chrome",
    fail_after_instructions: bool = False,
) -> tuple[int, Path]:
    scenario = load_scenario(SCENARIO_ROOT / f"{scenario_id}.json")
    identity = TrialIdentity.create(scenario_id)
    state_dir = new_state_dir(identity)
    record_path = state_dir / "trial.json"
    record = _record_base(
        identity, state_dir, kind="scenario", scenario_id=scenario_id, arm=arm
    )
    write_json(record_path, record)

    production_before = ProductionSnapshot.capture()
    record["production_before"] = production_before.__dict__
    project = ProjectClient(PROJECT_NAME, browser)
    original_instructions = project.instructions()
    desired = arm_instructions(arm)
    record["instructions"] = {
        "original": original_instructions,
        "desired": desired,
        "restored": False,
    }

    fixture = FixtureLease(scenario, identity, LocalMCP())
    artifact = ChatArtifact(PROJECT_ID, state_dir, browser)
    url_file = state_dir / "chat-url.txt"
    trial_error: Exception | None = None
    chat_cleanup_error: str | None = None
    fixture_cleanup: dict[str, Any] = {}

    try:
        fixture.__enter__()
        record["fixture"] = {
            "root": str(fixture.root),
            "jobs": fixture.jobs,
            "created": True,
        }
        record["prompt"] = fixture.rendered_prompt()
        record["stage"] = "fixture_ready"
        write_json(record_path, record)

        with InstructionLease(project, desired) as lease:
            record["instructions"]["changed"] = lease.changed
            record["stage"] = "instructions_applied"
            write_json(record_path, record)
            if fail_after_instructions:
                raise HarnessError("injected failure after instructions")

            timeout_s = float(scenario.max_turn_runtime_s + 20)
            record["stage"] = "chat_running"
            write_json(record_path, record)
            try:
                result = send_project_chat(
                    PROJECT_ID,
                    record["prompt"],
                    timeout_s,
                    url_file,
                    browser=browser,
                )
                record["chat"]["send_result"] = result
                artifact.url = result["url"]
            finally:
                artifact.discover(url_file)
                if artifact.chat_id is not None:
                    artifact.track(
                        f"Chat scheduling v2 {scenario_id} arm {arm} {identity.run_id}"
                    )
                    record["chat"]["chat_id"] = artifact.chat_id
                    record["chat"]["tracked"] = True
                    write_json(record_path, record)

        record["instructions"]["restored"] = (
            project.instructions() == original_instructions
        )
        if not record["instructions"]["restored"]:
            raise HarnessError("instruction lease returned without exact restoration")

        if artifact.chat_id is None:
            raise HarnessError("chat completed but no conversation id was discovered")
        record["stage"] = "chat_complete"
        write_json(record_path, record)

    except Exception as exc:  # noqa: BLE001 - trial boundary records arbitrary normal failures
        trial_error = exc
        record["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        # The lease has restored before we touch chat deletion or fixture teardown.
        try:
            record["instructions"]["restored"] = (
                project.instructions() == original_instructions
            )
        except Exception as exc:  # noqa: BLE001 - final restore verification must be recorded
            record["instructions"]["restored"] = False
            if trial_error is None:
                trial_error = exc
                record["error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }

        artifact.discover(url_file)
        if artifact.chat_id is not None and not artifact.tracked:
            try:
                artifact.track(
                    f"Chat scheduling v2 {scenario_id} arm {arm} {identity.run_id}"
                )
            except Exception as exc:  # noqa: BLE001 - keep exact chat id for later cleanup
                chat_cleanup_error = f"track failed: {type(exc).__name__}: {exc}"

        chat_cleanup, cleanup_error = _safe_chat_cleanup(artifact)
        if cleanup_error:
            chat_cleanup_error = (
                f"{chat_cleanup_error}; {cleanup_error}"
                if chat_cleanup_error
                else cleanup_error
            )
        record["cleanup"]["chat"] = chat_cleanup
        if chat_cleanup.get("conversation_saved"):
            record["chat"]["conversation_saved"] = True
        if chat_cleanup.get("deleted"):
            record["chat"]["tracked"] = False
            record["chat"]["deleted"] = True
        if chat_cleanup_error:
            record["cleanup"]["chat_error"] = chat_cleanup_error

        fixture_cleanup = fixture.cleanup()
        record["cleanup"]["fixture"] = fixture_cleanup

        try:
            production_after = ProductionSnapshot.capture()
            record["production_after"] = production_after.__dict__
            production_before.assert_unchanged(production_after)
            record["production_unchanged"] = True
        except Exception as exc:  # noqa: BLE001 - invariant failure is part of trial result
            record["production_unchanged"] = False
            if trial_error is None:
                trial_error = exc
                record["error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }

        cleanup_failed = bool(
            chat_cleanup_error
            or fixture_cleanup.get("errors")
            or not fixture_cleanup.get("root_removed", True)
        )
        if cleanup_failed and trial_error is None:
            trial_error = HarnessError("trial cleanup was incomplete")
            record["error"] = {
                "type": type(trial_error).__name__,
                "message": str(trial_error),
                "traceback": "",
            }

        record["finished_at"] = _now()
        record["status"] = "failed" if trial_error else "completed"
        record["stage"] = "finished"
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
    error: Exception | None = None
    try:
        result = send_project_chat(
            PROJECT_ID,
            f"Reply only harness-chat-smoke-{identity.nonce}",
            60,
            url_file,
            browser=browser,
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
    trial.add_argument("--arm", choices=["A", "B"], required=True)
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
        code, state = run_trial(
            args.scenario,
            args.arm,
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
