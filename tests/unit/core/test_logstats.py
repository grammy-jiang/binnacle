"""Implementation gate for binnacle/logstats.py (`binnacle stats`).

The sample reproduces the journal's real shapes: a timestamped record, a
same-second record that starts *indented* with no timestamp, payload lines
wrapped mid-token, a request_error, and a startup line.
"""

from binnacle import logstats

SAMPLE = """\
[09/01/26 10:00:00] INFO     event=request_start                  logging.py:122
                             method=tools/call source=client
                             payload={"_meta":null,"name":"read_f
                             ile","arguments":{"path":"/home/u/Proje
                             cts/demo/a.txt"}}
                             payload_type=CallToolRequestParams
                    INFO     event=request_success                logging.py:122
                             method=tools/call source=client
                             duration_ms=3.50
[09/01/26 10:00:05] INFO     event=request_start                  logging.py:122
                             method=tools/call source=client
                             payload={"_meta":null,"name":"run_co
                             mmand","arguments":{"command":"git s
                             tatus"}}
                             payload_type=CallToolRequestParams
                    INFO     event=request_success                logging.py:122
                             method=tools/call source=client
                             duration_ms=120.00
[09/01/26 11:30:00] INFO     event=request_start                  logging.py:122
                             method=tools/list source=client
                             payload={"method":"tools/list","para
                             ms":null}
INFO:     127.0.0.1:1 - "POST /mcp HTTP/1.1" 200 OK
                    INFO     event=request_success                logging.py:122
                             method=tools/list source=client
                             duration_ms=0.50
[09/01/26 11:30:02] Error calling tool 'job_status'
                    ERROR    event=request_error                  logging.py:122
                             method=tools/call source=client
                             duration_ms=1.00 error=No job with
                             id 'zzz'.
INFO:     Application startup complete.
"""


def parsed():
    return logstats.parse(SAMPLE)


def test_record_count_and_startups():
    records, startups = parsed()
    assert [r.event for r in records].count("request_start") == 3
    assert [r.event for r in records].count("request_success") == 3
    assert [r.event for r in records].count("request_error") == 1
    assert startups == 1


def test_wrapped_tool_names_rejoined():
    records, startups = parsed()
    st = logstats.analyze(records, startups)
    # "read_f|ile" and "run_co|mmand" were wrapped mid-token.
    assert st.tools["read_file"] == 1
    assert st.tools["run_command"] == 1


def test_command_and_area_extraction():
    records, _ = parsed()
    st = logstats.analyze(records)
    assert st.commands["git"] == 1
    assert st.areas["/home/u/Projects/demo"] == 1


def test_duration_pairing_per_tool():
    records, _ = parsed()
    st = logstats.analyze(records)
    assert st.durations["read_file"] == [3.5]
    assert st.durations["run_command"] == [120.0]
    assert st.durations["tools/list"] == [0.5]


def test_error_captured_with_stamp():
    records, _ = parsed()
    st = logstats.analyze(records)
    assert len(st.errors) == 1
    assert "No job withid 'zzz'." in st.errors[0]  # rejoin loses the wrap space
    assert st.errors[0].startswith("[09/01/26 11:30:02]")


def test_timeline_buckets():
    records, _ = parsed()
    st = logstats.analyze(records)
    assert st.per_day["09/01/26"] == 3
    assert st.per_hour["09/01/26 10:00"] == 2
    assert st.per_hour["09/01/26 11:00"] == 1


def test_render_smoke():
    records, startups = parsed()
    text = logstats.render(logstats.analyze(records, startups))
    assert "requests: 3   errors: 1" in text
    assert "read_file" in text and "git" in text


# New-format lines (request_id= / session= / client= / tool= appended by
# RequestLoggingMiddleware). The production collision: ChatGPT's legacy
# era opens a session per call, so BOTH requests carry request_id=0 and
# only the session tag tells them apart. Order pairing charged
# run_command's 50 s wait to the quick job_status that finished first.
SAMPLE_IDS = """\
[09/02/26 12:00:00] INFO     event=request_start                  logging.py:122
                             method=tools/call source=client
                             payload={"_meta":null,"name":"run_co
                             mmand","arguments":{"command":"sleep
                             50"}} request_id=0 session=aaaa
                             client=openai-mcp tool=run_command
                    INFO     event=request_start                  logging.py:122
                             method=tools/call source=client
                             payload={"_meta":null,"name":"job_st
                             atus","arguments":{}} request_id=0
                             session=bbbb
                             client=openai-mcp tool=job_status
                    INFO     event=request_success                logging.py:122
                             method=tools/call source=client
                             duration_ms=2.00 request_id=0
                             session=bbbb
                             client=openai-mcp tool=job_status
[09/02/26 12:00:50] INFO     event=request_success                logging.py:122
                             method=tools/call source=client
                             duration_ms=50000.00 request_id=0
                             session=aaaa
                             client=openai-mcp tool=run_command
"""


