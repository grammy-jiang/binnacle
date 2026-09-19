"""Shared derived state for one pure watchdog policy evaluation."""

from __future__ import annotations

from binnacle import uplink
from binnacle.ops.watchdog.config import Policy, usb_backoff
from binnacle.ops.watchdog.model import Action, DeviceInfo, Preference, State
from binnacle.ops.watchdog.schedule import _repairs_in_episode
from binnacle.uplink import ProbeResult, Route


class EvaluationContext:
    def __init__(
        self,
        routes: list[Route],
        probes: dict[str, ProbeResult],
        state: State,
        policy: Policy,
        now: float,
        preferences: dict[str, Preference],
        devices: dict[str, DeviceInfo],
        routes_known: bool,
    ) -> None:
        self.routes = routes
        self.probes = probes
        self.state = state
        self.policy = policy
        self.now = now
        self.prefs = preferences
        self.devs = devices
        self.routes_known = routes_known
        self.actions: list[Action] = []
        self.routed = {r.dev for r in routes}
        self.healthy_devs = {
            dev for dev, p in probes.items() if p.healthy and dev not in state.demoted
        }
        self.usable_devs = {
            dev
            for dev, p in probes.items()
            if p.layers.get("tcp") is True and dev not in state.demoted
        }

        for dev, started in list(state.repair_in_flight.items()):
            if now - started > 180.0:
                state.repair_in_flight.pop(dev, None)

        top = uplink.active_route(routes) if routes else None
        for dev in set(self.routed) | set(devices) | set(state.last_role):
            role = (
                "active"
                if top is not None and dev == top.dev
                else "standby"
                if dev in self.routed
                else "none"
            )
            if state.last_role.get(dev) != role:
                self.clear(dev)
                state.last_role[dev] = role

        self.active = uplink.active_route(routes) if routes else None
        self.active_probe = (
            probes.get(self.active.dev) if self.active is not None else None
        )
        self.active_healthy = (
            self.active_probe is not None and self.active_probe.healthy
        )

    def note(self, dev: str, rung: str, text: str) -> None:
        self.state.decisions.append((dev, rung, text))

    def reset_wait(self, dev: str, episode_start: float | None = None) -> float:
        last = self.state.last_reset.get(dev)
        if last is None:
            return 0.0
        limit = (
            self.policy.reset_floor_s
            if episode_start is not None and last < episode_start
            else self.policy.min_reset_interval_s
        )
        return max(0.0, limit - (self.now - last))

    def usb_wait(self, dev: str, episode_start: float | None = None) -> str:
        if not self.policy.usb_reset_enabled:
            return "USB reset disabled"
        reset_at, usb_at = _repairs_in_episode(self.state, dev, episode_start)
        if reset_at is None and usb_at is None:
            return "USB reset after the first re-association"
        last_repair = max(reset_at or 0.0, usb_at or 0.0)
        attempt = self.state.usb_attempts.get(dev, 0) + 1
        left = usb_backoff(self.policy.usb_reset_schedule, attempt) - (
            self.now - last_repair
        )
        return f"USB reset attempt {attempt} in {max(0.0, left):.0f} s"

    def in_flight(self, dev: str) -> bool:
        return dev in self.state.repair_in_flight

    def bump(self, dev: str) -> int:
        self.state.failures[dev] = self.state.failures.get(dev, 0) + 1
        if self.state.failures[dev] == 1:
            self.state.failure_since[dev] = self.now
        return self.state.failures[dev]

    def clear(self, dev: str) -> None:
        self.state.failures[dev] = 0
        self.state.failure_since.pop(dev, None)

    def usb_eligible(self, dev: str) -> bool:
        if not self.devs:
            return True
        info = self.devs.get(dev)
        return info is not None and info.usb_id in self.policy.usb_reset_ids

    def reload_eligible(self, dev: str) -> bool:
        info = self.devs.get(dev)
        return (
            self.policy.driver_reload_enabled
            and info is not None
            and info.usb_id is None
        )
