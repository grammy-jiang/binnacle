"""Schema and semantic validation for Chat scheduling v2 benchmark manifests."""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "chat-mode-scheduling-v2"
    / "scenarios"
)

CATALOG_SCENARIOS = {
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M6",
    "M7",
    "R1",
    "R2",
    "R3",
    "R4",
    "R5",
    "R6",
    "R7",
    "R8",
    "R9",
    "R10",
    "R11",
    "R12",
}
EXPECTED_PHASE1_STEPS = {
    "M1": "1.2",
    "M2": "1.2",
    "M3": "1.2",
    "M4": None,
    "M5": None,
    "M6": None,
    "M7": None,
    "R1": "1.3",
    "R2": "1.3",
    "R3": "1.4",
    "R4": None,
    "R5": "1.4",
    "R6": None,
    "R8": "1.5",
    "R9": "1.6",
    "R10": None,
    "R11": "1.7",
    "R12": None,
    "R7": "1.8",
}
PRODUCTION_TOOLS = {
    "read_file",
    "list_files",
    "search_text",
    "run_command",
    "job_status",
    "stop_job",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FixtureFile(StrictModel):
    path: str
    content: str


class FixtureJob(StrictModel):
    name: str
    command: str
    prelaunch: bool = False


class Fixture(StrictModel):
    kind: Literal["none", "ephemeral_dir", "ephemeral_git_repo", "dummy_jobs"]
    root_template: str | None = None
    files: list[FixtureFile] = Field(default_factory=list)
    jobs: list[FixtureJob] = Field(default_factory=list)
    allowed_mutation_globs: list[str] = Field(default_factory=list)
    production_mutation_allowed: bool = False


class Node(StrictModel):
    id: str
    kind: Literal["tool", "reasoning", "control"]
    tool: str | None = None
    access: Literal["read_only", "non_read_only", "reasoning", "control"]
    depends_on: list[str] = Field(default_factory=list)
    arguments: dict[str, Any] = Field(default_factory=dict)
    allow_repeats: bool = False
    completion_condition: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Node:
        if self.kind == "tool":
            if self.tool not in PRODUCTION_TOOLS:
                raise ValueError(f"tool node has unsupported tool {self.tool!r}")
            expected = (
                "read_only"
                if self.tool
                in {
                    "read_file",
                    "list_files",
                    "search_text",
                    "job_status",
                }
                else "non_read_only"
            )
            if self.access != expected:
                raise ValueError(
                    f"{self.tool} must be access={expected}, got {self.access}"
                )
        elif self.kind == "reasoning":
            if self.tool is not None or self.access != "reasoning":
                raise ValueError(
                    "reasoning node must have no tool and access=reasoning"
                )
        elif self.kind == "control":
            if self.tool is not None or self.access != "control":
                raise ValueError("control node must have no tool and access=control")
        if self.allow_repeats and not (
            self.kind == "tool" and self.tool == "job_status"
        ):
            raise ValueError("only job_status nodes may allow repeats")
        if self.completion_condition and self.kind != "tool":
            raise ValueError("completion_condition is only valid on tool nodes")
        return self


class OracleCheck(StrictModel):
    type: Literal[
        "exact_reply",
        "reply_contains_all",
        "tool_calls_exact_once",
        "event_relation",
        "job_state",
        "file_content",
        "pytest_pass",
        "command_exit_zero",
        "command_contains_exit_zero",
        "command_failure_precedes_success",
        "no_mutation_outside_scope",
        "all_nodes_complete",
        "job_status_any_call",
    ]
    params: dict[str, Any] = Field(default_factory=dict)


class Oracle(StrictModel):
    terminal_state: str
    checks: list[OracleCheck]


class Scenario(StrictModel):
    schema_version: Literal[1]
    id: str
    benchmark_class: Literal["micro", "macro"]
    phase1_step: str | None
    title: str
    purpose: str
    expected_runtime_s: int = Field(ge=0)
    max_turn_runtime_s: int = Field(gt=0)
    runtime_budget_margin_s: int | None = Field(default=None, ge=0)
    fixture: Fixture
    prompt_template: str
    dag: list[Node]
    oracle: Oracle
    metric_tags: list[str]

    @model_validator(mode="after")
    def validate_semantics(self) -> Scenario:
        if self.fixture.production_mutation_allowed:
            raise ValueError("production mutation must never be allowed")
        if self.id.startswith("M") != (self.benchmark_class == "micro"):
            raise ValueError("M* ids must be micro and R* ids must be macro")
        if self.expected_runtime_s > self.max_turn_runtime_s:
            raise ValueError("expected runtime exceeds max turn runtime")
        if self.id == "R12":
            if self.max_turn_runtime_s > 690:
                raise ValueError("R12 max turn runtime exceeds 690-second ceiling")
            if self.runtime_budget_margin_s != 30:
                raise ValueError("R12 runtime_budget_margin_s must be 30")
        else:
            if self.max_turn_runtime_s > 240:
                raise ValueError("max turn runtime exceeds 240-second ceiling")
            if self.runtime_budget_margin_s is not None:
                raise ValueError("runtime_budget_margin_s is only valid for R12")
        if self.phase1_step != EXPECTED_PHASE1_STEPS.get(self.id):
            raise ValueError(
                f"{self.id} phase1_step must be {EXPECTED_PHASE1_STEPS.get(self.id)!r}"
            )
        self._validate_fixture()
        self._validate_dag()
        self._validate_mutation_scope()
        self._validate_placeholders()
        return self

    def _validate_fixture(self) -> None:
        names = [job.name for job in self.fixture.jobs]
        if len(names) != len(set(names)):
            raise ValueError("fixture job names must be unique")
        for item in self.fixture.files:
            path = Path(item.path)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"fixture file path must stay relative: {item.path}")
        for glob in self.fixture.allowed_mutation_globs:
            if glob != "{root}" and not glob.startswith("{root}/"):
                raise ValueError(
                    f"allowed mutation glob must stay under {{root}}: {glob}"
                )

    def _validate_dag(self) -> None:
        ids = [node.id for node in self.dag]
        if len(ids) != len(set(ids)):
            raise ValueError("DAG node ids must be unique")
        known = set(ids)
        for node in self.dag:
            missing = set(node.depends_on) - known
            if missing:
                raise ValueError(f"{node.id} depends on unknown nodes {missing}")
            if node.id in node.depends_on:
                raise ValueError(f"{node.id} cannot depend on itself")

        children: dict[str, list[str]] = {node_id: [] for node_id in ids}
        indegree = {node_id: 0 for node_id in ids}
        for node in self.dag:
            for dep in node.depends_on:
                children[dep].append(node.id)
                indegree[node.id] += 1
        queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for child in children[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if visited != len(ids):
            raise ValueError("DAG contains a cycle")

    def _validate_mutation_scope(self) -> None:
        mutating = [
            node
            for node in self.dag
            if node.kind == "tool" and node.access == "non_read_only"
        ]
        if not mutating:
            return
        if self.fixture.kind == "none":
            raise ValueError("mutating scenario requires a disposable fixture")
        if not self.fixture.allowed_mutation_globs:
            raise ValueError("mutating scenario requires allowed_mutation_globs")

    def _validate_placeholders(self) -> None:
        job_names = {job.name for job in self.fixture.jobs}
        node_ids = {node.id for node in self.dag}
        allowed_simple = {"id", "run_id", "nonce", "root"}
        if self.id == "R12":
            allowed_simple.add("budget_plus_margin_s")

        def strings(value: Any):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)

        for text in strings(self.model_dump()):
            for token in re.findall(r"\{([^{}]+)\}", text):
                if token in allowed_simple:
                    continue
                if token.startswith("job:") and token[4:] in job_names:
                    continue
                if token.startswith("result:"):
                    ref = token[7:].split(".", 1)[0]
                    if ref in node_ids:
                        continue
                raise ValueError(f"unknown placeholder {{{token}}}")


def load_scenario(path: Path) -> Scenario:
    scenario = Scenario.model_validate_json(path.read_text())
    if path.stem != scenario.id:
        raise ValueError(f"{path.name}: file stem must match id {scenario.id}")
    return scenario


def load_all(root: Path = ROOT) -> dict[str, Scenario]:
    found = {path.stem: load_scenario(path) for path in sorted(root.glob("*.json"))}
    missing = CATALOG_SCENARIOS - set(found)
    extra = set(found) - CATALOG_SCENARIOS
    if missing or extra:
        raise ValueError(
            f"scenario catalog mismatch: missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )
    return found


def main() -> None:
    scenarios = load_all()
    phase_steps: dict[str, list[str]] = {}
    for scenario in scenarios.values():
        key = scenario.phase1_step or "mechanism-only"
        phase_steps.setdefault(key, []).append(scenario.id)
    print(f"validated {len(scenarios)} scenario manifests")
    for key, ids in sorted(phase_steps.items()):
        print(f"{key}: {', '.join(sorted(ids))}")


if __name__ == "__main__":
    main()
