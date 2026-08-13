#!/usr/bin/env python3
"""Emit bounded evidence of the exact commit/tree/parents checked by GitHub Actions."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from binnacle.evaluation.ci_attestation import (  # noqa: E402
    CiAttestationError,
    GitCheckoutIdentity,
    build_ci_checkout_attestation,
    ci_attestation_collector_sha256,
    ci_attestation_is_bound,
)
from binnacle.evaluation.digests import canonical_json_bytes  # noqa: E402

_MAX_EVENT_BYTES = 4_194_304
_GIT_BINARY = "/usr/bin/git"


def _read_event(path: Path) -> dict[str, Any]:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 1 <= metadata.st_size <= _MAX_EVENT_BYTES:
            raise CiAttestationError("GitHub event payload is not a bounded regular file")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            raw = source.read(_MAX_EVENT_BYTES + 1)
    except OSError as exc:
        raise CiAttestationError("GitHub event payload is unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > _MAX_EVENT_BYTES:
        raise CiAttestationError("GitHub event payload exceeds the reviewed limit")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise CiAttestationError("GitHub event payload is invalid JSON") from exc
    if not isinstance(value, dict):
        raise CiAttestationError("GitHub event payload must be an object")
    return cast(dict[str, Any], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate GitHub event field")
        value[key] = item
    return value


def _git(repo: Path, *arguments: str) -> str:
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/nonexistent",
        "XDG_CONFIG_HOME": "/nonexistent",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    }
    try:
        result = subprocess.run(
            [_GIT_BINARY, "-c", "core.hooksPath=/dev/null", *arguments],
            cwd=repo,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CiAttestationError("Git checkout identity could not be read") from exc
    value = result.stdout.strip()
    if not value or "\n" in value:
        raise CiAttestationError("Git checkout identity is not singular")
    return value


def _checkout(repo: Path) -> GitCheckoutIdentity:
    oid = _git(repo, "rev-parse", "--verify", "HEAD")
    tree_oid = _git(repo, "rev-parse", "--verify", "HEAD^{tree}")
    parent_line = _git(repo, "rev-list", "--parents", "-n", "1", "HEAD")
    fields = parent_line.split()
    if not fields or fields[0] != oid:
        raise CiAttestationError("Git parent evidence does not match checkout HEAD")
    return GitCheckoutIdentity(oid=oid, tree_oid=tree_oid, parent_oids=tuple(fields[1:]))


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("attestation write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    except OSError as exc:
        raise CiAttestationError("checkout attestation could not be written safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _append_summary(value: dict[str, object]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    line = (
        "### Binnacle checkout attestation\n\n"
        f"- Kind: `{value['checkout_kind']}`\n"
        f"- Commit: `{value['checkout_oid']}`\n"
        f"- Tree: `{value['checkout_tree_oid']}`\n"
        f"- Parents: `{', '.join(cast(list[str], value['checkout_parent_oids']))}`\n"
    )
    try:
        with Path(summary_path).open("a", encoding="utf-8") as output:
            output.write(line)
    except OSError as exc:
        raise CiAttestationError("GitHub step summary is unavailable") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--event-path", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--collector-commit", default=None)
    parser.add_argument("--expected-collector-commit", default=None)
    parser.add_argument("--expected-collector-sha256", default=None)
    parser.add_argument("--allow-unbound", action="store_true")
    parser.add_argument("--created-at", default=None, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    event_path = args.event_path
    if event_path is None:
        raw_event_path = os.environ.get("GITHUB_EVENT_PATH")
        if not raw_event_path:
            print("Checkout attestation failed: GITHUB_EVENT_PATH is missing", file=sys.stderr)
            return 2
        event_path = Path(raw_event_path)
    try:
        created_at = (
            datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
            if args.created_at
            else None
        )
        collector_commit_oid = args.collector_commit or _git(
            ROOT,
            "rev-parse",
            "--verify",
            "HEAD",
        )
        collector_sha256 = ci_attestation_collector_sha256(ROOT)
        if (
            args.expected_collector_commit is not None
            and collector_commit_oid != args.expected_collector_commit
        ):
            raise CiAttestationError("collector commit differs from the reviewed identity")
        if (
            args.expected_collector_sha256 is not None
            and collector_sha256 != args.expected_collector_sha256
        ):
            raise CiAttestationError("collector bundle differs from the reviewed identity")
        value = build_ci_checkout_attestation(
            event=_read_event(event_path),
            environment=os.environ,
            checkout=_checkout(args.repo.resolve()),
            collector_commit_oid=collector_commit_oid,
            collector_sha256=collector_sha256,
            job_name=args.job_name,
            created_at=created_at,
        )
        payload = canonical_json_bytes(value) + b"\n"
        _write_new(args.output, payload)
        _append_summary(value)
    except (CiAttestationError, OSError, ValueError) as exc:
        print(f"Checkout attestation failed: {exc}", file=sys.stderr)
        return 2
    print(payload.decode("utf-8").rstrip())
    if not args.allow_unbound and not ci_attestation_is_bound(value):
        print("Checkout attestation is unbound; refusing CI success", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
