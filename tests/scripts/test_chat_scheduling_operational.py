from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts import chat_scheduling_operational as operational

START = "2026-09-25T12:00:00+00:00"
END = "2026-09-25T12:01:00+00:00"
UNITS = {
    "server": "server.service",
    "jobs": "jobs.service",
    "tunnel": "tunnel.service",
}


def entry(
    when: str,
    unit: str,
    message: str,
    cursor: str,
    *,
    priority: int = 6,
) -> dict[str, str]:
    stamp = datetime.fromisoformat(when.replace("Z", "+00:00"))
    micros = int(stamp.astimezone(timezone.utc).timestamp() * 1_000_000)
    return {
        "__REALTIME_TIMESTAMP": str(micros),
        "__CURSOR": cursor,
        "_SYSTEMD_UNIT": unit,
        "PRIORITY": str(priority),
        "MESSAGE": message,
    }


def minimal_sources() -> dict[str, list[dict[str, str]]]:
    return {
        "server": [
            entry(
                "2026-09-25T12:00:01+00:00",
                UNITS["server"],
                "2026-09-25T12:00:01.000 INFO: event=tool_call "
                'call=s1 tool=read_file client=openai-mcp turn=t1/a args={"path":"/tmp/a"}',
                "s1",
            )
        ],
        "jobs": [
            entry(
                "2026-09-25T12:00:02+00:00",
                UNITS["jobs"],
                "2026-09-25T12:00:02.000 INFO: event=job_manager_start "
                "pid=1 owner=o boot=b recovered=0",
                "j1",
            )
        ],
        "tunnel": [
            entry(
                "2026-09-25T12:00:03+00:00",
                UNITS["tunnel"],
                "tunnel healthy",
                "t1",
            )
        ],
    }


def build(
    sources: dict[str, list[dict[str, str]]] | None = None,
) -> dict[str, object]:
    return operational.build_evidence(
        start=START,
        end=END,
        units=UNITS,
        entries_by_role=sources or minimal_sources(),
    )


def test_half_open_window_and_three_required_units_are_frozen():
    sources = minimal_sources()
    sources["server"].extend(
        [
            entry(
                START,
                UNITS["server"],
                "2026-09-25T12:00:00.000 INFO: event=tool_call "
                'call=start tool=list_files client=openai-mcp turn=t0/a args={"path":"/tmp"}',
                "s0",
            ),
            entry(
                END,
                UNITS["server"],
                "2026-09-25T12:01:00.000 INFO: event=tool_call "
                'call=end tool=list_files client=openai-mcp turn=t2/a args={"path":"/tmp"}',
                "s-end",
            ),
        ]
    )

    evidence = build(sources)

    assert evidence["window"]["semantics"] == "[start,end)"
    assert list(evidence["sources"]) == ["server", "jobs", "tunnel"]
    calls = evidence["telemetry"]["calls"]
    assert [item["call"] for item in calls] == ["start", "s1"]
    assert evidence["sources"]["server"]["in_window_entry_count"] == 2
    assert evidence["sources"]["server"]["last_cursor"] == "s1"


def test_duplicate_journal_lines_are_removed_without_double_counting():
    sources = minimal_sources()
    duplicate = dict(sources["server"][0])
    sources["server"].append(duplicate)

    evidence = build(sources)

    assert evidence["sources"]["server"]["duplicates_removed"] == 1
    assert evidence["sources"]["server"]["unique_entry_count"] == 1
    assert evidence["summary"]["efficiency"]["tool_call_count"] == 1


def test_turn_job_correlation_and_same_turn_completion_proxy():
    sources = minimal_sources()
    sources["server"] = [
        entry(
            "2026-09-25T12:00:05+00:00",
            UNITS["server"],
            "2026-09-25T12:00:05.000 INFO: event=tool_call "
            'call=c1 tool=run_command client=openai-mcp turn=turn-A/1 args={"command":"x"}',
            "s-call",
        ),
        entry(
            "2026-09-25T12:00:06+00:00",
            UNITS["server"],
            "2026-09-25T12:00:06.000 INFO: event=tool_result "
            "call=c1 tool=run_command client=openai-mcp is_error=False "
            "job_id=job-1 state=running",
            "s-result",
        ),
        entry(
            "2026-09-25T12:00:07+00:00",
            UNITS["server"],
            "2026-09-25T12:00:07.000 INFO: event=job_status_timing "
            "call=w1 job_id=job-1 wait_requested_s=0 wait_effective_s=0 waited_s=0 "
            "blocking_policy=tracked blocking_budget_exhausted=false "
            "turn=turn-A client=openai-mcp state=exited",
            "s-wait",
        ),
    ]
    sources["jobs"] = [
        entry(
            "2026-09-25T12:00:05.100000+00:00",
            UNITS["jobs"],
            "2026-09-25T12:00:05.100 INFO: event=job_start "
            "job_id=job-1 pid=1 call=c1 owner=manager",
            "j-start",
        ),
        entry(
            "2026-09-25T12:00:06.900000+00:00",
            UNITS["jobs"],
            "2026-09-25T12:00:06.900 INFO: event=job_exit "
            "job_id=job-1 exit_code=0 signal=None reason=normal_exit "
            "runtime_s=1.8 call=c1 owner=manager",
            "j-exit",
        ),
    ]

    evidence = build(sources)

    assert evidence["telemetry"]["jobs"][0]["turn"] == "turn-A"
    turn = evidence["telemetry"]["turns"][0]
    assert turn["turn"] == "turn-A"
    assert turn["job_ids"] == ["job-1"]
    assert turn["same_turn_job_completion_proxy"] is True


