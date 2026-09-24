"""Cross-event run_command workflow telemetry analysis."""

from binnacle import logstats
from binnacle.logstats_run_command import (
    analyze_run_command_workflow,
    build_run_command_index,
    dispatch_outcome,
    policy_mode,
)

SAMPLE = """
2026-09-24T12:00:00.000 INFO: event=tool_call call=a tool=run_command client=openai-mcp session=s request_id=0 args_chars=1 args={}
2026-09-24T12:00:00.010 INFO: event=run_command_auto_background call=a client=openai-mcp command_hash=aaaaaaaaaaaa
2026-09-24T12:00:00.020 INFO: event=job_start job_id=ja pid=1 command='x' workdir=/tmp call=a owner=manager owner_instance=owner command_hash=aaaaaaaaaaaa command_chars=1
2026-09-24T12:00:01.020 INFO: event=job_owner_timing op=start call=a job_id=ja owner_instance=owner wait_s=1 launch_ms=2 impl_ms=1002 state=running
2026-09-24T12:00:01.021 INFO: event=run_command_dispatch call=a client=openai-mcp job_id=ja owner=manager owner_instance=owner requested_wait_s=30 bounded_wait_s=30 effective_wait_s=1 background_arg=omitted auto_background=true handoff_reason=auto_background owner_roundtrip_ms=1003 command_hash=aaaaaaaaaaaa command_chars=1 state=running
2026-09-24T12:00:01.022 INFO: event=tool_result call=a tool=run_command client=openai-mcp session=s request_id=0 duration_ms=1004 is_error=False content_chars=1 structured_bytes=1 est_tokens=1 job_id=ja state=running background_job=true
2026-09-24T12:00:02.000 INFO: event=tool_call call=b tool=run_command client=openai-mcp session=s request_id=0 args_chars=1 args={}
2026-09-24T12:00:02.010 INFO: event=run_command_dispatch call=b client=openai-mcp job_id=jb owner=manager owner_instance=owner requested_wait_s=30 bounded_wait_s=30 effective_wait_s=1 background_arg=true auto_background=false handoff_reason=synchronous owner_roundtrip_ms=10 command_hash=bbbbbbbbbbbb command_chars=1 state=exited
2026-09-24T12:00:02.011 INFO: event=tool_result call=b tool=run_command client=openai-mcp session=s request_id=0 duration_ms=11 is_error=False content_chars=1 structured_bytes=1 est_tokens=1 job_id=jb state=exited background_job=false
2026-09-24T12:00:03.000 INFO: event=tool_call call=c tool=run_command client=openai-mcp session=s request_id=0 args_chars=1 args={}
2026-09-24T12:00:03.010 INFO: event=run_command_dispatch call=c client=openai-mcp job_id=jc owner=manager owner_instance=owner requested_wait_s=20 bounded_wait_s=20 effective_wait_s=20 background_arg=false auto_background=false handoff_reason=synchronous owner_roundtrip_ms=10 command_hash=cccccccccccc command_chars=1 state=exited
2026-09-24T12:00:03.011 INFO: event=tool_result call=c tool=run_command client=openai-mcp session=s request_id=0 duration_ms=11 is_error=False content_chars=1 structured_bytes=1 est_tokens=1 job_id=jc state=exited background_job=false
2026-09-24T12:00:04.000 INFO: event=tool_call call=d tool=run_command client=openai-mcp session=s request_id=0 args_chars=1 args={}
2026-09-24T12:00:24.010 INFO: event=run_command_dispatch call=d client=openai-mcp job_id=jd owner=manager owner_instance=owner requested_wait_s=20 bounded_wait_s=20 effective_wait_s=20 background_arg=omitted auto_background=false handoff_reason=wait_expired owner_roundtrip_ms=20010 command_hash=dddddddddddd command_chars=1 state=running
2026-09-24T12:00:24.011 INFO: event=tool_result call=d tool=run_command client=openai-mcp session=s request_id=0 duration_ms=20011 is_error=False content_chars=1 structured_bytes=1 est_tokens=1 job_id=jd state=running background_job=true
"""


def test_policy_and_outcome_are_independent_dimensions():
    assert (
        policy_mode({"background_arg": "omitted", "auto_background": "true"})
        == "auto_background"
    )
    assert (
        dispatch_outcome(
            {
                "background_arg": "omitted",
                "auto_background": "true",
                "state": "exited",
            }
        )
        == "warmup_finished"
    )
    assert (
        dispatch_outcome(
            {
                "background_arg": "true",
                "auto_background": "false",
                "state": "running",
            }
        )
        == "handed_off"
    )
    assert (
        dispatch_outcome(
            {
                "background_arg": "false",
                "auto_background": "false",
                "state": "running",
            }
        )
        == "wait_expired"
    )
    assert policy_mode({}) == "unknown_legacy"
    assert dispatch_outcome({}) == "unknown_legacy"


