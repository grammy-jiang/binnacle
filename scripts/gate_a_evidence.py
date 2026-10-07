"""Evidence binding helpers for the Gate A preparation report."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any


def build_payload(
    cells: Sequence[Any],
    *,
    candidate: str | None,
    observed_at: str | None = None,
) -> dict:
    """Bind every reported cell to one exact source snapshot."""

    stamp = (
        datetime.now(timezone.utc).isoformat() if observed_at is None else observed_at
    )
    return {
        "schema_version": 1,
        "kind": "gate-a-preparation-report",
        "candidate": candidate,
        "observed_at": stamp,
        "cells": [
            {
                "id": cell.id,
                "status": cell.status,
                "detail": cell.detail,
                "evidence": cell.evidence,
                "candidate": candidate,
                "observed_at": stamp,
            }
            for cell in cells
        ],
        "summary": {
            "pass": sum(cell.status == "PASS" for cell in cells),
            "fail": sum(cell.status == "FAIL" for cell in cells),
            "pending": sum(cell.status == "PENDING" for cell in cells),
        },
    }
