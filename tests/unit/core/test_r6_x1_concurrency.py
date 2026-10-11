"""r6 X1-t: one output snapshot per reply under real concurrency (R-X1 RX1-F2).

Since r6 W2 X1e (SD-74) each call passes the size its job state measured
explicitly to its log read; ``DurableCommandBackend`` keeps no per-thread or
per-instance pin. The X1 tests are single-threaded, so a size kept in plain
instance state would pass them. Here ONE shared backend serves two
spooled jobs that two writer threads keep growing; every size read appends
once more, and short delays inside the state and after the pin let other
calls interleave between each call's state and its log read. Calls run from a thread pool and through FastMCP's
async dispatch (``asyncio.gather`` over the in-memory client), and every
reply must be the snapshot of its own job: byte counts equal the bytes of the
returned text, which is the exact prefix or cursor slice of that job's
append-only log. The reused-thread test fixes that a state no read of the
same job followed leaves nothing on a worker thread.
"""

import asyncio
import json
import random
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastmcp import Client

from binnacle.config import RootsSettings, RunCommandSettings
from binnacle.features.commands import job_owner, jobs
from binnacle.features.commands.command_backend import DurableCommandBackend
from binnacle.features.commands.command_contracts import (
    read_log_snapshot,
    snapshot_size,
)
from binnacle.features.commands.commands_server import create_commands_server
from binnacle.features.commands.tools import job_status as job_status_tool
from binnacle.features.commands.tools import run_command as run_command_tool

LETTER = {"aaaaaaaaaaaa": "A", "bbbbbbbbbbbb": "B"}
JOB = {letter: job_id for job_id, letter in LETTER.items()}
ITERATIONS = 20
WORKERS = 12
BIG = 10_000_000
STATUS_LIMITS = {
    "quiet_after_s": 2,
    "history_limit": 1,
    "preview_chars": 20,
    "wait_max": 2,
}


def _spool(root: Path, job_id: str, text: bytes) -> Path:
    directory = root / job_id
    directory.mkdir(parents=True)
    now = time.time()
    meta = {
        "command": "burst",
        "workdir": "/tmp",
        "pid": 7,
        "started_at": now,
        "ended_at": now,
        "exit_code": 0,
    }
    (directory / "meta.json").write_text(json.dumps(meta))
    (directory / "out.log").write_bytes(text)
    return directory / "out.log"


@pytest.fixture
def spool_root(monkeypatch):
    """A test job spool under the temp dir (r6-x1t-*), never production's."""
    root = Path(tempfile.mkdtemp(prefix="r6-x1t-"))
    monkeypatch.setattr(jobs, "JOBS_DIR", root / "jobs")
    yield root
    shutil.rmtree(root, ignore_errors=True)