def test_request_id_pairing_beats_order():
    records, _ = logstats.parse(SAMPLE_IDS)
    st = logstats.analyze(records)
    assert st.durations["run_command"] == [50000.0]
    assert st.durations["job_status"] == [2.0]


def test_client_key_preferred_over_payload():
    records, _ = logstats.parse(SAMPLE_IDS)
    st = logstats.analyze(records)
    assert st.clients == {"openai-mcp": 2}


# binnacle's own single-line records (docs/logging.md). Old shape without a
# timestamp (2026-09-02 to 09-13) and the timestamped shape after; a
# tool_call whose args contain a lookalike " error=" key; an error result.
SAMPLE_PLAIN = """\
[09/13/26 22:00:00] INFO     event=request_start                  logging.py:122
                             method=tools/call source=client
                             payload={"_meta":null,"name":"run_co
                             mmand","arguments":{"command":"x"}}
                             request_id=0 session=aaaa
                             client=openai-mcp tool=run_command
INFO: event=jobs_pruned removed=1 skipped_running=0 keep_newest=50
INFO: event=job_start job_id=abc pid=1 command='x' workdir=/tmp
INFO: event=job_exit job_id=abc exit_code=1 signal=None
INFO: event=tool_result tool=run_command client=openai-mcp request_id=0 is_error=False content_chars=126
                    INFO     event=request_success                logging.py:122
                             method=tools/call source=client
                             duration_ms=8.00 request_id=0
                             session=aaaa
                             client=openai-mcp tool=run_command
2026-09-13T23:10:00.100 INFO: event=tool_call call=c1 tool=run_command client=openai-mcp session=bbbb request_id=0 turn=wfr_t1/a args_chars=44 args={"workdir":"/tmp","command":"grep error=1 f"}
2026-09-13T23:10:00.105 INFO: event=job_start job_id=def pid=2 command='grep error=1 f' workdir=/tmp call=c1
2026-09-13T23:10:00.120 INFO: event=job_exit job_id=def exit_code=0 signal=None runtime_s=0.010 log_bytes=12
2026-09-13T23:10:00.130 INFO: event=tool_result call=c1 tool=run_command client=openai-mcp session=bbbb request_id=0 duration_ms=30.00 is_error=False content_chars=126 structured_bytes=300 est_tokens=106 job_id=def state=exited exit_code=0 background_job=false truncated=true output_bytes=12
2026-09-13T23:10:01.000 INFO: event=tool_call call=c2 tool=read_file client=openai-mcp session=cccc request_id=0 turn=wfr_t1/b args_chars=22 args={"path":"/etc/passwd"}
2026-09-13T23:10:01.002 WARNING: event=tool_result call=c2 tool=read_file client=openai-mcp session=cccc request_id=0 duration_ms=2.00 is_error=True error_class=ToolError error=Path outside allowed roots: /etc/passwd
2026-09-13T23:10:02.000 INFO: event=tool_call call=c3 tool=run_command client=openai-mcp session=dddd request_id=0 turn=wfr_t2/a args_chars=30 args={"command":"sleep 9"}
2026-09-13T23:10:03.000 INFO: event=tool_result call=c3 tool=run_command client=openai-mcp session=dddd request_id=0 duration_ms=1000.00 is_error=False content_chars=97 structured_bytes=227 est_tokens=81 job_id=ghi state=running background_job=true truncated=false output_bytes=0
2026-09-13T23:10:12.000 INFO: event=job_exit job_id=ghi exit_code=None signal=15 runtime_s=9.000 log_bytes=0
"""


