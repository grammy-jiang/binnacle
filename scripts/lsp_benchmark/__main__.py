"""Run with python -m scripts.lsp_benchmark --help; no import-time work."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .corpus import synthetic, trusted_snapshot
from .native import NativeBackend, provenance
from .runner import Options, experiment

CANDIDATES = (
    "pyright",
    "typescript",
    "clangd",
    "rust-analyzer",
    "marksman",
    "bash",
    "make-ls",
    "yaml",
    "json",
)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        description="P3.5 opt-in, trust-only disposable Python benchmark; never a release gate"
    )
    cli.add_argument(
        "--run", action="store_true", help="explicitly enable local provider execution"
    )
    cli.add_argument("--provider", choices=CANDIDATES, default="pyright")
    cli.add_argument(
        "--binary",
        type=Path,
        help="explicit trusted preinstalled npm pyright-langserver",
    )
    cli.add_argument("--scale", choices=("small", "medium"), default="small")
    cli.add_argument(
        "--quiet-host",
        action="store_true",
        help="operator attests no competing agents/workloads; required beyond tiny smoke",
    )
    cli.add_argument("--real-root", type=Path)
    cli.add_argument("--real-manifest", type=Path)
    cli.add_argument(
        "--trust-real-workspace",
        type=Path,
        help="explicit authorization of this exact real root for reviewed snapshot ingestion",
    )
    cli.add_argument(
        "--output",
        type=Path,
        help="new JSON file; existing files are never overwritten",
    )
    for name, kind, default in (
        ("repeats", int, 30),
        ("warmup", int, 3),
        ("concurrency", int, 1),
        ("instances", int, 1),
        ("deadline-s", float, 15),
        ("total-s", float, 120),
        ("sample-interval-s", float, 0.1),
        ("p95-budget-ms", float, 100),
        ("rss-budget-mib", float, 512),
    ):
        cli.add_argument(f"--{name}", type=kind, default=default)
    return cli


def environment() -> dict:
    repo = Path(__file__).resolve().parents[2]
    # Ignore inherited repository-local Git variables. Never operate on corpus Git.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    revision = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            env=env,
            capture_output=True,
            check=True,
            timeout=5,
        ).stdout
    )
    source = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        source.update(path.name.encode())
        source.update(path.read_bytes())
    return {
        "utc": datetime.now(timezone.utc).isoformat(),
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "binnacle_revision": revision,
        "tracked_or_untracked_changes": dirty,
        "harness_sha256": source.hexdigest(),
        "uv_lock_sha256": hashlib.sha256((repo / "uv.lock").read_bytes()).hexdigest(),
    }


def unchanged(root: Path, expected: dict[str, bytes]) -> bool:
    expected = {**expected, ".git": b"gitdir: /nonexistent/p35-disposable\n"}
    directories = {
        parent.as_posix()
        for name in expected
        for parent in Path(name).parents
        if parent != Path(".")
    }
    seen = set()
    try:
        for path in root.rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_symlink():
                return False
            if path.is_dir():
                if name not in directories:
                    return False
                continue
            if name not in expected:
                return False
            with path.open("rb") as stream:
                if stream.read(len(expected[name]) + 1) != expected[name]:
                    return False
            seen.add(name)
    except OSError:
        return False
    return seen == set(expected)


def run(args) -> dict:
    options = Options(
        **{name: getattr(args, name) for name in Options.__dataclass_fields__}
    )
    if not args.run:
        raise ValueError("explicit_run_required")
    small_smoke = (
        args.scale == "small"
        and options.repeats <= 3
        and options.warmup == 1
        and options.concurrency == options.instances == 1
        and options.total_s <= 45
    )
    if not args.quiet_host and (not small_smoke or args.real_root is not None):
        raise ValueError("quiet_host_required_for_measurement")
    real_values = (args.real_root, args.real_manifest, args.trust_real_workspace)
    if any(value is not None for value in real_values) and not all(
        value is not None for value in real_values
    ):
        raise ValueError("explicit_real_workspace_trust_required")
    report = {
        "schema": "binnacle.p35/1",
        "environment": environment(),
        "authoritative_timings": False,
        "quiet_host_attested": args.quiet_host,
        "release_decision": "NOT_EVALUATED_READ_NO_GO",
    }
    if args.provider != "pyright":
        return {
            **report,
            "status": "profile_not_admitted",
            "provider": args.provider,
            "valid": False,
        }
    if args.binary is None:
        raise ValueError("absolute_trusted_binary_required")
    if not args.binary.is_file():
        return {
            **report,
            "status": "not_installed",
            "provider": "pyright",
            "valid": False,
        }
    report["provider"] = provenance(args.binary)
    corpus = (
        trusted_snapshot(args.real_root, args.real_manifest, args.trust_real_workspace)
        if args.real_root is not None
        else synthetic(args.scale)
    )
    with tempfile.TemporaryDirectory(prefix="binnacle-p35-") as temporary:
        roots = [
            Path(temporary).resolve() / f"workspace-{index}"
            for index in range(options.instances)
        ]
        for root in roots:
            corpus.materialize(root)
        # Upstream logger/diagnostics are not evidence. Keep JSON free of raw
        # messages, source snippets, file URIs and local paths, even on failure.
        old_logging = logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            with (
                open(os.devnull, "w") as sink,
                contextlib.redirect_stdout(sink),
                contextlib.redirect_stderr(sink),
            ):

                async def execute():
                    backend = NativeBackend(
                        args.binary, roots, options.concurrency, options.deadline_s
                    )
                    return await experiment(backend, corpus, options)

                report.update(asyncio.run(execute()))
        finally:
            logging.disable(old_logging)
        report["snapshot_unchanged"] = all(
            unchanged(root, corpus.files) for root in roots
        )
        report["valid"] = report["valid"] and report["snapshot_unchanged"]
    return report


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    # Claim output exclusively before starting anything, avoiding late overwrite.
    try:
        with (
            args.output.open("x")
            if args.output
            else contextlib.nullcontext(sys.stdout) as output
        ):
            try:
                report = run(args)
            except Exception:  # noqa: BLE001 - CLI must not disclose private error text
                report = {
                    "schema": "binnacle.p35/1",
                    "status": "admission_or_execution_error",
                    "valid": False,
                    "release_decision": "NOT_EVALUATED_READ_NO_GO",
                }
            json.dump(report, output, indent=2, allow_nan=False)
            output.write("\n")
            return 0 if report.get("valid") else 2
    except OSError:
        print("P3.5 output unavailable; no file overwritten", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
