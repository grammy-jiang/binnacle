"""Structured run-command/job-owner telemetry analysis."""

from collections.abc import Callable, Sequence

from binnacle.logstats_models import JobTelemetryStats, Record


def _number(fields: dict[str, str], name: str) -> float | None:
    try:
        return float(fields[name])
    except (KeyError, ValueError):
        return None


def analyze_job_telemetry(
    records: list[Record], fields: Callable[[str], dict[str, str]]
) -> JobTelemetryStats:
    """Aggregate durable-owner events without depending on journal timestamps."""
    out = JobTelemetryStats()
    owner_roundtrip_by_job: dict[str, float] = {}
    manager_impl_by_job: dict[str, float] = {}
    for record in records:
        f = fields(record.body)
        if record.event == "run_command_dispatch_error":
            out.dispatch_errors += 1
            out.owners[f.get("owner", "?")] += 1
            for name, target in (
                ("owner_roundtrip_ms", out.owner_roundtrip_ms),
                ("requested_wait_s", out.requested_wait_s),
                ("effective_wait_s", out.effective_wait_s),
            ):
                if (value := _number(f, name)) is not None:
                    target.append(value)
        elif record.event == "run_command_dispatch":
            out.dispatches += 1
            out.owners[f.get("owner", "?")] += 1
            out.handoffs[f.get("handoff_reason", "?")] += 1
            if (value := _number(f, "owner_roundtrip_ms")) is not None and (
                job_id := f.get("job_id")
            ):
                owner_roundtrip_by_job[job_id] = value
            for name, target in (
                ("owner_roundtrip_ms", out.owner_roundtrip_ms),
                ("requested_wait_s", out.requested_wait_s),
                ("effective_wait_s", out.effective_wait_s),
            ):
                if (value := _number(f, name)) is not None:
                    target.append(value)
        elif record.event == "job_owner_timing":
            op = f.get("op", "?")
            if op == "start":
                if (value := _number(f, "launch_ms")) is not None:
                    out.manager_launch_ms.append(value)
                if (value := _number(f, "impl_ms")) is not None:
                    out.manager_start_impl_ms.append(value)
                    if job_id := f.get("job_id"):
                        manager_impl_by_job[job_id] = value
            elif op == "stop":
                if (value := _number(f, "impl_ms")) is not None:
                    out.manager_stop_impl_ms.append(value)
        elif record.event == "job_status_timing":
            out.job_status_calls += 1
            wait_requested = _number(f, "wait_requested_s") or 0.0
            state_ms = _number(f, "state_ms")
            if wait_requested > 0:
                out.job_status_wait_calls += 1
                if f.get("state") == "running":
                    out.job_status_running_after_wait += 1
                if state_ms is not None:
                    out.job_status_wait_state_ms.append(state_ms)
            if state_ms is not None:
                out.job_status_state_ms.append(state_ms)
        elif record.event == "job_exit":
            if reason := f.get("reason"):
                out.exit_reasons[reason] += 1
            if (value := _number(f, "runtime_s")) is not None:
                out.job_runtime_s.append(value)
        elif record.event == "job_stop_requested":
            out.stop_requests += 1
        elif record.event == "job_stop_escalate":
            out.stop_escalations += 1
        elif record.event == "job_interrupted":
            out.interruptions[f.get("reason", "?")] += 1
        elif record.event == "job_manager_start":
            out.manager_starts += 1
            try:
                out.manager_recovered += int(f.get("recovered", "0"))
            except ValueError:
                pass
        elif record.event == "job_manager_client_disconnected":
            out.manager_disconnects += 1
            out.disconnect_ops[f.get("op", "?")] += 1
        elif record.event == "job_manager_request_invalid":
            out.manager_invalid_requests += 1
        elif record.event == "job_manager_request_error":
            out.manager_request_errors += 1
    for job_id, roundtrip in owner_roundtrip_by_job.items():
        if (impl := manager_impl_by_job.get(job_id)) is not None:
            out.owner_transport_overhead_ms.append(max(0.0, roundtrip - impl))
    return out


def _pct(values: Sequence[int | float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def render_job_telemetry(jobs: JobTelemetryStats) -> list[str]:
    """Human-readable execution/owner section for ``binnacle stats``."""
    if not (
        jobs.dispatches
        or jobs.dispatch_errors
        or jobs.job_runtime_s
        or jobs.manager_starts
    ):
        return []
    out = ["\nrun_command execution telemetry:"]
    if jobs.dispatches or jobs.dispatch_errors:
        owners = ", ".join(f"{k}={v}" for k, v in jobs.owners.most_common())
        handoffs = ", ".join(f"{k}={v}" for k, v in jobs.handoffs.most_common())
        out.append(
            f"  dispatches={jobs.dispatches} dispatch_errors={jobs.dispatch_errors}; "
            f"owner attempts: {owners}"
        )
        out.append(f"  handoff reasons: {handoffs}")
    for label, values, unit in (
        ("requested wait", jobs.requested_wait_s, "s"),
        ("effective wait", jobs.effective_wait_s, "s"),
        ("owner roundtrip", jobs.owner_roundtrip_ms, "ms"),
        ("manager launch", jobs.manager_launch_ms, "ms"),
        ("manager start implementation", jobs.manager_start_impl_ms, "ms"),
        ("owner transport overhead", jobs.owner_transport_overhead_ms, "ms"),
        ("manager stop implementation", jobs.manager_stop_impl_ms, "ms"),
        ("job runtime", jobs.job_runtime_s, "s"),
    ):
        if values:
            out.append(
                f"  {label} {unit}: n={len(values)} "
                f"p50={_pct(values, 0.5):.2f} p90={_pct(values, 0.9):.2f} "
                f"p95={_pct(values, 0.95):.2f} max={max(values):.2f}"
            )
    if jobs.job_status_calls:
        blocking_state_s = sum(jobs.job_status_wait_state_ms) / 1000
        out.append(
            f"  job_status: calls={jobs.job_status_calls} "
            f"wait_calls={jobs.job_status_wait_calls} "
            f"running_after_wait={jobs.job_status_running_after_wait} "
            f"blocking_state_total_s={blocking_state_s:.2f}"
        )
    if jobs.exit_reasons:
        reasons = ", ".join(f"{k}={v}" for k, v in jobs.exit_reasons.most_common())
        out.append(f"  exit reasons: {reasons}")
    if jobs.stop_requests or jobs.stop_escalations:
        out.append(
            f"  stops: requested={jobs.stop_requests} "
            f"escalated_to_kill={jobs.stop_escalations}"
        )
    if jobs.manager_starts or jobs.manager_disconnects or jobs.interruptions:
        out.append(
            f"  manager lifecycle: starts={jobs.manager_starts} "
            f"recovered_jobs={jobs.manager_recovered} "
            f"client_disconnects={jobs.manager_disconnects} "
            f"invalid_requests={jobs.manager_invalid_requests} "
            f"request_errors={jobs.manager_request_errors}"
        )
        if jobs.disconnect_ops:
            ops = ", ".join(f"{k}={v}" for k, v in jobs.disconnect_ops.most_common())
            out.append(f"  disconnect operations: {ops}")
        if jobs.interruptions:
            interruptions = ", ".join(
                f"{k}={v}" for k, v in jobs.interruptions.most_common()
            )
            out.append(f"  interrupted jobs: {interruptions}")
    return out
