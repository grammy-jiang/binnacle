"""Phase 1.1 validation: exact A -> B -> A Project switching."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.chat_scheduling_chat import InstructionLease, ProjectClient
from scripts.chat_scheduling_harness import PROJECT_ID, PROJECT_NAME, arm_instructions
from scripts.chat_scheduling_runtime import (
    HarnessError,
    ProductionSnapshot,
    TrialIdentity,
    new_state_dir,
    write_json,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def conversation_summary(path: Path, expected_reply: str) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    mapping = data.get("mapping") or {}
    current = mapping.get(data.get("current_node"), {})
    message = current.get("message") if isinstance(current, dict) else None
    if not isinstance(message, dict):
        raise HarnessError("switch evidence has no final message")
    if (message.get("author") or {}).get("role") != "assistant":
        raise HarnessError("switch evidence current node is not assistant")

    content = message.get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else []
    reply = "\n".join(part for part in (parts or []) if isinstance(part, str))
    metadata = message.get("metadata") or {}
    complete = bool(metadata.get("is_complete")) or (
        message.get("status") == "finished_successfully"
    )
    if reply.strip() != expected_reply:
        raise HarnessError(
            f"switch evidence reply mismatch: {reply!r} != {expected_reply!r}"
        )
    if not complete:
        raise HarnessError("switch evidence assistant reply was not complete")
    if data.get("conversation_template_id") != PROJECT_ID:
        raise HarnessError("switch evidence chat is not inside benchmark Project")

    return {
        "conversation_id": data.get("conversation_id"),
        "conversation_template_id": data.get("conversation_template_id"),
        "reply": reply,
        "complete": complete,
        "model_slug": metadata.get("model_slug"),
        "resolved_model_slug": metadata.get("resolved_model_slug"),
        "thinking_effort": metadata.get("thinking_effort"),
    }


def validate_chat_isolation(
    a_path: Path,
    b_path: Path,
    *,
    expected_a: str,
    expected_b: str,
) -> dict[str, Any]:
    arm_a = conversation_summary(a_path, expected_a)
    arm_b = conversation_summary(b_path, expected_b)
    a_id = arm_a.get("conversation_id")
    b_id = arm_b.get("conversation_id")
    if not a_id or not b_id or a_id == b_id:
        raise HarnessError("A/B evidence is not two distinct conversations")
    return {
        "A": arm_a,
        "B": arm_b,
        "chat_ids_distinct": True,
        "same_project": (
            arm_a["conversation_template_id"]
            == arm_b["conversation_template_id"]
            == PROJECT_ID
        ),
    }


def validate_failure_restore_evidence(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    instructions = data.get("instructions") or {}
    error = data.get("error") or {}
    if data.get("status") != "failed":
        raise HarnessError("failure-restore evidence is not a failed trial")
    if instructions.get("changed") is not True:
        raise HarnessError(
            "failure-restore evidence never applied alternate instructions"
        )
    if instructions.get("restored") is not True:
        raise HarnessError("failure-restore evidence did not restore instructions")
    if data.get("production_unchanged") is not True:
        raise HarnessError("failure-restore evidence changed production state")
    return {
        "status": data.get("status"),
        "error_type": error.get("type"),
        "error_message": error.get("message"),
        "instructions_changed": True,
        "instructions_restored": True,
        "production_unchanged": True,
    }


def run_switch_probe(
    browser: str = "chrome",
    *,
    a_conversation: Path | None = None,
    b_conversation: Path | None = None,
    expected_a: str | None = None,
    expected_b: str | None = None,
    failure_restore_evidence: Path | None = None,
) -> tuple[int, Path]:
    identity = TrialIdentity.create("switch-probe")
    state_dir = new_state_dir(identity)
    record_path = state_dir / "switch-probe.json"
    project = ProjectClient(PROJECT_NAME, browser)
    production_before = ProductionSnapshot.capture()
    arm_a = arm_instructions("A")
    arm_b = arm_instructions("B")

    record: dict[str, Any] = {
        "schema_version": 1,
        "run_id": identity.run_id,
        "nonce": identity.nonce,
        "status": "running",
        "arm_a_sha256": _sha(arm_a),
        "arm_b_sha256": _sha(arm_b),
        "checks": {},
        "chat_isolation": None,
        "failure_restore_evidence": None,
        "error": None,
    }
    write_json(record_path, record)

    try:
        if project.instructions() != arm_a:
            raise HarnessError("Step 1.1 must start from exact Arm A")
        record["checks"]["initial_a_exact"] = True

        with InstructionLease(project, arm_b) as lease:
            if not lease.changed:
                raise HarnessError("A -> B lease reported no instruction change")
            if project.instructions() != arm_b:
                raise HarnessError("B read-back did not match exact Arm B")
            record["checks"]["b_exact_readback"] = True

        if project.instructions() != arm_a:
            raise HarnessError("B -> A restore did not match exact Arm A")
        record["checks"]["a_exact_after_b"] = True

        evidence_values = (
            a_conversation,
            b_conversation,
            expected_a,
            expected_b,
        )
        if any(value is not None for value in evidence_values):
            if (
                a_conversation is None
                or b_conversation is None
                or expected_a is None
                or expected_b is None
            ):
                raise HarnessError("chat-isolation evidence arguments must be complete")
            record["chat_isolation"] = validate_chat_isolation(
                a_conversation,
                b_conversation,
                expected_a=expected_a,
                expected_b=expected_b,
            )
            record["checks"]["chat_ids_distinct"] = True
            record["checks"]["chat_project_isolation"] = True

        if failure_restore_evidence is not None:
            record["failure_restore_evidence"] = validate_failure_restore_evidence(
                failure_restore_evidence
            )
            record["checks"]["failure_restore_exact"] = True

        production_before.assert_unchanged(ProductionSnapshot.capture())
        record["checks"]["production_unchanged"] = True
        record["status"] = "passed"
        write_json(record_path, record)
        return 0, state_dir
    except Exception as exc:  # noqa: BLE001 - probe records all normal failures
        record["status"] = "failed"
        record["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        try:
            record["checks"]["final_a_exact"] = project.instructions() == arm_a
        except Exception as verify_exc:  # noqa: BLE001 - preserve primary failure
            record["checks"]["final_a_exact"] = False
            record["final_verify_error"] = f"{type(verify_exc).__name__}: {verify_exc}"
        write_json(record_path, record)
        return 1, state_dir


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="chat-scheduling-switch-probe")
    parser.add_argument(
        "--browser", choices=["chrome", "chromium", "auto"], default="chrome"
    )
    parser.add_argument("--a-conversation", type=Path)
    parser.add_argument("--b-conversation", type=Path)
    parser.add_argument("--expected-a")
    parser.add_argument("--expected-b")
    parser.add_argument("--failure-restore-evidence", type=Path)
    args = parser.parse_args()

    code, state = run_switch_probe(
        args.browser,
        a_conversation=args.a_conversation,
        b_conversation=args.b_conversation,
        expected_a=args.expected_a,
        expected_b=args.expected_b,
        failure_restore_evidence=args.failure_restore_evidence,
    )
    print(json.dumps({"exit_code": code, "state_dir": str(state)}, indent=2))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
