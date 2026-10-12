"""Shared fakes for the E2 emission tests (design §2.6)."""

import asyncio
from dataclasses import dataclass
from typing import Any

from binnacle.features.commands.job_awareness.session_binding import KeyBinding
from binnacle.features.commands.job_awareness.session_emission import emit_hint
from tests.unit.core.job_awareness.session_support import Lab

ORIGINAL = {"result": "original"}
POINTS = (
    "after_reserve",
    "in_adapt",
    "after_adapt",
    "after_validation",
    "before_commit",
)


@dataclass(frozen=True)
class Routed:
    result: object
    rendered: Any


class Adapter:
    """Fake CA-2 adapter: renders a chosen subset and returns a new result."""

    def __init__(self, render=None, pause=None, raises=None, lie=None):
        self.render, self.pause, self.raises, self.lie = render, pause, raises, lie
        self.routes = []
        self.carrier_holds = True

    def routed_carrier_holds(self):
        return self.carrier_holds

    async def adapt_routed(self, original, *, execution, route):
        self.routes.append(route)
        if self.pause is not None:
            await self.pause("in_adapt")
        if self.raises is not None:
            raise self.raises
        await asyncio.sleep(0)
        jobs = tuple(route.jobs) if self.render is None else tuple(self.render(route))
        if self.lie is not None:
            return self.lie(original, route)
        if not jobs:
            return Routed(original, ())
        return Routed({"hint": [job.canonical_key for job in jobs]}, jobs)


def allocate(lab: Lab, name: str, count: int) -> list[str]:
    handles = []
    for index in range(count):
        handle = lab.start(name, f"R3-SYN-JOB-{index + 1:02d}")
        assert isinstance(handle, str)
        handles.append(handle)
    return handles


def emit_states(lab: Lab, name: str | None = None) -> dict[str, str]:
    if name is None:
        rows = lab.rows("SELECT jobref,state FROM emit")
    else:
        rows = lab.rows("SELECT jobref,state FROM emit WHERE kd=?", (lab.key(name).kd,))
    return dict(rows)


def run(lab: Lab, name: str, adapter: Adapter, checkpoint=None):
    return asyncio.run(
        emit_hint(
            lab.lab,
            lab.outcome(name),
            ORIGINAL,
            execution=object(),
            adapter=adapter,
            checkpoint=checkpoint,
        )
    )


def binding_of(lab: Lab, name: str) -> KeyBinding:
    binding = lab.lab.table.get(lab.key(name).kd)
    assert binding is not None
    return binding
