"""Conservative, cross-platform MCP/tunnel liveness watchdog.

This companion does not own routing, Wi-Fi, USB hardware, or the job manager.
Its only optional repairs are the two allowlisted MCP/tunnel supervisors;
the original Raspberry Pi's uplink watchdog remains authoritative there.
A stopped service, missing observation, inaccessible supervisor, wake gap or
offline network is never permission to force-start or reset hardware.
"""

from __future__ import annotations

import argparse
import fcntl
import http.client
import json
import logging
import os
import re
import stat
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger("binnacle.service_watchdog")

SERVICE_TARGETS = {
    "linux": {
        "mcp": "binnacle-mcp.service",
        "tunnel": "binnacle-tunnel.service",
    },
    "darwin": {
        "mcp": "system/com.binnacle.mcp",
        "tunnel": "system/com.binnacle.tunnel",
    },
}
_LAUNCHD_RUNNING = re.compile(r"^\s*state = running\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Policy:
    interval_s: float = 30
    consecutive_failures: int = 3
    startup_grace_s: float = 120
    wake_gap_s: float = 120
    restart_cooldown_s: float = 900
    probe_timeout_s: float = 2

    def __post_init__(self) -> None:
        if (
            self.interval_s < 1
            or self.consecutive_failures < 2
            or self.startup_grace_s < 0
            or self.wake_gap_s <= self.interval_s
            or self.restart_cooldown_s < 30
            or not 0 < self.probe_timeout_s <= 10
        ):
            raise ValueError("invalid service watchdog policy")


@dataclass(frozen=True, slots=True)
class Observation:
    running: bool | None
    responsive: bool | None


@dataclass
class WatchState:
    failures: dict[str, int] = field(default_factory=dict)
    last_attempt: dict[str, float] = field(default_factory=dict)
    last_cycle: float | None = None
    boot_mono: float | None = None


def _read_tunnel_health_url(path: Path) -> str | None:
    """Use only user-owned local health URLs; never follow an external link."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_size > 256
            ):
                return None
            with os.fdopen(fd, "rb") as stream:
                fd = -1
                url = stream.read(257).decode("ascii", "strict").strip()
        finally:
            if fd >= 0:
                os.close(fd)
    except (OSError, UnicodeError):
        return None
    split = urlsplit(url)
    if split.scheme != "http" or split.hostname not in {"127.0.0.1", "::1"}:
        return None
    try:
        port = split.port
    except ValueError:
        return None
    if not port or split.username or split.password:
        return None
    return f"http://{split.netloc}/api/status"


def _local_http_responds(url: str, timeout: float) -> bool | None:
    """A local HTTP response proves liveness even if upstream is unavailable."""
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if not port:
        return None
    connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
    try:
        connection.request("GET", parsed.path or "/", headers={"Connection": "close"})
        response = connection.getresponse()
        # A 5xx is an ambiguous unhealthy application response, not proof
        # that a restart will repair the WAN. It must not trigger recovery.
        return None if response.status >= 500 else True
    except (OSError, http.client.HTTPException, TimeoutError):
        return False
    finally:
        connection.close()


class Supervisor:
    """Allowlisted systemd/launchd observation and restart. No generic target."""

    def __init__(self, host: str):
        if host not in SERVICE_TARGETS:
            raise ValueError("unknown watchdog host family")
        self.host = host

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                args, capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    def running(self, service: str) -> bool | None:
        label = SERVICE_TARGETS[self.host][service]
        if self.host == "linux":
            result = self._run(["systemctl", "--user", "is-active", label])
            if result is None:
                return None
            status = result.stdout.strip()
            if status == "active":
                return True
            if status in {"inactive", "failed", "activating", "deactivating"}:
                return False
            return None
        result = self._run(["/bin/launchctl", "print", label])
        if result is None or result.returncode != 0:
            return None
        if _LAUNCHD_RUNNING.search(result.stdout):
            return True
        if re.search(
            r"^\s*state = (?:waiting|stopped)\s*$", result.stdout, re.MULTILINE
        ):
            return False
        return None

    def restart(self, service: str) -> bool:
        label = SERVICE_TARGETS[self.host][service]
        if self.host == "linux":
            args = ["systemctl", "--user", "restart", label]
        else:
            # Never modify sudoers. If noninteractive authorisation is absent,
            # this simply fails and the decision remains in the audit trail.
            args = ["sudo", "-n", "/bin/launchctl", "kickstart", "-k", label]
        result = self._run(args)
        return result is not None and result.returncode == 0


class Watchdog:
    def __init__(
        self,
        supervisor: Supervisor,
        *,
        policy: Policy | None = None,
        state: WatchState | None = None,
        restart_enabled: bool = False,
        health_file: Path | None = None,
    ):
        self.supervisor = supervisor
        self.policy = policy or Policy()
        self.state = state or WatchState()
        self.restart_enabled = restart_enabled
        self.health_file = health_file

    def observe(self, service: str) -> Observation:
        running = self.supervisor.running(service)
        if running is not True:
            return Observation(running, None)
        endpoint: str | None
        if service == "mcp":
            endpoint = "http://127.0.0.1:8000/healthz"
        elif self.health_file is not None:
            endpoint = _read_tunnel_health_url(self.health_file)
        else:
            endpoint = None
        return Observation(
            running,
            _local_http_responds(endpoint, self.policy.probe_timeout_s)
            if endpoint
            else None,
        )

    def cycle(self, *, now_mono: float, now_wall: float) -> dict[str, str]:
        """Decide from observations; unknown/inactive services never restart."""
        st, policy = self.state, self.policy
        if st.boot_mono is None:
            st.boot_mono = now_mono
        woke = st.last_cycle is not None and (
            now_mono - st.last_cycle > policy.wake_gap_s or now_mono < st.last_cycle
        )
        if woke:
            st.failures.clear()
            st.boot_mono = now_mono
            log.info("event=service_watchdog_wake_gap reset_streaks=true")
        st.last_cycle = now_mono
        outcome: dict[str, str] = {}
        for service in SERVICE_TARGETS[self.supervisor.host]:
            obs = self.observe(service)
            if obs.running is True and obs.responsive is False:
                st.failures[service] = st.failures.get(service, 0) + 1
            else:
                st.failures[service] = 0
            count = st.failures[service]
            status = (
                "unknown"
                if obs.running is None
                else "running"
                if obs.running
                else "stopped"
            )
            response = (
                "unknown"
                if obs.responsive is None
                else "yes"
                if obs.responsive
                else "no"
            )
            log.info(
                "event=service_watchdog_check service=%s state=%s responsive=%s failures=%d",
                service,
                status,
                response,
                count,
            )
            outcome[service] = "observe"
            if obs.running is not True or obs.responsive is not False:
                continue
            if count < policy.consecutive_failures:
                continue
            if now_mono - st.boot_mono < policy.startup_grace_s:
                outcome[service] = "startup_grace"
                continue
            since_attempt = now_wall - st.last_attempt.get(service, float("-inf"))
            if since_attempt < policy.restart_cooldown_s:
                outcome[service] = "cooldown"
                continue
            if not self.restart_enabled:
                log.warning(
                    "event=service_watchdog_recovery_dry_run service=%s "
                    "failures=%d restart_enabled=false",
                    service,
                    count,
                )
                outcome[service] = "dry_run"
                continue
            # The caller persists this last_attempt BEFORE allowing a live
            # restart; crash/reexec must not cause an unbounded restart loop.
            outcome[service] = "restart_due"
        return outcome


def _load_attempts(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    try:
        # Never trust symbolic links in the state path.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            raise ValueError("oversized persistent watchdog state")
        value = json.loads(data)
        if value.get("version") != 1 or not isinstance(value.get("attempts"), dict):
            raise ValueError("invalid persistent watchdog state")
        attempts = value["attempts"]
        if set(attempts) - SERVICE_TARGETS["linux"].keys():
            raise ValueError("invalid watchdog service identifier")
        if not all(
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and 0 <= v <= time.time() + 3600
            for v in attempts.values()
        ):
            raise ValueError("invalid watchdog restart timestamp")
        return {str(k): float(v) for k, v in attempts.items()}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("watchdog state unknown; recovery must fail closed") from exc


def _persist_attempts(path: Path, attempts: dict[str, float]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps({"version": 1, "attempts": attempts}).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _default_health_file(host: str) -> Path:
    # The Mac's native tunnel profile writes here; Linux's tunnel-client
    # profile uses the health subdirectory under XDG state.
    if host == "darwin":
        return Path.home() / ".config/tunnel-client/binnacle-mac-health.url"
    return Path.home() / ".local/state/tunnel-client/health/binnacle.url"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--restart-enabled", action="store_true")
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument(
        "--state-file",
        type=Path,
        default=(Path.home() / ".local/state/binnacle/service-watchdog.json"),
    )
    parser.add_argument("--health-file", type=Path)
    parser.add_argument(
        "--pause-file",
        type=Path,
        default=Path.home() / ".local/state/binnacle/service-watchdog.pause",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    from binnacle.platform.composition import host_os_family

    host = host_os_family()
    lockfd: int | None = None
    try:
        policy = Policy(interval_s=args.interval)
        # The lock prevents two running companions from fighting over a
        # recovery decision, including during a deploy or manual smoke.
        lock = args.state_file.with_suffix(".lock")
        lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lockfd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.error("event=service_watchdog_duplicate_process")
            os.close(lockfd)
            return 2
        attempts = _load_attempts(args.state_file)
    except (OSError, ValueError, RuntimeError) as exc:
        if lockfd is not None:
            os.close(lockfd)
        log.error("event=service_watchdog_start_refused reason=%s", type(exc).__name__)
        return 2
    assert lockfd is not None
    try:
        watchdog = Watchdog(
            Supervisor(host),
            policy=policy,
            state=WatchState(last_attempt=attempts),
            restart_enabled=args.restart_enabled,
            health_file=args.health_file or _default_health_file(host),
        )
        log.info(
            "event=service_watchdog_start host=%s restart_enabled=%s "
            "hardware_repair=false interval_s=%s",
            host,
            args.restart_enabled,
            policy.interval_s,
        )
        while True:
            result = watchdog.cycle(now_mono=time.monotonic(), now_wall=time.time())
            if args.pause_file.exists():
                log.warning("event=service_watchdog_recovery_paused")
                result = dict.fromkeys(result, "paused")
            attempted = False
            for service, action in result.items():
                if action != "restart_due":
                    continue
                if attempted:
                    log.info(
                        "event=service_watchdog_restart_deferred service=%s "
                        "reason=single_repair_per_cycle",
                        service,
                    )
                    continue
                attempted = True
                now = time.time()
                watchdog.state.last_attempt[service] = now
                try:
                    _persist_attempts(args.state_file, watchdog.state.last_attempt)
                except OSError:
                    log.exception(
                        "event=service_watchdog_recovery_blocked service=%s "
                        "reason=state_not_durable",
                        service,
                    )
                    continue
                ok = watchdog.supervisor.restart(service)
                log.warning(
                    "event=service_watchdog_restart service=%s success=%s",
                    service,
                    ok,
                )
                watchdog.state.failures[service] = 0
            if args.once:
                return 0
            time.sleep(policy.interval_s)
    except KeyboardInterrupt:
        return 0
    finally:
        os.close(lockfd)


if __name__ == "__main__":
    raise SystemExit(main())
