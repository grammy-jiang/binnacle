"""E2 S4 / CA-2: adapt_routed names exactly the rendered jobs, within the route.

All values are synthetic. The wire-byte baseline of ``adapt`` is in
``test_hint_routed_wire``; concurrency and once-only emission are in
``test_hint_routed_emission``.
"""

from dataclasses import dataclass, replace
from unittest.mock import patch

import pytest

from binnacle.features.commands.job_awareness.hint_policy import MAX_HINT_JOBS
from binnacle.features.commands.job_awareness.hint_render import (
    MAX_HINT_JOBS as RENDER_MAX,
)
from binnacle.features.commands.job_awareness.models import (
    CandidateCategory,
    HintCarrier,
    ReminderCandidate,
)
from binnacle.features.commands.job_awareness.session_route import (
    MAX_ROUTE_JOBS,
    SessionRoute,
)
from binnacle.mcp.job_awareness_hint import (
    MAX_RENDERED,
    META_KEY,
    HintAdapter,
    HintBindings,
    RoutedOutcome,
)
from tests.contracts.job_awareness.routed_support import (
    RoutedLab,
    key_digest,
    text_only,
)
from tests.contracts.job_awareness.synthetic_app import in_loop, original
from tests.contracts.job_awareness.test_hint_schema_support import executed


def hinted(text: str) -> list[str]:
    body = text.removeprefix("[Binnacle job reminder] ")
    return [part.split(" ")[0] for part in body.split("; ")]


def ordered(jobs) -> tuple:
    return tuple(sorted(jobs, key=lambda job: job.canonical_key))


def unchanged(value) -> RoutedOutcome:
    return RoutedOutcome(value, ())


def test_rendered_cap_mirrors_core():
    caps = (MAX_RENDERED, MAX_HINT_JOBS, RENDER_MAX, MAX_ROUTE_JOBS)
    assert caps == (2, 2, 2, 2)  # nosec B101 - pytest assertion


def test_route_bindings_are_optional_exact_types():
    with RoutedLab(2) as lab:
        bindings = lab.routed().bindings
        assert bindings.route_type is SessionRoute  # nosec B101 - pytest assertion
        assert bindings.candidate_type is ReminderCandidate  # nosec B101 - pytest assertion
        for name in ("route_type", "candidate_type"):
            assert HintBindings.__dataclass_fields__[name].default is None  # nosec B101 - pytest assertion
            for value in (
                "SessionRoute",
                SessionRoute(key_digest(), lab.handle, lab.jobs[:1]),
            ):
                with pytest.raises(ValueError, match="invalid hint bindings"):
                    replace(bindings, **{name: value})


@pytest.mark.parametrize("carrier", [HintCarrier.META, HintCarrier.TEXT])
@in_loop
async def test_rendered_is_exactly_the_hinted_jobs(carrier):
    text_u = carrier is HintCarrier.TEXT  # routed TEXT = TEXT-U (g5 §9.2 S-2)
    with RoutedLab(4) as lab:
        adapter = lab.routed(structured=not text_u, enabled=True, carrier=carrier)
        routes = (lab.jobs[:1], lab.jobs[1:3], (lab.jobs[3], lab.jobs[0]))
        for jobs in routes:
            value = text_only() if text_u else original()
            value, outcome = await lab.call(adapter, lab.route(*jobs), value)
            assert type(outcome) is RoutedOutcome and outcome.result is not value  # nosec B101 - pytest assertion
            result = outcome.result
            text = (
                result.meta[META_KEY]
                if carrier is HintCarrier.META
                else result.content[-1].text
            )
            assert outcome.rendered == ordered(jobs)  # nosec B101 - pytest assertion
            assert hinted(text) == [job.canonical_key for job in ordered(jobs)]  # nosec B101 - pytest assertion
            assert set(outcome.rendered) <= set(jobs)  # nosec B101 - pytest assertion
            for job in set(lab.jobs) - set(jobs):
                assert job.canonical_key not in text  # nosec B101 - pytest assertion
            assert value.meta == {"existing": "kept"} and len(value.content) == 1  # nosec B101 - pytest assertion


@in_loop
async def test_only_selected_candidates_are_rendered():
    """A COMPLETE or expired job yields no candidate and is not rendered."""
    with RoutedLab(2) as lab:
        adapter = lab.routed(enabled=True)
        select = adapter.bindings.select
        adapter.bindings = replace(
            adapter.bindings,
            select=lambda grant, observed: tuple(
                c for c in select(grant, observed) if c.job != lab.jobs[0]
            ),
        )
        _, outcome = await lab.call(adapter, lab.route(*lab.jobs))
        assert outcome.rendered == (lab.jobs[1],)  # nosec B101 - pytest assertion
        assert hinted(outcome.result.meta[META_KEY]) == [lab.jobs[1].canonical_key]  # nosec B101 - pytest assertion