def test_plain_records_parse_with_their_own_timestamps():
    records, _ = logstats.parse(SAMPLE_PLAIN)
    events = [r.event for r in records]
    assert events.count("tool_call") == 3
    assert events.count("tool_result") == 4  # one old-shape, three new
    assert events.count("job_exit") == 3
    assert events.count("jobs_pruned") == 1
    # old shape inherits the last rich timestamp; new shape carries its own
    old = next(r for r in records if r.event == "jobs_pruned")
    assert (old.day, old.time) == ("09/13/26", "22:00:00")
    new = next(r for r in records if r.event == "tool_call")
    assert (new.day, new.time) == ("09/13/26", "23:10:00")
    # the rich record before them still closed cleanly
    assert records[0].event == "request_start" and "tool=run_command" in records[0].body


def test_plain_fields_split_the_free_text_tail_first():
    f = logstats.plain_fields(
        "event=tool_call call=c1 tool=run_command args_chars=44 "
        'args={"workdir":"/tmp","command":"grep error=1 f"}'
    )
    assert f["call"] == "c1" and f["args_chars"] == "44"
    assert f["args"] == '{"workdir":"/tmp","command":"grep error=1 f"}'
    assert "error" not in f
    g = logstats.plain_fields(
        "event=tool_result call=c2 is_error=True error_class=ToolError "
        "error=Path outside allowed roots: /etc/passwd"
    )
    assert g["error_class"] == "ToolError"
    assert g["error"] == "Path outside allowed roots: /etc/passwd"


def test_result_metrics_come_only_from_sized_lines():
    records, _ = logstats.parse(SAMPLE_PLAIN)
    st = logstats.analyze(records)
    assert st.results == {"run_command": 2}  # the old-shape line has no sizes
    assert st.result_tokens["run_command"] == [106, 81]
    assert st.truncated == {"run_command": 1}
    assert st.call_durations["run_command"] == [30.0, 1000.0]
    assert st.call_durations["read_file"] == [2.0]
    assert st.tool_errors == {"read_file: ToolError": 1}
    assert st.background_jobs == 1
    assert st.job_exits == {"1": 1, "0": 1, "signal 15": 1}
    assert st.turn_calls == {"wfr_t1": 2, "wfr_t2": 1}
    # request-level stats are untouched by the plain records
    assert st.tools == {"run_command": 1}
    assert st.durations["run_command"] == [8.0]


def test_render_shows_the_new_sections_only_with_data():
    records, _ = logstats.parse(SAMPLE_PLAIN)
    text = logstats.render(logstats.analyze(records))
    assert "result size by tool" in text
    assert "run_command" in text.split("result size by tool", 1)[1]
    assert "truncated results by tool" in text
    assert "read_file: ToolError" in text
    assert "job exits by code (job_exit lines): 1: 1, 0: 1, signal 15: 1" in text
    assert "became background jobs: 1" in text
    assert "2 turns, 3 tool calls" in text
    old_text = logstats.render(logstats.analyze(parsed()[0]))
    assert "result size by tool" not in old_text and "turns" not in old_text


def test_analysis_helpers_cover_malformed_and_non_project_inputs(monkeypatch):
    from pathlib import Path

    assert logstats._first_word("") == "?"
    assert logstats._area("/tmp/x/y") == "/tmp/..."
    assert logstats._area("/var/log/x") == "/var/log/x"
    assert logstats._request_key({}) is None
    assert logstats._request_key({"request_id": "-"}) is None
    assert logstats._request_key({"request_id": "7"}) == "-:7"

    assert logstats._json_args("event=tool_call") == {}
    assert logstats._json_args("event=tool_call args={bad") == {}
    assert logstats._json_args("event=tool_call args=[1,2]") == {}
    assert logstats._json_args("event=tool_call args={...") == {}

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/test")))
    relative_hash = logstats._path_hash("demo/file.py")
    absolute_hash = logstats._path_hash("/home/test/Projects/demo/file.py")
    assert relative_hash == absolute_hash

    assert logstats._int(None) == 0
    assert logstats._int("bad") == 0
    assert logstats._float(None) == 0.0
    assert logstats._float("bad") == 0.0


