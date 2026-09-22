"""Shared tool/config/error telemetry aggregation."""

from binnacle import logstats

SAMPLE = """
2026-09-22T17:00:00.000 INFO: event=tool_config tool=read_file max_lines=2000 max_chars=24000 max_line_chars=2000 max_file_bytes=20971520
2026-09-22T17:00:00.001 INFO: event=tool_config tool=list_files max_results_default=200 max_results_cap=2000 rg_timeout_s=20 rg_bin=rg
2026-09-22T17:00:00.002 INFO: event=tool_config tool=read_file max_lines=2000 max_chars=32000 max_line_chars=2000 max_file_bytes=20971520
2026-09-22T17:00:01.000 INFO: event=tool_call call=r1 tool=read_file client=x session=s request_id=1 args_chars=20 args={"path":"/tmp/a"}
2026-09-22T17:00:01.010 INFO: event=tool_result call=r1 tool=read_file client=x session=s request_id=1 duration_ms=2 is_error=False content_chars=1 structured_bytes=10 est_tokens=3 truncated=false kind=text total_lines=10 start_line=1 end_line=10 bytes=10
2026-09-22T17:00:02.000 INFO: event=tool_call call=r2 tool=read_file client=x session=s request_id=2 args_chars=50 args={"path":"/tmp/b","start_line":20,"end_line":40}
2026-09-22T17:00:02.010 INFO: event=tool_result call=r2 tool=read_file client=x session=s request_id=2 duration_ms=3 is_error=False content_chars=1 structured_bytes=10 est_tokens=3 truncated=true kind=text total_lines=100 start_line=20 end_line=30 next_start_line=31 fits_in_one_call=true lossy=true lines_clipped=2 bytes=100
2026-09-22T17:00:03.000 INFO: event=tool_call call=l1 tool=list_files client=x session=s request_id=3 args_chars=20 args={"path":"/tmp"}
2026-09-22T17:00:03.010 INFO: event=tool_result call=l1 tool=list_files client=x session=s request_id=3 duration_ms=1 is_error=False content_chars=1 structured_bytes=10 est_tokens=3 truncated=false count=3 mode=list entries=3
2026-09-22T17:00:04.000 INFO: event=tool_call call=l2 tool=list_files client=x session=s request_id=4 args_chars=40 args={"path":"/tmp","glob":"*.py"}
2026-09-22T17:00:04.010 INFO: event=tool_result call=l2 tool=list_files client=x session=s request_id=4 duration_ms=1 is_error=False content_chars=1 structured_bytes=10 est_tokens=3 truncated=false count=2 mode=glob entries=2
2026-09-22T17:00:05.000 WARNING: event=tool_result call=e1 tool=read_file client=x session=s request_id=5 duration_ms=1 is_error=True error_class=ToolError error_code=path_outside_root error=nope
2026-09-22T17:00:06.000 WARNING: event=tool_result call=e2 tool=search_text client=x session=s request_id=6 duration_ms=1 is_error=True error_class=ToolError error_code=rg_rejected error=bad
"""


def test_shared_tool_telemetry_aggregates_behavior_config_and_error_codes():
    records, starts = logstats.parse(SAMPLE)
    st = logstats.analyze(records, starts)
    assert st.read_file_requests == {"whole": 1, "range": 1}
    assert st.read_file_outcomes == {
        "kind:text": 2,
        "truncated": 1,
        "fits_in_one_call": 1,
        "lossy": 1,
        "continuation": 1,
        "lines_clipped_results": 1,
    }
    assert st.read_file_lines_clipped == 2
    assert st.list_files_requests == {"list": 1, "glob": 1}
    assert st.error_codes == {
        "read_file: path_outside_root": 1,
        "search_text: rg_rejected": 1,
    }
    assert len(st.tool_config_variants["read_file"]) == 2
    assert "max_chars=32000" in st.tool_config_latest["read_file"]

    text = logstats.render(st)
    assert "tool errors by stable code:" in text
    assert "read_file: path_outside_root" in text
    assert "read_file behavior: requests whole=1, range=1" in text
    assert "list_files behavior: requests list=1, glob=1" in text
    assert "read_file: variants=2" in text and "max_chars=32000" in text
