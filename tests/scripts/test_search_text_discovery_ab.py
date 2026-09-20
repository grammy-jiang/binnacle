from __future__ import annotations

from pathlib import Path

from scripts.search_text_ab_dataset import HistoricalCase, extract_cases, tool_events
from scripts.search_text_ab_replay import (
    build_b,
    compile_branches,
    rank_files,
    representative_matches,
    split_top_level_alternatives,
)
from scripts.search_text_ab_report import distribution, recall


def test_event_parser_ignores_budget_text_embedded_in_tool_arguments(tmp_path: Path):
    evidence = tmp_path / "evidence.py"
    evidence.write_text("needle\n")
    log = "\n".join(
        [
            (
                "2026-09-20T00:00:00 INFO: event=tool_call call=wrapper tool=run_command "
                'turn=wfr_other/x args={"command":"grep event=search_budget_hit"}'
            ),
            (
                "2026-09-20T00:00:01 INFO: event=tool_call call=abc tool=search_text "
                'turn=wfr_turn/one args={"path":"/tmp","pattern":"needle",'
                '"context_lines":2,"max_results":200}'
            ),
            (
                "2026-09-20T00:00:01 INFO: event=search_budget_hit call=abc "
                "result_bytes=65000 result_budget_bytes=65536 returned_entries=50 "
                "total_matches=500 names_only=false"
            ),
            (
                "2026-09-20T00:00:02 INFO: event=tool_result call=abc tool=search_text "
                "est_tokens=16000 is_error=False"
            ),
            (
                "2026-09-20T00:00:03 INFO: event=tool_call call=def tool=read_file "
                f'turn=wfr_turn/two args={{"path":"{evidence}"}}'
            ),
        ]
    )

    calls, _, hits = tool_events(log)
    assert hits == {"abc"}
    assert len(calls) == 3
    cases = extract_cases(log)
    assert len(cases) == 1
    assert cases[0].call == "abc"
    assert cases[0].historical_tokens == 16000
    assert cases[0].evidence_files == (str(evidence.resolve()),)


def test_split_top_level_alternatives_respects_groups_classes_and_escapes():
    assert split_top_level_alternatives("alpha|beta|gamma") == [
        "alpha",
        "beta",
        "gamma",
    ]
    assert split_top_level_alternatives(r"(alpha|beta)|gamma") == [
        "(alpha|beta)",
        "gamma",
    ]
    assert split_top_level_alternatives(r"alpha\|beta|gamma") == [
        r"alpha\|beta",
        "gamma",
    ]
    assert split_top_level_alternatives(r"[a|b]|gamma") == [r"[a|b]", "gamma"]


def test_diversity_ranking_prefers_new_branch_coverage_before_raw_match_count():
    files = {
        "/tmp/a.py": [
            {"line": 1, "text": "alpha"},
            {"line": 2, "text": "beta"},
        ],
        "/tmp/b.py": [{"line": i, "text": "alpha"} for i in range(1, 40)],
        "/tmp/c.py": [{"line": 1, "text": "gamma"}],
    }
    ranked, facts, _ = rank_files(files, "alpha|beta|gamma")

    assert ranked[0] == "/tmp/a.py"
    assert ranked[1] == "/tmp/c.py"
    assert ranked[2] == "/tmp/b.py"
    assert len(facts["/tmp/a.py"].branches) == 2
    assert facts["/tmp/b.py"].count == 39


def test_representative_matches_cover_different_branches():
    branches = compile_branches("alpha|beta|gamma", False)
    matches = [
        {"line": 1, "text": "alpha only"},
        {"line": 2, "text": "alpha repeated"},
        {"line": 3, "text": "beta and gamma"},
        {"line": 4, "text": "nothing"},
    ]

    selected = representative_matches(matches, branches, limit=2)

    assert selected[0]["line"] == 1
    assert selected[1]["line"] == 3


def test_build_b_has_detailed_front_and_count_only_tail(tmp_path: Path):
    files = {
        str(tmp_path / f"f{i}.py"): [
            {"line": 1, "text": f"alpha {i}"},
            {"line": 2, "text": f"beta {i}"},
        ]
        for i in range(6)
    }

    case = HistoricalCase(
        call="test",
        turn=None,
        args={"pattern": "alpha|beta", "fixed_strings": False},
        historical_tokens=0,
        evidence_files=(),
    )

    result = build_b(
        case,
        tmp_path,
        files,
        detailed=2,
        total_candidates=5,
        representatives=1,
    )

    assert result["candidate_file_count"] == 5
    assert result["detailed_file_count"] == 2
    assert result["tokens"] > 0
    assert result["structured_bytes"] > result["tokens"]


def test_metric_helpers():
    assert recall({"a", "b"}, {"b", "c"}) == {
        "hit": 1,
        "total": 2,
        "recall": 0.5,
        "all_recalled": False,
    }
    assert recall({"a"}, set())["recall"] is None
    assert distribution([1.0, 2.0, 3.0, 4.0]) == {
        "mean": 2.5,
        "p50": 3.0,
        "p90": 4.0,
        "max": 4.0,
    }
