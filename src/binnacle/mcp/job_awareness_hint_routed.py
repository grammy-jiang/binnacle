"""CA-2 routed request-local checks for the synthetic hint adapter (E2 lab).

Exact types run before any field access, and backing maps are read with
``object.__getattribute__``, so no descriptor or hook of a route or a
candidate runs. Moved from ``job_awareness_hint`` unchanged in behaviour to
keep that module under its size limit.
"""

from __future__ import annotations

from typing import Any

__all__ = ["MAX_RENDERED", "rendered_jobs", "route_fields"]

#: Mirrors hint_policy/hint_render MAX_HINT_JOBS; the adapter may not import them.
MAX_RENDERED = 2


def route_fields(
    binding: Any, route: object
) -> tuple[object, tuple[object, ...]] | None:
    """``(grant, jobs)`` of a route of exactly ``binding.route_type``, or None.

    ``jobs`` must be a tuple of 1 to ``MAX_RENDERED`` exact ``job_type``
    values. The fields are read once from the backing map and never stored.
    """
    if (
        binding.route_type is None
        or binding.candidate_type is None
        or type(route) is not binding.route_type
    ):
        return None
    try:  # the backing map of the exact type; no descriptor or hook runs
        data = object.__getattribute__(route, "__dict__")
    except AttributeError:  # a slotted route type has no backing map
        return None
    if type(data) is not dict or "grant" not in data or "jobs" not in data:
        return None
    grant, jobs = data["grant"], data["jobs"]
    if (
        type(jobs) is not tuple
        or not 1 <= len(jobs) <= MAX_RENDERED
        or not all(type(job) is binding.job_type for job in jobs)
    ):
        return None
    return grant, jobs


def rendered_jobs(
    binding: Any, candidates: object, jobs: tuple[object, ...]
) -> tuple[object, ...] | None:
    """Jobs of the exact candidate tuple handed to the renderer, or None.

    Exact types run before any field access: a candidate must be exactly
    ``candidate_type`` and carry a ``job`` of exactly ``job_type`` that is
    one of the route jobs, with no repeats. ``rendered`` is therefore a
    subset of the reserved jobs by construction.
    """
    if type(candidates) is not tuple or not 1 <= len(candidates) <= MAX_RENDERED:
        return None
    rendered: list[object] = []
    for candidate in candidates:
        if type(candidate) is not binding.candidate_type:
            return None
        data = object.__getattribute__(candidate, "__dict__")
        if type(data) is not dict or "job" not in data:
            return None
        job = data["job"]
        if type(job) is not binding.job_type or job in rendered or job not in jobs:
            return None
        rendered.append(job)
    return tuple(rendered)
