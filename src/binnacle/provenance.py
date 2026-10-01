"""Runtime package and source-revision provenance.

The distribution version answers which released package version this is.
The source revision answers which checkout commit this process is running.
Binnacle currently deploys from a Git checkout, so both are useful and neither
should be overloaded to mean the other.
"""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DIST_NAME = "binnacle-mcp"


@dataclass(frozen=True, slots=True)
class Provenance:
    package_version: str
    revision: str


def package_version() -> str:
    """Installed distribution version, or ? when metadata is unavailable."""

    try:
        return importlib.metadata.version(DIST_NAME)
    except importlib.metadata.PackageNotFoundError:
        return "?"


def source_root() -> Path | None:
    """Return the repository root for a src-layout checkout, if present."""

    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "pyproject.toml").is_file() and (candidate / ".git").exists():
        return candidate
    return None


def _clean_git_env(git: str) -> dict[str, str]:
    """Drop repository-local Git variables before inspecting another checkout."""

    env = os.environ.copy()
    proc = subprocess.run(
        [git, "rev-parse", "--local-env-vars"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=3,
    )
    if proc.returncode == 0:
        for name in proc.stdout.splitlines():
            env.pop(name, None)
    return env


def source_revision(root: Path | None = None) -> str:
    """Short Git revision, with +dirty for tracked checkout changes.

    Untracked files are deliberately ignored: development notes or other
    untracked artifacts do not change the code revision that the services run.
    Non-checkout installations report installed.
    """

    root = source_root() if root is None else root.resolve()
    if root is None or not (root / ".git").exists():
        return "installed"

    git = shutil.which("git")
    if git is None:
        return "unknown"
    env = _clean_git_env(git)

    try:
        head = subprocess.run(
            [git, "-C", str(root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=3,
        )
        if head.returncode != 0:
            return "unknown"
        sha = head.stdout.strip()
        if len(sha) < 12:
            return "unknown"

        status = subprocess.run(
            [
                git,
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"

    dirty = status.returncode == 0 and bool(status.stdout.strip())
    return f"{sha[:12]}{'+dirty' if dirty else ''}"


def runtime_provenance() -> Provenance:
    return Provenance(package_version=package_version(), revision=source_revision())
