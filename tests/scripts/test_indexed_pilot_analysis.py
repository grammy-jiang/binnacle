from __future__ import annotations

import hashlib
from pathlib import Path

from binnacle import logstats


def path_hash(value: str) -> str:
    return hashlib.sha256(str(Path(value).resolve()).encode()).hexdigest()[:12]


def sample(evidence: Path) -> str:
    digest = path_hash(str(evidence))
    return "\n".join(
        [
            '2026-09-19T20:00:00.000 INFO: event=tool_call call=aaaaaaaaaaaa tool=search_text turn=wfr_turn1/one args_chars=90 args={"path":"/tmp/repo","pattern":"@context find app"}',
            "2026-09-19T20:00:00.001 INFO: event=search_dispatch call=aaaaaaaaaaaa mode=indexed path_hash=abc pattern_chars=17",
            (
                "2026-09-19T20:00:00.010 INFO: event=index_context call=aaaaaaaaaaaa "
                "pilot_version=2026-09-19-v1 schema_version=3 parser_version=1 "
                "root_hash=abc query_hash=def query_chars=8 head=123 generation=2 "
                "cold_open=false open_ms=0.0 reconcile_ms=5 freshness_ms=4 "
                "changed_files=0 deleted_files=0 hashed_files=0 query_ms=3 surface_ms=1 "
                "total_ms=9 files=10 nodes=20 edges=30 db_bytes=1000 related_items=8 "
                "direct_items=2 package_items=10 package_bytes=8000 package_est_tokens=1900 "
                f"evidence_hashes={digest}"
            ),
            "2026-09-19T20:00:00.020 INFO: event=tool_result call=aaaaaaaaaaaa tool=search_text est_tokens=2000 is_error=False",
            '2026-09-19T20:00:01.000 INFO: event=tool_call call=dddddddddddd tool=run_command turn=wfr_turn1/mid args_chars=20 args={"command":"echo x"}',
            "2026-09-19T20:00:01.010 INFO: event=tool_result call=dddddddddddd tool=run_command est_tokens=999 is_error=False",
            f'2026-09-19T20:00:02.000 INFO: event=tool_call call=bbbbbbbbbbbb tool=read_file turn=wfr_turn1/two args_chars=70 args={{"path":"{evidence}"}}',
            "2026-09-19T20:00:02.010 INFO: event=tool_result call=bbbbbbbbbbbb tool=read_file est_tokens=500 is_error=False",
        ]
    )


def test_indexed_stats_join_first_hop_to_followup_evidence_read(tmp_path: Path):
    evidence = tmp_path / "repo" / "src" / "app.py"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("x\n")
    records, _ = logstats.parse(sample(evidence))
    report = logstats.indexed_context_report(logstats.analyze_indexed_context(records))

    assert report["indexed_successes"] == 1
    assert report["indexed_errors"] == 0
    assert report["result_tokens"]["p50"] == 2000
    assert report["followup_calls"]["p50"] == 1  # run_command is intentionally ignored
    assert report["followup_reads"]["p50"] == 1
    assert report["followup_result_tokens"]["p50"] == 500
    assert report["investigation_result_tokens"]["p50"] == 2500
    assert report["evidence_open_conversion"] == 1.0
    assert report["evidence_reads"] == 1
    assert report["rows"][0]["pilot_version"] == "2026-09-19-v1"
    assert report["rows"][0]["schema_version"] == 3


def test_indexed_stats_counts_error_phase():
    records, _ = logstats.parse(
        "2026-09-19T20:00:00.000 WARNING: event=index_context_error "
        "call=cccccccccccc root_hash=abc phase=reconcile error_class=ToolError "
        "total_ms=12 error=boom\n"
    )
    report = logstats.indexed_context_report(logstats.analyze_indexed_context(records))
    assert report["indexed_successes"] == 0
    assert report["indexed_errors"] == 1
    assert report["error_phases"] == {"reconcile": 1}


def test_main_stats_render_includes_indexed_section_only_when_present(tmp_path: Path):
    evidence = tmp_path / "repo" / "src" / "app.py"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("x\n")
    records, startups = logstats.parse(sample(evidence))
    text = logstats.render(logstats.analyze(records, startups))
    assert "indexed context pilot:" in text
    assert "success=1 errors=0" in text
    assert "evidence opened: 1/1 (100.0%)" in text
    assert "investigation tokens" in text

    plain, starts = logstats.parse(
        "2026-09-19T20:00:00.000 INFO: event=tool_call call=a tool=read_file "
        'turn=wfr_x/one args={"path":"/tmp/a"}\n'
    )
    assert "indexed context pilot:" not in logstats.render(
        logstats.analyze(plain, starts)
    )