def test_event_index_keeps_only_run_command_calls_but_all_tool_sequence():
    extra = (
        SAMPLE + "\n2026-09-24T12:00:25.000 INFO: event=tool_call call=r "
        "tool=read_file client=openai-mcp session=s request_id=0 "
        "args_chars=1 args={}\n"
    )
    records, _ = logstats.parse(extra)
    index = build_run_command_index(records, logstats.plain_fields)

    assert set(index.tool_calls) == {"a", "b", "c", "d"}
    assert [fields["tool"] for _, _, fields in index.tool_call_sequence][
        -1
    ] == "read_file"
    assert set(index.dispatches) == {"a", "b", "c", "d"}
    assert set(index.auto_markers) == {"a"}
    assert set(index.job_starts) == {"ja"}


def test_workflow_counts_policy_and_outcome_without_command_text():
    records, _ = logstats.parse(SAMPLE)
    stats = analyze_run_command_workflow(records, logstats.plain_fields)

    assert stats.tool_calls == 4
    assert stats.tool_results == 4
    assert stats.successful_dispatches == 4
    assert stats.dispatch_errors == 0
    assert stats.result_errors == 0
    assert stats.policy_modes == {
        "auto_background": 1,
        "explicit_background": 1,
        "explicit_foreground_override": 1,
        "foreground_default": 1,
    }
    assert stats.outcomes == {
        "handed_off": 1,
        "warmup_finished": 1,
        "synchronous": 1,
        "wait_expired": 1,
    }


LIFECYCLE_SAMPLE = """
2026-09-24T13:00:00.000 INFO: event=tool_call call=auto tool=run_command client=openai-mcp session=s request_id=0 turn=turn-a/run args_chars=1 args={}
2026-09-24T13:00:01.000 INFO: event=job_start job_id=jauto pid=10 command='x' workdir=/tmp call=auto owner=manager owner_instance=o command_hash=aaaaaaaaaaaa command_chars=1
2026-09-24T13:00:01.001 INFO: event=job_owner_timing op=start call=auto job_id=jauto owner_instance=o wait_s=1 launch_ms=2 impl_ms=1000 state=running
2026-09-24T13:00:01.002 INFO: event=run_command_dispatch call=auto client=openai-mcp job_id=jauto owner=manager owner_instance=o requested_wait_s=30 bounded_wait_s=30 effective_wait_s=1 background_arg=omitted auto_background=true handoff_reason=auto_background owner_roundtrip_ms=1001 command_hash=aaaaaaaaaaaa command_chars=1 state=running
2026-09-24T13:00:01.003 INFO: event=tool_result call=auto tool=run_command client=openai-mcp session=s request_id=0 turn=turn-a/run duration_ms=1002 is_error=False content_chars=1 structured_bytes=1 est_tokens=1 job_id=jauto state=running background_job=true
2026-09-24T13:00:02.000 INFO: event=tool_call call=read tool=read_file client=openai-mcp session=s request_id=0 turn=turn-a/read args_chars=1 args={}
2026-09-24T13:00:04.000 INFO: event=job_exit job_id=jauto exit_code=0 signal=None reason=normal_exit runtime_s=4 log_bytes=10 call=auto owner=manager owner_instance=o command_hash=aaaaaaaaaaaa
2026-09-24T13:00:06.000 INFO: event=tool_call call=status tool=job_status client=openai-mcp session=s request_id=0 turn=turn-a/status args_chars=1 args={}
2026-09-24T13:00:06.010 INFO: event=job_status_timing call=status job_id=jauto wait_requested_s=10 wait_bounded_s=10 wait_effective_s=10 waited_s=2 blocking_policy=no_policy state_ms=2000 state=exited
2026-09-24T13:00:07.000 INFO: event=tool_call call=warm tool=run_command client=openai-mcp session=s request_id=0 turn=turn-b/run args_chars=1 args={}
2026-09-24T13:00:07.010 INFO: event=job_start job_id=jwarm pid=11 command='x' workdir=/tmp call=warm owner=manager owner_instance=o command_hash=bbbbbbbbbbbb command_chars=1
2026-09-24T13:00:07.020 INFO: event=job_owner_timing op=start call=warm job_id=jwarm owner_instance=o wait_s=1 launch_ms=2 impl_ms=10 state=exited
2026-09-24T13:00:07.021 INFO: event=job_exit job_id=jwarm exit_code=0 signal=None reason=normal_exit runtime_s=0.2 log_bytes=0 call=warm owner=manager owner_instance=o command_hash=bbbbbbbbbbbb
2026-09-24T13:00:07.022 INFO: event=run_command_dispatch call=warm client=openai-mcp job_id=jwarm owner=manager owner_instance=o requested_wait_s=30 bounded_wait_s=30 effective_wait_s=1 background_arg=omitted auto_background=true handoff_reason=synchronous owner_roundtrip_ms=11 command_hash=bbbbbbbbbbbb command_chars=1 state=exited
2026-09-24T13:00:07.023 INFO: event=tool_result call=warm tool=run_command client=openai-mcp session=s request_id=0 turn=turn-b/run duration_ms=12 is_error=False content_chars=1 structured_bytes=1 est_tokens=1 job_id=jwarm state=exited background_job=false
2026-09-24T13:00:08.000 INFO: event=tool_call call=bad tool=run_command client=openai-mcp session=s request_id=0 turn=turn-c/run args_chars=1 args={}
2026-09-24T13:00:08.010 WARNING: event=tool_result call=bad tool=run_command client=openai-mcp session=s request_id=0 turn=turn-c/run duration_ms=1 is_error=True error_class=ToolError error_code=path_outside_root error=bad path
2026-09-24T13:00:09.000 INFO: event=tool_result call=orphan-result tool=run_command client=openai-mcp session=s request_id=0 duration_ms=1 is_error=False content_chars=1 structured_bytes=1 est_tokens=1
2026-09-24T13:00:10.000 INFO: event=run_command_dispatch call=orphan-dispatch client=openai-mcp job_id=jorphan owner=manager owner_instance=o requested_wait_s=30 bounded_wait_s=30 effective_wait_s=30 background_arg=omitted auto_background=false handoff_reason=synchronous owner_roundtrip_ms=1 command_hash=dddddddddddd command_chars=1 state=exited
"""