def test_blocking_union_and_exhaustion_are_normalized():
    sources = minimal_sources()
    sources["server"] = [
        entry(
            "2026-09-25T12:00:05+00:00",
            UNITS["server"],
            "2026-09-25T12:00:05.000 INFO: event=job_status_timing "
            "call=w1 job_id=j1 wait_requested_s=4 wait_effective_s=4 waited_s=4 "
            "blocking_budget_s=8 blocking_policy=tracked "
            "blocking_budget_exhausted=false turn=turn-B client=openai-mcp state=running",
            "s1",
        ),
        entry(
            "2026-09-25T12:00:05+00:00",
            UNITS["server"],
            "2026-09-25T12:00:05.000 INFO: event=blocking_window_closed "
            "call=w1 turn=turn-B client=openai-mcp blocking_budget_s=8 "
            "blocking_window_wall_s=4 blocking_spent_after_s=4 "
            "blocking_remaining_after_s=4",
            "s2",
        ),
        entry(
            "2026-09-25T12:00:06+00:00",
            UNITS["server"],
            "2026-09-25T12:00:06.000 INFO: event=job_status_timing "
            "call=w2 job_id=j2 wait_requested_s=2 wait_effective_s=0 waited_s=0 "
            "blocking_budget_s=8 blocking_policy=exhausted "
            "blocking_budget_exhausted=true turn=turn-B client=openai-mcp state=running",
            "s3",
        ),
        entry(
            "2026-09-25T12:00:06+00:00",
            UNITS["server"],
            "2026-09-25T12:00:06.000 INFO: event=blocking_window_closed "
            "call=w2 turn=turn-B client=openai-mcp blocking_budget_s=8 "
            "blocking_window_wall_s=2 blocking_spent_after_s=8 "
            "blocking_remaining_after_s=0",
            "s4",
        ),
    ]

    evidence = build(sources)
    blocking = evidence["summary"]["blocking_wall"]

    assert blocking["blocking_window_count"] == 2
    assert blocking["blocking_wall_union_s"] == 5.0
    assert blocking["exhausted_wait_count"] == 1
    review = operational.build_review(
        evidence,
        focus="blocking-wall",
        reference={"report_kind": "phase4-live-confirmatory", "selected_budget_s": 300},
    )
    assert review["metrics"]["blocking_wall_union_s_by_turn"] == {"turn-B": 5.0}
    assert review["metrics"]["exhausted_turns"] == ["turn-B"]


def test_errors_interruptions_and_tunnel_errors_use_normalized_categories():
    sources = minimal_sources()
    sources["server"] = [
        entry(
            "2026-09-25T12:00:10+00:00",
            UNITS["server"],
            "2026-09-25T12:00:10.000 WARNING: event=tool_result "
            "call=e1 tool=read_file client=openai-mcp is_error=True "
            "error_class=ToolError error_code=path_outside_root error=secret-prose",
            "s-err",
            priority=4,
        )
    ]
    sources["jobs"] = [
        entry(
            "2026-09-25T12:00:11+00:00",
            UNITS["jobs"],
            "2026-09-25T12:00:11.000 WARNING: event=job_interrupted "
            "job_id=j1 reason=owner_restart call=c1",
            "j-err",
            priority=4,
        )
    ]
    sources["tunnel"] = [
        entry(
            "2026-09-25T12:00:12+00:00",
            UNITS["tunnel"],
            "arbitrary tunnel error details must not be retained",
            "t-err",
            priority=3,
        )
    ]

    evidence = build(sources)
    categories = [item["category"] for item in evidence["telemetry"]["errors"]]

    assert categories == ["tool_error", "job_interrupted", "tunnel_journal_error"]
    frozen = json.dumps(evidence, sort_keys=True)
    assert "secret-prose" not in frozen
    assert "arbitrary tunnel error details" not in frozen


