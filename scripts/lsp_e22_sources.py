"""On-host project/document anchors for E2.2, without emitting any private text.

A nearby task document or matching task ID is a lead, never proof of the
original human request. Do not execute historic commands or modify repos.
"""

from __future__ import annotations

import collections
import datetime as dt
import os
import re
from pathlib import Path
from typing import Any

if __package__:
    from .lsp_e01_trace import _digest, _time
else:
    from lsp_e01_trace import _digest, _time

TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".rst", ".adoc"})
SKIP = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".next",
        "build",
        "dist",
        ".tox",
        ".pytest_cache",
        ".cache",
        "vendor",
        "target",
    }
)
MAX_DOCS_PER_REPO = 350
MAX_DOC_BYTES = 512 * 1024
DAYS_PREEXISTING = 7
TASK_REF = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:"
    r"[A-Z][A-Z0-9]{0,9}-[0-9]{2,8}(?:-[A-Z0-9]{1,20})?"
    r"|(?:P|E|R)[0-9]{1,3}(?:[.\-][0-9A-Z]{1,5}){1,3}"
    r"|#[0-9]{2,7}"
    r")(?![A-Za-z0-9_.-])"
)


def task_refs(value: str) -> frozenset[str]:
    """Potential IDs only; no raw substring ever leaves the originating host."""
    return frozenset(TASK_REF.findall(value))


def _explicit_project_path(value: Any, home: Path) -> Path | None:
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    expanded = Path(value).expanduser()
    if not expanded.is_absolute():
        return None
    # Explicit names only, not guesses from current working directory.
    try:
        path = expanded.resolve(strict=False)
        projects = (home / "Projects").resolve(strict=False)
        path.relative_to(projects)
    except (OSError, ValueError, RuntimeError):
        return None
    return path if path != projects else None


def _repo(path: Path, home: Path) -> Path | None:
    projects = (home / "Projects").resolve(strict=False)
    candidate = path if path.is_dir() else path.parent
    while candidate != projects and candidate != candidate.parent:
        try:
            candidate.relative_to(projects)
        except ValueError:
            return None
        if (candidate / ".git").exists():
            return candidate
        candidate = candidate.parent
    return None


def _case_input(args: Any, tool: str, home: Path) -> tuple[set[Path], set[str]]:
    if not isinstance(args, dict):
        return None, set()
    refs: set[str] = set()
    for key in ("command", "pattern"):
        value = args.get(key)
        if isinstance(value, str):
            refs.update(task_refs(value[:200_000]))
    repositories: set[Path] = set()
    for key in ("workdir", "path"):
        # A single call can reference different repos. Retain all explicit
        # candidates rather than privileging workdir over path.
        found = _explicit_project_path(args.get(key), home)
        if found is not None:
            repo = _repo(found, home)
            if repo is not None:
                repositories.add(repo)
    return repositories, refs


def inputs_by_call(
    capture_dir: Path,
    selected_calls: dict[tuple[str, str], Any],
    cutoff: dt.datetime,
    home: Path,
) -> tuple[dict, dict[str, int]]:
    """Safely recover only workspace anchors and potential literal task IDs."""
    anchored: dict = {}
    stats = collections.Counter()
    for file in sorted(capture_dir.glob("*.jsonl")):
        if file.is_symlink() or not file.is_file():
            stats["unreadable_capture_file"] += 1
            continue
        with file.open("rb") as stream:
            for line in stream:
                if not line.endswith(b"\n"):
                    stats["incomplete_capture_line"] += 1
                    continue
                try:
                    import json

                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    stats["malformed_capture_line"] += 1
                    continue
                if not isinstance(event, dict) or event.get("event") != "tool_call":
                    continue
                when = _time(event.get("timestamp"))
                if when is None or when >= cutoff:
                    continue
                corr = event.get("correlation")
                if not isinstance(corr, dict):
                    continue
                gen, identity = corr.get("server_gen"), corr.get("call")
                if not isinstance(gen, str) or not isinstance(identity, str):
                    stats["invalid_call_identity"] += 1
                    continue
                key = (gen, identity)
                call = selected_calls.get(key)
                if call is None:
                    continue
                args = event.get("arguments")
                try:
                    valid = _digest(args) == call.arguments_sha
                except ValueError:
                    valid = False
                if not valid:
                    stats["captured_arguments_inconsistent"] += 1
                    continue
                repositories, refs = _case_input(args, call.tool, home)
                if key in anchored:
                    stats["duplicate_input_events"] += 1
                    continue
                anchored[key] = {
                    "repositories": repositories,
                    "task_refs": refs,
                    "time": when.timestamp(),
                }
    return anchored, dict(stats)


def available_documents(repo: Path, as_of: float) -> tuple[int, set[str], dict]:
    """Read eligible project docs in place; only document count and IDs return."""
    if not repo.is_dir():
        return 0, set(), {"repository_unavailable": 1}
    window_start = as_of - DAYS_PREEXISTING * 86400
    counts = collections.Counter()
    refs: set[str] = set()
    docs = 0
    for d, folders, names in os.walk(repo, followlinks=False):
        folder = Path(d)
        if len(folder.relative_to(repo).parts) >= 5:
            folders[:] = []
        else:
            folders[:] = [name for name in folders if name not in SKIP]
        for name in sorted(names):
            if Path(name).suffix.lower() not in TEXT_SUFFIXES:
                continue
            path = folder / name
            try:
                if path.is_symlink():
                    counts["symlinked_source_skipped"] += 1
                    continue
                st = path.stat()
                if st.st_size > MAX_DOC_BYTES or st.st_mtime > as_of:
                    continue
                if st.st_mtime < window_start:
                    continue
                data = path.read_bytes()
            except OSError:
                counts["unreadable_document"] += 1
                continue
            docs += 1
            refs.update(task_refs(data.decode("utf-8", errors="replace")))
            if docs >= MAX_DOCS_PER_REPO:
                counts["document_scan_limit_reached"] += 1
                return docs, refs, dict(counts)
    return docs, refs, dict(counts)
