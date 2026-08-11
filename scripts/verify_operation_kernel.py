#!/usr/bin/env python3
"""Read-only local verification of the Phase 4 durable-operation kernel."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path

from binnacle.adapters.sqlite.engine import DatabaseRuntimeSettings
from binnacle.adapters.sqlite.migrations import upgrade_database
from binnacle.adapters.verification import (
    KernelVerificationPaths,
    verify_operation_kernel_read_only,
)
from binnacle.composition import KernelCompositionPaths, compose_operation_kernel
from binnacle.config import BinnacleSettings, load_settings


async def _verify(
    config: Path | None, *, paths: KernelVerificationPaths | None = None
) -> dict[str, object]:
    settings = load_settings(config_path=config)
    project_root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (project_root / "schemas/audit/audit-event.schema.json").read_text(encoding="utf-8")
    )
    if not isinstance(schema, dict):
        raise RuntimeError("audit schema is not an object")
    selected = paths or KernelVerificationPaths(
        settings.database.path,
        settings.audit.directory,
        settings.payload.directory,
        Path("/run/binnacle"),
    )
    report = await verify_operation_kernel_read_only(
        paths=selected,
        audit_schema=schema,
        busy_timeout_ms=settings.database.busy_timeout_ms,
        wal_autocheckpoint_pages=settings.database.wal_autocheckpoint_pages,
    )
    return report.as_dict()


async def _verify_temporary(root: Path) -> dict[str, object]:
    """Create an isolated CI fixture, then exercise the same read-only verifier."""

    project_root = Path(__file__).resolve().parents[1]
    paths = KernelVerificationPaths(
        root / "state/binnacle.db",
        root / "audit",
        root / "results",
        root / "run",
    )
    paths.database.parent.mkdir(parents=True)
    upgrade_database(
        DatabaseRuntimeSettings(paths.database, paths.runtime, verify_runtime_directory=False),
        project_root=project_root,
    )
    kernel = await compose_operation_kernel(
        settings=BinnacleSettings(),
        project_root=project_root,
        paths=KernelCompositionPaths(
            paths.database,
            paths.audit,
            paths.payload,
            paths.runtime,
            verify_runtime_directory=False,
        ),
    )
    await kernel.close()
    return await _verify(None, paths=paths)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify migrated SQLite, audit, obligation, payload, and gate state."
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--temporary",
        action="store_true",
        help="Build and verify an isolated temporary kernel fixture for CI.",
    )
    parser.add_argument("--output", choices=("human", "json"), default="human")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.temporary and args.config is not None:
            raise ValueError("--temporary and --config are mutually exclusive")
        if args.temporary:
            with tempfile.TemporaryDirectory(prefix="binnacle-kernel-verify-") as temporary:
                result = asyncio.run(_verify_temporary(Path(temporary)))
        else:
            result = asyncio.run(_verify(args.config))
    except Exception as exc:  # noqa: BLE001 - avoid exposing protected paths or contents.
        if args.output == "json":
            print(json.dumps({"status": "fail", "error_type": type(exc).__name__}))
        else:
            print(f"operation kernel verification failed: {type(exc).__name__}")
        return 1
    if args.output == "json":
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"status={result['status']} availability={result['availability']} "
            f"audit_sequence={result['audit_sequence']} "
            f"audit_obligations={result['audit_obligation_count']}"
        )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
