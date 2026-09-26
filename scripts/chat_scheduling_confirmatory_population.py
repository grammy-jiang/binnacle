"""Frozen Phase-4 confirmatory population loading for P4-A6."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PARTITIONS = ("R1-R2", "R3-R4", "R5-R6", "R7", "R8-R9", "R10-R11")


@dataclass(frozen=True)
class Trial:
    run_id: str
    scenario: str
    arm: str
    endpoint: str | None
    budget: int | None
    repeat: int | None
    slot_id: str | None
    order: tuple[float, str]
    metrics: dict[str, Any] | None
    evidence_error: bool


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _check_addendum(
    *,
    schedule_dir: Path,
    partition: str,
    checkpoint_row: Mapping[str, Any],
    state_dir: Path,
) -> str | None:
    source_hashes = checkpoint_row.get("source_file_sha256")
    if not isinstance(source_hashes, Mapping):
        return None
    frozen_chat_sha = source_hashes.get("chat-timing.json")
    chat_path = state_dir / "chat-timing.json"
    if not isinstance(frozen_chat_sha, str) or not chat_path.exists():
        return None
    current_chat_sha = _sha(chat_path)
    if current_chat_sha == frozen_chat_sha:
        return None

    addendum_path = (
        schedule_dir / f"phase4-confirmatory-{partition}-timing-addendum.json"
    )
    if not addendum_path.exists():
        raise ValueError(
            f"{checkpoint_row.get('slot_id')}: chat timing changed after checkpoint "
            f"but {addendum_path.name} is missing"
        )
    addendum = _load(addendum_path)
    rows = addendum.get("rows")
    if not isinstance(rows, list):
        raise TypeError(f"{addendum_path} rows must be a list")
    slot_id = checkpoint_row.get("slot_id")
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping) and row.get("slot_id") == slot_id
    ]
    if len(matches) != 1:
        raise ValueError(f"{slot_id}: timing addendum must contain exactly one row")
    row = matches[0]
    expected = {
        "old_chat_timing_sha256": frozen_chat_sha,
        "new_chat_timing_sha256": current_chat_sha,
        "new_metrics_sha256": _sha(state_dir / "metrics.json"),
        "new_trace_sha256": _sha(state_dir / "trace.json"),
    }
    for key, value in expected.items():
        if row.get(key) != value:
            raise ValueError(
                f"{slot_id}: timing addendum {key} does not match current evidence"
            )
    for name, key in (
        ("metrics.json.pre-p4a6", "old_metrics_sha256"),
        ("trace.json.pre-p4a6", "old_trace_sha256"),
    ):
        backup = state_dir / name
        if not backup.exists() or row.get(key) != _sha(backup):
            raise ValueError(
                f"{slot_id}: timing addendum {key} does not match preserved evidence"
            )
    return _sha(addendum_path)


def _trial_from_owner(
    *,
    slot: Mapping[str, Any],
    owner: Mapping[str, Any],
    state_dir: Path,
    order: int,
    submitted: Callable[[Mapping[str, Any]], bool],
) -> Trial:
    record = _load(state_dir / "trial.json")
    run_id = owner.get("run_id")
    if not isinstance(run_id, str) or record.get("run_id") != run_id:
        raise ValueError(
            f"{slot['slot_id']}: frozen run identity does not match trial.json"
        )
    if not submitted(record):
        raise ValueError(
            f"{slot['slot_id']}: frozen owner is not classified as submitted"
        )
    checks = {
        "scenario_id": slot["scenario_id"],
        "arm": slot["arm"],
        "endpoint_id": slot["endpoint_id"],
    }
    for key, expected in checks.items():
        if record.get(key) != expected:
            raise ValueError(f"{slot['slot_id']}: {key} mismatch in frozen owner")
    budget = _int(record.get("budget_s"))
    if budget is not None and budget != slot["budget_s"]:
        raise ValueError(f"{slot['slot_id']}: budget mismatch in frozen owner")
    metrics_path = state_dir / "metrics.json"
    metrics = _load(metrics_path) if metrics_path.exists() else None
    evidence_error = bool(record.get("evidence_integrity_error"))
    endpoint_evidence = state_dir / "endpoint-evidence.json"
    if endpoint_evidence.exists():
        evidence_error |= bool(_load(endpoint_evidence).get("evidence_integrity_error"))
    return Trial(
        run_id=run_id,
        scenario=str(slot["scenario_id"]),
        arm=str(slot["arm"]),
        endpoint=(
            record.get("endpoint_id")
            if isinstance(record.get("endpoint_id"), str)
            else None
        ),
        budget=budget,
        repeat=int(slot["repeat"]),
        slot_id=str(slot["slot_id"]),
        order=(float(order), run_id),
        metrics=metrics,
        evidence_error=evidence_error,
    )


def _load_r12_owner(
    *,
    schedule_dir: Path,
    runs_root: Path,
    slot: Mapping[str, Any],
    order: int,
    submitted: Callable[[Mapping[str, Any]], bool],
) -> tuple[Trial, dict[str, Any]]:
    result_path = runs_root.parent / "phase4" / "runs" / "4B-C300.json"
    result_sha = _sha(result_path)
    progress_path = schedule_dir / "phase4-progress.json"
    if progress_path.exists():
        progress = _load(progress_path)
        frozen = progress.get("frozen_hashes")
        expected_sha = (
            frozen.get("phase4_4B_C300_result_json")
            if isinstance(frozen, Mapping)
            else None
        )
        if isinstance(expected_sha, str) and result_sha != expected_sha:
            raise ValueError(
                "canonical R12 calibration result hash differs from frozen progress"
            )
    rows = _load(result_path).get("rows")
    if not isinstance(rows, list):
        raise TypeError(f"{result_path} rows must be a list")
    owners = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("slot_id") == "4B:C300:R12:1"
        and row.get("scenario") == "R12"
        and row.get("arm") == "C"
    ]
    if len(owners) != 1:
        raise ValueError(
            "frozen 4B-C300 result must contain exactly one canonical R12 owner"
        )
    owner = owners[0]
    state_value = owner.get("state_dir")
    if not isinstance(state_value, str):
        raise TypeError("canonical R12 owner has no state_dir")
    state_dir = Path(state_value)
    trial = _trial_from_owner(
        slot=slot,
        owner={"run_id": state_dir.name},
        state_dir=state_dir,
        order=order,
        submitted=submitted,
    )
    return trial, {
        "path": str(result_path),
        "sha256": result_sha,
        "run_id": trial.run_id,
    }


def load_frozen_population(
    *,
    schedule_path: Path,
    runs_root: Path,
    expected_slots: Sequence[Mapping[str, Any]],
    submitted: Callable[[Mapping[str, Any]], bool],
) -> tuple[list[Trial], dict[str, Any]]:
    """Load only checkpoint-frozen main owners; never scan the global runs directory."""
    schedule_dir = schedule_path.parent
    by_id = {str(slot["slot_id"]): slot for slot in expected_slots}
    trials: list[Trial] = []
    seen: set[str] = set()
    checkpoints: list[dict[str, Any]] = []
    addenda: dict[str, str] = {}
    order = 0

    for partition in PARTITIONS:
        path = schedule_dir / f"phase4-confirmatory-{partition}-checkpoint.json"
        payload = _load(path)
        rows = payload.get("canonical_slots")
        if not isinstance(rows, list):
            raise TypeError(f"{path} canonical_slots must be a list")
        for owner in rows:
            if not isinstance(owner, Mapping):
                raise TypeError(f"{path} canonical slot must be an object")
            slot_id = owner.get("slot_id")
            if (
                not isinstance(slot_id, str)
                or slot_id not in by_id
                or slot_id == "R12-r01-C"
            ):
                raise ValueError(
                    f"{path}: unknown/non-performance frozen slot {slot_id!r}"
                )
            if slot_id in seen:
                raise ValueError(f"duplicate frozen slot owner: {slot_id}")
            slot = by_id[slot_id]
            if owner.get("arm") != slot["arm"] or owner.get("repeat") != slot["repeat"]:
                raise ValueError(f"{slot_id}: checkpoint slot identity mismatch")
            state_value = owner.get("state_dir")
            if not isinstance(state_value, str):
                raise TypeError(f"{slot_id}: checkpoint owner has no state_dir")
            state_dir = Path(state_value)
            if state_dir.parent.resolve() != runs_root.resolve():
                raise ValueError(
                    f"{slot_id}: checkpoint state_dir is outside --runs-root"
                )
            addendum_sha = _check_addendum(
                schedule_dir=schedule_dir,
                partition=partition,
                checkpoint_row=owner,
                state_dir=state_dir,
            )
            if addendum_sha is not None:
                addenda[partition] = addendum_sha
            order += 1
            trials.append(
                _trial_from_owner(
                    slot=slot,
                    owner=owner,
                    state_dir=state_dir,
                    order=order,
                    submitted=submitted,
                )
            )
            seen.add(slot_id)
        checkpoints.append(
            {"partition": partition, "path": str(path), "sha256": _sha(path)}
        )

    expected_performance = {slot_id for slot_id in by_id if slot_id != "R12-r01-C"}
    if seen != expected_performance:
        missing = sorted(expected_performance - seen)
        extra = sorted(seen - expected_performance)
        raise ValueError(
            f"frozen checkpoint population mismatch: missing={missing}, extra={extra}"
        )

    r12_slot = by_id.get("R12-r01-C")
    if r12_slot is None:
        raise ValueError("schedule has no canonical R12-r01-C slot")
    order += 1
    r12, r12_source = _load_r12_owner(
        schedule_dir=schedule_dir,
        runs_root=runs_root,
        slot=r12_slot,
        order=order,
        submitted=submitted,
    )
    trials.append(r12)
    seen.add("R12-r01-C")
    if len(trials) != len(by_id) or len(seen) != len(by_id):
        raise ValueError(
            "frozen confirmatory population is not exactly the scheduled 160 slots"
        )

    return trials, {
        "selection": "six_frozen_checkpoint_owner_lists_plus_frozen_r12",
        "checkpoint_count": len(checkpoints),
        "checkpoint_owners": len(trials) - 1,
        "total_owners": len(trials),
        "checkpoints": checkpoints,
        "timing_addenda_sha256": addenda,
        "r12_source": r12_source,
    }
