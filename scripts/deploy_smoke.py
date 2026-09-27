#!/usr/bin/env python3
"""Post-deploy and daily smoke for the live binnacle MCP server.

    scripts/deploy_smoke.py [--full] [--rebaseline] [--quiet-ok]
    scripts/deploy_smoke.py deploy TARGET [--ci-timeout S] [--quiet-timeout S]

The smoke proves that the deployed server works for a real client:

- the doctor passes, and ``tools/list`` answers with authentication;
- every tool answers one call, each carrying an ``e2e-smoke-`` nonce, which
  the usage statistics treat as test traffic;
- the journal holds a tool_call and a tool_result line for each call, and no
  traceback;
- memory and start-up time stay within 1.25 times the recorded baseline.

``--full`` adds the tunnel and watchdog doctors; the daily cron run uses it.
``deploy`` fast-forwards the production checkout through the same smoke and
rolls back on failure (``scripts/deploy_flow.py``). The checks live in
``scripts/smoke_checks.py``.

Output follows cron-report: the first line is ``OK: ...``, ``WARN: ...`` or
``ALERT: ...``, and the exit code is non-zero only on ALERT. With
``--quiet-ok`` the command prints nothing when every check passes, so cron
sends no mail. Quality guard plan: docs/quality-guard-plan-2026-09-27.md,
step 2.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: make `scripts` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.smoke_checks import UNIT, Env, smoke

DEFAULT_CHECKOUT = Path.home() / "Projects" / "binnacle"
STATE_DIR = Path.home() / ".local" / "state" / "binnacle" / "smoke"
TOKEN_FILE = Path.home() / ".config" / "binnacle" / "token"
URL = "http://127.0.0.1:8000/mcp"


def run_command(argv: Sequence[str], timeout: float) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout:g} s"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def read_journal(since_epoch: float, until_epoch: float | None = None) -> list[str]:
    argv = ["journalctl", "--user", "-u", UNIT, "--since", f"@{int(since_epoch)}"]
    if until_epoch is not None:  # a bounded window: the unit may run for weeks
        argv += ["--until", f"@{int(until_epoch) + 1}"]
    rc, out = run_command([*argv, "--no-pager", "-o", "cat"], 60)
    return out.splitlines() if rc == 0 else []


def mcp_client() -> Any:
    """A real client. Its calls are told apart by their e2e-smoke- nonces."""
    from fastmcp import Client

    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    token = token.removeprefix("Bearer ").strip()
    return Client(URL, auth=token, timeout=60)


def default_env(checkout: Path = DEFAULT_CHECKOUT) -> Env:
    return Env(
        run=run_command,
        journal=read_journal,
        now=time.time,
        sleep=time.sleep,
        client=mcp_client,
        read=lambda p: p.read_text(encoding="utf-8"),
        checkout=checkout,
        state_dir=STATE_DIR,
        tmp_root=Path("/tmp"),
    )


def main(argv: Sequence[str] | None = None, env: Env | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live smoke and gated deploy.")
    parser.add_argument("--checkout", type=Path, default=DEFAULT_CHECKOUT)
    parser.add_argument(
        "--full", action="store_true", help="also run the tunnel and watchdog doctors"
    )
    parser.add_argument(
        "--rebaseline",
        action="store_true",
        help="record new RSS and start-up baselines",
    )
    parser.add_argument(
        "--quiet-ok", action="store_true", help="print nothing when every check passes"
    )
    sub = parser.add_subparsers(dest="command")
    dep = sub.add_parser("deploy", help="fast-forward the checkout through the smoke")
    dep.add_argument(
        "target", help="commit or ref to deploy (a fast-forward of master)"
    )
    dep.add_argument("--ci-timeout", type=float, default=900.0)
    dep.add_argument("--quiet-timeout", type=float, default=1800.0)
    args = parser.parse_args(argv)
    env = env or default_env(args.checkout)
    if args.command == "deploy":
        from scripts.deploy_flow import deploy

        level, text = deploy(
            env,
            args.target,
            ci_timeout=args.ci_timeout,
            quiet_timeout=args.quiet_timeout,
        )
    else:
        report = smoke(env, full=args.full, rebaseline=args.rebaseline)
        level = report.level
        text = "\n".join([f"{level.upper()}: {report.summary()}", *report.lines()])
    if not (args.quiet_ok and level == "ok"):
        print(text)
    return 1 if level == "alert" else 0


if __name__ == "__main__":
    sys.exit(main())
