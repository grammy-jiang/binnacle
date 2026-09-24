import hashlib
import json
from pathlib import Path

import pytest

from scripts.chat_scheduling_replay_corpus import (
    TURN_FIELDS,
    WAIT_FIELDS,
    CorpusError,
    _read_journal,
    extract_source,
    main,
    merge_shards,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _contract() -> dict:
    return {
        "schema_version": 1,
        "turn_fields": TURN_FIELDS,
        "wait_fields": WAIT_FIELDS,
    }


def _trace(run_id: str, *, arm: str = "A", waits: bool = True) -> dict:
    tools = (
        [
            {
                "call_id": "read-1",
                "node_id": "read_input",
                "tool": "read_file",
                "turn": "TURN-PRIVATE/suffix",
                "start_s": 1.0,
                "end_s": 1.2,
                "args": {"path": "/tmp/private"},
                "result": {"content": "SECRET conversation prose"},
            }
        ]
        if waits
        else []
    )
    jobs = []
    if waits:
        tools += [
            {
                "call_id": "wait-1",
                "node_id": "wait_result",
                "tool": "job_status",
                "turn": "TURN-PRIVATE/one",
                "start_s": 2.0,
                "end_s": 7.1,
                "blocking_start_s": 2.0,
                "blocking_end_s": 7.0,
                "args": {
                    "job_id": "JOB-SECRET",
                    "wait_seconds": 50,
                    "tail_lines": 20,
                },
                "result": {
                    "job_id": "JOB-SECRET",
                    "state": "running",
                    "waited_s": 5.0,
                    "output": "PRIVATE OUTPUT",
                },
            },
            {
                "call_id": "wait-2",
                "node_id": "wait_result",
                "tool": "job_status",
                "turn": "TURN-PRIVATE/two",
                "start_s": 10.0,
                "end_s": 12.1,
                "blocking_start_s": 10.0,
                "blocking_end_s": 12.0,
                "args": {"job_id": "JOB-SECRET", "wait_seconds": 10},
                "result": {
                    "job_id": "JOB-SECRET",
                    "state": "exited",
                    "waited_s": 2.0,
                    "output": "PRIVATE OUTPUT",
                },
            },
        ]
        jobs = [
            {
                "job_id": "JOB-SECRET",
                "start_s": 0.5,
                "end_s": 11.5,
                "exit_code": 0,
                "signal": None,
            }
        ]
    return {
        "schema_version": 1,
        "scenario_id": "R5",
        "run_id": run_id,
        "arm": arm,
        "timing_status": "complete",
        "tools": tools,
        "jobs": jobs,
    }


def _add_trial(
    root: Path,
    run_id: str,
    *,
    arm: str = "A",
    waits: bool = True,
) -> tuple[dict, dict]:
    evidence = root / run_id
    _write(
        evidence / "trial.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "scenario_id": "R5",
            "arm": arm,
            "status": "completed",
            "prompt": "SECRET user prose",
        },
    )
    _write(evidence / "trace.json", _trace(run_id, arm=arm, waits=waits))
    frozen = {
        "trial_id": run_id,
        "arm": arm,
        "scenario": "R5",
        "submitted": True,
        "trial_status": "completed",
        "evidence_dir": str(evidence),
        "correctness_passed": True,
        "same_prompt_completion": True,
    }
    slot = {
        "run_id": run_id,
        "arm": arm,
        "scenario_id": "R5",
        "submitted": True,
        "correctness_passed": True,
        "same_prompt_completion": True,
    }
    return frozen, slot


def _canonical_fixture(
    tmp_path: Path,
    trial_specs: list[tuple[str, str, bool]] | None = None,
) -> tuple[Path, dict]:
    specs = trial_specs or [("trial-b", "A", True)]
    state_root = tmp_path / "state"
    pairs = [
        _add_trial(state_root, run_id, arm=arm, waits=waits)
        for run_id, arm, waits in specs
    ]
    frozen = [pair[0] for pair in pairs]
    slots = [pair[1] for pair in pairs]
    report = tmp_path / "report.json"
    _write(
        report,
        {
            "canonical_slots": slots,
            "notes": "SECRET report prose that must not enter the shard",
        },
    )
    report_sha = hashlib.sha256(report.read_bytes()).hexdigest()
    source = {
        "source_id": "phase1-stepX",
        "kind": "phase1-macro-report",
        "report_path": str(report),
        "sha256": report_sha,
        "trial_count": len(frozen),
        "trials": frozen,
    }
    inventory = tmp_path / "inventory.json"
    _write(
        inventory,
        {
            "schema_version": 1,
            "replay_contract": _contract(),
            "sources": [source],
        },
    )
    return inventory, source


