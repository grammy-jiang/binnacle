#!/usr/bin/env python3
"""Upgrade Binnacle resource-job JSONL history from schema v1 to v2."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

from binnacle import job_resource_history

START_RE = re.compile(
    r"event=job_start job_id=(?P<job>[0-9a-f]{12}).*? call=(?P<call>\S+) owner="
)


def _spool_calls(jobs_dir: Path) -> dict[str, str]:
    calls: dict[str, str] = {}
    for meta_path in jobs_dir.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            continue
        call = meta.get("call_id")
        if isinstance(call, str) and call and call != "-":
            calls[meta_path.parent.name] = call
    return calls


def _journal_calls(unit: str, since: float | None) -> dict[str, str]:
    argv = ["journalctl", "--user", "-u", unit, "--no-pager", "-o", "cat"]
    if since is not None:
        argv += ["--since", f"@{max(0.0, since - 60.0):.3f}"]
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {}
    calls: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        match = START_RE.search(line)
        if match and match.group("call") != "-":
            calls[match.group("job")] = match.group("call")
    return calls


def _load(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"non-object row in {path}")
            rows.append(row)
    return rows


def migrate(root: Path, jobs_dir: Path, unit: str, *, dry_run: bool) -> dict[str, int]:
    files = sorted(root.glob("????-??-??.jsonl"))
    loaded = [(path, _load(path)) for path in files]
    all_rows = [row for _, rows in loaded for row in rows]
    starts = [
        float(row["started_at"])
        for row in all_rows
        if isinstance(row.get("started_at"), (int, float))
    ]
    calls = _journal_calls(unit, min(starts) if starts else None)
    calls.update(_spool_calls(jobs_dir))

    changed = unresolved = total = 0
    stamp = time.strftime("%Y%m%dT%H%M%S")
    for path, rows in loaded:
        upgraded: list[dict] = []
        file_changed = False
        for row in rows:
            total += 1
            call = calls.get(str(row.get("job_id")))
            new = job_resource_history.upgrade_row(row, call_id=call)
            unresolved += int(new.get("call_id") is None)
            row_changed = new != row
            changed += int(row_changed)
            file_changed = file_changed or row_changed
            upgraded.append(new)
        if not file_changed:
            continue
        if dry_run:
            continue
        backup = path.with_name(f"{path.name}.v1-backup-{stamp}")
        shutil.copy2(path, backup)
        mode = stat.S_IMODE(path.stat().st_mode)
        temp = path.with_name(f".{path.name}.v2-{os.getpid()}.tmp")
        with temp.open("w", encoding="utf-8") as out:
            for row in upgraded:
                out.write(
                    json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n"
                )
            out.flush()
            os.fsync(out.fileno())
        temp.chmod(mode)
        os.replace(temp, path)
    return {
        "files": len(files),
        "rows": total,
        "changed": changed,
        "unresolved_call_ids": unresolved,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("~/.local/state/binnacle/resource-jobs").expanduser(),
    )
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        default=Path("~/.local/state/binnacle/jobs").expanduser(),
    )
    parser.add_argument("--unit", default="binnacle-jobs.service")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            migrate(args.root, args.jobs_dir, args.unit, dry_run=args.dry_run), indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
