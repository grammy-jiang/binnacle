"""Static plan and model handoff consistency checks (no experiment execution)."""

from __future__ import annotations

import re

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from tests.job_awareness_feasibility.validation_lib import (
    BASE,
    COMMON,
    EXTRA,
    LANES,
    PLAN,
    SCHEMAS,
    assert_equal,
    fail,
    load_json,
    schema_validate,
)


def plan_check() -> dict:
    plan = load_json(PLAN)
    assert_equal(
        "static lane IDs", [x["id"] for x in plan["worker_lanes"]], list(LANES)
    )
    assert_equal("fan-out", plan["parallelism"]["max_all_workers_after_s0"], 5)
    assert_equal(
        "single GUI owner", plan["parallelism"]["concurrent_desktop_gui_operators"], 1
    )
    for schema_path in SCHEMAS.glob("*.schema.json"):
        Draft202012Validator.check_schema(load_json(schema_path))
    io = load_json(BASE / "step-io.json")
    schema_validate(io, "step-io.schema.json")
    assert_equal(
        "S0 step IDs", [s["id"] for s in io["s0_steps"]], [f"S0.{n}" for n in range(6)]
    )
    assert_equal(
        "supervisor step IDs",
        [s["id"] for s in io["supervisor_steps"]],
        [f"M{n}" for n in range(5)],
    )
    assert_equal(
        "static manifest IO version",
        plan["contracts"]["version"],
        "job-awareness-io-v1",
    )
    required_sup = {
        "supervisor/dispatch-ledger.json",
        "supervisor/collection-report.json",
        "supervisor/reconciliation.md",
        "decision.json",
        "MANAGER-SUMMARY.md",
    }
    if not required_sup.issubset(set(plan["supervisor"]["required_output_files"])):
        fail("supervisor output contract is incomplete")
    for lane in plan["worker_lanes"]:
        wid = lane["id"]
        if lane["starts_after"] != ["S0"] or lane["depends_on_worker_results"]:
            fail(f"{wid}: must start after S0 only, with no other worker dependency")
        prompt = BASE / "prompts" / f"{wid}.md"
        p = prompt.read_text(encoding="utf-8").lower()
        expect: tuple[str, ...]
        if lane["executor"] == "chatgpt-desktop":
            expect = (
                lane["operator_model_request"],
                lane["operator_effort_request"],
                lane["subject_model_request"],
                lane["subject_effort_request"],
            )
        else:
            expect = (lane["model"], lane["reasoning_effort"])
        for x in expect:
            if x.lower() not in p:
                fail(f"{wid}: dispatch prompt does not explicitly request {x!r}")
        if not lane["scenarios"] or len(lane["scenarios"]) != len(
            set(lane["scenarios"])
        ):
            fail(f"{wid}: missing or duplicate scenarios")
        assert_equal(
            wid + ".machine scenario IDs",
            [x["id"] for x in io["workers"][wid]],
            lane["scenarios"],
        )
        all_outputs = set(lane["required_output_files"])
        if not set(COMMON + EXTRA[wid]).issubset(all_outputs):
            fail(wid + ": static manifest missing mandated worker outputs")
        for step in io["workers"][wid]:
            if step["owner"] != wid or step["depends_on"] != ["S0.5"]:
                fail(wid + ": invalid case owner or cross-worker dependency")
            if not any(x["ref"] == f"inputs/{wid}.input.json" for x in step["inputs"]):
                fail(wid + ": case missing frozen worker packet input")
            outputs = {x["ref"] for x in step["outputs"]}
            if (
                f"{wid}/results.json" not in outputs
                or f"{wid}/events.jsonl" not in outputs
            ):
                fail(wid + ": case missing status/events outputs")
        for token in (
            "model-selection.json",
            "W" + wid[1:] + ".input.json",
            "effective",
            "fallback",
            "outputs",
        ):
            if token.lower() not in p:
                fail(wid + ": handoff prompt missing " + token)
        if (
            "no implicit default" not in p
            and "not ambient defaults" not in p
            and "no default models" not in p
            and "never rely on defaults" not in p
        ):
            # The model instructions must explicitly forbid default-selection.
            fail(f"{wid}: handoff prompt must prohibit ambient/default models")
    if not {"S0/preflight.json", "run-manifest.json", "S0/readiness.md"}.issubset(
        set(plan["s0"]["required_output_files"])
    ):
        fail("S0 outputs missing from manifest")
    s0 = (BASE / "prompts" / "S0.md").read_text(encoding="utf-8").lower()
    for x in (plan["s0"]["model"], plan["s0"]["reasoning_effort"]):
        if x.lower() not in s0:
            fail("S0 handoff prompt does not pin explicit model and effort")
    assert_equal(
        "S0 selection",
        [plan["s0"]["model"], plan["s0"]["reasoning_effort"]],
        ["gpt-6-sol", "medium"],
    )
    link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for source in BASE.rglob("*.md"):
        for match in link.findall(source.read_text(encoding="utf-8")):
            path = match.split("#")[0].split("?")[0]
            if not path or path.startswith(("http://", "https://", "mailto:")):
                continue
            if not (source.parent / path).exists():
                fail(f"bad Markdown link {source}: {path}")
    return plan