def test_workflow_joins_lifecycle_errors_status_and_intervening_work():
    records, _ = logstats.parse(LIFECYCLE_SAMPLE)
    stats = analyze_run_command_workflow(records, logstats.plain_fields)

    assert stats.tool_calls == 3
    assert stats.tool_results == 4
    assert stats.result_errors == 1
    assert stats.successful_dispatches == 3
    assert stats.not_dispatched_errors == 1
    assert stats.not_dispatched_error_reasons == {"path_outside_root": 1}
    assert stats.result_without_call == 1
    assert stats.dispatch_without_call == 1
    assert stats.call_without_result == 0

    assert stats.dispatch_result_linked == 2
    assert stats.dispatch_job_start_linked == 2
    assert stats.dispatch_owner_timing_linked == 2
    assert stats.synchronous_exit_expected == 2
    assert stats.synchronous_exit_linked == 1

    assert stats.auto_matches == 2
    assert stats.auto_warmup_finished == 1
    assert stats.auto_handed_off == 1
    assert stats.auto_terminal_observed == 1
    assert stats.auto_terminal_analysis_eligible == 1
    assert stats.auto_would_finish_within_original_wait == 1
    assert stats.auto_would_timeout_anyway == 0
    assert stats.auto_initial_wait_released_s == 3

    assert stats.auto_jobs_with_status == 1
    assert stats.auto_status_calls == 1
    assert stats.auto_first_status_states == {"exited": 1}
    assert stats.auto_first_status_same_turn == 1
    assert stats.auto_first_status_different_turn == 0
    assert stats.auto_jobs_with_intervening_non_status_calls == 1
    assert stats.auto_intervening_tools == {"read_file": 1}
    assert stats.auto_status_state_ms == [2000.0]
    assert stats.auto_status_waited_s == [2.0]


def test_auto_counterfactual_detects_jobs_that_would_timeout_anyway():
    sample = """
2026-09-24T14:00:00.000 INFO: event=tool_call call=a tool=run_command client=x session=s request_id=0 args_chars=1 args={}
2026-09-24T14:00:01.000 INFO: event=run_command_dispatch call=a client=x job_id=j owner=manager owner_instance=o requested_wait_s=20 bounded_wait_s=20 effective_wait_s=1 background_arg=omitted auto_background=true handoff_reason=auto_background owner_roundtrip_ms=1000 command_hash=a command_chars=1 state=running
2026-09-24T14:01:01.000 INFO: event=job_exit job_id=j exit_code=0 signal=None reason=normal_exit runtime_s=61 log_bytes=0 call=a owner=manager owner_instance=o command_hash=a
2026-09-24T14:01:01.010 INFO: event=tool_result call=a tool=run_command client=x session=s request_id=0 duration_ms=1000 is_error=False content_chars=1 structured_bytes=1 est_tokens=1 job_id=j state=running background_job=true
"""
    records, _ = logstats.parse(sample)
    stats = analyze_run_command_workflow(records, logstats.plain_fields)

    assert stats.auto_terminal_analysis_eligible == 1
    assert stats.auto_would_timeout_anyway == 1
    assert stats.auto_would_finish_within_original_wait == 0
    assert stats.auto_initial_wait_released_s == 19


