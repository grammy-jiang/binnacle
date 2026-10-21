"""E0/E1 request-window bounds and incomplete-outcome regressions."""

from __future__ import annotations

import json

import pytest

from scripts import lsp_e01_trace as engine
from tests.scripts.test_lsp_e01_trace import _calls, _write


@pytest.mark.parametrize(
    ("first_tool", "first_args", "middle", "window"),
    [
        ("search_text", {"pattern": "class Needle"}, 6, "search_then_read"),
        ("run_command", {"command": "git diff --stat"}, 10, "git_change_then_inspect"),
    ],
)
def test_unpaired_intervening_calls_consume_bounded_action_slots(
    tmp_path, first_tool, first_args, middle, window
):
    actions = [
        ("a", first_tool, first_args, None, 0, "wfr_gap/0"),
        *[
            (
                f"gap{i}",
                "job_status",
                {"job_id": f"fake{i}"},
                None,
                i + 1,
                f"wfr_gap/{i + 1}",
            )
            for i in range(middle)
        ],
        (
            "b",
            "read_file",
            {"path": "candidate.py"},
            None,
            middle + 2,
            f"wfr_gap/{middle + 2}",
        ),
    ]
    rows = [
        record
        for record in _calls(actions)
        if not (
            record["event"] == "mcp_request"
            and record["correlation"]["call"].startswith("gap")
        )
    ]
    out = engine.analyze(_write(tmp_path / "capture", rows).parent)
    assert out["calls"]["total"] == middle + 2
    assert out["request_pairing"]["exact_argument_match"] == 2
    assert out["request_pairing"]["missing_request"] == middle
    assert out["opportunity_windows"][window]["windows"] == 0
    assert "wfr_gap" not in json.dumps(out)


def test_close_read_after_unpaired_call_is_still_detectable(tmp_path):
    actions = [
        ("a", "search_text", {"pattern": "function Needle"}, None, 0, "wfr_gap/1"),
        ("gap", "job_status", {"job_id": "synthetic"}, None, 1, "wfr_gap/2"),
        ("b", "read_file", {"path": "candidate.py"}, None, 2, "wfr_gap/3"),
    ]
    rows = [
        item
        for item in _calls(actions)
        if not (item["event"] == "mcp_request" and item["correlation"]["call"] == "gap")
    ]
    result = engine.analyze(_write(tmp_path / "capture", rows).parent)
    assert result["opportunity_windows"]["search_then_read"] == {
        "windows": 1,
        "distinct_request_groups": 1,
    }


def test_post_cutoff_terminal_does_not_establish_task_completion(tmp_path):
    from datetime import datetime, timezone

    rows = _calls(
        [
            ("a", "search_text", {"pattern": "def Needle"}, None, 0, "wfr_cutoff/1"),
            ("b", "read_file", {"path": "needle.py"}, None, 2, "wfr_cutoff/2"),
        ]
    )
    rows[2]["timestamp"] = "2026-10-21T01:00:40Z"
    report = engine.analyze(
        _write(tmp_path / "capture", rows).parent,
        until_utc=datetime(2026, 10, 21, 1, 0, 30, tzinfo=timezone.utc),
    )
    assert report["calls"]["outcomes"]["unfinished"] == 1
    assert report["opportunity_windows"]["search_then_read"]["windows"] == 1
    assert (
        "window_is_call_start_evidence_not_verified_task_completion"
        in (report["interpretation_limits"])
    )


