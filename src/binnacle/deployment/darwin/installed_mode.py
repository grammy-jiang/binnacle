"""Managed mode updates for an already-installed, known macOS MCP LaunchDaemon.

This is NOT the separate Darwin test-owned provisioner. The single
system/com.binnacle.mcp service is validated before privileged mutation.
Cold installation and Jobs/tunnel management remain separate gated workflows.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import plistlib
import pwd
import secrets
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_PLIST = Path("/Library/LaunchDaemons/com.binnacle.mcp.plist")
TARGET = "system/com.binnacle.mcp"
ALLOWED_ENV = frozenset({"HOME", "PATH", "BINNACLE_CONFIG_FILE"})


class InstalledMcpModeError(RuntimeError):
    """A guarded installed-service action was rejected or failed."""


@dataclass(frozen=True)
class ModePlan:
    """Reviewed change; no machine side effects before apply."""

    mode: Literal["dev", "prod"]
    previous_mode: str
    previous_sha256: str
    previous: bytes
    proposed: bytes
    plist: Path
    repo: Path
    program: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.previous != self.proposed


class DarwinInstalledMcpMode:
    """Operate only on a pinned installed LaunchDaemon; no global scanning."""

    def __init__(
        self, *, plist: Path = DEFAULT_PLIST, state_root: Path | None = None, run=None
    ) -> None:
        self.plist = plist
        self.state_root = state_root or (
            Path.home() / ".local/state/binnacle/darwin-mode"
        )
        self._run = run or self._run_command

    @staticmethod
    def _run_command(args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args, text=True, capture_output=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InstalledMcpModeError(
                f"installed macOS service command unavailable: {type(exc).__name__}"
            ) from None

    def _command(self, *args: str) -> None:
        result = self._run(tuple(args))
        if result.returncode:
            raise InstalledMcpModeError(
                f"installed MCP service operation failed (exit {result.returncode})"
            )

    def _running(self) -> bool:
        return self._run(("/bin/launchctl", "print", TARGET)).returncode == 0

    def _load(self) -> tuple[bytes, dict]:
        try:
            info = self.plist.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_mode & 0o022
                or (
                    self.plist == DEFAULT_PLIST
                    and (info.st_uid != 0 or info.st_gid != 0)
                )
            ):
                raise InstalledMcpModeError("installed MCP plist ownership invalid")
            data = self.plist.read_bytes()
            parsed = plistlib.loads(data)
        except FileNotFoundError:
            raise InstalledMcpModeError(
                "installed MCP LaunchDaemon missing; cold installation is a separate "
                "gated native deployment, not Linux systemd setup"
            ) from None
        except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
            raise InstalledMcpModeError("installed MCP plist invalid") from None
        if not isinstance(parsed, dict):
            raise InstalledMcpModeError("installed MCP plist must be a dictionary")
        if (
            parsed.get("Label") != "com.binnacle.mcp"
            or parsed.get("UserName") != pwd.getpwuid(os.geteuid()).pw_name
            or not isinstance(parsed.get("EnvironmentVariables"), dict)
            or not parsed["EnvironmentVariables"].keys() <= ALLOWED_ENV
        ):
            raise InstalledMcpModeError("installed MCP identity or environment differs")
        return data, parsed

    @staticmethod
    def _mode_of(info: dict) -> tuple[str, Path, str, int]:
        args = info.get("ProgramArguments")
        home = info.get("WorkingDirectory")
        if not isinstance(args, list) or len(args) not in (6, 7):
            raise InstalledMcpModeError("installed MCP command shape not recognized")
        if (
            args[1:4] != ["serve", "--host", "127.0.0.1"]
            or args[4] != "--port"
            or not isinstance(args[0], str)
            or not isinstance(args[5], str)
            or (len(args) == 7 and args[6] != "--reload")
            or not isinstance(home, str)
        ):
            raise InstalledMcpModeError("installed MCP command shape not recognized")
        try:
            port = int(args[5])
        except ValueError:
            raise InstalledMcpModeError("invalid installed MCP port") from None
        repo = Path(home)
        if not repo.is_absolute() or not 1 <= port <= 65535:
            raise InstalledMcpModeError("invalid installed MCP checkout/port")
        if Path(args[0]) != repo / ".venv/bin/binnacle":
            raise InstalledMcpModeError("installed MCP binary differs from checkout")
        return ("dev" if len(args) == 7 else "prod"), repo, args[3], port

    def status(self) -> str:
        _, info = self._load()
        current, repo, host, port = self._mode_of(info)
        service = "running" if self._running() else "not-loaded"
        return (
            f"{TARGET}: {service}, {current} mode, "
            f"checkout={repo}, host={host}, port={port}"
        )

    def plan(
        self,
        mode: Literal["dev", "prod"],
        *,
        repo: Path | None = None,
        port: int | None = None,
    ) -> ModePlan:
        old, info = self._load()
        previous_mode, current_repo, host, current_port = self._mode_of(info)
        new_repo = (current_repo if repo is None else repo.expanduser()).resolve()
        executable = new_repo / ".venv/bin/binnacle"
        if (
            not new_repo.is_dir()
            or not (new_repo / "src/binnacle/server.py").is_file()
            or not executable.is_file()
            or not os.access(executable, os.X_OK)
        ):
            raise InstalledMcpModeError(
                "development checkout or binnacle executable missing"
            )
        selected_port = current_port if port is None else port
        if not 1 <= selected_port <= 65535:
            raise InstalledMcpModeError("invalid requested MCP port")
        args = [str(executable), "serve", "--host", host, "--port", str(selected_port)]
        if mode == "dev":
            args.append("--reload")
        next_info = dict(info, ProgramArguments=args, WorkingDirectory=str(new_repo))
        proposal = (
            old if next_info == info else plistlib.dumps(next_info, sort_keys=True)
        )
        return ModePlan(
            mode,
            previous_mode,
            hashlib.sha256(old).hexdigest(),
            old,
            proposal,
            self.plist,
            new_repo,
            tuple(args),
        )

    def preview(self, plan: ModePlan) -> str:
        action = "switch" if plan.changed else "already"
        return (
            f"{TARGET}: {action} {plan.previous_mode} -> {plan.mode}, "
            f"checkout={plan.repo}; {'restart needed' if plan.changed else 'no changes'}"
        )

    def apply(self, plan: ModePlan, *, force: bool = False) -> str:
        """Identity, transaction backup, exact one-label restart and rollback."""
        if not plan.changed:
            return self.preview(plan)
        if not force and self._running():
            raise InstalledMcpModeError(
                "active system LaunchDaemon cannot prove idle; mode change requires "
                "an explicit --force after verifying no in-flight MCP calls"
            )
        root = self.state_root
        if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
            raise InstalledMcpModeError("invalid private mode transaction root")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.stat().st_mode & 0o077:
            raise InstalledMcpModeError("mode transaction root must be private")
        lock = root / "update.lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise InstalledMcpModeError(
                    "another MCP mode transaction is active"
                ) from None
            old, _ = self._load()
            if hashlib.sha256(old).hexdigest() != plan.previous_sha256:
                raise InstalledMcpModeError("installed MCP plist changed since plan")
            suffix = secrets.token_hex(8)
            backup, candidate = (
                root / f"{suffix}.previous.plist",
                root / f"{suffix}.candidate.plist",
            )
            for path, body in ((backup, old), (candidate, plan.proposed)):
                with path.open("xb") as out:
                    out.write(body)
                path.chmod(0o600)
            return self._install(plan, backup, candidate)
        finally:
            os.close(fd)

    def _install(self, plan: ModePlan, backup: Path, candidate: Path) -> str:
        self._command("/usr/bin/sudo", "-n", "-v")
        was_running = self._running()
        installed = False
        stopped = False
        new_running = False
        try:
            self._install_plist(candidate)
            installed = True
            if was_running:
                self._command(
                    "/usr/bin/sudo", "-n", "/bin/launchctl", "bootout", TARGET
                )
                stopped = True
            self._command(
                "/usr/bin/sudo",
                "-n",
                "/bin/launchctl",
                "bootstrap",
                "system",
                str(plan.plist),
            )
            new_running = True
            if not self._running():
                raise InstalledMcpModeError("restarted MCP LaunchDaemon not loaded")
            return f"{TARGET}: switched to {plan.mode} mode (previous plist backed up)"
        except InstalledMcpModeError as exc:
            if installed:
                try:
                    if new_running:
                        self._command(
                            "/usr/bin/sudo", "-n", "/bin/launchctl", "bootout", TARGET
                        )
                    self._install_plist(backup)
                    if stopped:
                        self._command(
                            "/usr/bin/sudo",
                            "-n",
                            "/bin/launchctl",
                            "bootstrap",
                            "system",
                            str(plan.plist),
                        )
                except InstalledMcpModeError:
                    raise InstalledMcpModeError(
                        "MCP mode update AND rollback failed; inspect installed plist "
                        "and private transaction backup"
                    ) from exc
            raise InstalledMcpModeError(
                "MCP mode update failed; rollback attempted"
            ) from exc

    def _install_plist(self, path: Path) -> None:
        self._command(
            "/usr/bin/sudo",
            "-n",
            "/usr/bin/install",
            "-o",
            "root",
            "-g",
            "wheel",
            "-m",
            "0644",
            str(path),
            str(self.plist),
        )
