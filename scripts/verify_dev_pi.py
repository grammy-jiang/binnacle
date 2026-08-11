#!/usr/bin/env python3
"""Read-only verification of the fixed Binnacle development-Pi deployment."""

from __future__ import annotations

import argparse
import grp
import http.client
import json
import os
import platform
import pwd
import re
import socket
import stat
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

SERVICE_NAME = "binnacle-dev.service"
CANONICAL_REPO = Path("/srv/binnacle-dev/repo")
_MAX_CONFIG_BYTES = 65_536
_FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    """One sanitized deployment observation."""

    name: str
    status: str
    summary: str


def verify_deployment(
    *,
    config_path: Path,
    controller_profile_path: Path,
    expected_commit: str,
    repo: Path = CANONICAL_REPO,
) -> tuple[VerificationCheck, ...]:
    """Run finite read-only checks without rendering protected configuration values."""

    checks: list[VerificationCheck] = [
        _architecture_check(),
        _python_check(),
        _systemd_profile_check(),
        _repository_check(repo, expected_commit),
        _checkout_access_check(repo),
        _protected_directory_check(config_path.parent, "protected-config-directory"),
        _protected_file_check(config_path, "application-config"),
        _protected_file_check(controller_profile_path, "controller-profile"),
    ]
    if controller_profile_path.parent != config_path.parent:
        checks.append(
            VerificationCheck(
                "controller-profile-directory",
                "fail",
                "protected configuration files must share one reviewed directory",
            )
        )
    server = _safe_server_settings(config_path)
    if server is None:
        checks.append(
            VerificationCheck("server-config", "fail", "server settings could not be validated")
        )
        return tuple(checks + _pending_live_checks())
    host, port, workers = server
    if host not in {"127.0.0.1", "::1"} or workers != 1:
        checks.append(
            VerificationCheck(
                "server-config",
                "fail",
                "server must use one worker on a canonical loopback address",
            )
        )
    else:
        checks.append(
            VerificationCheck("server-config", "pass", "one-worker loopback profile observed")
        )
    checks.extend(_systemd_service_checks())
    checks.append(_listener_check(host, port))
    checks.append(_health_check(host, port))
    checks.append(_unauthenticated_mcp_check(host, port))
    checks.extend(_pending_live_checks())
    return tuple(checks)


def _architecture_check() -> VerificationCheck:
    machine = platform.machine().casefold()
    if sys.maxsize <= 2**32 or machine not in {"aarch64", "arm64"}:
        return VerificationCheck(
            "architecture",
            "fail",
            "a 64-bit ARM development Pi was not observed",
        )
    return VerificationCheck("architecture", "pass", "64-bit ARM observed")


def _python_check() -> VerificationCheck:
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        return VerificationCheck("python", "fail", "Python must be 3.11 through 3.13")
    return VerificationCheck(
        "python",
        "pass",
        f"Python {sys.version_info.major}.{sys.version_info.minor}",
    )


def _systemd_profile_check() -> VerificationCheck:
    if not Path("/run/systemd/system").is_dir():
        return VerificationCheck("systemd", "fail", "running systemd manager not observed")
    return VerificationCheck("systemd", "pass", "running systemd manager observed")


def _repository_check(repo: Path, expected_commit: str) -> VerificationCheck:
    if _FULL_GIT_SHA.fullmatch(expected_commit) is None:
        return VerificationCheck(
            "repository",
            "fail",
            "expected commit must be a full lowercase 40-character Git SHA",
        )
    try:
        canonical = repo.resolve(strict=True)
    except OSError:
        return VerificationCheck("repository", "fail", "source checkout is missing")
    if canonical != CANONICAL_REPO or not (canonical / ".git").exists():
        return VerificationCheck("repository", "fail", "canonical Git checkout not observed")
    try:
        safe_directory = f"safe.directory={canonical}"
        commit = _run_bounded(
            ["git", "-c", safe_directory, "rev-parse", "--verify", "HEAD"],
            cwd=canonical,
        )
        dirty = bool(
            _run_bounded(
                ["git", "-c", safe_directory, "status", "--porcelain"],
                cwd=canonical,
            )
        )
    except (OSError, subprocess.CalledProcessError):
        return VerificationCheck("repository", "fail", "Git identity could not be read")
    if commit != expected_commit:
        return VerificationCheck(
            "repository",
            "fail",
            "checkout HEAD does not match the expected reviewed commit",
        )
    state = "dirty" if dirty else "clean"
    return VerificationCheck(
        "repository",
        "pass" if not dirty else "fail",
        f"{state} checkout at {commit[:12]}",
    )