def candidate(lab, job, category=CandidateCategory.TERMINAL_UNCONFIRMED):
    return ReminderCandidate(job, category, "8" * 32, lab.snapshot.sha256)


class Candidate(ReminderCandidate):
    """A subclass is not the bound candidate type."""


HOSTILE = (
    "none",
    "list",
    "empty",
    "outside_route",
    "duplicate",
    "foreign_type",
    "subclass",
    "three",
    "job_subclass",
    "no_job_field",
    "render_none",
)


@pytest.mark.parametrize("case", HOSTILE)
@in_loop
async def test_unsafe_candidates_or_render_suppress(case):
    with RoutedLab(3) as lab:
        adapter = lab.routed(enabled=True)
        select = adapter.bindings.select

        def hostile(grant, observed):
            real = select(grant, observed)
            first = real[0]

            def outside():
                return candidate(lab, lab.jobs[2])

            def no_job_field():
                bad = replace(first)
                del bad.__dict__["job"]
                return (bad,)

            def job_subclass():
                job = type("Job", (type(first.job),), {})(*vars(first.job).values())
                bad = replace(first)
                object.__setattr__(bad, "job", job)
                return (bad,)

            built = {
                "none": lambda: None,
                "list": lambda: list(real),
                "empty": lambda: (),
                "outside_route": lambda: (first, outside()),
                "duplicate": lambda: (first, first),
                "foreign_type": lambda: (object(),),
                "subclass": lambda: (Candidate(*vars(first).values()),),
                "three": lambda: (*real, outside()),
                "job_subclass": job_subclass,
                "no_job_field": no_job_field,
            }.get(case, lambda: real)()
            returned.append(case)
            return built

        returned, rendered = [], []

        def render(candidates, carrier):
            rendered.append(candidates)
            return None if case == "render_none" else real_render(candidates, carrier)

        real_render = adapter.bindings.render
        adapter.bindings = replace(adapter.bindings, select=hostile, render=render)
        value, outcome = await lab.call(adapter, lab.route(*lab.jobs[:2]))
        assert outcome == unchanged(value) and outcome.result is value  # nosec B101 - pytest assertion
        # The guard, not an exception, suppressed: select returned, and only
        # the render_none case ever reached the renderer.
        assert returned == [case]  # nosec B101 - pytest assertion
        assert len(rendered) == (1 if case == "render_none" else 0)  # nosec B101 - pytest assertion
        assert value.meta == {"existing": "kept"}  # nosec B101 - pytest assertion


class Route(SessionRoute):
    """A subclass is not the bound route type."""


ROUTES = (
    "none",
    "dict",
    "tuple",
    "subclass",
    "empty",
    "three",
    "foreign_job",
    "list_jobs",
    "no_jobs_field",
    "no_route_type",
    "no_candidate_type",
)


@pytest.mark.parametrize("case", ROUTES)
@in_loop
async def test_invalid_route_reads_and_consumes_nothing(case):
    with RoutedLab(3) as lab:
        adapter = lab.routed(enabled=True)
        good = lab.route(*lab.jobs[:2])
        route = {
            "none": None,
            "dict": {"grant": lab.handle, "jobs": lab.jobs[:2]},
            "tuple": (good.key, lab.handle, lab.jobs[:2]),
            "subclass": Route(good.key, good.grant, good.jobs),
        }.get(case, replace(good))
        jobs = {
            "empty": (),
            "three": lab.jobs,
            "foreign_job": (object(),),
            "list_jobs": list(lab.jobs[:2]),
        }
        if case in jobs:
            object.__setattr__(route, "jobs", jobs[case])
        if case == "no_jobs_field":
            del route.__dict__["jobs"]
        if case.startswith("no_") and case != "no_jobs_field":
            name = case.removeprefix("no_")
            adapter.bindings = replace(adapter.bindings, **{name: None})
        value = original()
        receipt = executed(value, adapter.bound_tool)
        outcome = await adapter.adapt_routed(value, execution=receipt, route=route)
        assert outcome == unchanged(value)  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion
        if case.startswith("no_") and case != "no_jobs_field":
            return
        # The receipt was not consumed: the same call with a valid route works.
        outcome = await adapter.adapt_routed(value, execution=receipt, route=good)
        assert outcome.rendered == ordered(lab.jobs[:2])  # nosec B101 - pytest assertion


