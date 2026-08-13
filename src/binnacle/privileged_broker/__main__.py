"""Entrypoint for the independently installed privileged broker artifact."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from binnacle.privileged_broker.config import DEFAULT_PRIVILEGED_CONFIG_PATH
from binnacle.privileged_broker.runtime import run_privileged_broker_service


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Binnacle privileged broker")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_PRIVILEGED_CONFIG_PATH,
        help="exact protected broker configuration path",
    )
    arguments = parser.parse_args(argv)
    try:
        asyncio.run(run_privileged_broker_service(arguments.config))
    except Exception as exc:  # noqa: BLE001 - root service output must not disclose values.
        print(f"Privileged broker failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main().
    raise SystemExit(main())