def _checkout_access_check(repo: Path) -> VerificationCheck:
    try:
        service_user = pwd.getpwnam("binnacle")
        canonical = repo.resolve(strict=True)
    except (KeyError, OSError):
        return VerificationCheck(
            "checkout-access",
            "fail",
            "service identity or source checkout is missing",
        )
    if os.geteuid() != service_user.pw_uid:
        return VerificationCheck(
            "checkout-access",
            "fail",
            "run the verifier as the unprivileged binnacle service identity",
        )

    traverse_paths = (
        canonical,
        canonical / "src",
        canonical / "src/binnacle",
        canonical / ".venv",
        canonical / ".venv/bin",
    )
    readable_paths = (
        canonical / "pyproject.toml",
        canonical / "uv.lock",
        canonical / "src/binnacle/__init__.py",
    )
    entry_point = canonical / ".venv/bin/binnacle"
    if any(not os.access(path, os.R_OK | os.X_OK) for path in traverse_paths):
        return VerificationCheck(
            "checkout-access",
            "fail",
            "binnacle cannot read and traverse the source checkout",
        )
    if any(not os.access(path, os.R_OK) for path in readable_paths) or not os.access(
        entry_point,
        os.R_OK | os.X_OK,
    ):
        return VerificationCheck(
            "checkout-access",
            "fail",
            "binnacle cannot read tracked inputs or execute the locked entry point",
        )
    writable_paths = (
        canonical,
        canonical / ".git",
        canonical / ".venv",
        canonical / "src",
        entry_point,
        *readable_paths,
    )
    if any(os.access(path, os.W_OK) for path in writable_paths):
        return VerificationCheck(
            "checkout-access",
            "fail",
            "binnacle has prohibited source-checkout write access",
        )
    return VerificationCheck(
        "checkout-access",
        "pass",
        "service identity has read/execute access without source write access",
    )


def _protected_directory_check(path: Path, name: str) -> VerificationCheck:
    try:
        metadata = path.stat(follow_symlinks=False)
        expected_group = grp.getgrnam("binnacle").gr_gid
    except (KeyError, OSError):
        return VerificationCheck(name, "fail", "protected directory or binnacle group is missing")
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != expected_group
        or mode & ~0o750
    ):
        return VerificationCheck(
            name,
            "fail",
            "ownership or mode is broader than root:binnacle 0750",
        )
    return VerificationCheck(name, "pass", "protected root:binnacle directory observed")


def _protected_file_check(path: Path, name: str) -> VerificationCheck:
    try:
        metadata = path.stat(follow_symlinks=False)
        expected_group = grp.getgrnam("binnacle").gr_gid
    except (KeyError, OSError):
        return VerificationCheck(name, "fail", "protected file or binnacle group is missing")
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or not 0 <= metadata.st_size <= _MAX_CONFIG_BYTES
        or metadata.st_uid != 0
        or metadata.st_gid != expected_group
        or mode & ~0o640
    ):
        return VerificationCheck(
            name,
            "fail",
            "ownership or mode is broader than root:binnacle 0640",
        )
    return VerificationCheck(name, "pass", "protected root:binnacle file observed")


