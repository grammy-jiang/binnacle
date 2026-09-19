"""Model-based integration testing for the durable job lifecycle."""

import tempfile
from pathlib import Path

from fastmcp.exceptions import ToolError
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from binnacle import jobs as jobstore
from tests.integration.job_test_support import run, status, stop


class JobLifecycleMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.temp = tempfile.TemporaryDirectory(prefix="binnacle-job-model-")
        self.original_dir = jobstore.JOBS_DIR
        self.original_warmup = jobstore.WARMUP_S
        jobstore.JOBS_DIR = Path(self.temp.name)
        jobstore.WARMUP_S = 0.01
        self.job_id: str | None = None
        self.final: tuple[int | None, int | None] | None = None

    def teardown(self):
        if self.job_id is not None:
            try:
                current = status(self.job_id)
                if current["state"] == "running":
                    stop(self.job_id)
            except (KeyError, OSError, ToolError):
                pass
        jobstore.JOBS_DIR = self.original_dir
        jobstore.WARMUP_S = self.original_warmup
        self.temp.cleanup()

    @precondition(lambda self: self.job_id is None)
    @rule()
    def start_background_job(self):
        started = run("sleep 10", background=True)
        assert started["state"] == "running"
        assert started["background_job"] is True
        self.job_id = started["job_id"]

    @precondition(lambda self: self.job_id is not None and self.final is None)
    @rule()
    def inspect_running_or_naturally_finished_job(self):
        current = status(self.job_id)
        assert current["state"] in {"running", "exited"}
        if current["state"] == "exited":
            self.final = (current["exit_code"], current["signal"])

    @precondition(lambda self: self.job_id is not None)
    @rule()
    def list_contains_the_job(self):
        rows = status()["jobs"]
        row = next(item for item in rows if item["job_id"] == self.job_id)
        if self.final is None:
            assert row["state"] in {"running", "exited"}
            if row["state"] == "exited":
                self.final = (row["exit_code"], row["signal"])
        else:
            assert row["state"] == "exited"

    @precondition(lambda self: self.job_id is not None and self.final is None)
    @rule()
    def stop_job_to_terminal_state(self):
        stopped = stop(self.job_id)
        assert stopped["state"] == "exited"
        self.final = (stopped["exit_code"], stopped["signal"])

    @precondition(lambda self: self.job_id is not None and self.final is not None)
    @rule()
    def repeated_stop_is_idempotent(self):
        stopped = stop(self.job_id)
        assert stopped["state"] == "exited"
        assert (stopped["exit_code"], stopped["signal"]) == self.final

    @invariant()
    def terminal_state_never_returns_to_running(self):
        if self.job_id is None or self.final is None:
            return
        current = status(self.job_id)
        assert current["state"] == "exited"
        assert (current["exit_code"], current["signal"]) == self.final


TestJobLifecycleStateMachine = JobLifecycleMachine.TestCase
TestJobLifecycleStateMachine.settings = settings(
    max_examples=8,
    stateful_step_count=8,
    deadline=None,
)