def test_collection_lag_uses_precise_plain_record_timestamps():
    sample = """
2026-09-24T15:00:00.000 INFO: event=tool_call call=a tool=run_command client=x session=s request_id=0 turn=t/a args_chars=1 args={}
2026-09-24T15:00:01.000 INFO: event=run_command_dispatch call=a client=x job_id=j owner=manager owner_instance=o requested_wait_s=30 bounded_wait_s=30 effective_wait_s=1 background_arg=omitted auto_background=true handoff_reason=auto_background owner_roundtrip_ms=1000 command_hash=a command_chars=1 state=running
2026-09-24T15:00:04.250 INFO: event=job_exit job_id=j exit_code=0 signal=None reason=normal_exit runtime_s=4.25 log_bytes=0 call=a owner=manager owner_instance=o command_hash=a
2026-09-24T15:00:06.875 INFO: event=tool_call call=s tool=job_status client=x session=s request_id=0 turn=t/s args_chars=1 args={}
2026-09-24T15:00:06.900 INFO: event=job_status_timing call=s job_id=j wait_requested_s=10 waited_s=0 state_ms=1 state=exited
2026-09-24T15:00:06.901 INFO: event=tool_result call=a tool=run_command client=x session=s request_id=0 duration_ms=1000 is_error=False content_chars=1 structured_bytes=1 est_tokens=1
"""
    records, _ = logstats.parse(sample)
    stats = analyze_run_command_workflow(records, logstats.plain_fields)

    assert stats.auto_terminal_collection_lag_s == [2.65]


def test_render_exposes_policy_outcome_coverage_and_counterfactuals():
    records, startups = logstats.parse(LIFECYCLE_SAMPLE)
    text = logstats.render(logstats.analyze(records, startups))

    assert "run_command workflow:" in text
    assert "policy:" in text and "auto_background=2" in text
    assert "outcome:" in text and "warmup_finished=1" in text
    assert "in-window linkage:" in text
    assert "not-dispatched errors: path_outside_root=1" in text
    assert "counterfactual:" in text
    assert "would_finish_within_original_wait=1" in text
    assert "first_status_same_turn=1" in text
    assert "jobs_with_intervening_non_status_tools=1" in text


def test_mixed_version_dispatch_without_policy_fields_is_not_synthesized():
    sample = """
2026-09-22T15:00:00.000 INFO: event=tool_call call=old tool=run_command client=x session=s request_id=0 args_chars=1 args={}
2026-09-22T15:00:00.010 INFO: event=run_command_dispatch call=old client=x job_id=j owner=manager owner_instance=o owner_roundtrip_ms=1 state=exited
2026-09-22T15:00:00.020 INFO: event=tool_result call=old tool=run_command client=x session=s request_id=0 duration_ms=1 is_error=False content_chars=1 structured_bytes=1 est_tokens=1
"""
    records, _ = logstats.parse(sample)
    stats = analyze_run_command_workflow(records, logstats.plain_fields)

    assert stats.policy_modes == {"unknown_legacy": 1}
    assert stats.outcomes == {"unknown_legacy": 1}
    assert stats.auto_matches == 0


def test_old_untimestamped_records_do_not_invent_collection_lag():
    sample = """
INFO: event=tool_call call=a tool=run_command client=x session=s request_id=0 turn=t/a args_chars=1 args={}
INFO: event=run_command_dispatch call=a client=x job_id=j owner=manager owner_instance=o requested_wait_s=30 bounded_wait_s=30 effective_wait_s=1 background_arg=omitted auto_background=true handoff_reason=auto_background owner_roundtrip_ms=1 state=running
INFO: event=job_exit job_id=j exit_code=0 signal=None reason=normal_exit runtime_s=4 log_bytes=0 call=a owner=manager owner_instance=o command_hash=a
INFO: event=tool_call call=s tool=job_status client=x session=s request_id=0 turn=t/s args_chars=1 args={}
INFO: event=job_status_timing call=s job_id=j wait_requested_s=0 state_ms=1 state=exited
INFO: event=tool_result call=a tool=run_command client=x session=s request_id=0 duration_ms=1 is_error=False content_chars=1 structured_bytes=1 est_tokens=1
"""
    records, _ = logstats.parse(sample)
    stats = analyze_run_command_workflow(records, logstats.plain_fields)

    assert stats.auto_terminal_observed == 1
    assert stats.auto_terminal_collection_lag_s == []
