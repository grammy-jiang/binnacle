"""Fetch tracking refs and safely fast-forward under the Pi session lock."""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dev_branch_sync_core import State, SyncCore, SyncError


class Sync(SyncCore):
    """Inspect and fast-forward using the guarded Git operations."""

    def snapshot(self, target: str, published: str | None) -> State:
        inventory = self.validate_refs()
        head = self.git(self.wt, "rev-parse", "HEAD").strip()
        relation, effective = "not-observed-on-selected-remote", head
        if published:
            if head == published:
                relation = "current"
            elif self.ancestor(head, published):
                relation, effective = "behind", published
            else:
                relation = (
                    "local-ahead" if self.ancestor(published, head) else "diverged"
                )
        destination = effective if self.ancestor(target, effective) else target
        branch = self.git(self.wt, "symbolic-ref", "-q", "HEAD", ok=(0, 1)).strip()
        base = self.sha(f"refs/heads/{self.base}")
        reasons = []
        markers = [
            "rebase-merge",
            "rebase-apply",
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "REVERT_HEAD",
            "sequencer",
            "BISECT_LOG",
        ]
        progress = any(self.gitpath(self.wt, "--git-path", m).exists() for m in markers)
        dirty = self.git(
            self.wt,
            "status",
            *["--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"],
        )
        if dirty or progress:
            reasons.append("Dirty or operation-in-progress worktree; resolve manually")
        if branch != f"refs/heads/{self.branch}":
            reasons.append("Selected branch is no longer checked out")
        if base and not self.ancestor(base, target):
            reasons.append("Local base non-fast-forward refused")
        for path, fields, branches in inventory:
            unavailable = not Path(path).is_dir() or "bare" in fields
            if unavailable or any(f.startswith("prunable") for f in fields):
                reasons.append(f"Unknown/prunable worktree ownership: {path}")
            if base != target and f"refs/heads/{self.base}" in branches:
                reasons.append(f"Local base is checked out: {path}")
            if Path(path).resolve() == self.wt:
                if any(f == "locked" or f.startswith("locked ") for f in fields):
                    reasons.append(f"Locked worktree: {path}")
            elif f"refs/heads/{self.branch}" in branches:
                reasons.append(f"Feature checked out elsewhere: {path}")
        if not self.ancestor(head, destination) or (
            published and not self.ancestor(published, destination)
        ):
            reasons.append(
                f"manual-rebase-required: review feature {head} against base {target}; no automatic rewrite"
            )
        for config_path in (self.repo, self.wt):
            if any(
                self.git(
                    config_path,
                    "config",
                    "--get-all",
                    f"branch.{self.branch}.mergeOptions",
                    ok=(0, 1),
                ).splitlines()
            ):
                reasons.append(
                    "Nonempty feature mergeOptions refused; remove before sync"
                )
        if errors := self.publication_errors():
            reasons.append(f"Ambiguous publication configuration: {errors}")
        collisions = self.ignored_collisions(destination) if head != destination else ()
        if collisions:
            reasons.append(f"Ignored paths collide with tracked paths: {collisions}")
        return State(
            head,
            target,
            base,
            self.sha(self.tracking),
            self.sha(self.feature_tracking),
            relation,
            destination,
            tuple(reasons),
        )

    def verify(self, heads: dict[str, str], state: State) -> None:
        if self.remote_heads() != heads:
            raise SyncError("Remote base/feature changed since fetch; rerun status")
        published = heads.get(f"refs/heads/{self.branch}")
        if self.snapshot(state.target_sha, published) != state:
            raise SyncError("Local state changed since inspection; rerun status")

    def run(self, apply: bool, report: dict[str, object], timeout: float = 12) -> int:
        if not 0 <= timeout <= 60:
            raise SyncError("Lock timeout must be between 0 and 60 seconds")
        # Persistent inode: never unlink/steal a lock held or awaited by a peer.
        with (self.common / "binnacle-dev-sync.lock").open("a") as lock:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise SyncError(
                            "Timed out waiting for cooperative sync lock"
                        ) from None
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            return self.synchronize(apply, report)

    def synchronize(self, apply: bool, report: dict[str, object]) -> int:
        self.validate_refs()
        heads = self.remote_heads()
        target = heads[f"refs/heads/{self.base}"]
        published = heads.get(f"refs/heads/{self.branch}")
        report.update(published_feature_sha=published, target_sha=target)
        self.fetch_heads(heads)
        before = self.snapshot(target, published)
        report["before"] = asdict(before)
        self.verify(heads, before)
        if before.tracking_sha != target or before.published_tracking_sha != published:
            raise SyncError("Tracking refs differ from advertised SHAs; rerun status")
        report["refusals"] = before.refusals
        if before.refusals:
            report["result"] = "refused"
            return 2
        needed = (
            before.local_base_sha != target
        ) or before.feature_sha != before.feature_target_sha
        current = (
            "local-ahead" if before.publication_state == "local-ahead" else "current"
        )
        if not apply:
            report["result"] = "needs-sync" if needed else current
            return int(report["result"] != "current")
        actions: list[str] = []
        report["actions"] = actions
        primary: BaseException | None = None
        try:
            self.verify(heads, before)
            if before.local_base_sha != target:
                self.git(
                    self.repo,
                    *["update-ref", "--no-deref"],
                    f"refs/heads/{self.base}",
                    target,
                    before.local_base_sha or "",
                )
                actions.append("fast-forward-local-base")
            ready = self.snapshot(target, published)
            if ready.feature_sha != before.feature_sha or ready.refusals:
                raise SyncError("Worktree changed before feature synchronization")
            self.verify(heads, ready)
            if ready.feature_sha != ready.feature_target_sha:
                # Unsupported Git versions fail closed; never retry without guard.
                self.git(
                    self.wt,
                    *[
                        "merge",
                        "--ff-only",
                        "--no-squash",
                        "--no-autostash",
                        "--no-overwrite-ignore",
                    ],
                    ready.feature_target_sha,
                )
                actions.append("fast-forward-feature")
            after = self.snapshot(target, published)
            self.verify(heads, after)
            if (
                (after.local_base_sha != target)
                or after.tracking_sha != target
                or after.published_tracking_sha != published
                or after.publication_state in {"behind", "diverged"}
                or not self.ancestor(target, after.feature_sha)
                or after.refusals
            ):
                raise SyncError("Post-sync checks failed; inspect preserved state")
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                report["after"] = asdict(self.snapshot(target, published))
            except Exception as exc:
                if primary is None:
                    raise
                report["after_error"] = str(exc)
        report["result"] = "synced" if actions else current
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--base", default="master")
    parser.add_argument(
        "--session-lock-held",
        action="store_true",
        help="Attest supervising Pi holds exclusive mac-session lock across all writers",
    )
    parser.add_argument("--lock-timeout", type=float, default=12)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true", help="Update tracking refs only")
    args = parser.parse_args(argv)
    report: dict[str, object] = {
        "mode": "apply" if args.apply else "check",
        "branch": args.branch,
        "base": args.base,
        "remote": args.remote,
    }
    try:
        if not args.session_lock_held:
            raise SyncError(
                "Hold the external Pi mac-session lock across all writers and pass --session-lock-held"
            )
        code = Sync(args.repo, args.worktree, args.branch, args.remote, args.base).run(
            args.apply, report, args.lock_timeout
        )
    except (SyncError, OSError, subprocess.SubprocessError) as exc:
        report.update(result="error", error=str(exc))
        report["diagnostics"] = getattr(exc, "cleanup", [])
        code = 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
