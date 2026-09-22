"""Durable run-command/job-owner telemetry aggregation."""

import pytest

from binnacle import logstats

JOB_TELEMETRY_SAMPLE = """
2026-09-22T16:00:00.000 INFO: event=job_manager_start pid=10 owner=owner12345678 boot=boot recovered=2 protocol=1 package_version=1.0.0 socket=/run/jobs.sock
2026-09-22T16:00:01.000 INFO: event=run_command_dispatch call=c1 client=openai-mcp job_id=j1 owner=manager requested_wait_s=30 bounded_wait_s=30 effective_wait_s=1 background_arg=omitted auto_background=true handoff_reason=auto_background owner_roundtrip_ms=1002.5 command_hash=aaaaaaaaaaaa command_chars=12 state=running
2026-09-22T16:00:01.001 INFO: event=job_owner_timing op=start call=c1 job_id=j1 owner_instance=owner123456 wait_s=1 launch_ms=3.5 impl_ms=1001.4 state=running
2026-09-22T16:00:05.000 INFO: event=job_exit job_id=j1 exit_code=0 signal=None reason=normal_exit runtime_s=5.0 log_bytes=10 call=c1 owner=manager owner_instance=owner123456 command_hash=aaaaaaaaaaaa
2026-09-22T16:00:06.000 INFO: event=run_command_dispatch call=c2 client=openai-mcp job_id=j2 owner=manager requested_wait_s=50 bounded_wait_s=50 effective_wait_s=50 background_arg=false auto_background=false handoff_reason=synchronous owner_roundtrip_ms=12.5 command_hash=bbbbbbbbbbbb command_chars=4 state=exited
2026-09-22T16:00:06.001 INFO: event=job_owner_timing op=start call=c2 job_id=j2 owner_instance=owner123456 wait_s=50 launch_ms=2.5 impl_ms=11.5 state=exited
2026-09-22T16:00:06.002 INFO: event=job_exit job_id=j2 exit_code=0 signal=None reason=normal_exit runtime_s=0.01 log_bytes=0 call=c2 owner=manager owner_instance=owner123456 command_hash=bbbbbbbbbbbb
2026-09-22T16:00:06.100 INFO: event=job_status_timing call=js1 job_id=j1 wait_requested_s=50 dispatch_ms=1 state_ms=50000 read_log_ms=0.1 process_scan_ms=4 impl_ms=50004 state=running processes=2 log_bytes=10
2026-09-22T16:00:06.200 INFO: event=job_status_timing call=js2 job_id=j1 wait_requested_s=50 dispatch_ms=1 state_ms=12000 read_log_ms=0.1 process_scan_ms=0 impl_ms=12001 state=exited processes=0 log_bytes=10
2026-09-22T16:00:06.300 INFO: event=job_status_timing call=js3 job_id=j2 wait_requested_s=0 dispatch_ms=1 state_ms=0.3 read_log_ms=0.1 process_scan_ms=0 impl_ms=0.5 state=exited processes=0 log_bytes=0
2026-09-22T16:00:07.000 INFO: event=job_stop_requested job_id=j3 call=s1 origin_call=c3 owner_instance=owner123456 command_hash=cccccccccccc
2026-09-22T16:00:12.000 WARNING: event=job_stop_escalate job_id=j3 call=s1 signal=SIGKILL grace_s=5.0
2026-09-22T16:00:12.100 INFO: event=job_owner_timing op=stop call=s1 job_id=j3 owner_instance=owner123456 impl_ms=5100.0 state=exited
2026-09-22T16:00:12.101 INFO: event=job_exit job_id=j3 exit_code=None signal=9 reason=stop_requested runtime_s=8.0 log_bytes=0 call=c3 owner=manager owner_instance=owner123456 command_hash=cccccccccccc
2026-09-22T16:00:13.000 WARNING: event=job_interrupted job_id=j4 reason=owner_restart call=c4 previous_owner=oldowner1234 current_owner=owner123456 command_hash=dddddddddddd
2026-09-22T16:00:14.000 INFO: event=job_manager_client_disconnected op=start call=c5 job_id=j5
2026-09-22T16:00:14.100 WARNING: event=job_manager_request_invalid op=stop call=bad error_class=KeyError
2026-09-22T16:00:14.200 ERROR: event=job_manager_request_error op=start call=boom error_class=RuntimeError
2026-09-22T16:00:15.000 WARNING: event=run_command_dispatch_error call=c6 client=openai-mcp owner=manager requested_wait_s=30 bounded_wait_s=30 effective_wait_s=30 background_arg=omitted auto_background=false owner_roundtrip_ms=1.5 command_hash=eeeeeeeeeeee command_chars=6 error_class=JobManagerError
"""


def test_job_execution_telemetry_is_aggregated_and_rendered():
    records, _ = logstats.parse(JOB_TELEMETRY_SAMPLE)
    st = logstats.analyze(records)
    jt = st.jobs
    assert jt.dispatches == 2 and jt.dispatch_errors == 1
    assert jt.owners == {"manager": 3}
    assert jt.handoffs == {"auto_background": 1, "synchronous": 1}
    assert jt.owner_roundtrip_ms == [1002.5, 12.5, 1.5]
    assert jt.requested_wait_s == [30.0, 50.0, 30.0]
    assert jt.effective_wait_s == [1.0, 50.0, 30.0]
    assert jt.manager_launch_ms == [3.5, 2.5]
    assert jt.manager_start_impl_ms == [1001.4, 11.5]
    assert jt.owner_transport_overhead_ms == pytest.approx([1.1, 1.0])
    assert jt.manager_stop_impl_ms == [5100.0]
    assert jt.job_runtime_s == [5.0, 0.01, 8.0]
    assert jt.exit_reasons == {"normal_exit": 2, "stop_requested": 1}
    assert jt.stop_requests == 1 and jt.stop_escalations == 1
    assert jt.interruptions == {"owner_restart": 1}
    assert jt.manager_starts == 1 and jt.manager_recovered == 2
    assert jt.manager_disconnects == 1 and jt.disconnect_ops == {"start": 1}
    assert jt.manager_invalid_requests == 1 and jt.manager_request_errors == 1
    assert jt.job_status_calls == 3 and jt.job_status_wait_calls == 2
    assert jt.job_status_running_after_wait == 1
    assert jt.job_status_state_ms == [50000.0, 12000.0, 0.3]
    assert jt.job_status_wait_state_ms == [50000.0, 12000.0]

    text = logstats.render(st)
    assert "run_command execution telemetry:" in text
    assert "dispatches=2 dispatch_errors=1" in text
    assert "auto_background=1" in text and "synchronous=1" in text
    assert "manager launch ms" in text
    assert "owner transport overhead ms" in text
    assert "job_status: calls=3 wait_calls=2 running_after_wait=1" in text
    assert "blocking_state_total_s=62.00" in text
    assert "exit reasons: normal_exit=2, stop_requested=1" in text
    assert "requested=1 escalated_to_kill=1" in text
    assert "starts=1 recovered_jobs=2 client_disconnects=1" in text
    assert "invalid_requests=1 request_errors=1" in text
