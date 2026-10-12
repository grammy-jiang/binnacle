"""list_files glob mode — recursive `rg --files` match, newest first.

Spec: docs/tools/list_files.md. Split out of tools/list_files.py
behavior-neutrally (r6 W3 SP1, FILES-FOLLOWUP-list-files-split); the tool
module keeps the r6 names _glob_entries and _glob_mode importable. Uses the
system ripgrep on purpose: bundled jemalloc builds abort on this Pi's 16 KB
kernel pages (Copilot lesson).
"""

import errno
import os
import stat
import subprocess
from pathlib import Path

from fastmcp.tools.base import ToolResult

from binnacle.config import get_settings
from binnacle.errors import CodedToolError
from binnacle.features.files.paths import full_match
from binnacle.features.search.fd_chain import EXHAUSTED, DirectoryChain
from binnacle.features.search.rg_env import NO_CONFIG, rg_env


def is_shortage(exc: OSError) -> bool:
    """EMFILE or ENFILE: search_text's descriptor-shortage set (fd_chain)."""
    return exc.errno in EXHAUSTED


def descriptor_shortage(task: str, advice: str) -> CodedToolError:
    """search_text's refusal for EMFILE/ENFILE, worded for list_files.

    One policy with search_text (SRC-W2-04, SD-79): a descriptor shortage
    is not evidence about a path, so nothing is omitted or kept unchecked.
    """
    return CodedToolError(
        "too_many_open_files",
        f"list_files could not {task}: the server has too many open files. {advice}",
    )


def glob_entries(root: Path, lines: list[str]) -> list[dict]:
    """Size each listed file by ONE no-follow lstat (r6 W2 X3c-a3, SD-78).

    rg lists by path string and never lists a symlink. A line that is
    absolute or has a '..' component is rejected: rg --files below root
    prints neither. Every component from '/' to the file's directory is
    opened no-follow (O_PATH on Linux); only the chain of the current path
    is open (fd_chain, a stack bounded by the path depth). The file is
    lstat-ed relative to that descriptor. A path whose directory is no
    longer a directory (swapped for a symlink or a file) or whose final
    component is now a symlink is omitted: no outside object is typed or
    sized. A final component that is now a directory, a FIFO or any other
    non-regular object is omitted too: an entry typed 'file' is a regular
    file, as in search_text_verify.is_regular (SRC-W2-12). Any other
    failure, including a descriptor shortage, keeps the entry without
    bytes, as r6 did when p.stat() failed.
    """
    entries: list[dict] = []
    # Plain string splitting: PurePath costs more than the walk itself. The
    # components and the reported path equal those of root / line.
    top = [part for part in str(root).split("/") if part]
    with DirectoryChain() as chain:
        for line in lines:
            below = [part for part in line.split("/") if part not in ("", ".")]
            if line.startswith("/") or ".." in below or not below:
                continue
            parts = top + below
            entry: dict = {"path": "/" + "/".join(parts), "type": "file"}
            try:
                info = os.lstat(below[-1], dir_fd=chain.directory(tuple(parts[:-1])))
            except OSError as exc:
                if exc.errno in (errno.ENOTDIR, errno.ELOOP):
                    continue
                entries.append(entry)
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            entry["bytes"] = info.st_size
            entries.append(entry)
    return entries


def glob_mode(
    root: Path,
    glob: str,
    max_results: int,
    include_hidden: bool,
    *,
    rg_bin: str | None = None,
    timeout_s: int | None = None,
) -> ToolResult:
    if rg_bin is None or timeout_s is None:
        defaults = get_settings()
        rg_bin = defaults.rg_bin if rg_bin is None else rg_bin
        timeout_s = defaults.list_files.rg_timeout_s if timeout_s is None else timeout_s
    # rg only walks (gitignore/hidden respected); the glob filter runs in
    # Python: rg's --glob "always overrides any other ignore logic", so a
    # positive --glob would whitelist gitignored files (found by the gate).
    pattern = glob if "/" in glob else f"**/{glob}"
    cmd = [rg_bin, NO_CONFIG, "--files", "--sortr", "modified"]
    if include_hidden:
        cmd += ["--hidden", "--glob", "!**/.git/**"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=rg_env(),
        )
    except FileNotFoundError as exc:
        raise CodedToolError(
            "rg_missing",
            "ripgrep (rg) is not available on this system; "
            "use run_command (find, ls) instead.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CodedToolError(
            "rg_timeout",
            f"Glob search timed out after {timeout_s} s in {root}. "
            f"Narrow the glob or point path at a subdirectory.",
        ) from exc
    if proc.returncode not in (0, 1):
        stderr = proc.stderr.strip()[-300:]
        raise CodedToolError(
            "rg_failed",
            f"ripgrep failed in {root}: {stderr or 'unknown error'}. "
            f"Use run_command (find, ls) as a fallback.",
        )

    try:
        lines = [
            line
            for line in proc.stdout.splitlines()
            if line and full_match(line, pattern)
        ]
    except ValueError as e:
        raise CodedToolError(
            "invalid_glob", f"Invalid glob pattern {glob!r}: {e}"
        ) from e
    truncated = len(lines) > max_results
    entries = glob_entries(root, lines[:max_results])
    payload = {
        "path": str(root),
        "mode": "glob",
        "entries": entries,
        "count": len(entries),
        "truncated": truncated,
    }
    if not entries:
        payload["note"] = (
            f"No files match {glob!r} under {root} "
            f"(gitignored and hidden files are skipped by default)."
        )
        summary = f"No files match {glob!r} under {root}."
    elif truncated:
        payload["note"] = (
            f"Showing first {max_results} of {len(lines)} matches; "
            f"narrow the glob or raise max_results."
        )
        summary = (
            f"Found {len(lines)} files matching {glob!r} under {root}; "
            f"showing newest {max_results}."
        )
    else:
        summary = (
            f"Found {len(entries)} files matching {glob!r} under {root} (newest first)."
        )
    return ToolResult(content=summary, structured_content=payload)
