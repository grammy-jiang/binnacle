"""Layered uplink diagnostics owned by the reliability companion."""

from binnacle.companions.watchdog import uplink
from binnacle.doctor_contracts import Check, fail, ok, warn


def check_uplink(
    host: str = uplink.UPSTREAM_HOST,
    timeout: float = 3.0,
    run: uplink.Run = uplink._run,
    fallback_nameserver: str | None = None,
) -> list[Check]:
    """Does the route traffic takes actually carry traffic?

    Probes every default route end to end. A wedged active route is a
    FAIL: the host is up, the server is up, and nothing can reach it.
    """
    routes = uplink.default_routes(run)
    if not routes:
        return [warn("uplink", "no default route with a gateway and source address")]
    probes = uplink.probe_all(
        routes,
        host=host,
        timeout=timeout,
        run=run,
        fallback_nameserver=fallback_nameserver,
    )
    active = uplink.active_route(routes)
    out: list[Check] = []
    for route in routes:
        probe = probes.get(route.dev)
        if probe is None:
            continue
        is_active = active is not None and route.dev == active.dev
        role = "active" if is_active else "standby"
        if probe.healthy:
            out.append(ok("uplink", f"{role} {route.label}: {probe.summary()}"))
        elif probe.wedged and is_active:
            out.append(
                fail(
                    "uplink",
                    f"active {route.label} carries nothing: {probe.summary()}",
                    "another route must take over; inspect the route and uplink state",
                )
            )
        elif probe.wedged:
            out.append(
                warn(
                    "uplink",
                    f"standby {route.label} carries nothing: {probe.summary()}",
                    f"no impact while {active.dev if active else '?'} is healthy",
                )
            )
        else:
            deepest = probe.deepest_ok or "nothing"
            out.append(
                warn(
                    "uplink",
                    f"{role} {route.label} degraded: {probe.summary()} "
                    f"(deepest layer reached: {deepest})",
                    probe.errors.get(probe.first_failure or "", ""),
                )
            )
    return out