class Bursts:
    """Two append-only job logs, a forced race and in-flight accounting."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.rng = random.Random(12345)
        self.counter = dict.fromkeys(LETTER, 0)
        self.locks = {job_id: threading.Lock() for job_id in LETTER}
        self.gate = threading.Lock()
        self.inflight = 0
        self.max_inflight = 0
        self.stop = threading.Event()
        for job_id in LETTER:
            _spool(root, job_id, b"")
            self.append(job_id, 1)

    def append(self, job_id: str, lines: int) -> None:
        with self.locks[job_id]:
            chunk = b""
            for _ in range(lines):
                self.counter[job_id] += 1
                chunk += f"{LETTER[job_id]}{self.counter[job_id]:07d}\n".encode()
            with (self.root / job_id / "out.log").open("ab") as out:
                out.write(chunk)

    def instrument(self, monkeypatch) -> None:
        measure, read, read_range = jobs.job_state, jobs.read_log, jobs.read_log_range

        def racing_state(job_id):
            with self.gate:
                self.inflight += 1
                self.max_inflight = max(self.max_inflight, self.inflight)
            try:
                state = measure(job_id)
                self.append(job_id, self.rng.randint(1, 3))  # before the read
                time.sleep(self.rng.random() * 0.002)  # others interleave here
                return state
            finally:
                with self.gate:
                    self.inflight -= 1

        def slow_read(job_id):
            time.sleep(self.rng.random() * 0.002)
            return read(job_id)

        def slow_range(job_id, start, max_bytes):
            time.sleep(self.rng.random() * 0.002)
            return read_range(job_id, start, max_bytes)

        monkeypatch.setattr(jobs, "job_state", racing_state)
        monkeypatch.setattr(jobs, "read_log", slow_read)
        monkeypatch.setattr(jobs, "read_log_range", slow_range)
        # The size leaves the backend with the state and reaches the read as a
        # value, so the delays above lie outside that hand-over. Delay after
        # the real state methods too: other calls then measure in between.
        for name in ("job_state", "await_exit"):
            monkeypatch.setattr(
                DurableCommandBackend,
                name,
                self._delayed(getattr(DurableCommandBackend, name)),
            )

    def _delayed(self, method):
        def delayed(backend, *args):
            state = method(backend, *args)
            time.sleep(self.rng.random() * 0.002)
            return state

        return delayed

    def write_continuously(self, job_id: str) -> None:
        while not self.stop.is_set():
            self.append(job_id, self.rng.randint(1, 20))
            time.sleep(0.0005)

    def logs(self) -> dict[str, bytes]:
        return {j: (self.root / j / "out.log").read_bytes() for j in LETTER}


@pytest.fixture
def bursts(spool_root, monkeypatch):
    state = Bursts(spool_root / "jobs")
    state.instrument(monkeypatch)
    monkeypatch.setattr(jobs, "RUN_MAX_OUTPUT_CHARS", 50_000_000)  # no clipping
    # run_command "burstA"/"burstB" starts nothing; it reports that spooled job.
    monkeypatch.setattr(
        job_owner, "start_and_wait", lambda command, *_: JOB[command[-1]]
    )
    writers = [
        threading.Thread(target=state.write_continuously, args=(job_id,))
        for job_id in LETTER
    ]
    for writer in writers:
        writer.start()
    yield state
    state.stop.set()
    for writer in writers:
        writer.join(timeout=10)


def _plan(rng: random.Random, cursors: dict[str, str]) -> list[tuple]:
    """Twelve calls, six per job: every log-reading reply shape."""
    plan = []
    for letter, job_id in JOB.items():
        plan += [
            ("run_command", job_id, {"command": f"burst{letter}", "wait_seconds": 1}),
            ("tail", job_id, {"job_id": job_id, "tail_lines": BIG}),
            ("wait", job_id, {"job_id": job_id, "tail_lines": BIG, "wait_seconds": 1}),
            ("cursor_start", job_id, {"job_id": job_id, "cursor": "start"}),
            ("cursor_next", job_id, {"job_id": job_id, "cursor": cursors[job_id]}),
            ("cursor_end", job_id, {"job_id": job_id, "cursor": "end"}),
        ]
    rng.shuffle(plan)
    return plan


def _violation(kind: str, job_id: str, payload: dict, log: bytes) -> str | None:
    """Why a reply is not its own job's snapshot, or None when it is."""
    if "error" in payload:
        return f"error {payload['error']}"
    if kind == "run_command":
        text, size = payload["output"], payload["output_bytes"]
        if payload.get("job_id") != job_id:
            return "wrong job_id"
        if len(text.encode()) != size:
            return f"output_bytes {size} != output bytes {len(text.encode())}"
        if text.encode() != log[:size] or payload["truncated"]:
            return "output is not the prefix output_bytes measures"
    elif kind in ("tail", "wait"):
        text, size = payload["log_tail"], payload["log_bytes"]
        if len((text + "\n").encode()) != size:
            return (
                f"log_bytes {size} != log_tail bytes {len((text + chr(10)).encode())}"
            )
        if text != "\n".join(log[:size].decode().splitlines()):
            return "log_tail is not the log log_bytes measures"
    else:
        start, end = payload["delta_start"], payload["delta_end"]
        text, size = payload["log_delta"], payload["log_bytes"]
        if end != size:
            return f"delta_end {end} != log_bytes {size}"
        if kind == "cursor_start" and start != 0:
            return "cursor start not at 0"
        if kind == "cursor_end" and (start, text) != (size, ""):
            return "cursor end not at log_bytes"
        if text.encode() != log[start:end] or payload["has_more"]:
            return "log_delta is not the slice its offsets measure"
    if ("B" if LETTER[job_id] == "A" else "A") in text:
        return "another job's output"
    if text and LETTER[job_id] not in text:
        return "no own output"
    return None


def _threads(backend, roots, records) -> None:
    settings = RunCommandSettings()

    def direct(kind, args):
        if kind == "run_command":
            return run_command_tool.run_command_impl(
                args["command"],
                str(roots.default_root),
                args["wait_seconds"],
                False,
                None,
                roots=roots,
                settings=settings,
                backend=backend,
            ).structured_content
        return job_status_tool.job_status_impl(
            args["job_id"],
            args.get("tail_lines", 20),
            args.get("wait_seconds", 0),
            backend=backend,
            cursor=args.get("cursor"),
            **STATUS_LIMITS,
        ).structured_content

    rng = random.Random(1)
    cursors = dict.fromkeys(LETTER, "start")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for _ in range(ITERATIONS):
            plan = _plan(rng, cursors)
            futures = [pool.submit(direct, kind, args) for kind, _, args in plan]
            for (kind, job_id, _), future in zip(plan, futures, strict=True):
                try:
                    payload = future.result()
                except Exception as exc:  # noqa: BLE001 - recorded as a violation
                    payload = {"error": repr(exc)}
                records.append(("threads", kind, job_id, payload))
                if kind == "cursor_next" and "next_cursor" in payload:
                    cursors[job_id] = payload["next_cursor"]