def _operational_source() -> dict:
    return {
        "source_id": "operational-journal",
        "kind": "operational-journal",
        "status": "available",
        "service": "binnacle-mcp.service",
        "event_filter": "job_status_timing",
        "line_count": 1,
        "oldest_unix_s": "1005.000000",
        "newest_unix_s": "1005.000000",
    }


def _operational_inventory(tmp_path: Path) -> Path:
    path = tmp_path / "operational-inventory.json"
    _write(
        path,
        {
            "schema_version": 1,
            "replay_contract": _contract(),
            "sources": [_operational_source()],
        },
    )
    return path


def _journal() -> str:
    return "999.000000 host app: event=tool_call call=c0 tool=read_file turn=TURN-SECRET/x args={}\n1000.000000 host app: event=tool_call call=c1 tool=job_status turn=TURN-SECRET/a args={}\n1004.900000 host app: event=job_exit job_id=JOB-SECRET exit_code=0 signal=null\n1005.000000 host app: event=job_status_timing call=c1 job_id=JOB-SECRET wait_requested_s=50 waited_s=5 state=exited turn=TURN-SECRET/a\n1005.100000 host app: event=tool_result call=c1 tool=job_status turn=TURN-SECRET/a state=exited\n"


def test_extract_canonical_uses_actual_waits_completion_and_redaction(tmp_path):
    inventory, source = _canonical_fixture(tmp_path)

    shard = extract_source(inventory, "phase1-stepX")

    assert shard["status"] == "available"
    assert shard["source_sha256"] == source["sha256"]
    assert shard["trial_count"] == shard["row_count"] == 1
    row = shard["rows"][0]
    assert set(row) == set(TURN_FIELDS)
    assert row["observed_blocking_wall_s"] == 7.0
    assert row["observed_required_completions"] == 1
    assert row["terminal_state"] == "completed"
    assert row["correct"] is True
    assert row["same_prompt"] is True
    assert row["base_turn"] == "TURN-PRIVATE"
    assert len(row["waits"]) == 2
    first, second = row["waits"]
    assert set(first) == set(WAIT_FIELDS)
    assert first["call_start_offset_s"] == 1.0
    assert first["blocking_end_offset_s"] == 6.0
    assert first["waited_s"] == 5.0
    assert first["observed_completion"] is False
    assert second["job_exit_offset_s"] == 10.5
    assert second["observed_completion"] is True
    assert second["job_id_hash"] == hashlib.sha256(b"JOB-SECRET").hexdigest()
    serialized = json.dumps(shard)
    assert "JOB-SECRET" not in serialized
    assert "SECRET conversation prose" not in serialized
    assert "PRIVATE OUTPUT" not in serialized


def test_extract_keeps_zero_wait_canonical_slots_and_sorts_deterministically(tmp_path):
    inventory, _ = _canonical_fixture(
        tmp_path,
        [("trial-z", "B", False), ("trial-a", "A", True)],
    )

    shard = extract_source(inventory, "phase1-stepX")

    assert shard["trial_count"] == 2
    assert [row["trial_id"] for row in shard["rows"]] == ["trial-a", "trial-z"]
    zero = shard["rows"][1]
    assert zero["waits"] == []
    assert zero["observed_blocking_wall_s"] == 0
    assert zero["observed_required_completions"] == 0


