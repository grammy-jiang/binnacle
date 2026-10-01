"""Read-only Git worktree inventory for repository development tooling."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from scripts.dev_common import Runner, Which


@dataclasses.dataclass(frozen=True)
class WorktreeBase:
    path: Path
    head: str | None
    branch: str | None
    locked: str | None = None
    prunable: str | None = None
    bare: bool = False


@dataclasses.dataclass(frozen=True)
class WorktreeStatus:
    path: str
    branch: str
    head: str
    upstream: str
    ahead: int | None
    behind: int | None
    merged_to_master: bool | None
    dirty_changes: int | None
    venv: bool
    lock: str
    locked: str | None
    flags: tuple[str, ...]
    bare: bool = False


def parse_worktree_porcelain(text: str) -> list[WorktreeBase]:
    worktrees: list[WorktreeBase] = []
    for block in (part for part in text.strip().split("\n\n") if part.strip()):
        values: dict[str, str] = {}
        flags: set[str] = set()
        for line in block.splitlines():
            key, separator, value = line.partition(" ")
            if separator:
                values[key] = value
            else:
                flags.add(key)
        if "worktree" not in values:
            continue
        bare = "bare" in flags
        if "HEAD" not in values and not bare:
            continue

        branch = values.get("branch")
        if branch and branch.startswith("refs/heads/"):
            branch = branch.removeprefix("refs/heads/")
        if "detached" in flags:
            branch = None

        locked = values.get("locked")
        if "locked" in flags:
            locked = "(no reason)"
        prunable = values.get("prunable")
        if "prunable" in flags:
            prunable = "(no reason)"

        worktrees.append(
            WorktreeBase(
                path=Path(values["worktree"]),
                head=values.get("HEAD"),
                branch=branch,
                locked=locked,
                prunable=prunable,
                bare=bare,
            )
        )
    return worktrees


def primary_worktree_integrity(
    root: Path,
    *,
    git: str,
    run: Runner,
) -> tuple[bool, str]:
    """Check that Git still registers the repository's primary checkout normally."""

    listed = run((git, "worktree", "list", "--porcelain"), root)
    if listed.returncode:
        return False, listed.output.strip() or "git worktree list failed"

    items = parse_worktree_porcelain(listed.output)
    if not items:
        return False, "no registered Git worktrees"

    primary = items[0]
    if primary.bare:
        git_dir = primary.path / ".git"
        detail = (
            f"{primary.path} is registered bare; repair after verification with: "
            f"git --git-dir={git_dir} config core.bare false"
        )
        return False, detail
    return True, str(primary.path)


def worktree_health(
    *,
    branch: str | None,
    merged_to_master: bool | None,
    dirty_changes: int | None,
    upstream: str,
    venv: bool,
    lock: str,
    locked: str | None,
    bare: bool = False,
) -> tuple[str, ...]:
    flags: list[str] = []
    if bare:
        flags.append("bare")
    if locked:
        flags.append("locked")
    if dirty_changes is None:
        flags.append("state-unknown")
    elif dirty_changes:
        flags.append("dirty")
    if upstream == "gone":
        flags.append("upstream-gone")
    if merged_to_master and branch not in (None, "master"):
        flags.append("merged")
    if not venv:
        flags.append("no-venv")
    if lock == "drift":
        flags.append("lock-drift")
    return tuple(flags or ("ok",))


def _upstream(
    item: WorktreeBase,
    *,
    root: Path,
    git: str,
    run: Runner,
) -> tuple[str, int | None, int | None]:
    if item.bare or item.branch is None:
        return "-", None, None

    path = item.path
    configured_remote = run(
        (
            git,
            "-C",
            str(path),
            "config",
            "--get",
            f"branch.{item.branch}.remote",
        ),
        root,
    )
    configured_merge = run(
        (
            git,
            "-C",
            str(path),
            "config",
            "--get",
            f"branch.{item.branch}.merge",
        ),
        root,
    )
    resolved = run(
        (
            git,
            "-C",
            str(path),
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        ),
        root,
    )
    if resolved.returncode != 0 or not resolved.output.strip():
        configured = (
            configured_remote.returncode == 0 and configured_merge.returncode == 0
        )
        return ("gone" if configured else "-"), None, None

    upstream = resolved.output.strip().splitlines()[-1]
    counts = run(
        (
            git,
            "-C",
            str(path),
            "rev-list",
            "--left-right",
            "--count",
            "HEAD...@{upstream}",
        ),
        root,
    )
    if counts.returncode:
        return upstream, None, None
    parts = counts.output.split()
    if len(parts) < 2:
        return upstream, None, None
    return upstream, int(parts[0]), int(parts[1])


def inspect_worktree(
    item: WorktreeBase,
    *,
    root: Path,
    git: str,
    uv: str | None,
    run: Runner,
) -> WorktreeStatus:
    path = item.path
    if item.bare:
        dirty_changes = None
        upstream, ahead, behind = "-", None, None
        merged_to_master = None
    else:
        status = run((git, "-C", str(path), "status", "--porcelain"), root)
        dirty_changes = (
            len([line for line in status.output.splitlines() if line.strip()])
            if status.returncode == 0
            else None
        )
        upstream, ahead, behind = _upstream(
            item,
            root=root,
            git=git,
            run=run,
        )

        merged_result = run(
            (
                git,
                "-C",
                str(path),
                "merge-base",
                "--is-ancestor",
                "HEAD",
                "master",
            ),
            root,
        )
        merged_to_master = (
            True
            if merged_result.returncode == 0
            else False
            if merged_result.returncode == 1
            else None
        )

    lock = "unknown"
    if (
        uv is not None
        and (path / "pyproject.toml").exists()
        and (path / "uv.lock").exists()
    ):
        lock_result = run((uv, "lock", "--check", "--offline"), path)
        lock = "current" if lock_result.returncode == 0 else "drift"

    venv = (path / ".venv" / "bin" / "python").exists()
    flags = worktree_health(
        branch=item.branch,
        merged_to_master=merged_to_master,
        dirty_changes=dirty_changes,
        upstream=upstream,
        venv=venv,
        lock=lock,
        locked=item.locked,
        bare=item.bare,
    )
    return WorktreeStatus(
        path=str(path),
        branch="(bare)" if item.bare else item.branch or "(detached)",
        head=item.head[:12] if item.head else "(none)",
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        merged_to_master=merged_to_master,
        dirty_changes=dirty_changes,
        venv=venv,
        lock=lock,
        locked=item.locked,
        flags=flags,
        bare=item.bare,
    )


def worktree_inventory(
    root: Path,
    *,
    run: Runner,
    which: Which,
) -> list[WorktreeStatus]:
    root = root.resolve()
    git = which("git")
    if git is None:
        raise RuntimeError("git is not on PATH")

    listed = run((git, "worktree", "list", "--porcelain"), root)
    if listed.returncode:
        raise RuntimeError(listed.output.strip() or "git worktree list failed")

    uv = which("uv")
    return [
        inspect_worktree(
            item,
            root=root,
            git=git,
            uv=uv,
            run=run,
        )
        for item in parse_worktree_porcelain(listed.output)
    ]
