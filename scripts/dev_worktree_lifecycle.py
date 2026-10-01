"""Transactional creation and guarded cleanup of Git worktrees."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from scripts.dev_common import Runner, Which
from scripts.dev_worktrees import worktree_inventory

Bootstrap = Callable[[Path], int]


def create_worktree(
    root: Path,
    *,
    path: Path,
    branch: str,
    base: str,
    run: Runner,
    which: Which,
    bootstrap: Bootstrap,
) -> tuple[bool, str]:
    """Create a new worktree and bootstrap it as one transaction."""

    root = root.resolve()
    target = path.expanduser().resolve()
    git = which("git")
    if git is None:
        return False, "git is not on PATH"
    if target == root:
        return False, "target path is the current worktree"
    if target.is_relative_to(root):
        return False, "target path must be outside the current worktree"
    if target.exists():
        return False, f"target path already exists: {target}"

    valid = run((git, "check-ref-format", "--branch", branch), root)
    if valid.returncode:
        return False, valid.output.strip() or f"invalid branch name: {branch}"

    branch_refs = (
        ("local branch", f"refs/heads/{branch}"),
        ("origin branch", f"refs/remotes/origin/{branch}"),
    )
    for label, ref in branch_refs:
        existing = run(
            (git, "show-ref", "--verify", "--quiet", ref),
            root,
        )
        if existing.returncode == 0:
            return False, f"{label} already exists: {branch}"
        if existing.returncode not in (1,):
            return False, existing.output.strip() or f"could not inspect {label}"

    resolved = run((git, "rev-parse", "--verify", f"{base}^{{commit}}"), root)
    if resolved.returncode:
        return False, resolved.output.strip() or f"unknown base: {base}"
    base_sha = resolved.output.strip().splitlines()[-1]

    added = run(
        (git, "worktree", "add", "-b", branch, str(target), base),
        root,
    )
    if added.returncode:
        return False, added.output.strip() or "git worktree add failed"

    bootstrap_rc = bootstrap(target)
    if bootstrap_rc == 0:
        return True, f"created {target} on {branch} from {base} and bootstrapped it"

    status = run((git, "-C", str(target), "status", "--porcelain"), root)
    head = run((git, "-C", str(target), "rev-parse", "HEAD"), root)
    safe_to_rollback = (
        status.returncode == 0
        and not status.output.strip()
        and head.returncode == 0
        and head.output.strip() == base_sha
    )
    if not safe_to_rollback:
        return (
            False,
            f"bootstrap {bootstrap_rc} failed; preserved changed worktree {target}",
        )

    removed = run(
        (git, "worktree", "remove", "--force", str(target)),
        root,
    )
    if removed.returncode:
        return (
            False,
            f"bootstrap {bootstrap_rc} failed; rollback failed: {removed.output.strip()}",
        )
    deleted = run((git, "branch", "-D", branch), root)
    if deleted.returncode:
        return (
            False,
            f"bootstrap {bootstrap_rc} failed; branch cleanup failed: {deleted.output.strip()}",
        )
    return (
        False,
        f"bootstrap {bootstrap_rc} failed; worktree and branch were rolled back",
    )


def cleanup_worktree(
    root: Path,
    *,
    path: Path,
    delete_branch: bool,
    apply: bool,
    run: Runner,
    which: Which,
) -> tuple[bool, str]:
    """Plan or perform a guarded worktree cleanup."""

    root = root.resolve()
    target = path.expanduser().resolve()
    if target == root:
        return False, "refusing to remove the current worktree"

    try:
        items = worktree_inventory(root, run=run, which=which)
    except RuntimeError as exc:
        return False, str(exc)

    item = next(
        (candidate for candidate in items if Path(candidate.path).resolve() == target),
        None,
    )
    if item is None:
        return False, f"not a registered worktree: {target}"

    blockers: list[str] = []
    if item.bare:
        blockers.append("bare worktree")
    if item.locked:
        blockers.append("locked")
    if item.dirty_changes is None:
        blockers.append("working-tree state unknown")
    elif item.dirty_changes:
        blockers.append(f"dirty ({item.dirty_changes} change(s))")
    if item.merged_to_master is not True:
        blockers.append("HEAD is not merged into master")
    if item.branch in {"master", "proof-of-concept"}:
        blockers.append(f"protected local branch {item.branch}")

    if blockers:
        return False, f"refusing cleanup of {target}: " + ", ".join(blockers)

    branch = None if item.branch == "(detached)" else item.branch
    branch_note = f" and local branch {branch}" if delete_branch and branch else ""
    if not apply:
        return (
            True,
            f"safe to remove {target}{branch_note}; rerun with --apply",
        )

    git = which("git")
    if git is None:
        return False, "git is not on PATH"
    removed = run((git, "worktree", "remove", str(target)), root)
    if removed.returncode:
        return False, removed.output.strip() or "git worktree remove failed"

    if delete_branch and branch:
        deleted = run((git, "branch", "-d", branch), root)
        if deleted.returncode:
            return (
                False,
                f"worktree removed; branch {branch} preserved: {deleted.output.strip()}",
            )
    return True, f"removed {target}{branch_note}"