@pytest.mark.parametrize(
    ("first_tool", "first_args", "middle", "window"),
    [
        ("search_text", {"pattern": "class Gap"}, 5, "search_then_read"),
        ("run_command", {"command": "git diff --stat"}, 10, "git_change_then_inspect"),
    ],
)
@pytest.mark.parametrize("with_cutoff", [False, True])
def test_unorderable_intermediate_call_invalidates_group_windows(
    tmp_path, first_tool, first_args, middle, window, with_cutoff
):
    actions = [
        ("a", first_tool, first_args, None, 0, "wfr_missingtime/0"),
        *[
            (
                f"gap{i}",
                "job_status",
                {"job_id": f"job{i}"},
                None,
                i + 1,
                f"wfr_missingtime/{i + 1}",
            )
            for i in range(middle)
        ],
        (
            "b",
            "read_file",
            {"path": "read.py"},
            None,
            middle + 2,
            f"wfr_missingtime/{middle + 2}",
        ),
    ]
    rows = [
        row
        for row in _calls(actions)
        if not (
            row["event"] == "mcp_request"
            and row["correlation"]["call"].startswith("gap")
        )
    ]
    # One intervening call has no reliable clock, so observed action order
    # cannot be established from timestamps; refuse to squeeze the gap.
    for row in rows:
        if row["event"] == "tool_call" and row["correlation"]["call"] == "gap0":
            row.pop("timestamp")
    from datetime import datetime, timezone

    kwargs = (
        {"until_utc": datetime(2026, 10, 21, 2, tzinfo=timezone.utc)}
        if with_cutoff
        else {}
    )
    out = engine.analyze(_write(tmp_path / "capture", rows).parent, **kwargs)
    assert out["request_pairing"]["exact_argument_match"] == 2
    assert out["request_pairing"]["missing_request"] == middle - int(with_cutoff)
    if with_cutoff:
        assert out["coverage"]["unknown_timestamp_excluded"] == 1
    assert out["grouping"]["groups_excluded_missing_timestamp"] == 1
    assert out["opportunity_windows"][window]["windows"] == 0


@pytest.mark.parametrize(
    "invalid_time",
    ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"],
)
def test_extreme_offsets_never_crash_or_create_chronology(tmp_path, invalid_time):
    from datetime import datetime, timezone

    assert engine._time(invalid_time) is None
    rows = _calls(
        [
            ("a", "search_text", {"pattern": "class Overflow"}, None, 0, "wfr_edge/1"),
            ("b", "read_file", {"path": "overflow.py"}, None, 2, "wfr_edge/2"),
        ]
    )
    # The structurally valid row remains in the raw coverage population,
    # but cannot become ordered opportunity evidence.
    rows[1]["timestamp"] = invalid_time
    root = _write(tmp_path / "capture", rows).parent
    no_cutoff = engine.analyze(root)
    assert no_cutoff["calls"]["total"] == 2
    assert no_cutoff["grouping"]["groups_excluded_missing_timestamp"] == 1
    assert no_cutoff["opportunity_windows"]["search_then_read"]["windows"] == 0
    cutoff = engine.analyze(
        root, until_utc=datetime(2026, 10, 21, 2, tzinfo=timezone.utc)
    )
    assert cutoff["coverage"]["unknown_timestamp_excluded"] == 1
    assert cutoff["calls"]["total"] == 1
    assert cutoff["opportunity_windows"]["search_then_read"]["windows"] == 0


@pytest.mark.parametrize(
    ("first_tool", "first_args", "middle", "window"),
    [
        ("search_text", {"pattern": "class Needle"}, 5, "search_then_read"),
        ("run_command", {"command": "git diff --stat"}, 10, "git_change_then_inspect"),
    ],
)
def test_cutoff_unorderable_middle_calls_block_windows(
    tmp_path, first_tool, first_args, middle, window
):
    from datetime import datetime, timezone

    items = [("a", first_tool, first_args, None, 0, "wfr_unknown/0")]
    items.extend(
        (
            f"gap{i}",
            "job_status",
            {"job_id": f"synthetic{i}"},
            None,
            i + 1,
            f"wfr_unknown/{i + 1}",
        )
        for i in range(middle)
    )
    items.append(
        (
            "b",
            "read_file",
            {"path": "fixture.py"},
            None,
            middle + 2,
            f"wfr_unknown/{middle + 2}",
        )
    )
    rows = [
        row
        for row in _calls(items)
        if not (
            row["event"] == "mcp_request"
            and row["correlation"]["call"].startswith("gap")
        )
    ]
    for row in rows:
        if row["event"] == "tool_call" and row["correlation"]["call"].startswith("gap"):
            row.pop("timestamp")
    report = engine.analyze(
        _write(tmp_path / "capture", rows).parent,
        until_utc=datetime(2026, 10, 21, 2, tzinfo=timezone.utc),
    )
    assert report["coverage"]["unknown_timestamp_excluded"] == middle
    assert report["calls"]["total"] == 2
    assert report["request_pairing"]["exact_argument_match"] == 2
    assert report["grouping"]["groups_excluded_missing_timestamp"] == 1
    assert report["opportunity_windows"][window]["windows"] == 0