async def _fastmcp(backend, roots, records) -> None:
    server = create_commands_server(
        backend=backend,
        roots=roots,
        run_settings=RunCommandSettings(),
        quiet_after_s=2,
        listing_history_limit=1,
        listing_command_preview_chars=20,
    )
    rng = random.Random(2)
    cursors = dict.fromkeys(LETTER, "start")

    async with Client(server) as client:

        async def one(kind, args):
            tool = "run_command" if kind == "run_command" else "job_status"
            if kind == "run_command":
                args = {**args, "workdir": str(roots.default_root)}
            try:
                return (await client.call_tool(tool, args)).structured_content
            except Exception as exc:  # noqa: BLE001 - recorded as a violation
                return {"error": repr(exc)}

        for _ in range(ITERATIONS):
            plan = _plan(rng, cursors)
            replies = await asyncio.gather(*(one(kind, args) for kind, _, args in plan))
            for (kind, job_id, _), payload in zip(plan, replies, strict=True):
                records.append(("fastmcp", kind, job_id, payload))
                if kind == "cursor_next" and "next_cursor" in payload:
                    cursors[job_id] = payload["next_cursor"]


def test_one_shared_backend_keeps_every_reply_its_own_snapshot(bursts, spool_root):
    backend = DurableCommandBackend()  # the ONE instance every call shares
    roots = RootsSettings(default_root=spool_root, extra_roots=())
    records = []
    overlap = {}
    _threads(backend, roots, records)
    overlap["threads"], bursts.max_inflight = bursts.max_inflight, 0
    asyncio.run(_fastmcp(backend, roots, records))
    overlap["fastmcp"] = bursts.max_inflight
    bursts.stop.set()
    logs = bursts.logs()

    counts = {"threads": [0, 0], "fastmcp": [0, 0]}
    examples = []
    for mode, kind, job_id, payload in records:
        counts[mode][0] += 1
        problem = _violation(kind, job_id, payload, logs[job_id])
        if problem:
            counts[mode][1] += 1
            examples.append((mode, kind, LETTER[job_id], problem))
    assert counts == {
        "threads": [ITERATIONS * 12, 0],
        "fastmcp": [ITERATIONS * 12, 0],
    }, f"[calls, violations] per mode: {counts}; first: {examples[:5]}"
    # The race is real: state reads of several calls were in flight at once.
    assert overlap["threads"] >= 2 and overlap["fastmcp"] >= 2, overlap


def test_a_reused_thread_carries_no_size_between_calls(spool_root):
    """A state that no read of its job followed leaves nothing behind.

    Before X1e a state pinned (job, size) on the calling thread until the next
    log read consumed it. Now the size is a value the caller passes on, so on
    one reused worker thread every plain read is the whole log, whatever state
    calls preceded it, and only an explicit size cuts a prefix.
    """
    root = spool_root / "jobs"
    a, b = JOB["A"], JOB["B"]
    log_a = _spool(root, a, b"a1\n")
    log_b = _spool(root, b, b"b1\nb2\nb3\nb4\n")
    backend = DurableCommandBackend()

    def grow(log: Path, line: bytes) -> None:
        with log.open("ab") as out:
            out.write(line)

    with ThreadPoolExecutor(max_workers=1) as worker:
        threads = set()

        def on_worker(method, *args):
            def call():
                threads.add(threading.get_ident())
                return method(*args)

            return worker.submit(call).result()

        # A state of A that no read of A follows (as when a call fails after
        # its state): before X1e it left A's pin (3 bytes) on the worker.
        assert on_worker(backend.job_state, a)["log_bytes"] == 3
        grow(log_a, b"a2\n")
        grow(log_b, b"b5\n")
        assert on_worker(backend.read_log, b) == log_b.read_bytes()
        assert on_worker(backend.read_log, a) == b"a1\na2\n"
        whole_b = log_b.read_bytes()
        assert on_worker(backend.read_log_range, b, 0, BIG) == (whole_b, len(whole_b))
        assert on_worker(backend.read_log_range, a, 0, BIG) == (log_a.read_bytes(), 6)

        # The explicit size cuts the prefix on any thread, as often as asked.
        size = snapshot_size(on_worker(backend.job_state, a))
        assert size == 6
        grow(log_a, b"a3\n")
        assert on_worker(read_log_snapshot, backend, a, size) == b"a1\na2\n"
        assert read_log_snapshot(backend, a, size) == b"a1\na2\n"
        assert on_worker(backend.read_log, a) == b"a1\na2\na3\n"
        assert backend.read_log(a) == b"a1\na2\na3\n"
    assert len(threads) == 1  # every on_worker call ran on one reused thread
