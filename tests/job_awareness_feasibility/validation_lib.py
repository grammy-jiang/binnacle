"""Validation helpers for Job Awareness feasibility *evidence*, not production code.

These utilities check structural consistency, never assert that ChatGPT
received a tool result or that a model actually continued a workflow.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)

BASE = Path(__file__).resolve().parents[2] / "docs" / "job-awareness-feasibility"
SCHEMAS = BASE / "schemas"
PLAN = BASE / "worker-manifest.json"
LANES = ("W1", "W2", "W3", "W4", "W5")
STATES = ("PASS", "FAIL", "INCONCLUSIVE", "BLOCKED", "NOT_RUN")
HYPOTHESES = {
    "W1": ("H1",),
    "W2": ("H3",),
    "W3": ("H4",),
    "W4": ("H5",),
    "W5": ("H2", "H3", "H4", "H6"),
}
COMMON = (
    "results.json",
    "findings.md",
    "evidence-index.json",
    "events.jsonl",
    "model-selection.json",
)
EXTRA = {
    "W1": ("carrier-matrix.csv",),
    "W2": ("identity-matrix.csv", "identity-provenance.md"),
    "W3": ("receipt-transitions.csv", "receipt-verdict.json"),
    "W4": ("latency-samples.csv", "metrics.json"),
    "W5": ("trials.csv", "surface-capability.json"),
}
CSV_COLUMNS = {
    "W1": (
        "case_id",
        "carrier",
        "protocol_era",
        "wire_valid",
        "schema_preserved",
        "error_semantics_preserved",
        "model_visibility",
        "trace_ref",
    ),
    "W2": (
        "case_id",
        "call_index",
        "claimed_chat",
        "verified_chat",
        "identity_source",
        "trust_level",
        "expected_hint_ids",
        "actual_hint_ids",
        "leak",
        "trace_ref",
    ),
    "W3": (
        "case_id",
        "step_index",
        "job_id",
        "consumer_id",
        "from_state",
        "event",
        "to_state",
        "server_served",
        "client_received",
        "has_more",
        "acknowledged",
        "cursor_start",
        "cursor_end",
        "trace_ref",
    ),
    "W4": (
        "sample_id",
        "case_id",
        "pair_id",
        "cohort_jobs",
        "carrier",
        "arm",
        "round_index",
        "wall_ms",
        "processing_ms",
        "returned_bytes",
        "reminder_bytes",
        "token_count",
        "token_method",
        "cpu_pct",
        "ram_bytes",
        "host_load",
        "trace_ref",
    ),
    "W5": (
        "trial_id",
        "pair_id",
        "carrier",
        "arm",
        "arm_order",
        "chat_label",
        "surface",
        "subject_model",
        "subject_effort",
        "model_verified",
        "server_sent",
        "client_received",
        "model_used",
        "correct_fetch",
        "fully_drained",
        "meaningful_followup",
        "same_prompt_completed",
        "premature_handoff",
        "elapsed_ms",
        "tool_calls",
        "reminder_bytes",
        "token_count",
        "trace_ref",
    ),
}
BOOL_COLS = {
    "W1": ("wire_valid", "schema_preserved", "error_semantics_preserved"),
    "W2": ("leak",),
    "W3": ("server_served", "client_received", "has_more", "acknowledged"),
    "W4": (),
    "W5": (
        "model_verified",
        "server_sent",
        "client_received",
        "model_used",
        "correct_fetch",
        "fully_drained",
        "meaningful_followup",
        "same_prompt_completed",
        "premature_handoff",
    ),
}
INT_COLS = {
    "W1": (),
    "W2": ("call_index",),
    "W3": ("step_index", "cursor_start", "cursor_end"),
    "W4": (
        "cohort_jobs",
        "round_index",
        "returned_bytes",
        "reminder_bytes",
        "token_count",
        "ram_bytes",
    ),
    "W5": (
        "arm_order",
        "tool_calls",
        "reminder_bytes",
        "token_count",
    ),
}
FLOAT_COLS = {
    "W1": (),
    "W2": (),
    "W3": (),
    "W4": ("wall_ms", "processing_ms", "cpu_pct", "host_load"),
    "W5": ("elapsed_ms",),
}


class ContractError(ValueError):
    """A failed structural/evidence invariant with a precise explanation."""


def fail(message: str) -> NoReturn:
    raise ContractError(message)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            fail(f"duplicate JSON key: {key}")
        obj[key] = value
    return obj


def _no_constant(token: str) -> None:
    fail(f"non-standard JSON constant: {token}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_no_constant,
        )
    except (
        FileNotFoundError,
        UnicodeError,
        json.JSONDecodeError,
        IsADirectoryError,
    ) as exc:
        raise ContractError(f"{path}: cannot read valid UTF-8 JSON: {exc}") from exc


def schema_validate(value: Any, name: str) -> None:
    schema = load_json(SCHEMAS / name)
    Draft202012Validator.check_schema(schema)
    failures = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if failures:
        e = failures[0]
        location = "/".join(str(x) for x in e.absolute_path) or "/"
        fail(f"{name}:{location}: {e.message}")


def sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(131072), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError) as exc:
        raise ContractError(f"cannot hash {path}: {exc}") from exc


def safe_relative(base: Path, relative: str, *, must_exist: bool = True) -> Path:
    rel = PurePosixPath(relative)
    if (
        not relative
        or relative.startswith("/")
        or rel.is_absolute()
        or any(part in ("..", ".", "") for part in rel.parts)
        or "\\" in relative
        or "://" in relative
    ):
        fail(f"unsafe artifact reference: {relative!r}")
    if base.is_symlink():
        fail(f"unsafe symlink evidence root: {base}")
    p = base.joinpath(*rel.parts)
    parent = base.resolve(strict=False)
    if not p.resolve(strict=False).is_relative_to(parent):
        fail(f"evidence reference escaped owner root: {relative!r}")
    if p.is_symlink() or any(x.is_symlink() for x in [*p.parents] if x != base):
        fail(f"evidence reference traverses symlink: {relative!r}")
    if must_exist and (not p.is_file() or p.is_symlink()):
        fail(f"missing or unsafe evidence file: {p}")
    return p


def assert_equal(field: str, left: Any, right: Any) -> None:
    if left != right:
        fail(f"{field} mismatch: {left!r} != {right!r}")


def read_csv(path: Path, lane: str) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, restkey="__extra__", restval=None)
            assert_equal(
                f"{lane} CSV header", tuple(reader.fieldnames or ()), CSV_COLUMNS[lane]
            )
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ContractError(f"invalid CSV {path}: {exc}") from exc
    for pos, row in enumerate(rows, 2):
        if "__extra__" in row or any(value is None for value in row.values()):
            fail(f"{path} row {pos}: wrong column count")
        for col in BOOL_COLS[lane]:
            if row[col] and row[col] not in ("true", "false"):
                fail(f"{path} row {pos}, {col}: boolean must be true/false")
        for col in INT_COLS[lane]:
            if row[col] and not row[col].isdigit():
                fail(f"{path} row {pos}, {col}: must be a nonnegative integer")
        for col in FLOAT_COLS[lane]:
            if row[col]:
                try:
                    x = float(row[col])
                except ValueError:
                    fail(f"{path} row {pos}, {col}: must be a finite number")
                if not math.isfinite(x) or x < 0:
                    fail(f"{path} row {pos}, {col}: must be nonnegative finite")
        if lane == "W4":
            if row["cohort_jobs"] and int(row["cohort_jobs"]) not in (0, 1, 10, 100):
                fail(f"{path} row {pos}: invalid cohort")
            if row["token_method"] not in ("MEASURED", "ESTIMATED", "UNAVAILABLE"):
                fail(f"{path} row {pos}: invalid token method")
            if row["token_method"] == "UNAVAILABLE" and row["token_count"]:
                fail(f"{path} row {pos}: unavailable token count cannot have a value")
        if lane == "W5" and row["arm"] not in ("CONTROL", "CANDIDATE"):
            fail(f"{path} row {pos}: invalid trial arm")
    return rows


def read_events(
    path: Path, worker: str, run_id: str, expected_cases: set[str]
) -> dict[str, dict]:
    values = {}
    try:
        with path.open("r", encoding="utf-8") as stream:
            for lineno, line in enumerate(stream, 1):
                if not line.strip():
                    fail(f"{path}:{lineno}: blank JSONL line")
                try:
                    event = json.loads(
                        line,
                        object_pairs_hook=_no_duplicate_keys,
                        parse_constant=_no_constant,
                    )
                except (json.JSONDecodeError, UnicodeError) as exc:
                    raise ContractError(
                        f"{path}:{lineno}: invalid JSONL {exc}"
                    ) from exc
                schema_validate(event, "event.schema.json")
                assert_equal("event.worker", event["worker"], worker)
                assert_equal("event.run_id", event["run_id"], run_id)
                if event["scenario_id"] not in expected_cases:
                    fail(f"{path}:{lineno}: unexpected case ID")
                if event["event_id"] in values:
                    fail(f"{path}:{lineno}: duplicate event ID")
                values[event["event_id"]] = event
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"cannot open event log {path}: {exc}") from exc
    return values


def model_check(actual: dict, requested: dict, *, require_verified: bool) -> None:
    assert_equal("model.requested_model", actual["requested_model"], requested["model"])
    assert_equal(
        "model.requested_effort", actual["requested_effort"], requested["effort"]
    )
    if actual["fallback_used"]:
        fail("automatic model fallback is prohibited")
    if actual["verification"] == "VERIFIED":
        if not (actual["model_match_verified"] and actual["effort_match_verified"]):
            fail("model or effort was not verified as the requested selection")
        if not (actual["effective_model"] and actual["effective_effort"]):
            fail("VERIFIED requires observed effective model and effort")
        if not actual["verification_evidence_ref"]:
            fail("VERIFIED requires the originating selector/CLI evidence ref")
    elif require_verified:
        fail("a PASS result requires verified effective model and effort")