def _safe_server_settings(path: Path) -> tuple[str, int, int] | None:
    try:
        values = tomllib.loads(_read_bounded_regular_file(path).decode("utf-8"))
        server = values.get("server")
        if not isinstance(server, dict):
            return None
        host = server.get("host")
        port = server.get("port")
        workers = server.get("workers")
        if (
            not isinstance(host, str)
            or isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
            or isinstance(workers, bool)
            or not isinstance(workers, int)
            or workers != 1
        ):
            return None
        return host, port, workers
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _read_bounded_regular_file(path: Path) -> bytes:
    descriptor: int | None = None
    try:
        path_metadata = path.stat(follow_symlinks=False)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if (
            path_metadata.st_dev != metadata.st_dev
            or path_metadata.st_ino != metadata.st_ino
            or not stat.S_ISREG(metadata.st_mode)
            or not 0 <= metadata.st_size <= _MAX_CONFIG_BYTES
        ):
            raise ValueError("configuration file is missing, unsafe, or unbounded")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            data = source.read(_MAX_CONFIG_BYTES + 1)
        if len(data) > _MAX_CONFIG_BYTES:
            raise ValueError("configuration file is unbounded")
        return data
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _systemd_service_checks() -> list[VerificationCheck]:
    try:
        properties = _systemd_properties(
            (
                "ActiveState",
                "UnitFileState",
                "User",
                "Group",
                "SupplementaryGroups",
                "Environment",
                "EnvironmentFiles",
            )
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        return [VerificationCheck("service", "fail", "systemd service properties unavailable")]
    checks = [
        VerificationCheck(
            "service-active",
            "pass" if properties["ActiveState"] == "active" else "fail",
            "service is active"
            if properties["ActiveState"] == "active"
            else "service is not active",
        ),
        VerificationCheck(
            "service-enabled",
            "pass" if properties["UnitFileState"] == "enabled" else "fail",
            "service is enabled"
            if properties["UnitFileState"] == "enabled"
            else "service is not enabled",
        ),
    ]
    identity_ok = (
        properties["User"] == "binnacle"
        and properties["Group"] == "binnacle"
        and set(properties["SupplementaryGroups"].split()) == {"binnacle-dev"}
    )
    try:
        identity_ok = identity_ok and pwd.getpwnam("binnacle").pw_uid != 0
    except KeyError:
        identity_ok = False
    checks.append(
        VerificationCheck(
            "service-identity",
            "pass" if identity_ok else "fail",
            "non-root binnacle:binnacle with source-read group"
            if identity_ok
            else "service identity or group boundary differs",
        )
    )
    environment_ok = not properties["Environment"] and not properties["EnvironmentFiles"]
    checks.append(
        VerificationCheck(
            "service-environment",
            "pass" if environment_ok else "fail",
            "no service environment credentials configured"
            if environment_ok
            else "service environment is non-empty and requires security review",
        )
    )
    return checks


def _systemd_properties(names: tuple[str, ...]) -> dict[str, str]:
    command = ["systemctl", "show", SERVICE_NAME]
    for name in names:
        command.extend(("--property", name))
    output = _run_bounded(command)
    values: dict[str, str] = {}
    for line in output.splitlines():
        name, separator, value = line.partition("=")
        if separator and name in names:
            values[name] = value
    if set(values) != set(names):
        raise ValueError("systemd property set is incomplete")
    return values


def _listener_check(host: str, port: int) -> VerificationCheck:
    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except OSError:
        return VerificationCheck("listener", "fail", "configured loopback listener unavailable")
    return VerificationCheck("listener", "pass", "configured loopback listener reachable")


def _health_check(host: str, port: int) -> VerificationCheck:
    try:
        connection = http.client.HTTPConnection(host, port, timeout=2)
        connection.request("GET", "/readyz")
        response = connection.getresponse()
        body = response.read(4096)
        connection.close()
        value = json.loads(body)
    except (OSError, json.JSONDecodeError, http.client.HTTPException):
        return VerificationCheck("readiness", "fail", "bounded readiness check failed")
    if response.status != 200 or value != {"status": "ready"}:
        return VerificationCheck("readiness", "fail", "application is not ready")
    return VerificationCheck("readiness", "pass", "application readiness observed")


def _unauthenticated_mcp_check(host: str, port: int) -> VerificationCheck:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientInfo": {
                        "name": "deployment-verifier",
                        "version": "1",
                    },
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        connection = http.client.HTTPConnection(host, port, timeout=2)
        connection.request(
            "POST",
            "/mcp",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/list",
            },
        )
        response = connection.getresponse()
        response.read(4096)
        connection.close()
    except (OSError, http.client.HTTPException):
        return VerificationCheck("unauthenticated-mcp", "fail", "MCP rejection check failed")
    if response.status not in {401, 403}:
        return VerificationCheck(
            "unauthenticated-mcp",
            "fail",
            "unauthenticated MCP request was not rejected at the security boundary",
        )
    return VerificationCheck(
        "unauthenticated-mcp",
        "pass",
        "unauthenticated MCP request rejected before dispatch",
    )


def _pending_live_checks() -> list[VerificationCheck]:
    return [
        VerificationCheck(
            "selected-auth-profile",
            "blocked",
            "requires live ChatGPT/tunnel/identity-provider feasibility evidence",
        ),
        VerificationCheck(
            "authenticated-catalogue",
            "blocked",
            "requires the selected concrete authentication adapter and credential path",
        ),
        VerificationCheck(
            "tunnel-identity",
            "blocked",
            "requires the actual supported private-connectivity mechanism",
        ),
    ]


def _run_bounded(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if len(result.stdout.encode("utf-8")) > 65_536:
        raise ValueError("command output exceeded verifier bound")
    return result.stdout.strip()


def _render(checks: tuple[VerificationCheck, ...], *, output: str) -> None:
    passed = all(check.status == "pass" for check in checks)
    if output == "json":
        print(
            json.dumps(
                {
                    "passed": passed,
                    "checks": [asdict(check) for check in checks],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    for check in checks:
        print(f"{check.status.upper():7} {check.name}: {check.summary}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--controller-profile", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--repo", type=Path, default=CANONICAL_REPO)
    parser.add_argument("--output", choices=("human", "json"), default="human")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Render sanitized verification results; blocked live gates are non-zero."""

    arguments = _parser().parse_args(argv)
    checks = verify_deployment(
        config_path=arguments.config,
        controller_profile_path=arguments.controller_profile,
        expected_commit=arguments.expected_commit,
        repo=arguments.repo,
    )
    _render(checks, output=arguments.output)
    return 0 if all(check.status == "pass" for check in checks) else 2


if __name__ == "__main__":
    raise SystemExit(main())
