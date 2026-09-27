"""Golden outputs: every tool on fixed fixtures, compared with snapshots.

Each test builds the same small tree in its tmp directory, calls the tools
through fastmcp's in-memory Client (which validates every structured result
against the tool's output schema) and compares the masked result with
tests/contracts/snapshots/<case>.json, including its size budget. The
masking and the size rules are in golden_support.py. The job tools run on a
job spool inside the tmp directory, never on the real one.

To update the snapshots on purpose, run

    BINNACLE_UPDATE_SNAPSHOTS=1 uv run pytest tests/contracts/test_golden_outputs.py

review ``git diff tests/contracts/snapshots``, and give the reason in the
commit message. docs/testing.md has the details.
"""

import asyncio
import os
import signal

import pytest
from fastmcp import Client

from binnacle import jobs, server
from tests.contracts.golden_support import SNAPSHOT_DIR, Masker, check

CASES = (
    "read_file-small",
    "read_file-truncated",
    "list_files",
    "search_text-literal",
    "search_text-regex",
    "write_file",
    "edit_file",
    "run_command-fast",
    "run_command-job",
    "job_status-wait",
    "job_status-listing",
    "run_command-background",
    "stop_job",
)
SMALL = "alpha\nbeta gamma\ngamma delta\nnaïve café\n"
#: Waits for a file instead of a clock, so it is still running when
#: run_command returns and prints nothing until the test releases it.
RELEASE_LOOP = (
    "i=0; while [ ! -e release ] && [ $i -lt 200 ]; do sleep 0.05; i=$((i+1)); "
    "done; printf 'released\\n'"
)


@pytest.fixture()
def work(tmp_path, monkeypatch):
    """The fixture tree, and a private job spool with a short warm-up."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs, "WARMUP_S", 0.05)
    root = tmp_path / "work"
    (root / "src").mkdir(parents=True)
    (root / "small.txt").write_text(SMALL)
    (root / "long.txt").write_text("".join(f"{n}\n" for n in range(1, 2002)))
    (root / "notes.md").write_text("# Notes\ngamma ray\ncost: $5.00 each\n")
    (root / "src" / "app.py").write_text("def main():\n    return 'gamma'\n")
    yield root
    for state in jobs.list_jobs():  # a failed test must not leave a job behind
        if state["state"] == "running":
            try:
                os.killpg(state["pgid"], signal.SIGKILL)
            except ProcessLookupError:
                pass


def run(steps):
    """Run ``steps(call)`` in one client session; ``call`` returns the result."""

    async def go():
        async with Client(server.mcp) as client:

            async def call(name, **arguments):
                return await client.call_tool(name, arguments)

            return await steps(call)

    return asyncio.run(go())


def test_read_file(work, tmp_path):
    masker = Masker(tmp_path)

    async def steps(call):
        small = await call("read_file", path=str(work / "small.txt"))
        long = await call("read_file", path=str(work / "long.txt"))
        return small, long

    small, long = run(steps)
    check("read_file-small", masker.record(small))
    check("read_file-truncated", masker.record(long))
    assert long.structured_content["truncated"] is True


def test_list_files(work, tmp_path):
    async def steps(call):
        return await call("list_files", path=str(work))

    check("list_files", Masker(tmp_path).record(run(steps)))


def test_search_text(work, tmp_path):
    masker = Masker(tmp_path)

    async def steps(call):
        literal = await call(
            "search_text", pattern="$5.00", path=str(work), fixed_strings=True
        )
        regex = await call("search_text", pattern=r"gam+a\s\w+", path=str(work))
        return literal, regex

    literal, regex = run(steps)
    for name, result in (
        ("search_text-literal", literal),
        ("search_text-regex", regex),
    ):
        recorded = masker.record(result)
        # ripgrep searches files in parallel, so their order is not stable.
        entries = recorded["structured"]["entries"]
        entries.sort(key=lambda entry: (entry["file"], entry["line"]))
        check(name, recorded)


def test_write_file_then_edit_file(work, tmp_path):
    masker = Masker(tmp_path)
    target = work / "new.txt"

    async def steps(call):
        written = await call("write_file", path=str(target), content="one\ntwo\n")
        edited = await call(
            "edit_file", path=str(target), old_string="two", new_string="three"
        )
        return written, edited

    written, edited = run(steps)
    check("write_file", masker.record(written))
    check("edit_file", masker.record(edited))
    assert target.read_text() == "one\nthree\n"


def test_run_command_fast(work, tmp_path):
    async def steps(call):
        return await call(
            "run_command", command="printf 'hello golden\\n'", workdir=str(work)
        )

    check("run_command-fast", Masker(tmp_path).record(run(steps)))


def test_job_that_outlives_its_wait(work, tmp_path):
    masker = Masker(tmp_path)

    async def steps(call):
        started = await call(
            "run_command", command=RELEASE_LOOP, workdir=str(work), wait_seconds=1
        )
        (work / "release").touch()
        job_id = started.structured_content["job_id"]
        waited = await call("job_status", job_id=job_id, wait_seconds=10)
        listing = await call("job_status")
        return started, waited, listing

    started, waited, listing = run(steps)
    check("run_command-job", masker.record(started))
    check("job_status-wait", masker.record(waited))
    check("job_status-listing", masker.record(listing))


def test_stop_job(work, tmp_path):
    masker = Masker(tmp_path)

    async def steps(call):
        started = await call(
            "run_command", command="sleep 30", workdir=str(work), background=True
        )
        stopped = await call("stop_job", job_id=started.structured_content["job_id"])
        return started, stopped

    started, stopped = run(steps)
    check("run_command-background", masker.record(started))
    check("stop_job", masker.record(stopped))


def test_every_snapshot_belongs_to_a_case():
    assert sorted(p.stem for p in SNAPSHOT_DIR.glob("*.json")) == sorted(CASES)
