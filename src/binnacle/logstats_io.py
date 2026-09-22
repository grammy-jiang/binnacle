"""Journal IO for usage statistics."""

import subprocess
from collections.abc import Sequence


def fetch_journal(
    unit: str | Sequence[str], since: str, until: str | None = None
) -> str:
    units = (unit,) if isinstance(unit, str) else tuple(unit)
    cmd = ["journalctl", "--user"]
    for name in units:
        cmd += ["-u", name]
    cmd += ["--since", since, "-o", "cat", "--no-pager"]
    if until:
        cmd += ["--until", until]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"journalctl failed: {proc.stderr.strip()[:200]}")
    return proc.stdout