def test_indexed_context_analysis_joins_exact_search_and_read_evidence(tmp_path):
    evidence = tmp_path / "repo" / "src" / "app.py"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("x")
    digest = logstats._path_hash(str(evidence))

    records = [
        logstats.Record(
            "tool_call",
            "event=tool_call call=idx tool=search_text turn=turn1/one "
            'args={"path":"/tmp/repo","pattern":"@context app"}',
        ),
        logstats.Record(
            "search_dispatch",
            "event=search_dispatch call=idx mode=indexed",
        ),
        logstats.Record(
            "index_context",
            "event=index_context call=idx pilot_version=v1 schema_version=3 "
            "parser_version=2 root_hash=root query_hash=query head=abc generation=4 "
            "cold_open=true changed_files=2 package_est_tokens=80 package_bytes=320 "
            "package_items=3 total_ms=12.5 reconcile_ms=3.5 query_ms=4.0 "
            f"evidence_hashes={digest}",
        ),
        logstats.Record(
            "tool_result",
            "event=tool_result call=idx tool=search_text est_tokens=100",
        ),
        logstats.Record(
            "tool_call",
            f"event=tool_call call=search tool=search_text turn=turn1/two "
            f'args={{"path":"{evidence}","pattern":"target"}}',
        ),
        logstats.Record(
            "search_dispatch",
            "event=search_dispatch call=search mode=exact",
        ),
        logstats.Record(
            "tool_result",
            "event=tool_result call=search tool=search_text est_tokens=20",
        ),
        logstats.Record(
            "tool_call",
            f"event=tool_call call=read tool=read_file turn=turn1/three "
            f'args={{"path":"{evidence}"}}',
        ),
        logstats.Record(
            "tool_result",
            "event=tool_result call=read tool=read_file est_tokens=30",
        ),
        logstats.Record(
            "tool_call",
            "event=tool_call call=ignored tool=run_command turn=turn1/four "
            'args={"command":"echo x"}',
        ),
        logstats.Record(
            "index_context_error",
            "event=index_context_error call=bad phase=query error_class=ToolError",
        ),
    ]

    stats = logstats.analyze_indexed_context(records)

    assert stats.successes == 1
    assert stats.errors == 1
    assert stats.error_phases == {"query": 1}
    assert stats.cold_opens == 1
    assert stats.changed_files == 2
    assert stats.evidence_opened == 1
    assert stats.evidence_reads == 1
    assert stats.evidence_file_searches == 1
    assert stats.followup_calls == [2]
    assert stats.followup_exact_searches == [1]
    assert stats.followup_reads == [1]
    assert stats.followup_result_tokens == [50]
    assert stats.investigation_result_tokens == [150]
    row = stats.rows[0]
    assert row["pilot_version"] == "v1"
    assert row["schema_version"] == 3
    assert row["parser_version"] == 2
    assert row["generation"] == 4
    assert row["package_est_tokens"] == 80
    assert row["package_bytes"] == 320
    assert row["package_items"] == 3


def test_indexed_context_analysis_tolerates_missing_ids_and_bad_metrics():
    records = [
        logstats.Record("tool_call", "event=tool_call tool=search_text"),
        logstats.Record("tool_result", "event=tool_result tool=search_text"),
        logstats.Record("search_dispatch", "event=search_dispatch mode=exact"),
        logstats.Record(
            "index_context",
            "event=index_context schema_version=x parser_version=x "
            "generation=x package_bytes=x total_ms=x evidence_hashes=-",
        ),
    ]

    stats = logstats.analyze_indexed_context(records)

    assert stats.successes == 1
    assert stats.rows[0]["call"] == "-"
    assert stats.rows[0]["schema_version"] == 0
    assert stats.rows[0]["total_ms"] == 0.0


def test_analyze_covers_unpaired_and_unsized_result_edges():
    records = [
        logstats.Record(
            "request_start",
            "event=request_start method=tools/call source=client",
        ),
        logstats.Record(
            "request_success",
            "event=request_success method=tools/call duration_ms=1.25",
        ),
        logstats.Record(
            "request_error",
            "event=request_error method=tools/list",
        ),
        logstats.Record(
            "tool_call",
            "event=tool_call call=c tool=read_file",
        ),
        logstats.Record(
            "tool_result",
            "event=tool_result tool=read_file duration_ms=bad is_error=True",
        ),
        logstats.Record(
            "job_exit",
            "event=job_exit exit_code=? signal=null",
        ),
    ]

    stats = logstats.analyze(records)

    assert stats.tools["(name beyond payload clip)"] == 1
    assert stats.durations["tools/call"] == [1.25]
    assert stats.errors
    assert stats.tool_errors["read_file: ?"] == 1
    assert stats.job_exits["?"] == 1
