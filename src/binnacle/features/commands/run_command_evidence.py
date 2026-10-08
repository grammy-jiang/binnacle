"""Private full-command evidence for automatic-background policy review."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

EVIDENCE_DIR = Path.home() / ".local" / "state" / "binnacle" / "run-command-evidence"
_LOCK = threading.Lock()
log = logging.getLogger("binnacle.run_command_evidence")


def _day_path(root: Path, day: date) -> Path:
    return root / f"{day.isoformat()}.jsonl"


def _prune(root: Path, today: date, retention_days: int) -> None:
    cutoff = today - timedelta(days=max(1, retention_days) - 1)
    for path in root.glob("????-??-??.jsonl"):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day < cutoff:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue


def record_auto_match(
    *,
    retention_days: int,
    call_id: str,
    client: str | None,
    command: str,
    command_hash: str,
    policy_hash: str,
    behavior_hash: str,
    semantics_version: int,
    auto_warmup_s: float,
    rule_hash: str,
    match_start: int | None = None,
    match_end: int | None = None,
    root: Path = EVIDENCE_DIR,
    now: datetime | None = None,
) -> Path | None:
    """Append one private evidence row; disabled when retention is zero."""

    if retention_days <= 0:
        return None
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    row: dict[str, Any] = {
        "timestamp": timestamp.isoformat(),
        "call": call_id,
        "client": client,
        "command": command,
        "command_hash": command_hash,
        "command_chars": len(command),
        "policy_hash": policy_hash,
        "behavior_hash": behavior_hash,
        "semantics_version": semantics_version,
        "auto_warmup_s": auto_warmup_s,
        "rule_hash": rule_hash,
        "match_start": match_start,
        "match_end": match_end,
    }
    encoded = (
        json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    try:
        with _LOCK:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(root, 0o700)
            path = _day_path(root, timestamp.date())
            fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "ab") as stream:
                stream.write(encoded)
            _prune(root, timestamp.date(), retention_days)
        return path
    except OSError as exc:
        log.warning(
            "event=run_command_evidence_error call=%s behavior_hash=%s "
            "rule_hash=%s error_class=%s",
            call_id,
            behavior_hash,
            rule_hash,
            type(exc).__name__,
        )
        return None


def load_evidence(root: Path = EVIDENCE_DIR) -> list[dict[str, Any]]:
    """Load valid evidence rows in file/date order for local analysis."""

    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("????-??-??.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows
