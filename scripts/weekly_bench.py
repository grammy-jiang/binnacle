#!/usr/bin/env python3
"""The weekly latency benchmark (scripts/weekly_quality.py).

    scripts/weekly_bench.py --workdir /tmp/binnacle-bench-<run> --out <json> [--reps N]

Run as a program inside the benchmark's scope, it builds a fixed fixture
tree, a configuration and a token of its own under ``--workdir``, starts a
temporary server from this checkout on a free port of 127.0.0.1 (embedded
job owner, job spool and evidence directory under ``--workdir``, no
reload), calls every tool in a fixed order ``--reps`` times after
``WARMUP`` rounds, writes each call's client-side time to ``--out``, stops
the server and deletes ``--workdir``. Client and server share the scope's
one CPU, the same way every week. Production is never called: the only
server it talks to is the one it started.

The runner side (``bench_checks``) compares p50 and p95 per case with the
baseline in the state directory (the first run records it) and warns above
1.25 times the baseline p95 plus a small absolute slack.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

WARMUP = 2
REPS = 20
BENCH_TIMEOUT_S = 900
WARN_RATIO = 1.25
SLACK_MS = 5.0
SMALL = "alpha\nbeta gamma\ngamma delta\nnaive cafe\n"


def build_fixtures(work: Path) -> None:
    """The same tree every week: two text files and 200 small modules."""
    work.mkdir(parents=True)
    (work / "small.txt").write_text(SMALL, encoding="utf-8")
    (work / "long.txt").write_text(
        "".join(f"line {n}{' gamma' if n % 50 == 0 else ''}\n" for n in range(1, 2001)),
        encoding="utf-8",
    )
    for d in range(10):
        pkg = work / "src" / f"pkg{d}"
        pkg.mkdir(parents=True)
        for f in range(20):
            body = "".join(
                f"def func_{d}_{f}_{k}():\n    return {k}{'  # gamma' if k % 7 == 0 else ''}\n"
                for k in range(25)
            )
            (pkg / f"mod{f}.py").write_text(body, encoding="utf-8")


def config_text(base: Path, work: Path, port: int) -> str:
    q = json.dumps  # a JSON string is a valid TOML basic string for these paths
    return "\n".join(
        [
            "[roots]",
            f"default_root = {q(str(work))}",
            "extra_roots = []",
            "[auth]",
            f"token_file = {q(str(base / 'token'))}",
            "[serve]",
            'host = "127.0.0.1"',
            f"port = {port}",
            "[jobs]",
            'owner = "embedded"',
            f"dir = {q(str(base / 'jobs'))}",
            f"socket_path = {q(str(base / 'jobs.sock'))}",
            "[run_command]",
            f"auto_background_evidence_dir = {q(str(base / 'evidence'))}",
            "",
        ]
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_port(port: int, proc: subprocess.Popen, limit_s: float = 90.0) -> float:
    started = time.monotonic()
    while time.monotonic() - started < limit_s:
        if proc.poll() is not None:
            raise RuntimeError(f"the server exited {proc.returncode} before listening")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return time.monotonic() - started
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"the server did not listen within {limit_s:g} s")


def _rss_kb(pid: int) -> int:
    for line in Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return 0


def cases(work: Path, rep: int) -> list[tuple[str, str, dict[str, Any]]]:
    """(case, tool, arguments) in the fixed order of one round."""
    scratch = str(work / f"scratch-{rep}.txt")
    return [
        ("read_file-small", "read_file", {"path": str(work / "small.txt")}),
        (
            "read_file-range",
            "read_file",
            {"path": str(work / "long.txt"), "start_line": 1000, "end_line": 1400},
        ),
        ("list_files-glob", "list_files", {"path": str(work), "glob": "**/*.py"}),
        (
            "search_text-literal",
            "search_text",
            {"pattern": "gamma", "path": str(work), "fixed_strings": True},
        ),
        (
            "search_text-regex",
            "search_text",
            {"pattern": r"func_\d_1\d_7\(", "path": str(work)},
        ),
        ("write_file", "write_file", {"path": scratch, "content": "x bench\n"}),
        (
            "edit_file",
            "edit_file",
            {"path": scratch, "old_string": "x ", "new_string": "y "},
        ),
        (
            "run_command-fast",
            "run_command",
            {"command": "printf ok", "workdir": str(work), "wait_seconds": 10},
        ),
        ("job_status-listing", "job_status", {}),
    ]


async def _rounds(url: str, token: str, work: Path, reps: int) -> tuple[dict, dict]:
    from fastmcp import Client

    timings: dict[str, list[float]] = {}
    errors: dict[str, str] = {}

    async def timed(client: Any, case: str, tool: str, args: dict, keep: bool) -> Any:
        started = time.perf_counter()
        try:
            result = await client.call_tool(tool, args)
        except Exception as exc:  # noqa: BLE001 - recorded, the round goes on
            errors.setdefault(case, str(exc)[:200])
            return None
        if keep:
            timings.setdefault(case, []).append((time.perf_counter() - started) * 1000)
        return result

    async with Client(url, auth=token, timeout=60) as client:
        for rep in range(WARMUP + reps):
            keep = rep >= WARMUP
            for case, tool, args in cases(work, rep):
                await timed(client, case, tool, args, keep)
            job = await timed(
                client,
                "run_command-background",
                "run_command",
                {"command": "sleep 30", "workdir": str(work), "background": True},
                keep,
            )
            job_id = (getattr(job, "structured_content", None) or {}).get("job_id")
            if job_id:
                await timed(client, "stop_job", "stop_job", {"job_id": job_id}, keep)
    return timings, errors


def run_bench(base: Path, reps: int) -> dict[str, Any]:
    """Start the temporary server, time every case, stop it."""
    work = base / "work"
    build_fixtures(work)
    token = secrets.token_hex(24)
    (base / "token").write_text(f"Bearer {token}\n", encoding="utf-8")
    port = free_port()
    (base / "config.toml").write_text(config_text(base, work, port), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "BINNACLE_MANAGED_DEPLOYMENT"}
    env["BINNACLE_CONFIG_FILE"] = str(base / "config.toml")
    argv = [
        sys.executable,
        "-m",
        "uvicorn",
        "binnacle.server:app",
        "--host",
        "127.0.0.1",
    ]
    argv += ["--port", str(port), "--loop", "uvloop", "--http", "httptools"]
    log = base / "server.log"
    with open(log, "wb") as out:
        proc = subprocess.Popen(
            argv, cwd=base, env=env, stdout=out, stderr=subprocess.STDOUT
        )
    try:
        startup_s = _wait_port(port, proc)
        url = f"http://127.0.0.1:{port}/mcp"
        timings, errors = asyncio.run(_rounds(url, token, work, reps))
        rss_kb = _rss_kb(proc.pid)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
    return {
        "reps": reps,
        "startup_s": round(startup_s, 3),
        "rss_kb": rss_kb,
        "cases": timings,
        "errors": errors,
        "server_log_tail": tail if errors else [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly latency benchmark (one run).")
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reps", type=int, default=REPS)
    args = parser.parse_args(argv)
    if args.workdir.exists():
        print(f"{args.workdir} exists; refusing to reuse it", file=sys.stderr)
        return 2
    args.workdir.mkdir(parents=True)
    try:
        data = run_bench(args.workdir, args.reps)
    finally:
        shutil.rmtree(args.workdir, ignore_errors=True)
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