@in_loop
async def test_slotted_route_type_suppresses():
    with RoutedLab(1) as lab:

        @dataclass(frozen=True, slots=True)
        class Slotted:
            grant: object
            jobs: tuple

        adapter = lab.routed(enabled=True)
        adapter.bindings = replace(adapter.bindings, route_type=Slotted)
        value = original()
        receipt = executed(value, adapter.bound_tool)
        route = Slotted(lab.handle, lab.jobs)
        outcome = await adapter.adapt_routed(value, execution=receipt, route=route)
        assert outcome == unchanged(value)  # nosec B101 - pytest assertion


@in_loop
async def test_route_grant_must_authorize_every_route_job():
    with RoutedLab(2) as lab:
        adapter = lab.routed(enabled=True)
        narrow = lab.consumer("d" * 32, jobs=lab.jobs[:1])
        route = lab.route(*lab.jobs, grant=narrow)
        value, outcome = await lab.call(adapter, route)
        assert outcome == unchanged(value)  # nosec B101 - pytest assertion
        _, outcome = await lab.call(adapter, lab.route(lab.jobs[0], grant=narrow))
        assert outcome.rendered == (lab.jobs[0],)  # nosec B101 - pytest assertion


@in_loop
async def test_routed_path_ignores_and_never_stores_adapter_jobs():
    with RoutedLab(3) as lab:
        adapter = lab.routed(enabled=True)
        adapter.grant, adapter.jobs = object(), ()
        before = {k: v for k, v in vars(adapter).items() if k != "last_meter"}
        _, outcome = await lab.call(adapter, lab.route(lab.jobs[2]))
        assert outcome.rendered == (lab.jobs[2],)  # nosec B101 - pytest assertion
        after = {k: v for k, v in vars(adapter).items() if k != "last_meter"}
        assert after == before  # nosec B101 - pytest assertion
        assert not any(type(v) is SessionRoute for v in vars(adapter).values())  # nosec B101 - pytest assertion
        # adapt() still uses the adapter's own, now invalid, grant and jobs.
        value = original()
        receipt = executed(value, adapter.bound_tool)
        assert await adapter.adapt(value, execution=receipt) is value  # nosec B101 - pytest assertion


@in_loop
async def test_disabled_or_unwitnessed_routed_calls_read_nothing():
    with RoutedLab(2) as lab:
        route = lab.route(*lab.jobs)
        for enabled, exclusive in ((False, True), (True, False)):
            adapter = lab.routed(enabled=enabled, exclusive=exclusive)
            value, outcome = await lab.call(adapter, route)
            assert outcome == unchanged(value)  # nosec B101 - pytest assertion
        adapter = lab.routed(enabled=True)
        value = original()
        for execution in (None, adapter.bound_tool, executed(original(), adapter.tool)):
            outcome = await adapter.adapt_routed(
                value, execution=execution, route=route
            )
            assert outcome == unchanged(value)  # nosec B101 - pytest assertion
        assert lab.catalog_reads == lab.queries == 0  # nosec B101 - pytest assertion
        receipt = executed(value, adapter.bound_tool)
        assert (
            await adapter.adapt_routed(value, execution=receipt, route=route)
        ).rendered  # nosec B101 - pytest assertion
        again = await adapter.adapt_routed(value, execution=receipt, route=route)
        assert again == unchanged(value)  # nosec B101 - pytest assertion


@in_loop
async def test_busy_failing_or_error_results_return_original():
    with RoutedLab(2) as lab:
        adapter = lab.routed(enabled=True)
        route = lab.route(*lab.jobs)
        with patch.object(lab.budget, "reserve", return_value=None):
            value, outcome = await lab.call(adapter, route)
        assert outcome == unchanged(value)  # nosec B101 - pytest assertion
        for target, name in (
            (lab, "query"),
            (lab, "observe"),
            (lab.authority, "check"),
        ):
            with patch.object(target, name, side_effect=RuntimeError("secret")):
                value, outcome = await lab.call(adapter, route)
            assert outcome == unchanged(value)  # nosec B101 - pytest assertion
        value = original()
        value.is_error = True
        _, outcome = await lab.call(adapter, route, value)
        assert outcome == unchanged(value)  # nosec B101 - pytest assertion
        value = original()
        value.meta[META_KEY] = "producer-owned"
        _, outcome = await lab.call(adapter, route, value)
        assert outcome == unchanged(value)  # nosec B101 - pytest assertion
        value = original()
        value.structured_content = {"ok": "schema-invalid"}
        _, outcome = await lab.call(adapter, route, value)
        assert outcome == unchanged(value)  # nosec B101 - pytest assertion


def test_route_key_is_never_read():
    """Only grant and jobs leave the route; the digest key stays behind."""
    names = HintAdapter.adapt_routed.__code__.co_consts
    assert "grant" in names and "jobs" in names and "key" not in names  # nosec B101 - pytest assertion
