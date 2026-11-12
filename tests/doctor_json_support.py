"""Read the ``startup`` rows of ``binnacle doctor --json`` output in tests."""

import json


def startup_statuses(text: str) -> list[str]:
    rows = json.loads(text)["checks"]
    return [row["status"] for row in rows if row.get("group") == "startup"]


def startup_clean(text: str) -> bool:
    """A startup row exists and none fails: the deploy gate's doctor can pass."""
    statuses = startup_statuses(text)
    return bool(statuses) and "fail" not in statuses
