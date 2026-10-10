"""Git identity, ownership validation and guarded tracking-ref operations."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class SyncError(RuntimeError):
    """A Git failure or unsafe synchronization precondition."""


@dataclass(frozen=True)
class State:
    feature_sha: str
    target_sha: str
    local_base_sha: str | None
    tracking_sha: str | None
    published_tracking_sha: str | None
    publication_state: str
    feature_target_sha: str
    refusals: tuple[str, ...]


class SyncCore:
    """Shared Git operations and safety checks for branch synchronization."""

    def git_environment(self) -> dict[str, str]:
        """Reject config/namespace injection; drop hook-local repository overrides."""
        for key, value in os.environ.items():
            if key == "GIT_NAMESPACE" or (
                key.startswith("GIT_CONFIG")
                and (key, value)
                not in {
                    ("GIT_CONFIG_GLOBAL", os.devnull),
                    ("GIT_CONFIG_SYSTEM", os.devnull),
                    ("GIT_CONFIG_NOSYSTEM", "1"),
                }
            ):
                raise SyncError(f"Inherited namespace/config override refused: {key}")
        local = self.git(self.repo, "rev-parse", "--local-env-vars").splitlines()
        env = {key: value for key, value in os.environ.items() if key not in local}
        env.update(
            GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0"
        )
        return env

    def __init__(self, repo: Path, worktree: Path, branch: str, remote: str, base: str):
        self.repo, self.wt = repo.resolve(), worktree.resolve()
        self.branch, self.remote, self.base = branch, remote, base
        self.env = dict(os.environ)
        self.env = self.git_environment()
        for path in (self.repo, self.wt):
            top = self.git(path, "rev-parse", "--show-toplevel").strip()
            if Path(top).resolve() != path:
                raise SyncError(f"Expected a Git worktree root: {path}")
        common = [self.gitpath(p, "--git-common-dir") for p in (self.repo, self.wt)]
        if common[0] != common[1]:
            raise SyncError("Repo and worktree must have the same Git common directory")
        self.common = common[0]
        if any(name.startswith("-") for name in (branch, base)):
            raise SyncError("Branch names cannot start with '-'")
        if branch.casefold() in {base.casefold(), "master", "main", "proof-of-concept"}:
            raise SyncError("Select a development feature branch, not a protected base")
        remotes = self.git(self.repo, "remote").splitlines()
        if remote.startswith("-") or remote not in remotes:
            raise SyncError("Remote must name a configured Git remote")
        self.tracking = f"refs/remotes/{remote}/{base}"
        self.feature_tracking = f"refs/remotes/{remote}/{branch}"
        self.refs = [self.tracking, self.feature_tracking]
        self.refs.extend(f"refs/heads/{name}" for name in (base, branch))
        for ref in self.refs:
            self.git(self.repo, "check-ref-format", ref)
        self.validate_refs()
        self.url = self.git(self.repo, "remote", "get-url", remote)
        if self.sha(f"refs/heads/{branch}") is None:
            raise SyncError("Selected feature branch does not exist locally")
        shallow = self.git(self.repo, "rev-parse", "--is-shallow-repository")
        if shallow.strip() == "true":
            raise SyncError("Shallow history cannot prove ancestry")

    def git(
        self,
        path: Path,
        *args: str,
        ok: tuple[int, ...] = (0,),
        input: str | None = None,
    ) -> str:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            input=input,
        )
        if result.returncode not in ok:
            raise SyncError(
                f"git {' '.join(args)} (exit {result.returncode})\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return result.stdout

    def gitpath(self, path: Path, *args: str) -> Path:
        value = self.git(path, "rev-parse", "--path-format=absolute", *args).strip()
        return Path(value).resolve()

    def sha(self, ref: str) -> str | None:
        value = self.git(
            self.repo,
            *["rev-parse", "--verify", "--quiet"],
            f"{ref}^{{commit}}",
            ok=(0, 1),
        )
        return value.strip() or None

    def ancestor(self, source: str, target: str) -> bool:
        base = self.git(self.repo, "merge-base", source, target, ok=(0, 1))
        return base.strip() == source

    def inventory(self) -> list[tuple[str, list[str], list[str]]]:
        entries = []
        output = self.git(self.repo, "worktree", "list", "--porcelain", "-z")
        for record in output.split("\0\0"):
            fields = record.split("\0")
            if not fields[0].startswith("worktree "):
                continue
            path = fields[0].removeprefix("worktree ")
            branches = [
                f.removeprefix("branch ") for f in fields if f.startswith("branch ")
            ]
            if Path(path).is_dir() and "detached" in fields:
                for marker in (
                    "rebase-merge/head-name",
                    "rebase-apply/head-name",
                    "BISECT_START",
                ):
                    metadata = self.gitpath(Path(path), "--git-path", marker)
                    if metadata.is_file():
                        name = metadata.read_text(encoding="utf-8").strip()
                        branches.append(
                            name if name.startswith("refs/") else f"refs/heads/{name}"
                        )
            entries.append((path, fields, branches))
        return entries

    def head_ownership(self, path: Path) -> list[str]:
        """Read HEAD itself: worktree porcelain can omit non-branch owners."""
        self.git(path, "rev-parse", "--verify", "HEAD^{commit}")
        resolved = self.git(path, "symbolic-ref", "--quiet", "HEAD", ok=(0, 1)).strip()
        owned: list[str] = []
        ref = "HEAD"
        while True:
            target = self.git(
                path, "symbolic-ref", "--quiet", "--no-recurse", ref, ok=(0, 1)
            ).strip()
            if not target:
                break
            self.git(path, "check-ref-format", target)
            if target.casefold() in {name.casefold() for name in owned}:
                raise SyncError(f"Invalid symbolic HEAD ownership: {path}")
            owned.append(target)
            ref = target
        if resolved != (owned[-1] if owned else ""):
            raise SyncError(f"Symbolic HEAD ownership changed: {path}")
        return owned

    @staticmethod
    def reject_aliases(refs: list[str]) -> None:
        seen: dict[str, str] = {}
        for ref in refs:
            # Directory components can alias on APFS even with different leaves.
            parts = ref.split("/")
            for i in range(1, len(parts) + 1):
                name = "/".join(parts[:i])
                prior = seen.setdefault(name.casefold(), name)
                if prior != name:
                    raise SyncError(f"Case alias refused: {prior} / {name}")

    def validate_refs(
        self, extra_updates: tuple[str, ...] = ()
    ) -> list[tuple[str, list[str], list[str]]]:
        refs = self.git(self.repo, "for-each-ref", "--format=%(refname)").splitlines()
        refs.extend(self.refs)
        inventory = self.inventory()
        updates = {ref.casefold() for ref in (*self.refs[:2], *extra_updates)}
        for path, fields, branches in inventory:
            if (
                not Path(path).is_dir()
                or "bare" in fields
                or any(field.startswith("prunable") for field in fields)
            ):
                raise SyncError(f"Unknown/unavailable worktree ownership: {path}")
            branches.extend(self.head_ownership(Path(path)))
            refs.extend(branches)
            if updates.intersection(ref.casefold() for ref in branches):
                raise SyncError(f"Worktree HEAD owns a ref planned for update: {path}")
        self.reject_aliases(refs)
        for ref in self.refs:
            if self.git(self.repo, "symbolic-ref", "--quiet", ref, ok=(0, 1)):
                raise SyncError(f"Symbolic branch/tracking ref is unsafe: {ref}")
        return inventory

    def publication_errors(self) -> tuple[str, ...]:
        expected = {
            f"branch.{self.branch}.remote": self.remote,
            f"branch.{self.branch}.merge": f"refs/heads/{self.branch}",
            f"branch.{self.branch}.pushRemote": self.remote,
            "remote.pushDefault": self.remote,
            "push.default": "simple",
            f"remote.{self.remote}.url": self.url.strip(),
            f"remote.{self.remote}.push": "",
            f"remote.{self.remote}.pushurl": "",
        }
        errors = []
        for key, value in expected.items():
            values = self.git(
                self.repo, "config", "--get-all", key, ok=(0, 1)
            ).splitlines()
            if values and (not value or values != [value]):
                errors.append(key)
        return tuple(errors)

    def remote_heads(self) -> dict[str, str]:
        if self.git(self.repo, "remote", "get-url", self.remote) != self.url:
            raise SyncError("Remote URL changed; rerun status")
        output = self.git(self.repo, "ls-remote", "--heads", self.remote)
        heads = dict(line.split()[::-1] for line in output.splitlines())
        wanted = {f"refs/heads/{self.base}", f"refs/heads/{self.branch}"}
        self.reject_aliases([*heads, *wanted])
        if f"refs/heads/{self.base}" not in heads:
            raise SyncError("Remote base branch is missing")
        return {ref: sha for ref, sha in heads.items() if ref in wanted}

    def fetch_heads(self, heads: dict[str, str]) -> None:
        refs = dict(zip(self.refs[2:], self.refs[:2], strict=True))
        old = {ref: self.sha(ref) for ref in refs.values()}
        if f"refs/heads/{self.branch}" not in heads and old[self.feature_tracking]:
            raise SyncError(
                "Published feature deleted; owner-reviewed resolution required (tracking history preserved)"
            )
        temporary = {source: f"refs/binnacle-sync/{uuid4().hex}" for source in heads}
        primary: BaseException | None = None
        self.validate_refs(tuple(temporary.values()))
        try:
            self.git(
                self.repo,
                *[
                    "fetch",
                    "--no-tags",
                    "--no-recurse-submodules",
                    "--no-write-fetch-head",
                    "--no-auto-maintenance",
                    "--refmap=",
                ],
                self.remote,
                *(f"{source}:{dest}" for source, dest in temporary.items()),
            )
            if self.remote_heads() != heads:
                raise SyncError("Remote base/feature changed since fetch; rerun status")
            self.validate_refs(tuple(temporary.values()))
            updates = []
            for source, sha in heads.items():
                if self.sha(temporary[source]) != sha:
                    raise SyncError(
                        "Fetched head differs from advertised SHA; rerun status"
                    )
                ref, previous = refs[source], old[refs[source]]
                if previous and not self.ancestor(previous, sha):
                    raise SyncError(
                        "Remote published history rewritten/non-fast-forward; owner-reviewed resolution required"
                    )
                updates.append(
                    f"update {ref} {sha} {previous}"
                    if previous
                    else f"create {ref} {sha}"
                )
            self.git(
                self.repo,
                *["update-ref", "--no-deref", "--stdin"],
                input="\n".join(["start", *updates, "prepare", "commit", ""]),
            )
        except BaseException as exc:
            primary = exc
            raise
        finally:
            for ref in temporary.values():
                try:
                    self.git(self.repo, "update-ref", "--no-deref", "-d", ref)
                except Exception as exc:
                    if primary is None:
                        raise
                    primary.__dict__.setdefault("cleanup", []).append(str(exc))

    def ignored_collisions(self, target: str) -> tuple[str, ...]:
        ignored = self.git(
            self.wt,
            *["ls-files", "-z", "--others", "--ignored", "--exclude-standard"],
        ).split("\0")
        incoming = self.git(self.repo, "ls-tree", "-rz", "--name-only", target)
        # Conservatively fold case even on case-sensitive filesystems. Include
        # file/directory swaps, symlinks and ignored nested files.
        tracked = {p.casefold() for p in incoming.split("\0") if p}
        parents = {str(parent) for p in tracked for parent in Path(p).parents}
        return tuple(
            p
            for p in ignored
            if p
            and (
                p.casefold() in tracked
                or p.casefold() in parents
                or any(str(parent).casefold() in tracked for parent in Path(p).parents)
            )
        )