def test_tokenizer_fields_precede_estimates_and_optional_fields_may_be_missing():
    sources = minimal_sources()
    sources["server"] = [
        entry(
            "2026-09-25T12:00:01+00:00",
            UNITS["server"],
            "2026-09-25T12:00:01.000 INFO: event=tool_call "
            'call=a tool=read_file client=openai-mcp turn=t1/a args={"path":"/tmp/a"}',
            "a1",
        ),
        entry(
            "2026-09-25T12:00:02+00:00",
            UNITS["server"],
            "2026-09-25T12:00:02.000 INFO: event=tool_result "
            "call=a tool=read_file client=openai-mcp is_error=False "
            "tokenizer_tokens=12 tokenizer_encoding=o200k_base est_tokens=99",
            "a2",
        ),
        entry(
            "2026-09-25T12:00:03+00:00",
            UNITS["server"],
            "2026-09-25T12:00:03.000 INFO: event=tool_call "
            'call=b tool=list_files client=openai-mcp turn=t1/b args={"path":"/tmp"}',
            "b1",
        ),
        entry(
            "2026-09-25T12:00:04+00:00",
            UNITS["server"],
            "2026-09-25T12:00:04.000 INFO: event=tool_result "
            "call=b tool=list_files client=openai-mcp is_error=False est_tokens=3",
            "b2",
        ),
    ]

    evidence = build(sources)
    calls = evidence["telemetry"]["calls"]

    assert calls[0]["tool_result_tokens"] == 12
    assert calls[0]["source_kind"] == "tokenizer"
    assert calls[1]["tool_result_tokens"] == 3
    assert calls[1]["source_kind"] == "estimate"
    efficiency = evidence["summary"]["efficiency"]
    assert efficiency["tool_result_tokens_total"] == 15
    assert efficiency["tokenizer_telemetry_calls"] == 1
    assert efficiency["estimated_token_calls"] == 1


def test_output_order_and_hash_are_stable_for_shuffled_input():
    left = minimal_sources()
    left["server"].append(
        entry(
            "2026-09-25T12:00:00.500000+00:00",
            UNITS["server"],
            "2026-09-25T12:00:00.500 INFO: event=tool_call "
            'call=early tool=search_text client=openai-mcp turn=t0/a args={"pattern":"x"}',
            "early",
        )
    )
    right = {role: list(reversed(rows)) for role, rows in left.items()}

    first = build(left)
    second = build(right)

    assert operational._json_bytes(first) == operational._json_bytes(second)
    assert operational._sha_payload(first) == operational._sha_payload(second)


def test_workflow_review_uses_explicit_continuation_only_and_reference_identity():
    sources = minimal_sources()
    sources["server"].append(
        entry(
            "2026-09-25T12:00:04+00:00",
            UNITS["server"],
            "2026-09-25T12:00:04.000 INFO: event=manual_continuation "
            "turn=t1 user_prompt=DO-NOT-RETAIN",
            "cont",
        )
    )
    evidence = build(sources)
    review = operational.build_review(
        evidence,
        focus="workflow-ux",
        reference={
            "report_kind": "phase4-live-confirmatory",
            "verdict": "GO_PHASE5",
            "selected_budget_s": 300,
            "phase4_source_head": "abc123",
        },
    )

    assert review["metrics"]["explicit_continuation_incident_count"] == 1
    assert review["metrics"]["continuation_evidence"] == [
        {
            "at": "2026-09-25T12:00:04.000000Z",
            "event": "manual_continuation",
            "turn": "t1",
        }
    ]
    assert review["reference"]["selected_budget_s"] == 300
    assert "DO-NOT-RETAIN" not in json.dumps(review)
    assert "user prompt text is inferred" in review["metrics"]["proxy_note"]


def test_missing_required_source_and_wrong_unit_are_evidence_errors():
    sources = minimal_sources()
    del sources["tunnel"]
    with pytest.raises(operational.OperationalEvidenceError, match="missing required"):
        build(sources)

    sources = minimal_sources()
    sources["jobs"][0]["_SYSTEMD_UNIT"] = "different.service"
    with pytest.raises(operational.OperationalEvidenceError, match="source mismatch"):
        build(sources)


def test_window_timestamps_must_be_offset_aware():
    with pytest.raises(operational.OperationalEvidenceError, match="offset-aware"):
        operational.build_evidence(
            start="2026-09-25T12:00:00",
            end=END,
            units=UNITS,
            entries_by_role=minimal_sources(),
        )
