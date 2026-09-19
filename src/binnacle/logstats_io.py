"""Journal IO for usage statistics."""

import subprocess


def fetch_journal(unit: str, since: str, until: str | None = None) -> str:
    cmd = [
        "journalctl",
        "--user",
        "-u",
        unit,
        "--since",
        since,
        "-o",
        "cat",
        "--no-pager",
    ]
    if until:
        cmd += ["--until", until]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"journalctl failed: {proc.stderr.strip()[:200]}")
    return proc.stdout