def test_extract_fails_when_referenced_canonical_trial_is_missing_from_report(tmp_path):
    inventory, source = _canonical_fixture(tmp_path)
    report_path = Path(source["report_path"])
    _write(report_path, {"canonical_slots": []})
    source["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    document = json.loads(inventory.read_text())
    document["sources"][0]["sha256"] = source["sha256"]
    _write(inventory, document)

    with pytest.raises(CorpusError, match="referenced canonical trial missing"):
        extract_source(inventory, "phase1-stepX")


def test_extract_fails_when_referenced_canonical_evidence_is_missing(tmp_path):
    inventory, _ = _canonical_fixture(tmp_path)
    document = json.loads(inventory.read_text())
    evidence = Path(document["sources"][0]["trials"][0]["evidence_dir"])
    (evidence / "trace.json").unlink()

    with pytest.raises(CorpusError, match="trial evidence is missing"):
        extract_source(inventory, "phase1-stepX")


def test_extract_fails_on_frozen_source_hash_mismatch(tmp_path):
    inventory, source = _canonical_fixture(tmp_path)
    Path(source["report_path"]).write_text("{}\n", encoding="utf-8")

    with pytest.raises(CorpusError, match="report SHA-256 mismatch"):
        extract_source(inventory, "phase1-stepX")


def test_operational_extraction_normalizes_turns_hashes_ids_and_uses_actual_wait(
    tmp_path,
):
    inventory = _operational_inventory(tmp_path)

    shard = extract_source(
        inventory,
        "operational-journal",
        journal_text=_journal(),
    )

    assert shard["status"] == "available"
    assert shard["source_window"]["line_count"] == 1
    [row] = shard["rows"]
    assert row["trial_id"].startswith("operational-")
    assert row["base_turn"].startswith("turn-")
    assert row["observed_blocking_wall_s"] == 5.0
    assert row["terminal_state"] == "exited"
    [wait] = row["waits"]
    assert wait["call_start_offset_s"] == 1.0
    assert wait["blocking_end_offset_s"] == 6.0
    assert wait["waited_s"] == 5.0
    assert wait["job_exit_offset_s"] == 5.9
    assert wait["required_completion"] is False
    serialized = json.dumps(shard)
    assert "TURN-SECRET" not in serialized
    assert "JOB-SECRET" not in serialized


def test_operational_window_check_uses_token_filter_before_event_parsing(tmp_path):
    inventory = _operational_inventory(tmp_path)
    document = json.loads(inventory.read_text())
    document["sources"][0]["line_count"] = 2
    _write(inventory, document)
    incidental = (
        "1005.000000 host app: event=tool_call call=c2 tool=search_text "
        'turn=TURN-SECRET/b args={"pattern":"job_status_timing"}\n'
    )

    shard = extract_source(
        inventory,
        "operational-journal",
        journal_text=_journal() + incidental,
    )

    assert shard["status"] == "available"
    assert shard["source_window"]["line_count"] == 2
    assert shard["source_window"]["window_line_count"] == 2
    assert shard["source_window"]["parsed_rows"] == 1
    assert shard["source_window"]["replayable_wait_count"] == 1
    assert shard["row_count"] == 1


def test_operational_reader_uses_user_journal_and_frozen_bounds(monkeypatch):
    seen = {}

    class Result:
        returncode = 0
        stdout = "journal\n"

    def run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr("scripts.chat_scheduling_replay_corpus.subprocess.run", run)

    assert _read_journal(_operational_source()) == "journal\n"
    assert seen["command"][:4] == [
        "journalctl",
        "--user",
        "-u",
        "binnacle-mcp.service",
    ]
    assert seen["command"][-3:] == ["-o", "short-unix", "--no-pager"]
    assert seen["kwargs"] == {
        "check": False,
        "capture_output": True,
        "text": True,
    }


def test_operational_missing_frozen_window_produces_explicit_unavailable_shard(
    tmp_path,
):
    inventory = _operational_inventory(tmp_path)

    shard = extract_source(inventory, "operational-journal", journal_text="")

    assert shard["status"] == "unavailable"
    assert shard["row_count"] == 0
    assert "frozen_window_line_count_mismatch" in shard["reason"]


def test_extract_cli_contract_writes_requested_shard(tmp_path):
    inventory, _ = _canonical_fixture(tmp_path)
    output = tmp_path / "shard.json"

    assert (
        main(
            [
                "extract",
                "--inventory",
                str(inventory),
                "--source-id",
                "phase1-stepX",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text())["source_id"] == "phase1-stepX"


def test_merge_uses_frozen_header_contract_and_reports_optional_exclusion(tmp_path):
    inventory, canonical_source = _canonical_fixture(tmp_path)
    document = json.loads(inventory.read_text())
    document["sources"].append(
        {
            **_operational_source(),
            "status": "unavailable",
        }
    )
    _write(inventory, document)
    canonical = extract_source(inventory, "phase1-stepX")
    operational = extract_source(inventory, "operational-journal")
    shards = tmp_path / "shards"
    _write(shards / "phase1-stepX.json", canonical)
    _write(shards / "operational-journal.json", operational)
    output, report = tmp_path / "corpus.json", tmp_path / "corpus.md"

    corpus = merge_shards(inventory, shards, output, report)

    assert list(corpus) == ["schema_version", "fields", "wait_fields", "rows"]
    assert corpus["fields"] == TURN_FIELDS
    assert corpus["wait_fields"] == WAIT_FIELDS
    assert corpus["rows"][0]["source_sha256"] == canonical_source["sha256"]
    text = report.read_text()
    assert "operational-journal" in text
    assert "inventory_window_unavailable" in text
    assert "Conversation prose" in text
    assert hashlib.sha256(output.read_bytes()).hexdigest() in text


def test_merge_fails_when_any_frozen_source_has_no_shard(tmp_path):
    inventory, _ = _canonical_fixture(tmp_path)

    with pytest.raises(CorpusError, match="missing shard for frozen source"):
        merge_shards(
            inventory,
            tmp_path / "missing-shards",
            tmp_path / "out.json",
            tmp_path / "out.md",
        )
