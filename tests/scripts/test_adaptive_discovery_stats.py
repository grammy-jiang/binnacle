from __future__ import annotations

import hashlib
from pathlib import Path

from binnacle import logstats
from binnacle.logstats_render import adaptive_discovery_report


def path_hash(value: str) -> str:
    return hashlib.sha256(str(Path(value).resolve()).encode()).hexdigest()[:12]


def sample(evidence: Path) -> str:
    digest = path_hash(str(evidence))
    return "\n".join(
        [
            '2026-09-21T07:00:00.000 INFO: event=tool_call call=aaaaaaaaaaaa tool=search_text turn=wfr_turn1/one args_chars=80 args={"path":"/tmp/repo","pattern":"alpha"}',
            "2026-09-21T07:00:00.001 INFO: event=search_dispatch call=aaaaaaaaaaaa mode=exact path_hash=abc pattern_chars=5",
            (
                "2026-09-21T07:00:00.010 INFO: event=search_adaptive_discovery "
                "call=aaaaaaaaaaaa trigger_bytes=65000 total_matches=100 "
                "matching_files=20 detailed_files=10 candidate_files=20 "
                "representative_entries=20 tail_entries=10 result_bytes=12000 "
                "result_budget_bytes=65536 budget_trimmed=false "
                f"candidate_hashes={digest},bbbbbbbbbbbb detailed_hashes={digest}"
            ),
            "2026-09-21T07:00:00.020 INFO: event=tool_result call=aaaaaaaaaaaa tool=search_text est_tokens=3000 is_error=False",
            '2026-09-21T07:00:01.000 INFO: event=tool_call call=runrunrunrun tool=run_command turn=wfr_turn1/two args_chars=20 args={"command":"echo x"}',
            "2026-09-21T07:00:01.010 INFO: event=tool_result call=runrunrunrun tool=run_command est_tokens=50 is_error=False",
            f'2026-09-21T07:00:02.000 INFO: event=tool_call call=bbbbbbbbbbbb tool=read_file turn=wfr_turn1/three args_chars=70 args={{"path":"{evidence}"}}',
            "2026-09-21T07:00:02.010 INFO: event=tool_result call=bbbbbbbbbbbb tool=read_file est_tokens=500 is_error=False",
            f'2026-09-21T07:00:03.000 INFO: event=tool_call call=cccccccccccc tool=search_text turn=wfr_turn1/four args_chars=100 args={{"path":"{evidence}","pattern":"alpha"}}',
            "2026-09-21T07:00:03.001 INFO: event=search_dispatch call=cccccccccccc mode=exact path_hash=def pattern_chars=5",
            "2026-09-21T07:00:03.010 INFO: event=tool_result call=cccccccccccc tool=search_text est_tokens=200 is_error=False",
        ]
    )


def test_adaptive_stats_join_followup_candidate_use(tmp_path: Path):
    evidence = tmp_path / "repo" / "src" / "app.py"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("alpha\n")

    records, _ = logstats.parse(sample(evidence))
    adaptive = logstats.analyze_adaptive_discovery(records)
    report = adaptive_discovery_report(adaptive)

    assert report["adaptive_calls"] == 1
    assert report["budget_trimmed"] == 0
    assert report["candidate_open_conversion"] == 1.0
    assert report["detailed_open_conversion"] == 1.0
    assert report["candidate_reads"] == 1
    assert report["candidate_file_searches"] == 1
    assert report["result_tokens"]["p50"] == 3000
    assert report["followup_calls"]["p50"] == 2
    assert report["followup_reads"]["p50"] == 1
    assert report["followup_exact_searches"]["p50"] == 1
    assert report["followup_result_tokens"]["p50"] == 700
    assert report["investigation_result_tokens"]["p50"] == 3700
    assert report["trigger_bytes"]["p50"] == 65000
    assert report["result_bytes"]["p50"] == 12000


def test_main_stats_render_adds_adaptive_section_only_when_present(tmp_path: Path):
    evidence = tmp_path / "repo" / "src" / "app.py"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("alpha\n")

    records, startups = logstats.parse(sample(evidence))
    text = logstats.render(logstats.analyze(records, startups))

    assert "adaptive search discovery pilot:" in text
    assert "calls=1 budget_trimmed=0 candidate_opened=1 detailed_opened=1" in text
    assert "investigation tokens" in text

    plain, starts = logstats.parse(
        '2026-09-21T07:00:00.000 INFO: event=tool_call call=a tool=read_file turn=wfr_x/one args={"path":"/tmp/a"}\n'
    )
    assert "adaptive search discovery pilot:" not in logstats.render(
        logstats.analyze(plain, starts)
    )
