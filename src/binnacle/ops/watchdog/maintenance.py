"""Service and host-service maintenance for one watchdog cycle."""

import logging

from binnacle.ops.watchdog.command import Run
from binnacle.ops.watchdog.config import Policy
from binnacle.ops.watchdog.model import DeviceInfo, State
from binnacle.ops.watchdog.services import (
    evaluate_services,
    evaluate_system,
    nm_answers,
    observe_services,
    observe_system,
)
from binnacle.ops.watchdog.tunnel import restart_tunnel, tunnel_affinity_check
from binnacle.uplink import ProbeResult, Route

log = logging.getLogger("binnacle.watchdog")


def maintain_services(
    state: State,
    policy: Policy,
    run: Run,
    routes: list[Route],
    probes: dict[str, ProbeResult],
    devices: dict[str, DeviceInfo],
    *,
    cycle_n: int,
    now: float,
    holding: bool,
) -> tuple[str, str]:

    # -- the processes between the uplink and ChatGPT, and the ones under it
    n = cycle_n
    now_cycle = now
    services_note = "-"
    tunnel_note = "-"
    if policy.service_repair:
        obs = observe_services(policy, run)
        tunnel_word = (
            "stopped"
            if not obs.tunnel_active
            else "FROZEN"
            if obs.tunnel_health_ok is False
            else f"failing({obs.poll_failures})"
            if obs.poll_failures
            else "ok"
        )
        services_note = (
            f"mcp={'ok' if obs.endpoint_ok else 'DOWN' if obs.endpoint_ok is False else 'stopped'}"
            f",tunnel={tunnel_word}"
        )
        restarts = evaluate_services(obs, state, policy, now_cycle)
        if holding and restarts:
            log.warning(
                "event=%s cycle=%s skipped_services=%s",
                "dry_run" if policy.dry_run else "paused",
                n,
                ",".join(u for u, _ in restarts),
            )
            restarts = []
        for unit, reason in restarts:
            name = "tunnel" if unit == policy.tunnel_unit else "mcp"
            state.last_service_restart[name] = now_cycle
            if name == "tunnel":
                restart_tunnel(state, policy, run, reason, now_cycle)
                continue
            proc = run("systemctl", "--user", "restart", unit, timeout=120.0)
            log.warning(
                "event=service_restart cycle=%s unit=%s ok=%s reason=%s err=%s",
                n,
                unit,
                proc.returncode == 0,
                reason,
                proc.stderr.strip(),
            )
        tunnel_note = tunnel_affinity_check(
            state, policy, run, routes, probes, obs, n, now_cycle, holding
        )
        if obs.mcp_unit and obs.endpoint_ok is False:
            state.extra_issues["mcp"] = (
                f"{policy.mcp_url} not answering while {obs.mcp_unit} is active"
            )
        if obs.tunnel_active and obs.tunnel_health_ok is False:
            state.extra_issues["tunnel"] = (
                "tunnel health server not answering (process frozen?)"
            )
        elif (
            obs.tunnel_active
            and obs.poll_last is not None
            and now_cycle - obs.poll_last >= policy.tunnel_stale_after_s
        ):
            state.extra_issues["tunnel"] = (
                f"tunnel log silent for {int(now_cycle - obs.poll_last)} s (reported only)"
            )
        if obs.tunnel_active and obs.poll_failures:
            state.extra_issues["tunnel"] = (
                f"tunnel poll failing ({obs.poll_failures} in a row); ChatGPT sees the "
                "connector offline"
                if obs.poll_failures >= policy.service_failures_before_action
                else f"tunnel poll failing ({obs.poll_failures} in a row)"
            )
    if policy.system_service_repair:
        sys_obs = observe_system(policy, devices, nm_answers(run), run)
        if not sys_obs.nm_active:
            state.extra_issues["networkmanager"] = f"{policy.nm_unit} is not active"
        elif not sys_obs.nm_responsive:
            state.extra_issues["networkmanager"] = (
                f"{policy.nm_unit} answered nothing for {state.nm_unresponsive_cycles + 1} cycles"
            )
        if sys_obs.nm_active and not sys_obs.supplicant_active:
            state.extra_issues["supplicant"] = f"{policy.supplicant_unit} is not active"
        restarts = evaluate_system(sys_obs, state, policy, now_cycle)
        if holding and restarts:
            log.warning(
                "event=%s cycle=%s skipped_system=%s",
                "dry_run" if policy.dry_run else "paused",
                n,
                ",".join(u for u, _ in restarts),
            )
            restarts = []
        for unit, reason in restarts:
            name = "nm" if unit == policy.nm_unit else "supplicant"
            state.last_system_restart[name] = now_cycle
            proc = run("sudo", "-n", "systemctl", "restart", unit, timeout=120.0)
            log.warning(
                "event=system_service_restart cycle=%s unit=%s ok=%s reason=%s err=%s",
                n,
                unit,
                proc.returncode == 0,
                reason,
                proc.stderr.strip(),
            )

    return services_note, tunnel_note
